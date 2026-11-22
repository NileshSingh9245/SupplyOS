"""Staff lifecycle contracts on the identified owned API and real PostgreSQL only."""
from __future__ import annotations

import asyncio
import json
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
import pytest
import requests
from fastapi import FastAPI
from sqlalchemy import create_engine, event, func, select, text, update
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.infrastructure.db.models.customer import Customer, LedgerEntry
from app.infrastructure.db.models.order import Delivery, Order, OrderStatusHistory
from app.infrastructure.db.models.tenant import Tenant
from app.infrastructure.db.models.user import AuditLog, PasswordResetToken, RefreshToken, User
from app.infrastructure.db.models.warehouse import Warehouse

ROLES = ("warehouse_manager", "accountant", "delivery_partner")
SAFE_FIELDS = {"id", "email", "full_name", "phone", "role", "is_active", "created_at"}
INVALID_DATA = {"detail": [{
    "loc": ["body"], "msg": "Invalid request data", "type": "value_error",
}]}


@dataclass(frozen=True)
class Identity:
    id: uuid.UUID
    tenant_id: uuid.UUID
    email: str
    password: str = field(repr=False)


@dataclass(frozen=True)
class Tokens:
    access: str = field(repr=False)
    refresh: str = field(repr=False)


@dataclass(frozen=True)
class Database:
    engine: Engine = field(repr=False)
    tenant_id: uuid.UUID
    owner_id: uuid.UUID


@pytest.fixture(scope="module")
def staff_database(base_url, admin_session):
    # base_url proves the owned API identity before any direct database connection or mutation.
    sync = make_url(os.environ.get("DATABASE_URL_SYNC", ""))
    asynchronous = make_url(os.environ.get("DATABASE_URL", ""))
    if (
        os.environ.get("APP_ENV") != "test"
        or os.environ.get("SUPPLYOS_ALLOW_API_WRITE_TESTS") != "1"
        or sync.drivername != "postgresql+psycopg2"
        or asynchronous.drivername != "postgresql+asyncpg"
        or sync.host not in {"127.0.0.1", "localhost", "::1"}
        or not (sync.database or "").startswith("supplyos_test_")
        or (sync.host, sync.port, sync.database)
        != (asynchronous.host, asynchronous.port, asynchronous.database)
    ):
        pytest.fail("Staff tests require the matched owned verifier PostgreSQL", pytrace=False)
    tenant_id = uuid.UUID(admin_session.admin_user["tenant_id"])
    owner_id = uuid.UUID(admin_session.admin_user["id"])
    engine = create_engine(sync, hide_parameters=True)
    try:
        with engine.connect() as connection:
            owner = connection.scalar(select(User.id).where(
                User.id == owner_id, User.tenant_id == tenant_id, User.role == "super_admin",
                User.email == os.environ["TEST_ADMIN_EMAIL"],
            ))
            if owner is None:
                pytest.fail("Staff database does not match the identified owned API", pytrace=False)
        yield Database(engine, tenant_id, owner_id)
    finally:
        engine.dispose()


@pytest.fixture
def make_identity(staff_database):
    from app.core.security import hash_password

    def create(*, role="warehouse_manager", tenant_id=None, identifier=None, email=None,
               customer_id=None, is_active=True):
        tenant_id = tenant_id or staff_database.tenant_id
        password = f"Individual-{uuid.uuid4().hex}!"
        with Session(staff_database.engine, expire_on_commit=False) as db:
            user = User(
                id=identifier or uuid.uuid4(), tenant_id=tenant_id,
                email=email or f"staff-test-{uuid.uuid4().hex}@example.com",
                password_hash=hash_password(password), full_name="Individual test holder",
                role=role, customer_id=customer_id, is_active=is_active, is_email_verified=False,
            )
            db.add(user)
            db.commit()
            return Identity(user.id, user.tenant_id, user.email, password)
    return create


@pytest.fixture
def target(make_identity):
    return make_identity()


@pytest.fixture
def other_tenant(staff_database):
    with Session(staff_database.engine, expire_on_commit=False) as db:
        tenant = Tenant(name="Owned staff tenant", is_setup_complete=True)
        db.add(tenant)
        db.commit()
        return tenant.id


def _payload(**changes):
    return {
        "email": f"selected-{uuid.uuid4().hex}@example.com", "full_name": "Selected holder",
        "phone": None, "role": "warehouse_manager",
        "password": f"Individual-{uuid.uuid4().hex}!", **changes,
    }


def _login(api, identity):
    response = requests.post(f"{api}/auth/login", json={
        "email": identity.email, "password": identity.password,
        "tenant_id": str(identity.tenant_id),
    }, timeout=20)
    if response.status_code != 200:
        pytest.fail(f"Owned staff login failed (HTTP {response.status_code})", pytrace=False)
    return Tokens(response.json()["access_token"], response.cookies["refresh_token"])


def _me(api, tokens):
    return requests.get(f"{api}/auth/me", headers={
        "Authorization": f"Bearer {tokens.access}",
    }, timeout=15)


def _refresh(api, tokens):
    return requests.post(f"{api}/auth/refresh", cookies={
        "refresh_token": tokens.refresh,
    }, timeout=20)


def _safe(response, *secrets):
    assert response.headers["Cache-Control"] == "no-store"
    if any(value and value in response.text for value in secrets):
        pytest.fail("Staff response exposed a private input", pytrace=False)
    assert "set-cookie" not in response.headers


def _count(database, model, *conditions):
    with database.engine.connect() as connection:
        return connection.scalar(select(func.count()).select_from(model).where(*conditions))


