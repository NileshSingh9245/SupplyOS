"""Private first-owner admission, input redaction and real PostgreSQL serialization."""
from __future__ import annotations

import asyncio
import secrets
import time
import uuid

import httpx
import pytest
from alembic import command
from fastapi import FastAPI
from pydantic import ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.features.tenants import router as tenant_routes
from app.features.tenants import security as setup_security
from app.features.tenants.router import SetupRequest
from app.infrastructure.db.models.tenant import Tenant
from app.infrastructure.db.models.user import AuditLog, User
from app.infrastructure.db.models.warehouse import Warehouse
from test_migrations import database  # noqa: F401 owned disposable PostgreSQL


def payload():
    return {
        "company_name": "  Setup fixture  ", "admin_full_name": "  Fixture owner  ",
        "admin_email": "owner@example.com", "admin_password": secrets.token_urlsafe(24),
        "email": "", "warehouses": [{"code": " WH-1 ", "name": " Main ", "city": ""}],
    }


@pytest.fixture
def settings():
    # The owned verifier supplies private runtime configuration; no real .env is inspected.
    return get_settings().model_copy(update={"setup_authorization_token": secrets.token_urlsafe(48)})


@pytest.mark.parametrize("field,value", [
    ("admin_password", "too-short"), ("admin_password", "x" * 73),
    ("admin_password", "\u00e9" * 37), ("company_name", "  "),
    ("admin_full_name", " "), ("email", "not-email"),
    ("currency", "usd"), ("tenant_id", str(uuid.UUID(int=1))),
    ("role", "super_admin"), ("password_hash", "unused"),
])
def test_strict_setup_input(field, value):
    data = payload()
    data[field] = value
    with pytest.raises(ValidationError):
        SetupRequest(**data)


def test_contact_blanks_normalize_and_credentials_never_export():
    data = payload()
    request = SetupRequest(**data)
    assert request.company_name == "Setup fixture" and request.admin_full_name == "Fixture owner"
    assert request.email is None and request.warehouses[0].city is None
    assert request.warehouses[0].code == "WH-1"
    assert "admin_password" not in request.model_dump()
    if data["admin_password"] in repr(request) or data["admin_password"] in request.model_dump_json():
        pytest.fail("A setup credential escaped a DTO", pytrace=False)


def test_duplicate_trimmed_warehouse_codes_fail_before_writing():
    data = payload()
    data["warehouses"].append({"code": "WH-1", "name": "Other"})
    with pytest.raises(ValidationError):
        SetupRequest(**data)


@pytest.mark.parametrize("path", [
    "/api/setup/initialize", "/api/v1/setup/initialize", "/custom/v1/setup/initialize/",
])
@pytest.mark.parametrize("headers,expected", [([], 403), ([(b"x-setup-authorization", b"short")], 403)])
def test_admission_rejects_before_receiving_body(settings, path, headers, expected):
    seen = {"body": 0, "app": 0}

    async def inner(scope, receive, send):
        seen["app"] += 1

    async def receive():
        seen["body"] += 1
        return {"type": "http.request", "body": b"invalid secret body"}

    messages = []

    async def send(message):
        messages.append(message)

    app = setup_security.SetupAuthorizationMiddleware(
        inner, settings=settings, prefixes=("/api", "/api/v1", "/custom/v1"),
    )
    asyncio.run(app({"type": "http", "method": "POST", "path": path, "headers": headers}, receive, send))
    assert seen == {"body": 0, "app": 0}
    assert messages[0]["status"] == expected


def test_duplicate_authorization_is_not_collapsed(settings):
    value = settings.setup_authorization_token.encode()
    with pytest.raises(Exception) as failure:
        setup_security.authorize_setup({"headers": [
            (b"x-setup-authorization", value), (b"X-Setup-Authorization", value),
        ]}, settings)
    assert failure.value.status_code == 403


def test_setup_authorization_is_default_held_and_not_exported(settings):
    with pytest.raises(Exception) as failure:
        setup_security.authorize_setup({"headers": []}, settings.model_copy(update={"setup_authorization_token": ""}))
    assert failure.value.status_code == 503
    assert "setup_authorization_token" not in settings.model_dump()
    if settings.setup_authorization_token in repr(settings) or settings.setup_authorization_token in settings.model_dump_json():
        pytest.fail("Operator authorization escaped settings", pytrace=False)