def _snapshot(database, identifier):
    with database.engine.connect() as connection:
        user = connection.execute(select(
            User.email, User.password_hash, User.full_name, User.phone, User.role, User.is_active,
            User.is_email_verified, User.customer_id, User.session_version,
        ).where(User.id == identifier)).one()
        refresh = connection.execute(select(RefreshToken.id, RefreshToken.revoked_at).where(
            RefreshToken.user_id == identifier,
        ).order_by(RefreshToken.id)).all()
        reset = connection.execute(select(PasswordResetToken.id, PasswordResetToken.used_at).where(
            PasswordResetToken.user_id == identifier,
        ).order_by(PasswordResetToken.id)).all()
        audits = connection.execute(select(AuditLog.id).where(
            AuditLog.resource_id == str(identifier), AuditLog.action.like("staff.%"),
        ).order_by(AuditLog.id)).all()
    return user, refresh, reset, audits


def _unchanged(database, identifier, snapshot):
    if _snapshot(database, identifier) != snapshot:
        pytest.fail("Denied/failed staff request changed persisted account effects", pytrace=False)


def _reset_link(database, identity):
    from app.features.auth import service

    async def issue():
        engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool,
                                     hide_parameters=True)
        try:
            factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
            async with factory() as db:
                return await service.create_password_reset(db, identity.email, identity.tenant_id)
        finally:
            await engine.dispose()
    token = asyncio.run(issue())
    if token is None:
        pytest.fail("Owned test reset issuance failed", pytrace=False)
    return token


@pytest.mark.parametrize("role", ROLES)
def test_create_individual_unverified_staff_without_login_or_delivery_claims(
    api_prefix, admin_session, staff_database, role,
):
    from app.core.security import verify_password
    payload = _payload(role=role, full_name="  Selected holder  ", phone="  +91 9876543210  ")
    payload["email"] = payload["email"].upper()
    response = admin_session.post(f"{api_prefix}/staff", json=payload, timeout=20)
    assert response.status_code == 201
    _safe(response, payload["password"])
    body = response.json()
    assert set(body) == SAFE_FIELDS
    assert body["role"] == role and body["is_active"] is True
    assert body["email"] == payload["email"].lower()
    assert body["full_name"] == "Selected holder" and body["phone"] == "+91 9876543210"
    assert datetime.fromisoformat(body["created_at"]).tzinfo is not None
    identifier = uuid.UUID(body["id"])
    with Session(staff_database.engine) as db:
        user = db.get(User, identifier)
        assert user.tenant_id == staff_database.tenant_id
        assert user.customer_id is None and user.is_email_verified is False
        assert user.session_version == 0
        assert int(user.password_hash.split("$")[2]) == 12
        if not verify_password(payload["password"], user.password_hash):
            pytest.fail("Staff hash does not verify the selected password", pytrace=False)
        entry = db.scalar(select(AuditLog).where(
            AuditLog.action == "staff.create", AuditLog.resource_id == str(identifier),
        ))
        assert entry.actor_id == staff_database.owner_id and entry.actor_email is None
        assert entry.metadata_json == {"changed_fields": ["email", "full_name", "phone", "role"]}
    assert _count(staff_database, RefreshToken, RefreshToken.user_id == identifier) == 0
    assert _count(staff_database, PasswordResetToken, PasswordResetToken.user_id == identifier) == 0


@pytest.mark.parametrize("phone", [None, "", "  "], ids=["null", "empty", "blank"])
def test_optional_phone_is_normalized_to_null(api_prefix, admin_session, phone):
    response = admin_session.post(f"{api_prefix}/staff", json=_payload(phone=phone), timeout=20)
    assert response.status_code == 201 and response.json()["phone"] is None


def test_list_is_bounded_deterministic_tenant_scoped_and_excludes_owner_customer_links(
    api_prefix, admin_session, staff_database, make_identity, other_tenant,
):
    for role in ROLES:
        make_identity(role=role)
    inactive = make_identity(is_active=False)
    excluded = [make_identity(role="super_admin"), make_identity(role="customer"),
                make_identity(tenant_id=other_tenant)]
    with Session(staff_database.engine, expire_on_commit=False) as db:
        customer = Customer(
            tenant_id=staff_database.tenant_id, code=f"LINK-{uuid.uuid4().hex[:16]}",
            name="Existing business profile",
        )
        db.add(customer)
        db.commit()
        excluded.append(make_identity(customer_id=customer.id))
    with staff_database.engine.connect() as connection:
        expected = [str(identifier) for identifier in connection.execute(select(User.id).where(
            User.tenant_id == staff_database.tenant_id, User.role.in_(ROLES),
            User.customer_id.is_(None),
        ).order_by(User.created_at.desc(), User.id)).scalars()]
    first = admin_session.get(f"{api_prefix}/staff?page=1&page_size=2", timeout=15)
    second = admin_session.get(f"{api_prefix}/staff?page=2&page_size=2", timeout=15)
    again = admin_session.get(f"{api_prefix}/staff?page=1&page_size=2", timeout=15)
    for response in (first, second, again):
        assert response.status_code == 200
        _safe(response)
        body = response.json()
        assert set(body) == {"items", "total", "page", "page_size"}
        assert body["total"] == len(expected)
        assert all(set(item) == SAFE_FIELDS for item in body["items"])
    assert [item["id"] for item in first.json()["items"]] == expected[:2]
    assert [item["id"] for item in second.json()["items"]] == expected[2:4]
    assert first.json() == again.json()
    assert str(inactive.id) in expected
    assert not {str(identity.id) for identity in excluded}.intersection(expected)
    empty = admin_session.get(
        f"{api_prefix}/staff?page={len(expected) + 1}&page_size=2", timeout=15,
    )
    assert empty.status_code == 200 and empty.json()["items"] == []
    alias = admin_session.get(f"{api_prefix.removesuffix('/v1')}/staff", timeout=15)
    assert alias.status_code == 200
    _safe(alias)


@pytest.mark.parametrize("role", [*ROLES, "customer", "owner"])
def test_every_staff_operation_requires_persisted_super_admin(
    api_prefix, staff_database, make_identity, target, role,
):
    caller = make_identity(role=role)
    tokens = _login(api_prefix, caller)
    before = _snapshot(staff_database, target.id)
    payload = _payload()
    for method, path, body in (
        ("GET", "/staff", None), ("POST", "/staff", payload),
        ("PATCH", f"/staff/{target.id}", {"full_name": "Not permitted"}),
        ("POST", f"/staff/{target.id}/revoke-sessions", {}),
    ):
        response = requests.request(method, f"{api_prefix}{path}", json=body, headers={
            "Authorization": f"Bearer {tokens.access}",
        }, timeout=20)
        assert response.status_code == 403
        assert response.json() == {"detail": "Only the owner may manage staff"}
        _safe(response, payload["password"], tokens.access, tokens.refresh)
    _unchanged(staff_database, target.id, before)
    assert _count(staff_database, User, User.email == payload["email"]) == 0


def test_anonymous_staff_operations_are_denied(api_prefix, target):
    for method, path, body in (
        ("GET", "/staff", None), ("POST", "/staff", _payload()),
        ("PATCH", f"/staff/{target.id}", {"is_active": False}),
        ("POST", f"/staff/{target.id}/revoke-sessions", {}),
    ):
        response = requests.request(method, f"{api_prefix}{path}", json=body, timeout=15)
        assert response.status_code == 401
        _safe(response)


@pytest.mark.parametrize("role", ["super_admin", "customer", "delivery", "manager", "ACCOUNTANT",
                                  "warehouse-manager", "", None])
def test_only_the_three_exact_staff_roles_can_be_created_or_selected(
    api_prefix, admin_session, staff_database, target, role,
):
    payload = _payload(role=role)
    before = _snapshot(staff_database, target.id)
    for response in (
        admin_session.post(f"{api_prefix}/staff", json=payload, timeout=20),
        admin_session.patch(f"{api_prefix}/staff/{target.id}", json={"role": role}, timeout=20),
    ):
        assert response.status_code == 422 and response.json() == INVALID_DATA
        _safe(response, payload["password"])
    _unchanged(staff_database, target.id, before)
    assert _count(staff_database, User, User.email == payload["email"]) == 0


OVERPOSTS = ("tenant_id", "callerRole", "is_email_verified", "password_hash", "session_version",
            "session_id", "refresh_token", "reset_token", "customer_id", "verification", "hash")


@pytest.mark.parametrize("operation", ["create", "patch", "revoke"])
@pytest.mark.parametrize("overpost", OVERPOSTS)
def test_credential_tenant_session_and_verification_overposts_are_private_and_atomic(
    api_prefix, admin_session, staff_database, target, operation, overpost,
):
    marker = f"Private-overpost-{uuid.uuid4().hex}"
    payload = _payload() if operation == "create" else (
        {"full_name": "Not changed"} if operation == "patch" else {}
    )
    payload[overpost] = marker
    before = _snapshot(staff_database, target.id)
    method = "patch" if operation == "patch" else "post"
    path = "/staff" if operation == "create" else f"/staff/{target.id}"
    if operation == "revoke":
        path += "/revoke-sessions"
    response = getattr(admin_session, method)(f"{api_prefix}{path}", json=payload, timeout=20)
    assert response.status_code == 422 and response.json() == INVALID_DATA
    _safe(response, marker, payload.get("password"))
    _unchanged(staff_database, target.id, before)
    if operation == "create":
        assert _count(staff_database, User, User.email == payload["email"]) == 0


@pytest.mark.parametrize("field_name", ["email", "password", "is_active", "deleted_at"])
def test_create_or_patch_rejects_other_non_whitelisted_inputs(
    api_prefix, admin_session, target, field_name,
):
    payload = {field_name: f"Private-{uuid.uuid4().hex}"}
    method, path = "patch", f"/staff/{target.id}"
    if field_name == "is_active":
        method, path = "post", "/staff"
        payload = {**_payload(), "is_active": False}
    response = getattr(admin_session, method)(f"{api_prefix}{path}", json=payload, timeout=20)
    assert response.status_code == 422 and response.json() == INVALID_DATA
    _safe(response, payload.get("password"))


@pytest.mark.parametrize("query", ["page=0", "page=2147483648", "page_size=0", "page_size=201",
                                  "page=wrong",
                                  "tenant_id=private", "callerRole=private", "session_id=private"])
def test_list_query_rejects_bounds_and_untrusted_authority_fields(api_prefix, admin_session, query):
    response = admin_session.get(f"{api_prefix}/staff?{query}", timeout=15)
    assert response.status_code == 422 and response.json() == INVALID_DATA
    _safe(response, "private")


@pytest.mark.parametrize("value", ["x" * 11, "x" * 73, "\u00e9" * 37, "\ud800" * 12, None, 123],
                         ids=["short", "long", "utf8_bytes", "invalid_utf8", "null", "not_string"])
def test_weak_or_invalid_passwords_cannot_create_and_are_fully_redacted(
    api_prefix, admin_session, staff_database, value,
):
    payload = _payload(password=value)
    response = admin_session.post(f"{api_prefix}/staff", json=payload, timeout=20)
    assert response.status_code == 422 and response.json() == INVALID_DATA
    _safe(response, value if isinstance(value, str) else None, payload["email"])
    assert _count(staff_database, User, User.email == payload["email"]) == 0


@pytest.mark.parametrize("value", ["x" * 12, "x" * 72, "\u00e9" * 36],
                         ids=["minimum", "maximum_ascii", "maximum_utf8"])