@pytest.fixture
def setup_app(database, settings, monkeypatch):
    engine, config = database
    command.upgrade(config, "head")
    monkeypatch.setattr(setup_security, "get_settings", lambda: settings)
    monkeypatch.setattr(tenant_routes, "get_settings", lambda: settings)
    asynchronous = create_async_engine(engine.url.set(drivername="postgresql+asyncpg"), poolclass=NullPool)
    factory = async_sessionmaker(asynchronous, expire_on_commit=False, autoflush=False)

    async def db():
        async with factory() as session:
            yield session

    app = FastAPI()
    app.include_router(tenant_routes.router, prefix="/api/v1")
    app.dependency_overrides[get_db] = db
    app.add_middleware(setup_security.SetupAuthorizationMiddleware, settings=settings, prefixes=("/api/v1",))
    try:
        yield app, engine, settings
    finally:
        asyncio.run(asynchronous.dispose())


async def initialize(app, settings, data):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1") as client:
        return await client.post("/api/v1/setup/initialize", json=data, headers={
            "X-Setup-Authorization": settings.setup_authorization_token,
        })


@pytest.mark.integration
def test_empty_setup_commits_exactly_one_unverified_owner_and_private_status(setup_app):
    app, engine, settings = setup_app
    data = payload()
    result = asyncio.run(initialize(app, settings, data))
    assert result.status_code == 201 and result.json()["is_initialized"] is True
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(Tenant)) == 1
        owner = db.scalars(select(User)).one()
        assert owner.role == "super_admin" and owner.is_email_verified is False
        assert owner.email == "owner@example.com"
        assert db.scalars(select(Warehouse)).one().code == "WH-1"
        assert db.scalar(select(func.count()).select_from(AuditLog)) == 1

    async def status():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1") as client:
            return await client.get("/api/v1/setup/status")

    public = asyncio.run(status())
    assert public.status_code == 200 and public.json()["is_setup_complete"] is True
    assert public.json()["tenant_id"] is None and public.json()["company_name"] is None
    assert public.headers["cache-control"] == "no-store"
    if data["admin_password"] in result.text or settings.setup_authorization_token in result.text:
        pytest.fail("A bootstrap credential escaped the response", pytrace=False)


@pytest.mark.integration
def test_incomplete_existing_setup_is_not_reclaimed(setup_app):
    app, engine, settings = setup_app
    with Session(engine) as db:
        existing = Tenant(name="Preserved incomplete record", is_setup_complete=False)
        db.add(existing)
        db.commit()
        identifier = existing.id
    assert asyncio.run(initialize(app, settings, payload())).status_code == 409
    with Session(engine) as db:
        assert db.get(Tenant, identifier).name == "Preserved incomplete record"
        assert db.scalar(select(func.count()).select_from(User)) == 0


@pytest.mark.integration
def test_authorized_concurrent_first_setup_has_one_committed_winner(setup_app):
    app, engine, settings = setup_app
    with engine.connect() as holder:
        holder.execute(text("SELECT pg_advisory_xact_lock(:namespace, :resource)"), {
            "namespace": 0x53555050, "resource": 1,
        })
        pid = holder.scalar(text("SELECT pg_backend_pid()"))

        async def concurrent_requests():
            # Async engines belong to one event loop, just like the real ASGI server.
            calls = [asyncio.create_task(initialize(app, settings, payload())) for _ in range(2)]
            try:
                deadline, blocked = time.monotonic() + 10, 0
                while time.monotonic() < deadline:
                    with engine.connect() as observe:
                        blocked = observe.scalar(text(
                            "SELECT count(*) FROM pg_stat_activity WHERE :holder=ANY(pg_blocking_pids(pid))"
                        ), {"holder": pid})
                    if blocked == 2:
                        break
                    await asyncio.sleep(0.02)
                assert blocked == 2
            finally:
                holder.commit()
            return await asyncio.wait_for(asyncio.gather(*calls), timeout=20)

        responses = asyncio.run(concurrent_requests())
    assert sorted(response.status_code for response in responses) == [201, 409]
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(Tenant)) == 1
        assert db.scalar(select(func.count()).select_from(User)) == 1
        assert db.scalar(select(func.count()).select_from(Warehouse)) == 1


@pytest.mark.integration
def test_setup_validation_is_static_even_for_secret_input_keys(setup_app):
    app, _, settings = setup_app
    secret = secrets.token_urlsafe(48)
    data = payload()
    data[secret] = secret
    response = asyncio.run(initialize(app, settings, data))
    assert response.status_code == 422
    assert response.json()["detail"] == [{"loc": ["body"], "msg": "Invalid request data", "type": "value_error"}]
    if secret in response.text or data["admin_password"] in response.text:
        pytest.fail("Validation echoed operator input", pytrace=False)