def test_complete_selected_password_is_hashed_at_bcrypt12_without_truncation(
    api_prefix, admin_session, staff_database, value,
):
    from app.core.security import verify_password
    payload = _payload(password=value)
    response = admin_session.post(f"{api_prefix}/staff", json=payload, timeout=20)
    assert response.status_code == 201
    _safe(response, value)
    with staff_database.engine.connect() as connection:
        encoded = connection.scalar(select(User.password_hash).where(
            User.id == uuid.UUID(response.json()["id"]),
        ))
    assert int(encoded.split("$")[2]) == 12
    if not verify_password(value, encoded):
        pytest.fail("Complete selected password was not preserved by bcrypt", pytrace=False)


def test_password_is_required_and_excluded_from_dto_repr_and_exports(
    api_prefix, admin_session, staff_database,
):
    from app.features.staff.schemas import StaffCreate
    payload = _payload()
    dto = StaffCreate.model_validate(payload)
    if payload["password"] in repr(dto) or "password" in dto.model_dump():
        pytest.fail("Staff credential DTO can expose its password", pytrace=False)
    del payload["password"]
    response = admin_session.post(f"{api_prefix}/staff", json=payload, timeout=20)
    assert response.status_code == 422 and response.json() == INVALID_DATA
    assert _count(staff_database, User, User.email == payload["email"]) == 0


@pytest.mark.parametrize("payload", [
    {"full_name": None}, {"full_name": "  "}, {"full_name": "x"}, {"full_name": "x" * 201},
    {"phone": "x" * 31}, {"phone": 123}, {"role": None}, {"is_active": None},
    {"is_active": 1}, {"is_active": "true"},
], ids=["null_name", "blank_name", "short_name", "long_name", "long_phone", "numeric_phone",
        "null_role", "null_activity", "integer_activity", "string_activity"])
def test_patch_rejects_null_and_coerced_non_contact_fields(
    api_prefix, admin_session, target, payload,
):
    response = admin_session.patch(f"{api_prefix}/staff/{target.id}", json=payload, timeout=20)
    assert response.status_code == 422 and response.json() == INVALID_DATA


@pytest.mark.parametrize("kind", ["owner", "self", "customer", "foreign", "linked", "missing"])
def test_owner_self_customer_cross_tenant_or_linked_targets_are_never_mutable(
    api_prefix, admin_session, staff_database, make_identity, other_tenant, kind,
):
    if kind == "self":
        identifier = staff_database.owner_id
    elif kind == "missing":
        identifier = uuid.uuid4()
    elif kind == "linked":
        with Session(staff_database.engine, expire_on_commit=False) as db:
            customer = Customer(tenant_id=staff_database.tenant_id, name="Bound customer",
                                code=f"BOUND-{uuid.uuid4().hex[:16]}")
            db.add(customer)
            db.commit()
            identifier = make_identity(customer_id=customer.id).id
    else:
        identifier = make_identity(
            role={"owner": "super_admin", "customer": "customer", "foreign": "accountant"}[kind],
            tenant_id=other_tenant if kind == "foreign" else None,
        ).id
    before = _snapshot(staff_database, identifier) if kind != "missing" else None
    for response in (
        admin_session.patch(
            f"{api_prefix}/staff/{identifier}", json={"is_active": False}, timeout=20,
        ),
        admin_session.post(f"{api_prefix}/staff/{identifier}/revoke-sessions", json={}, timeout=20),
    ):
        assert response.status_code == 404
        assert response.json() == {"detail": "Staff member not found"}
        _safe(response)
    if before is not None:
        _unchanged(staff_database, identifier, before)


def test_staff_delete_is_not_exposed_and_empty_patch_is_not_an_effect(
    api_prefix, admin_session, staff_database, target,
):
    before = _snapshot(staff_database, target.id)
    assert admin_session.delete(f"{api_prefix}/staff/{target.id}", timeout=15).status_code == 405
    response = admin_session.patch(f"{api_prefix}/staff/{target.id}", json={}, timeout=20)
    assert response.status_code == 400
    assert response.json() == {"detail": "No staff changes supplied"}
    _unchanged(staff_database, target.id, before)


@pytest.mark.parametrize("role", ["warehouse_manager", "super_admin", "customer"])
def test_email_identity_conflict_is_case_insensitive_and_does_not_convert_existing_user(
    api_prefix, admin_session, staff_database, make_identity, role,
):
    identity = make_identity(role=role)
    before = _snapshot(staff_database, identity.id)
    payload = _payload(email=identity.email.upper())
    response = admin_session.post(f"{api_prefix}/staff", json=payload, timeout=20)
    assert response.status_code == 409 and response.json() == {"detail": "Email already registered"}
    _safe(response, payload["password"])
    _unchanged(staff_database, identity.id, before)
    assert _count(staff_database, User, func.lower(User.email) == identity.email.lower(),
                  User.tenant_id == identity.tenant_id) == 1


def test_contact_and_noop_updates_keep_sessions_passwords_and_reset_links(
    api_prefix, admin_session, staff_database, target,
):
    tokens = _login(api_prefix, target)
    reset = _reset_link(staff_database, target)
    before = _snapshot(staff_database, target.id)
    response = admin_session.patch(f"{api_prefix}/staff/{target.id}", json={
        "full_name": "  New holder name  ", "phone": "  ",
    }, timeout=20)
    assert response.status_code == 200
    _safe(response, target.password, reset, tokens.access, tokens.refresh)
    assert response.json()["full_name"] == "New holder name" and response.json()["phone"] is None
    after = _snapshot(staff_database, target.id)
    if before[0][1] != after[0][1] or before[1:3] != after[1:3]:
        pytest.fail("Contact edit changed password/session/reset data", pytrace=False)
    assert after[0][-1] == 0 and _me(api_prefix, tokens).status_code == 200
    noop = admin_session.patch(f"{api_prefix}/staff/{target.id}", json={
        "role": "warehouse_manager", "is_active": True,
    }, timeout=20)
    assert noop.status_code == 200
    assert _snapshot(staff_database, target.id)[0][-1] == 0
    with staff_database.engine.connect() as connection:
        metadata = connection.execute(select(AuditLog.metadata_json).where(
            AuditLog.resource_id == str(target.id), AuditLog.action == "staff.update",
        ).order_by(AuditLog.created_at, AuditLog.id)).scalars().all()
    assert metadata == [{"changed_fields": ["full_name"]}, {"changed_fields": []}]
    if target.password in json.dumps(metadata) or reset in json.dumps(metadata):
        pytest.fail("Staff audit contains credentials", pytrace=False)


@pytest.mark.parametrize("operation", ["role", "deactivate", "revoke"])
def test_sensitive_changes_atomically_retire_every_session_family_and_reset_link(
    api_prefix, admin_session, staff_database, target, operation,
):
    first, second = _login(api_prefix, target), _login(api_prefix, target)
    rotated = _refresh(api_prefix, first)
    assert rotated.status_code == 200
    replacement = Tokens(rotated.json()["access_token"], rotated.cookies["refresh_token"])
    reset = _reset_link(staff_database, target)
    if operation == "revoke":
        response = admin_session.post(f"{api_prefix}/staff/{target.id}/revoke-sessions", timeout=20)
        assert response.json() == {"message": "Staff sessions revoked"}
    else:
        response = admin_session.patch(f"{api_prefix}/staff/{target.id}", json=(
            {"role": "accountant"} if operation == "role" else {"is_active": False}
        ), timeout=20)
        assert set(response.json()) == SAFE_FIELDS
    assert response.status_code == 200
    _safe(response, target.password, reset, first.access, first.refresh)
    assert _snapshot(staff_database, target.id)[0][-1] == 1
    assert _count(staff_database, RefreshToken, RefreshToken.user_id == target.id,
                  RefreshToken.revoked_at.is_(None)) == 0
    assert _count(staff_database, PasswordResetToken, PasswordResetToken.user_id == target.id,
                  PasswordResetToken.used_at.is_(None)) == 0
    for old in (first, second, replacement):
        assert _me(api_prefix, old).status_code == 401
        assert _refresh(api_prefix, old).status_code == 401
    rejected = requests.post(f"{api_prefix}/auth/reset-password", json={
        "token": reset, "new_password": f"Unused-{uuid.uuid4().hex}!",
    }, timeout=20)
    assert rejected.status_code in {400, 404}
    if operation != "deactivate":
        fresh = _login(api_prefix, target)
        assert _refresh(api_prefix, first).status_code == 401
        assert _me(api_prefix, fresh).status_code == 200


def test_reactivation_and_role_return_cannot_resurrect_old_tokens_or_reset_links(
    api_prefix, admin_session, staff_database, target,
):
    old = _login(api_prefix, target)
    reset = _reset_link(staff_database, target)
    for values, version in (({"is_active": False}, 1), ({"is_active": True}, 2),
                            ({"role": "accountant"}, 3), ({"role": "warehouse_manager"}, 4)):
        response = admin_session.patch(f"{api_prefix}/staff/{target.id}", json=values, timeout=20)
        assert response.status_code == 200
        assert _snapshot(staff_database, target.id)[0][-1] == version
        assert _me(api_prefix, old).status_code == 401
        assert _refresh(api_prefix, old).status_code == 401
    fresh = _login(api_prefix, target)
    assert _refresh(api_prefix, old).status_code == 401
    assert _me(api_prefix, fresh).status_code == 200
    rejected = requests.post(f"{api_prefix}/auth/reset-password", json={
        "token": reset, "new_password": f"Unused-{uuid.uuid4().hex}!",
    }, timeout=20)
    assert rejected.status_code == 400


@dataclass
class Case:
    app: FastAPI = field(repr=False)
    database: Database = field(repr=False)
    actor: Identity
    target: Identity
    tokens: Tokens = field(repr=False)
    factory: async_sessionmaker = field(repr=False)

    async def request(self, *, operation="patch", payload=None, tokens=None, suffix=""):
        path, method = f"/api/v1/staff/{self.target.id}", "PATCH"
        if operation in {"create", "list"}:
            path, method = "/api/v1/staff", "POST" if operation == "create" else "GET"
        elif operation == "revoke":
            path, method = path + "/revoke-sessions", "POST"
        if payload is None and operation == "patch":
            payload = {"full_name": "Updated under lock"}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(
            app=self.app, raise_app_exceptions=False,
        ), base_url="http://owned-asgi") as client:
            return await client.request(method, path + suffix, json=payload, headers={
                "Authorization": f"Bearer {(tokens or self.tokens).access}",
            })


@pytest.fixture
def case(api_prefix, staff_database, make_identity):
    from app.core.database import get_db
    from app.features.staff.router import router
    low, high = sorted((uuid.uuid4(), uuid.uuid4()))
    actor = make_identity(role="super_admin", identifier=high)
    staff = make_identity(identifier=low)
    tokens = _login(api_prefix, actor)
    engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool,
                                 hide_parameters=True)
    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    async def session():
        async with factory() as db:
            yield db

    app.dependency_overrides[get_db] = session
    try:
        yield Case(app, staff_database, actor, staff, tokens, factory)
    finally:
        asyncio.run(engine.dispose())


def _wait_for_lock(database, holder_pid):
    deadline = time.monotonic() + 8
    with database.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as observer:
        while time.monotonic() < deadline:
            if observer.scalar(text(
                "SELECT EXISTS (SELECT 1 FROM pg_stat_activity "
                "WHERE wait_event_type='Lock' AND :holder = ANY(pg_blocking_pids(pid)))"
            ), {"holder": holder_pid}):
                return
            time.sleep(0.01)
    pytest.fail("Staff request did not reach the expected real PostgreSQL lock wait", pytrace=False)


def test_distinct_owners_racing_case_variants_hit_one_real_email_constraint(
    case, make_identity, monkeypatch,
):
    from app.features.staff import repositories, service
    second = make_identity(role="super_admin")
    api = os.environ["TEST_API_URL"] + "/api/v1"
    second_tokens = _login(api, second)
    payload = _payload()
    recognized = []
    original_check = repositories.is_email_conflict
    original_exists = service.auth_repository.email_exists

    async def race():
        barrier = asyncio.Barrier(2)

        async def synchronized_exists(*args, **kwargs):
            exists = await original_exists(*args, **kwargs)
            assert exists is False
            await asyncio.wait_for(barrier.wait(), timeout=10)
            return exists

        def observed_conflict(error):
            result = original_check(error)
            recognized.append(result)
            return result

        monkeypatch.setattr(service.auth_repository, "email_exists", synchronized_exists)
        monkeypatch.setattr(repositories, "is_email_conflict", observed_conflict)
        return await asyncio.gather(
            case.request(operation="create", payload=payload),
            case.request(operation="create", payload={**payload, "email": payload["email"].upper()},
                         tokens=second_tokens),
        )
    responses = asyncio.run(race())
    assert sorted(response.status_code for response in responses) == [201, 409]
    assert recognized == [True]
    for response in responses:
        _safe(response, payload["password"])
    assert _count(case.database, User, User.tenant_id == case.actor.tenant_id,
                  func.lower(User.email) == payload["email"].lower()) == 1


@pytest.mark.parametrize("operation", ["create", "patch", "revoke"])
def test_mutations_reject_query_authority_overposts_without_effects(case, operation):
    before = _snapshot(case.database, case.target.id)
    payload = _payload() if operation == "create" else (
        {"is_active": False} if operation == "patch" else {}
    )
    response = asyncio.run(case.request(
        operation=operation, payload=payload, suffix="?tenant_id=untrusted",
    ))
    assert response.status_code == 422
    _safe(response, "untrusted", payload.get("password"))
    _unchanged(case.database, case.target.id, before)
    if operation == "create":
        assert _count(case.database, User, User.email == payload["email"]) == 0


def test_preexisting_uppercase_identity_is_not_duplicated(
    api_prefix, admin_session, staff_database, make_identity,
):
    identity = make_identity(email=f"LEGACY-{uuid.uuid4().hex}@EXAMPLE.COM")
    payload = _payload(email=identity.email.lower())
    response = admin_session.post(f"{api_prefix}/staff", json=payload, timeout=20)
    assert response.status_code == 409
    _safe(response, payload["password"])
    assert _count(staff_database, User, User.tenant_id == identity.tenant_id,
                  func.lower(User.email) == identity.email.lower()) == 1


def test_other_tenant_email_is_not_a_global_identity_or_promotion_authority(
    api_prefix, admin_session, staff_database, make_identity, other_tenant,
):
    other = make_identity(role="super_admin", tenant_id=other_tenant)
    before = _snapshot(staff_database, other.id)
    payload = _payload(email=other.email)
    response = admin_session.post(f"{api_prefix}/staff", json=payload, timeout=20)
    assert response.status_code == 201
    _safe(response, payload["password"])
    identifier = uuid.UUID(response.json()["id"])
    with staff_database.engine.connect() as connection:
        assert connection.scalar(select(User.tenant_id).where(
            User.id == identifier,
        )) == staff_database.tenant_id
    _unchanged(staff_database, other.id, before)


def test_unrelated_primary_key_failure_is_not_reported_as_an_email_conflict(case):
    payload = _payload()

    def collide_primary_key(db, context, instances):
        for obj in db.new:
            if isinstance(obj, User):
                obj.id = case.target.id

    event.listen(Session, "before_flush", collide_primary_key)
    try:
        response = asyncio.run(case.request(operation="create", payload=payload))
    finally:
        event.remove(Session, "before_flush", collide_primary_key)
    assert response.status_code == 500
    assert _count(case.database, User, User.email == payload["email"]) == 0
    if payload["password"] in response.text:
        pytest.fail("Unexpected database failure exposed staff credentials", pytrace=False)


@pytest.mark.parametrize("operation", ["create", "patch", "revoke"])
@pytest.mark.parametrize("failure", ["raise", "constraint"])
def test_audit_failure_rolls_back_all_staged_account_session_and_reset_effects(
    case, api_prefix, operation, failure, monkeypatch,
):
    from app.features.staff import service
    tokens = _login(api_prefix, case.target)
    reset = _reset_link(case.database, case.target)
    before = _snapshot(case.database, case.target.id)
    original = service.audit

    async def broken_audit(db, **kwargs):
        await original(db, **kwargs)
        if failure == "raise":
            raise RuntimeError("Forced staff audit failure")
        for entry in db.new:
            if isinstance(entry, AuditLog):
                entry.action = None

    monkeypatch.setattr(service, "audit", broken_audit)
    payload = _payload() if operation == "create" else {"role": "accountant"}
    response = asyncio.run(case.request(operation=operation, payload=(
        {} if operation == "revoke" else payload
    )))
    assert response.status_code == 500
    _unchanged(case.database, case.target.id, before)
    assert _me(api_prefix, tokens).status_code == 200
    if reset in response.text or case.target.password in response.text:
        pytest.fail("Audit failure exposed staff credentials", pytrace=False)
    if operation == "create":
        assert _count(case.database, User, User.email == payload["email"]) == 0


@pytest.mark.parametrize("change", ["inactive", "role", "version", "revoked", "expiry"])
@pytest.mark.parametrize("operation", ["patch", "revoke"])
def test_actor_revocation_wins_a_canonical_target_user_lock_wait(case, change, operation):
    before = _snapshot(case.database, case.target.id)
    with case.database.engine.connect() as holder, ThreadPoolExecutor(max_workers=1) as workers:
        holder.execute(select(User.id).where(User.id == case.target.id).with_for_update())
        pid = holder.scalar(text("SELECT pg_backend_pid()"))
        pending = workers.submit(lambda: asyncio.run(case.request(operation=operation)))
        try:
            _wait_for_lock(case.database, pid)
            # Target sorts first. An actor-first implementation would already block this lock.
            holder.execute(select(User.id).where(User.id == case.actor.id)
                           .with_for_update(key_share=True, nowait=True))
            if change in {"revoked", "expiry"}:
                values = {"revoked_at": datetime.now(timezone.utc)} if change == "revoked" else {
                    "expires_at": datetime.now(timezone.utc) - timedelta(seconds=1),
                }
                holder.execute(update(RefreshToken).where(
                    RefreshToken.user_id == case.actor.id,
                ).values(**values))
            else:
                values = {"inactive": {"is_active": False}, "role": {"role": "accountant"},
                          "version": {"session_version": 1}}[change]
                holder.execute(update(User).where(User.id == case.actor.id).values(**values))
            holder.commit()
            response = pending.result(timeout=20)
        finally:
            holder.rollback()
    assert response.status_code == 401
    _safe(response, case.actor.password, case.tokens.access)
    _unchanged(case.database, case.target.id, before)


@pytest.mark.parametrize("operation", ["list", "create"])
def test_actor_user_revocation_is_rechecked_after_auth_lock_wait(case, operation):
    payload = _payload() if operation == "create" else None
    with case.database.engine.connect() as holder, ThreadPoolExecutor(max_workers=1) as workers:
        holder.execute(select(User.id).where(User.id == case.actor.id).with_for_update())
        pid = holder.scalar(text("SELECT pg_backend_pid()"))
        pending = workers.submit(lambda: asyncio.run(case.request(
            operation=operation, payload=payload,
        )))
        try:
            _wait_for_lock(case.database, pid)
            holder.execute(update(User).where(User.id == case.actor.id).values(session_version=1))
            holder.commit()
            response = pending.result(timeout=20)
        finally:
            holder.rollback()
    assert response.status_code == 401
    if payload is not None:
        assert _count(case.database, User, User.email == payload["email"]) == 0


@pytest.mark.parametrize("operation", ["patch", "revoke"])
def test_actor_session_revocation_is_rechecked_after_session_lock_wait(case, operation):
    before = _snapshot(case.database, case.target.id)
    with case.database.engine.connect() as holder, ThreadPoolExecutor(max_workers=1) as workers:
        holder.execute(select(RefreshToken.id).where(
            RefreshToken.user_id == case.actor.id,
        ).with_for_update())
        pid = holder.scalar(text("SELECT pg_backend_pid()"))
        pending = workers.submit(lambda: asyncio.run(case.request(operation=operation)))
        try:
            _wait_for_lock(case.database, pid)
            holder.execute(update(RefreshToken).where(RefreshToken.user_id == case.actor.id).values(
                revoked_at=datetime.now(timezone.utc),
            ))
            holder.commit()
            response = pending.result(timeout=20)
        finally:
            holder.rollback()
    assert response.status_code == 401
    _unchanged(case.database, case.target.id, before)


@pytest.mark.parametrize("operation", ["patch", "revoke"])
@pytest.mark.parametrize("role", ["customer", "super_admin"])
def test_staff_target_eligibility_is_rechecked_after_its_lock_wait(case, operation, role):
    with case.database.engine.connect() as holder, ThreadPoolExecutor(max_workers=1) as workers:
        holder.execute(select(User.id).where(User.id == case.target.id).with_for_update())
        pid = holder.scalar(text("SELECT pg_backend_pid()"))
        pending = workers.submit(lambda: asyncio.run(case.request(operation=operation)))
        try:
            _wait_for_lock(case.database, pid)
            holder.execute(update(User).where(User.id == case.target.id).values(role=role))
            holder.commit()
            response = pending.result(timeout=20)
        finally:
            holder.rollback()
    assert response.status_code == 404 and response.json() == {"detail": "Staff member not found"}
    assert _snapshot(case.database, case.target.id)[0][-1] == 0
    assert _count(case.database, AuditLog, AuditLog.resource_id == str(case.target.id),
                  AuditLog.action.like("staff.%")) == 0


@pytest.mark.parametrize("operation", ["patch", "revoke"])
def test_final_auth_expiry_after_target_session_wait_rolls_back_every_effect(case, operation):
    api = os.environ["TEST_API_URL"] + "/api/v1"
    _login(api, case.target)
    reset = _reset_link(case.database, case.target)
    before = _snapshot(case.database, case.target.id)
    expires = datetime.now(timezone.utc) + timedelta(seconds=2)
    with case.database.engine.begin() as setup:
        setup.execute(update(RefreshToken).where(RefreshToken.user_id == case.actor.id).values(
            expires_at=expires,
        ))
    with case.database.engine.connect() as holder, ThreadPoolExecutor(max_workers=1) as workers:
        holder.execute(select(RefreshToken.id).where(
            RefreshToken.user_id == case.target.id, RefreshToken.revoked_at.is_(None),
        ).with_for_update())
        pid = holder.scalar(text("SELECT pg_backend_pid()"))
        pending = workers.submit(lambda: asyncio.run(case.request(
            operation=operation, payload={"role": "accountant"} if operation == "patch" else {},
        )))
        try:
            _wait_for_lock(case.database, pid)
            while datetime.now(timezone.utc) <= expires:
                time.sleep(0.02)
            holder.commit()
            response = pending.result(timeout=20)
        finally:
            holder.rollback()
    assert response.status_code == 401
    _safe(response, reset)
    _unchanged(case.database, case.target.id, before)


def test_canonical_non_key_user_and_actor_session_locks_survive_through_commit(case):
    from app.core.database import get_db
    committing, release = threading.Event(), threading.Event()
    statements = []

    class PausedCommit(AsyncSession):
        async def commit(self):
            committing.set()
            if not await asyncio.to_thread(release.wait, 10):
                raise RuntimeError("Commit barrier timed out")
            await super().commit()

    async def session():
        async with PausedCommit(bind=case.factory.kw["bind"], expire_on_commit=False,
                                autoflush=False) as db:
            yield db

    def observed(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    case.app.dependency_overrides[get_db] = session
    event.listen(case.factory.kw["bind"].sync_engine, "before_cursor_execute", observed)
    try:
        with ThreadPoolExecutor(max_workers=1) as workers:
            pending = workers.submit(lambda: asyncio.run(case.request(
                payload={"role": "accountant"},
            )))
            try:
                assert committing.wait(timeout=10)
                with case.database.engine.connect() as foreign_key:
                    # Actual KEY SHARE is compatible with NO KEY UPDATE on both existing users.
                    assert len(foreign_key.execute(select(User.id).where(
                        User.id.in_([case.actor.id, case.target.id]),
                    ).with_for_update(read=True, key_share=True, nowait=True)).all()) == 2
                    foreign_key.execute(text("SET LOCAL lock_timeout='150ms'"))
                    foreign_key.execute(Warehouse.__table__.insert().values(
                        tenant_id=case.actor.tenant_id, code=f"FK-{uuid.uuid4().hex[:16]}",
                        name="Owned FK compatibility fixture", manager_id=case.target.id,
                    ))
                    foreign_key.rollback()
                for model, column, identifier, values in (
                    (User, User.id, case.actor.id, {"session_version": 1}),
                    (User, User.id, case.target.id, {"is_active": False}),
                    (RefreshToken, RefreshToken.user_id, case.actor.id,
                     {"revoked_at": datetime.now(timezone.utc)}),
                ):
                    with case.database.engine.connect() as revoker:
                        revoker.execute(text("SET LOCAL lock_timeout='150ms'"))
                        with pytest.raises(DBAPIError) as error:
                            revoker.execute(
                                update(model).where(column == identifier).values(**values),
                            )
                        assert error.value.orig.pgcode == "55P03"
                        revoker.rollback()
            finally:
                release.set()
            response = pending.result(timeout=20)
    finally:
        event.remove(case.factory.kw["bind"].sync_engine, "before_cursor_execute", observed)
    assert response.status_code == 200
    canonical = next(index for index, sql in enumerate(statements) if (
        "ORDER BY users.id" in sql and "FOR NO KEY UPDATE" in sql
    ))
    actor_session = next(index for index, sql in enumerate(statements) if (
        "FROM refresh_tokens" in sql and "FOR UPDATE" in sql
    ))
    assert canonical < actor_session
    assert "JOIN refresh_tokens" in statements[-1]
    assert not any(f"UPDATE {table}" in sql for sql in statements for table in (
        "customers", "orders", "deliveries", "warehouses", "ledger_entries",
    ))


def test_staff_deactivation_leaves_deliveries_warehouse_links_and_money_history_untouched(
    api_prefix, admin_session, staff_database, make_identity,
):
    partner = make_identity(role="delivery_partner")
    with Session(staff_database.engine, expire_on_commit=False) as db:
        customer = Customer(
            tenant_id=partner.tenant_id, code=f"HIST-{uuid.uuid4().hex[:16]}",
            name="Historical customer",
            outstanding=Decimal("25.00"), credit_limit=Decimal("100.00"),
        )
        warehouse = Warehouse(tenant_id=partner.tenant_id, code=f"WH-{uuid.uuid4().hex[:16]}",
                              name="Historical warehouse", manager_id=partner.id)
        db.add_all([customer, warehouse])
        db.flush()
        order = Order(tenant_id=partner.tenant_id, order_number=f"H-{uuid.uuid4().hex[:20]}",
                      customer_id=customer.id, warehouse_id=warehouse.id)
        db.add(order)
        db.flush()
        delivery = Delivery(tenant_id=partner.tenant_id, order_id=order.id, partner_id=partner.id)
        history = OrderStatusHistory(tenant_id=partner.tenant_id, order_id=order.id,
                                     to_status="pending", actor_id=partner.id)
        ledger = LedgerEntry(tenant_id=partner.tenant_id, customer_id=customer.id,
                             debit=Decimal("25.00"), balance_after=Decimal("25.00"))
        db.add_all([delivery, history, ledger])
        db.commit()
        identifiers = (customer.id, warehouse.id, order.id, delivery.id, history.id, ledger.id)
    with staff_database.engine.connect() as connection:
        before = [connection.execute(select(model.__table__).where(model.id == identifier)).one()
                  for model, identifier in zip(
                      (Customer, Warehouse, Order, Delivery, OrderStatusHistory, LedgerEntry),
                      identifiers,
                  )]
    response = admin_session.patch(f"{api_prefix}/staff/{partner.id}", json={
        "is_active": False, "role": "accountant",
    }, timeout=20)
    assert response.status_code == 200
    with staff_database.engine.connect() as connection:
        after = [connection.execute(select(model.__table__).where(model.id == identifier)).one()
                 for model, identifier in zip(
                     (Customer, Warehouse, Order, Delivery, OrderStatusHistory, LedgerEntry),
                     identifiers,
                 )]
    assert before == after
