"""Auth contracts and real PostgreSQL contention on the identified isolated verifier."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import secrets
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from http.cookies import SimpleCookie
from pathlib import Path

import bcrypt
import jwt
import pytest
import requests
from alembic import command
from alembic.config import Config
from pydantic import ValidationError
from sqlalchemy import MetaData, Table, create_engine, delete, func, inspect, select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.core.config import Settings, get_settings
from app.infrastructure.db.models.tenant import Tenant
from app.infrastructure.db.models.user import AuditLog, LoginAttempt, PasswordResetToken, RefreshToken, User


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


@pytest.fixture
def security(monkeypatch):
    from app.core import config
    if os.environ.get("SUPPLYOS_ALLOW_API_WRITE_TESTS") == "1":
        settings = get_settings()
    else:
        settings = Settings(
            _env_file=None, app_env="test",
            database_url="postgresql+asyncpg://unused@127.0.0.1/supplyos_test_unit",
            database_url_sync="postgresql+psycopg2://unused@127.0.0.1/supplyos_test_unit",
            redis_url="redis://127.0.0.1:6379/0", jwt_secret=secrets.token_urlsafe(48),
        )
    monkeypatch.setattr(config, "get_settings", lambda: settings)
    from app.core import security as module
    monkeypatch.setattr(module, "settings", settings)
    return module


@pytest.mark.parametrize("value", ["x" * 12, "x" * 72, "\u00e9" * 36],
                         ids=["minimum", "maximum_ascii", "maximum_utf8"])
def test_new_password_policy_accepts_complete_bcrypt_input(security, value):
    encoded = security.hash_password(value)
    assert int(encoded.split("$")[2]) >= 12
    if not security.verify_password(value, encoded):
        pytest.fail("A valid new password did not verify", pytrace=False)


@pytest.mark.parametrize("value", ["x" * 11, "x" * 73, "\u00e9" * 37, "\ud800" * 12],
                         ids=["short", "long_ascii", "long_utf8", "invalid_utf8"])
def test_new_password_policy_rejects_truncation_and_invalid_utf8(security, value):
    from app.core.exceptions import DomainError
    with pytest.raises(DomainError):
        security.hash_password(value)
    from app.features.auth.schemas import RegisterCustomerRequest, ResetPasswordRequest
    with pytest.raises(ValidationError):
        RegisterCustomerRequest(email="unused@example.com", password=value, full_name="Unused")
    with pytest.raises(ValidationError):
        ResetPasswordRequest(token=secrets.token_urlsafe(32), new_password=value)


def test_existing_short_password_hashes_are_still_verified(security):
    old_password = secrets.token_urlsafe(6)
    old_hash = bcrypt.hashpw(old_password.encode(), bcrypt.gensalt(rounds=4)).decode()
    if not security.verify_password(old_password, old_hash):
        pytest.fail("Legacy password verification was gratuitously invalidated", pytrace=False)
    assert security.verify_password("unused", "not-a-bcrypt-hash") is False


@pytest.fixture(scope="module")
def auth_database(base_url, admin_session):
    # The API identity guard runs first. Direct DB tests additionally verify its seeded tenant.
    value = os.environ.get("DATABASE_URL_SYNC", "")
    url = make_url(value)
    if (
        url.drivername != "postgresql+psycopg2"
        or url.host not in {"127.0.0.1", "localhost", "::1"}
        or not (url.database or "").startswith("supplyos_test_")
        or os.environ.get("APP_ENV") != "test"
    ):
        pytest.fail("Direct auth tests require the owned verifier database", pytrace=False)
    setup = admin_session.get(f"{base_url}/api/v1/setup/status", timeout=10)
    assert setup.status_code == 200
    tenant_id = uuid.UUID(setup.json()["tenant_id"])
    assert str(tenant_id) == admin_session.admin_user["tenant_id"]
    assert admin_session.admin_user["role"] == "super_admin"
    engine = create_engine(value, hide_parameters=True)
    try:
        with engine.connect() as connection:
            owner = connection.execute(select(User.id).where(
                User.tenant_id == tenant_id, User.email == os.environ["TEST_ADMIN_EMAIL"],
                User.role == "super_admin", User.is_active.is_(True),
            )).scalar_one_or_none()
            if owner != uuid.UUID(admin_session.admin_user["id"]):
                pytest.fail("Database does not match the identified test API", pytrace=False)
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def tenant_id(api_prefix, admin_session):
    response = admin_session.get(f"{api_prefix}/setup/status", timeout=10)
    assert response.status_code == 200
    assert response.json()["tenant_id"] == admin_session.admin_user["tenant_id"]
    return uuid.UUID(response.json()["tenant_id"])


@pytest.fixture
def schema_database(auth_database, monkeypatch):
    from test_migrations import isolated_urls
    monkeypatch.setenv("SUPPLYOS_POSTGRES_MIGRATION_TESTS", "1")
    monkeypatch.setenv("TEST_DATABASE_URL_SYNC", os.environ["DATABASE_URL_SYNC"])
    with isolated_urls() as (sync_url, async_url):
        monkeypatch.setenv("DATABASE_URL_SYNC", sync_url)
        monkeypatch.setenv("DATABASE_URL", async_url)
        config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        engine = create_engine(sync_url, hide_parameters=True)
        try:
            yield engine, config
        finally:
            engine.dispose()


@pytest.fixture
def new_identity(api_prefix, tenant_id, admin_session):
    def create(*, email=None, password=None, tenant=None, implicit_tenant=False, owner=None):
        caller = owner if owner is not None else admin_session
        expected_tenant = uuid.UUID(caller.admin_user["tenant_id"])
        if tenant is not None and tenant != expected_tenant:
            pytest.fail("Customer fixture requires its own tenant's authenticated owner", pytrace=False)
        email = email or f"auth-{uuid.uuid4().hex}@example.com"
        password = password or secrets.token_urlsafe(24)
        payload = {"email": email, "password": password, "full_name": "Auth verification customer"}
        if not implicit_tenant:
            payload["tenant_id"] = str(expected_tenant)
        response = caller.post(f"{api_prefix}/auth/register-customer", json=payload, timeout=15)
        if response.status_code != 201:
            pytest.fail(f"Isolated customer creation failed (HTTP {response.status_code})", pytrace=False)
        body = response.json()
        assert set(body) == {"id", "tenant_id", "email", "full_name", "phone", "role", "is_active"}
        assert body["role"] == "customer"
        assert body["tenant_id"] == str(expected_tenant)
        assert response.headers["Cache-Control"] == "no-store"
        assert "Set-Cookie" not in response.headers
        assert not response.cookies
        return Identity(uuid.UUID(body["id"]), uuid.UUID(body["tenant_id"]), email, password)
    return create


@pytest.fixture
def identity(new_identity):
    return new_identity()


@pytest.fixture
def extra_tenant(auth_database):
    with Session(auth_database, expire_on_commit=False) as session:
        tenant = Tenant(name="Owned auth tenant", is_setup_complete=True)
        session.add(tenant)
        session.commit()
        identifier = tenant.id
    try:
        yield identifier
    finally:
        # Remove only our own temporary tenant; audit rows are never deleted.
        with auth_database.begin() as connection:
            connection.execute(delete(Tenant).where(Tenant.id == identifier))


@pytest.fixture
def extra_tenant_owner(extra_tenant, auth_database, api_prefix):
    email, password = f"owner-{uuid.uuid4().hex}@example.com", secrets.token_urlsafe(24)
    encoded = bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()
    with Session(auth_database, expire_on_commit=False) as database:
        actor = User(
            tenant_id=extra_tenant, email=email, password_hash=encoded,
            full_name="Owned auth tenant owner", role="super_admin", is_active=True,
            is_email_verified=False,
        )
        database.add(actor)
        database.commit()
        owner_id = actor.id
    with requests.Session() as owner:
        response = owner.post(f"{api_prefix}/auth/login", json={
            "email": email, "password": password, "tenant_id": str(extra_tenant),
        }, timeout=15)
        if response.status_code != 200:
            pytest.fail(f"Owned tenant login failed (HTTP {response.status_code})", pytrace=False)
        owner.admin_user = response.json()["user"]
        assert owner.admin_user["id"] == str(owner_id)
        assert owner.admin_user["tenant_id"] == str(extra_tenant)
        assert owner.admin_user["role"] == "super_admin"
        setup = owner.get(f"{api_prefix}/setup/status", timeout=10)
        assert setup.status_code == 200
        assert setup.json()["tenant_id"] == str(extra_tenant)
        yield owner


@pytest.fixture
def service_call(auth_database, security, monkeypatch):
    from app.features.auth import service
    monkeypatch.setattr(service, "settings", get_settings())
    async_url = make_url(os.environ["DATABASE_URL"])
    sync_url = make_url(os.environ["DATABASE_URL_SYNC"])
    if (async_url.host, async_url.port, async_url.database) != (sync_url.host, sync_url.port, sync_url.database):
        pytest.fail("Async auth database does not match the owned verifier", pytrace=False)

    def invoke(name, *args, **kwargs):
        async def run():
            engine = create_async_engine(async_url, poolclass=NullPool, hide_parameters=True)
            try:
                factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
                async with factory() as session:
                    result = await getattr(service, name)(session, *args, **kwargs)
                    if session.in_transaction() and session.is_active:
                        await session.commit()
                    return result
            finally:
                await engine.dispose()
        return asyncio.run(run())
    return invoke


def _login(api, identity, *, tenant_context=False):
    payload = {"email": identity.email, "password": identity.password}
    if tenant_context:
        payload["tenant_id"] = str(identity.tenant_id)
    response = requests.post(f"{api}/auth/login", json=payload, timeout=15)
    if response.status_code != 200:
        pytest.fail(f"Isolated login failed (HTTP {response.status_code})", pytrace=False)
    body = response.json()
    assert set(body) == {"user", "access_token", "token_type"}
    assert body["token_type"] == "bearer"
    assert body["user"]["id"] == str(identity.id)
    assert response.headers["Cache-Control"] == "no-store"
    return Tokens(body["access_token"], response.cookies["refresh_token"])


def _me(api, token):
    return requests.get(f"{api}/auth/me", headers={"Authorization": f"Bearer {token}"}, timeout=10)


def _refresh(api, token):
    return requests.post(f"{api}/auth/refresh", cookies={"refresh_token": token}, timeout=15)


def _cookie_flags(response):
    cookies = SimpleCookie()
    for header in response.raw.headers.getlist("Set-Cookie"):
        cookies.load(header)
    return {
        name: {key: cookie[key] for key in ("httponly", "samesite", "secure", "path", "max-age")}
        for name, cookie in cookies.items()
    }


def _changed(first, second):
    if first == second:
        pytest.fail("Rotation did not issue a distinct token", pytrace=False)


def _signed(security, payload):
    return jwt.encode(payload, security.settings.jwt_secret, algorithm=security.settings.jwt_algorithm)


def _active_sessions(engine, identity):
    with engine.connect() as connection:
        return connection.scalar(select(func.count()).select_from(RefreshToken).where(
            RefreshToken.user_id == identity.id, RefreshToken.revoked_at.is_(None),
        ))


def _locked_calls(engine, table, row_id, calls):
    """Prove each HTTP worker waits on our actual PostgreSQL row lock, then release it."""
    with engine.connect() as holder, ThreadPoolExecutor(max_workers=len(calls)) as workers:
        holder.execute(select(table.id).where(table.id == row_id).with_for_update())
        holder_pid = holder.scalar(select(func.pg_backend_pid()))
        pending = [workers.submit(call) for call in calls]
        blocked = False
        try:
            deadline = time.monotonic() + 8
            with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as observer:
                while time.monotonic() < deadline:
                    count = observer.scalar(text(
                        "WITH RECURSIVE waiters(pid) AS ("
                        "SELECT pid FROM pg_stat_activity WHERE wait_event_type = 'Lock' "
                        "AND :holder = ANY(pg_blocking_pids(pid)) UNION "
                        "SELECT activity.pid FROM pg_stat_activity activity JOIN waiters "
                        "ON waiters.pid = ANY(pg_blocking_pids(activity.pid)) "
                        "WHERE activity.wait_event_type = 'Lock') "
                        "SELECT count(*) FROM waiters"
                    ), {"holder": holder_pid})
                    if count >= len(calls):
                        blocked = True
                        break
                    time.sleep(0.01)
        finally:
            holder.rollback()
        responses = [future.result(timeout=20) for future in pending]
    if not blocked:
        pytest.fail("Concurrent auth workers did not wait on the real PostgreSQL lock", pytrace=False)
    return responses


def test_rotation_sets_both_new_cookies_and_preserves_active_access(
    api_prefix, base_url, identity, security, auth_database,
):
    tokens = _login(api_prefix, identity)
    before = security.decode_token(tokens.refresh)
    rotated = _refresh(f"{base_url}/api", tokens.refresh)
    assert rotated.status_code == 200
    assert set(rotated.json()) == {"access_token", "token_type"}
    assert rotated.json()["token_type"] == "bearer"
    replacement = rotated.cookies["refresh_token"]
    _changed(tokens.refresh, replacement)
    _changed(tokens.access, rotated.json()["access_token"])
    after = security.decode_token(replacement)
    assert before["sid"] == after["sid"]
    assert before["ver"] == after["ver"] == 0
    _changed(before["jti"], after["jti"])
    flags = _cookie_flags(rotated)
    assert set(flags) == {"access_token", "refresh_token"}
    for attributes in flags.values():
        assert attributes["httponly"] is True
        assert attributes["samesite"] == "lax"
        assert attributes["path"] == "/"
        assert int(attributes["max-age"]) > 0
    assert _me(api_prefix, tokens.access).status_code == 200
    assert _me(api_prefix, rotated.json()["access_token"]).status_code == 200
    assert _active_sessions(auth_database, identity) == 1
    with auth_database.connect() as connection:
        revoked = connection.scalar(select(RefreshToken.revoked_at).where(RefreshToken.jti == before["jti"]))
        assert revoked is not None
    again = _refresh(api_prefix, replacement)
    assert again.status_code == 200
    _changed(replacement, again.cookies["refresh_token"])


def test_refresh_reuse_durably_revokes_every_access_and_refresh_session(
    api_prefix, identity, new_identity, security, auth_database,
):
    first = _login(api_prefix, identity)
    second = _login(api_prefix, identity)
    unaffected = _login(api_prefix, new_identity())
    rotated = _refresh(api_prefix, first.refresh)
    assert rotated.status_code == 200
    reused = _refresh(api_prefix, first.refresh)
    assert reused.status_code == 401
    assert all(attributes["max-age"] == "0" for attributes in _cookie_flags(reused).values())
    assert _active_sessions(auth_database, identity) == 0
    for token in (first.access, second.access, rotated.json()["access_token"]):
        assert _me(api_prefix, token).status_code == 401
    assert _me(api_prefix, unaffected.access).status_code == 200
    with auth_database.connect() as connection:
        assert connection.scalar(select(User.session_version).where(User.id == identity.id)) == 1
        assert connection.scalar(select(func.count()).select_from(AuditLog).where(
            AuditLog.actor_id == identity.id, AuditLog.action == "auth.refresh_reuse",
        )) == 1
    assert _refresh(api_prefix, second.refresh).status_code == 401
    renewed = _login(api_prefix, identity)
    assert _me(api_prefix, renewed.access).status_code == 200
    assert security.decode_token(renewed.access)["ver"] > 0


def test_old_epoch_replays_cannot_revoke_new_authenticated_sessions(api_prefix, identity, security, auth_database):
    old = _login(api_prefix, identity)
    assert _refresh(api_prefix, old.refresh).status_code == 200
    assert _refresh(api_prefix, old.refresh).status_code == 401
    renewed = _login(api_prefix, identity)
    payload = security.decode_token(old.refresh)
    expired = {**payload, "exp": datetime.now(timezone.utc) - timedelta(seconds=1)}
    legacy = {key: value for key, value in expired.items() if key not in {"sid", "ver"}}
    for replay in (old.refresh, _signed(security, expired), _signed(security, legacy), old.refresh):
        assert _refresh(api_prefix, replay).status_code == 401
        assert _me(api_prefix, renewed.access).status_code == 200
    with auth_database.connect() as connection:
        assert connection.scalar(select(User.session_version).where(User.id == identity.id)) == 1
    assert _active_sessions(auth_database, identity) == 1
    assert _refresh(api_prefix, renewed.refresh).status_code == 200


def test_pre_reset_refresh_replay_does_not_revoke_post_reset_login(
    api_prefix, identity, security, auth_database, service_call,
):
    old = _login(api_prefix, identity)
    reset = service_call("create_password_reset", identity.email)
    password = secrets.token_urlsafe(24)
    response = requests.post(f"{api_prefix}/auth/reset-password", json={
        "token": reset, "new_password": password,
    }, timeout=15)
    assert response.status_code == 200
    renewed = _login(api_prefix, Identity(identity.id, identity.tenant_id, identity.email, password))
    for _ in range(2):
        assert _refresh(api_prefix, old.refresh).status_code == 401
        assert _me(api_prefix, renewed.access).status_code == 200
    with auth_database.connect() as connection:
        assert connection.scalar(select(User.session_version).where(User.id == identity.id)) == 1
    assert _active_sessions(auth_database, identity) == 1


@pytest.mark.parametrize("change", ["tenant", "role", "session", "version", "missing_session", "expiry", "type"],
                         ids=["tenant", "role", "session", "version", "unbound", "expired", "refresh_as_access"])
def test_access_requires_the_current_persisted_identity(api_prefix, identity, security, change):
    tokens = _login(api_prefix, identity)
    payload = security.decode_token(tokens.access)
    if change == "tenant":
        payload["tenant_id"] = str(uuid.uuid4())
    elif change == "role":
        payload["role"] = "super_admin"
    elif change == "session":
        payload["sid"] = str(uuid.uuid4())
    elif change == "version":
        payload["ver"] += 1
    elif change == "missing_session":
        payload.pop("sid")
        payload.pop("ver")
    elif change == "expiry":
        payload["exp"] = int(time.time()) - 60
    else:
        payload["type"] = "refresh"
    assert _me(api_prefix, _signed(security, payload)).status_code == 401


@pytest.mark.parametrize("change", ["sub", "tenant", "sid", "ver", "exp", "signature"],
                         ids=["malformed_user", "malformed_tenant", "malformed_session", "boolean_version", "missing_expiry", "bad_signature"])
def test_malformed_signed_tokens_fail_without_server_errors(api_prefix, identity, security, change):
    tokens = _login(api_prefix, identity)
    payload = security.decode_token(tokens.refresh)
    if change in {"sub", "tenant", "sid"}:
        payload[{"tenant": "tenant_id"}.get(change, change)] = "not-a-uuid"
    elif change == "ver":
        payload["ver"] = True
    elif change == "exp":
        payload.pop("exp")
    candidate = _signed(security, payload)
    if change == "signature":
        candidate = jwt.encode(payload, secrets.token_urlsafe(48), algorithm="HS256")
    assert _refresh(api_prefix, candidate).status_code == 401
    assert _me(api_prefix, tokens.access).status_code == 200


def test_cookie_and_bearer_transport_priority_remains_compatible(api_prefix, identity):
    tokens = _login(api_prefix, identity)
    assert _me(api_prefix, tokens.access).status_code == 200
    assert requests.get(f"{api_prefix}/auth/me", cookies={"access_token": tokens.access}, timeout=10).status_code == 200
    response = requests.get(f"{api_prefix}/auth/me", cookies={"access_token": "invalid"},
                            headers={"Authorization": f"Bearer {tokens.access}"}, timeout=10)
    assert response.status_code == 401


def test_wrong_credentials_record_durable_attempts_without_sessions(api_prefix, identity, auth_database):
    response = requests.post(f"{api_prefix}/auth/login", json={
        "email": identity.email, "password": secrets.token_urlsafe(24),
    }, timeout=15)
    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid credentials"}
    assert _active_sessions(auth_database, identity) == 0
    with auth_database.connect() as connection:
        assert connection.scalar(select(User.failed_login_attempts).where(User.id == identity.id)) == 1
        assert connection.scalar(select(func.count()).select_from(LoginAttempt).where(
            LoginAttempt.email == identity.email, LoginAttempt.success.is_(False),
        )) == 1


def test_lockout_counters_are_durable_and_reset_after_the_lock_expires(api_prefix, identity, auth_database):
    for _ in range(5):
        response = requests.post(f"{api_prefix}/auth/login", json={
            "email": identity.email, "password": secrets.token_urlsafe(24),
        }, timeout=15)
        assert response.status_code == 401
    locked = requests.post(f"{api_prefix}/auth/login", json={
        "email": identity.email, "password": identity.password,
    }, timeout=15)
    assert locked.status_code == 401
    with auth_database.begin() as connection:
        assert connection.scalar(select(User.failed_login_attempts).where(User.id == identity.id)) == 5
        connection.execute(update(User).where(User.id == identity.id).values(
            locked_until=datetime.now(timezone.utc) - timedelta(seconds=1),
        ))
    tokens = _login(api_prefix, identity)
    assert _me(api_prefix, tokens.access).status_code == 200
    with auth_database.connect() as connection:
        assert connection.scalar(select(User.failed_login_attempts).where(User.id == identity.id)) == 0


@pytest.mark.parametrize("endpoint,overpost", [
    ("login", {"role": "super_admin"}),
    ("register-customer", {"role": "super_admin"}),
    ("reset-password", {"role": "super_admin"}),
    ("forgot-password", {"role": "super_admin"}),
    ("register-customer", {"email_verified": True}),
    ("register-customer", {"is_email_verified": True}),
    ("register-customer", {"password_hash": "must-not-be-accepted"}),
], ids=["login", "register-customer", "reset-password", "forgot-password",
        "registration-email-verified", "registration-is-email-verified", "registration-hash"])
def test_auth_rejects_role_injection_and_redacts_validation_inputs(
    api_prefix, tenant_id, admin_session, endpoint, overpost,
):
    password = secrets.token_urlsafe(24)
    token = secrets.token_urlsafe(32)
    payload = {"email": f"unused-{uuid.uuid4().hex}@example.com", **overpost}
    if endpoint in {"login", "register-customer"}:
        payload["password"] = password
    if endpoint == "register-customer":
        payload.update(full_name="Unused", tenant_id=str(tenant_id))
    if endpoint == "reset-password":
        payload = {"token": token, "new_password": password, **overpost}
    caller = admin_session if endpoint == "register-customer" else requests
    response = caller.post(f"{api_prefix}/auth/{endpoint}", json=payload, timeout=15)
    assert response.status_code == 422
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json() == {"detail": [{
        "loc": ["body"], "msg": "Invalid request data", "type": "value_error",
    }]}
    assert all("input" not in error and "ctx" not in error for error in response.json()["detail"])
    assert "Set-Cookie" not in response.headers
    if password in response.text or token in response.text:
        pytest.fail("Auth validation echoed credentials", pytrace=False)


def test_password_validation_errors_do_not_echo_passwords_or_reset_secrets(api_prefix, admin_session):
    password, token = secrets.token_urlsafe(6), secrets.token_urlsafe(32)
    for endpoint, payload in (
        ("register-customer", {"email": "unused@example.com", "full_name": "Unused", "password": password}),
        ("reset-password", {"token": token, "new_password": password}),
    ):
        caller = admin_session if endpoint == "register-customer" else requests
        response = caller.post(f"{api_prefix}/auth/{endpoint}", json=payload, timeout=15)
        assert response.status_code == 422
        assert response.headers["Cache-Control"] == "no-store"
        assert response.json() == {"detail": [{
            "loc": ["body"], "msg": "Invalid request data", "type": "value_error",
        }]}
        assert "Set-Cookie" not in response.headers
        if password in response.text or token in response.text:
            pytest.fail("Password validation echoed a secret", pytrace=False)


def test_existing_short_password_hash_remains_usable_through_login(api_prefix, identity, auth_database):
    password = secrets.token_urlsafe(6)
    encoded = bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=4)).decode()
    with auth_database.begin() as connection:
        connection.execute(update(User).where(User.id == identity.id).values(password_hash=encoded))
    legacy = Identity(identity.id, identity.tenant_id, identity.email, password)
    assert _me(api_prefix, _login(api_prefix, legacy).access).status_code == 200
    with auth_database.connect() as connection:
        if connection.scalar(select(User.password_hash).where(User.id == identity.id)) != encoded:
            pytest.fail("Login unexpectedly replaced an existing password hash", pytrace=False)


def test_single_tenant_registration_and_unique_email_login_need_no_new_context(
    schema_database, service_call, security,
):
    from app.features.auth.schemas import LoginRequest, RegisterCustomerRequest
    from app.infrastructure.db.models.customer import Customer
    from app.shared.deps import get_current_user
    from starlette.requests import Request
    engine, config = schema_database
    command.upgrade(config, "head")
    owner_password = secrets.token_urlsafe(24)
    owner_hash = bcrypt.hashpw(owner_password.encode(), bcrypt.gensalt(rounds=12)).decode()
    with Session(engine, expire_on_commit=False) as session:
        tenant = Tenant(name="Sole initialized tenant", is_setup_complete=True)
        session.add(tenant)
        session.flush()
        actor = User(
            tenant_id=tenant.id, email=f"owner-{uuid.uuid4().hex}@example.com",
            password_hash=owner_hash, full_name="Sole tenant owner", role="super_admin",
            is_active=True, is_email_verified=False,
        )
        session.add(actor)
        session.commit()
        expected_tenant = tenant.id
    email, password = f"sole-{uuid.uuid4().hex}@example.com", secrets.token_urlsafe(24)
    user = service_call("register_customer", RegisterCustomerRequest(
        email=email, password=password, full_name="Sole tenant customer",
    ), "127.0.0.1", actor=actor)
    assert user.tenant_id == expected_tenant
    assert user.role == "customer"
    assert user.is_email_verified is False
    with engine.connect() as connection:
        assert connection.scalar(select(User.tenant_id).where(User.id == user.id)) == expected_tenant
        assert connection.scalar(select(Customer.tenant_id).where(
            Customer.id == user.customer_id,
        )) == expected_tenant
        assert connection.scalar(select(Customer.credit_limit).where(Customer.id == user.customer_id)) == 0
        assert connection.scalar(select(func.count()).select_from(RefreshToken).where(
            RefreshToken.user_id == user.id,
        )) == 0
    _, access, _, _ = service_call("authenticate", LoginRequest(email=email, password=password),
                                  "127.0.0.1", "test")
    async def check_session():
        database = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool,
                                       hide_parameters=True)
        try:
            factory = async_sessionmaker(database, expire_on_commit=False)
            async with factory() as session:
                request = Request({"type": "http", "headers": [
                    (b"authorization", f"Bearer {access}".encode()),
                ]})
                return (await get_current_user(request, session)).id
        finally:
            await database.dispose()
    assert asyncio.run(check_session()) == user.id


def test_registration_requires_unambiguous_initialized_tenant_context(
    api_prefix, tenant_id, extra_tenant, extra_tenant_owner, new_identity, auth_database, admin_session,
):
    from app.infrastructure.db.models.customer import Customer
    payload = {"email": f"ambiguous-{uuid.uuid4().hex}@example.com",
               "password": secrets.token_urlsafe(24), "full_name": "Unused"}
    for context in (None, tenant_id, extra_tenant):
        body = {**payload, "tenant_id": str(context)} if context is not None else payload
        response = requests.post(f"{api_prefix}/auth/register-customer", json=body, timeout=15)
        assert response.status_code == 401
        assert response.headers["Cache-Control"] == "no-store"
        assert "Set-Cookie" not in response.headers
    for owner, context in ((admin_session, extra_tenant), (extra_tenant_owner, tenant_id)):
        response = owner.post(f"{api_prefix}/auth/register-customer", json={
            **payload, "tenant_id": str(context),
        }, timeout=15)
        assert response.status_code == 403
        assert response.headers["Cache-Control"] == "no-store"
        assert "Set-Cookie" not in response.headers
    with auth_database.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(User).where(User.email == payload["email"])) == 0
        assert connection.scalar(select(func.count()).select_from(Customer).where(
            Customer.email == payload["email"],
        )) == 0
    first = new_identity(tenant=tenant_id, implicit_tenant=True)
    second = new_identity(tenant=extra_tenant, implicit_tenant=True, owner=extra_tenant_owner)
    assert first.tenant_id == tenant_id
    assert second.tenant_id == extra_tenant
    assert _me(api_prefix, _login(api_prefix, first).access).status_code == 200


def test_duplicate_cross_tenant_emails_require_context_for_login_and_reset(
    api_prefix, extra_tenant, extra_tenant_owner, new_identity, service_call, auth_database,
):
    email = f"shared-{uuid.uuid4().hex}@example.com"
    first = new_identity(email=email)
    second = new_identity(email=email, tenant=extra_tenant, owner=extra_tenant_owner)
    for identity in (first, second):
        response = requests.post(f"{api_prefix}/auth/login", json={
            "email": email, "password": identity.password,
        }, timeout=15)
        assert response.status_code == 401
        assert response.json() == {"detail": "Invalid credentials"}
        assert _login(api_prefix, identity, tenant_context=True)
    assert service_call("create_password_reset", email) is None
    token = service_call("create_password_reset", email, first.tenant_id)
    if token is None:
        pytest.fail("Explicit tenant identity did not resolve for reset", pytrace=False)
    with auth_database.connect() as connection:
        owners = connection.execute(select(PasswordResetToken.user_id).where(
            PasswordResetToken.user_id.in_([first.id, second.id]),
        )).scalars().all()
        assert owners == [first.id]


def test_registration_rejects_unknown_or_uninitialized_tenants(
    api_prefix, extra_tenant, extra_tenant_owner, auth_database, admin_session,
):
    from app.infrastructure.db.models.customer import Customer
    with auth_database.begin() as connection:
        connection.execute(update(Tenant).where(Tenant.id == extra_tenant).values(is_setup_complete=False))
    for context in (uuid.uuid4(), extra_tenant):
        payload = {
            "email": f"unused-{uuid.uuid4().hex}@example.com", "password": secrets.token_urlsafe(24),
            "full_name": "Unused", "tenant_id": str(context),
        }
        for caller, expected in ((requests, 401), (admin_session, 403)):
            response = caller.post(f"{api_prefix}/auth/register-customer", json=payload, timeout=15)
            assert response.status_code == expected
            assert response.headers["Cache-Control"] == "no-store"
            assert "Set-Cookie" not in response.headers
        if context == extra_tenant:
            for body in (payload, {key: value for key, value in payload.items() if key != "tenant_id"}):
                response = extra_tenant_owner.post(
                    f"{api_prefix}/auth/register-customer", json=body, timeout=15,
                )
                assert response.status_code == 400
                assert response.headers["Cache-Control"] == "no-store"
                assert "Set-Cookie" not in response.headers
        with auth_database.connect() as connection:
            assert connection.scalar(select(func.count()).select_from(User).where(
                User.email == payload["email"],
            )) == 0
            assert connection.scalar(select(func.count()).select_from(Customer).where(
                Customer.email == payload["email"],
            )) == 0


@pytest.mark.parametrize("transport", ["refresh_cookie", "access_cookie", "bearer"])
def test_logout_revokes_its_session_even_when_signed_tokens_are_expired(
    api_prefix, identity, security, auth_database, transport,
):
    tokens = _login(api_prefix, identity)
    other = _login(api_prefix, identity)
    access = security.decode_token(tokens.access)
    refresh = security.decode_token(tokens.refresh)
    access["exp"] = refresh["exp"] = int(time.time()) - 60
    options = {}
    if transport == "refresh_cookie":
        options["cookies"] = {"access_token": _signed(security, access), "refresh_token": _signed(security, refresh)}
    elif transport == "access_cookie":
        options["cookies"] = {"access_token": _signed(security, access)}
    else:
        options["headers"] = {"Authorization": f"Bearer {_signed(security, access)}"}
    response = requests.post(f"{api_prefix}/auth/logout", timeout=15, **options)
    assert response.status_code == 200
    assert response.json() == {"message": "Logged out"}
    assert set(_cookie_flags(response)) == {"access_token", "refresh_token"}
    assert all(attributes["max-age"] == "0" for attributes in _cookie_flags(response).values())
    assert _me(api_prefix, tokens.access).status_code == 401
    assert _me(api_prefix, other.access).status_code == 200
    assert _active_sessions(auth_database, identity) == 1


def test_logout_with_a_rotated_old_refresh_revokes_only_its_family(api_prefix, identity):
    first = _login(api_prefix, identity)
    other = _login(api_prefix, identity)
    rotated = _refresh(api_prefix, first.refresh)
    assert rotated.status_code == 200
    response = requests.post(f"{api_prefix}/auth/logout", cookies={"refresh_token": first.refresh}, timeout=15)
    assert response.status_code == 200
    assert _me(api_prefix, rotated.json()["access_token"]).status_code == 401
    assert _me(api_prefix, other.access).status_code == 200


def test_anonymous_or_invalid_logout_still_clears_cookies(api_prefix):
    response = requests.post(f"{api_prefix}/auth/logout", cookies={
        "access_token": "invalid", "refresh_token": "invalid",
    }, timeout=15)
    assert response.status_code == 200
    assert all(attributes["max-age"] == "0" for attributes in _cookie_flags(response).values())


def test_persisted_session_expiry_invalidates_access_and_refresh(api_prefix, identity, security, auth_database):
    tokens = _login(api_prefix, identity)
    sid = uuid.UUID(security.decode_token(tokens.refresh)["sid"])
    with auth_database.begin() as connection:
        connection.execute(update(RefreshToken).where(RefreshToken.session_id == sid).values(
            expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        ))
    assert _me(api_prefix, tokens.access).status_code == 401
    assert _refresh(api_prefix, tokens.refresh).status_code == 401
    assert _active_sessions(auth_database, identity) == 0


def test_expired_refresh_cannot_renew_but_consumed_jti_reuse_still_revokes_globally(
    api_prefix, identity, security, auth_database,
):
    tokens = _login(api_prefix, identity)
    other = _login(api_prefix, identity)
    payload = security.decode_token(tokens.refresh)
    payload["exp"] = int(time.time()) - 60
    expired = _signed(security, payload)
    assert _refresh(api_prefix, expired).status_code == 401
    assert _me(api_prefix, other.access).status_code == 200
    assert _refresh(api_prefix, expired).status_code == 401
    assert _active_sessions(auth_database, identity) == 0
    assert _me(api_prefix, other.access).status_code == 401


@pytest.mark.parametrize("change", ["inactive", "role", "version"])
def test_current_user_state_invalidates_stale_identity_tokens(api_prefix, identity, auth_database, change):
    tokens = _login(api_prefix, identity)
    values = {"inactive": {"is_active": False}, "role": {"role": "accountant"}, "version": {"session_version": 1}}
    with auth_database.begin() as connection:
        connection.execute(update(User).where(User.id == identity.id).values(**values[change]))
    assert _me(api_prefix, tokens.access).status_code == 401
    assert _refresh(api_prefix, tokens.refresh).status_code == 401
    assert _active_sessions(auth_database, identity) == 0


def test_legacy_refresh_can_upgrade_but_unbound_access_cannot_bypass_revocation(
    api_prefix, identity, security, auth_database,
):
    tokens = _login(api_prefix, identity)
    payload = security.decode_token(tokens.refresh)
    payload.pop("sid")
    payload.pop("ver")
    old = _signed(security, payload)
    upgraded = _refresh(api_prefix, old)
    assert upgraded.status_code == 200
    assert security.decode_token(upgraded.cookies["refresh_token"])["sid"]
    assert _refresh(api_prefix, old).status_code == 401
    assert _active_sessions(auth_database, identity) == 0
    assert _me(api_prefix, upgraded.json()["access_token"]).status_code == 401


def test_password_reset_consumes_once_and_revokes_all_sessions_without_plaintext_storage(
    api_prefix, identity, service_call, auth_database, caplog,
):
    sessions = [_login(api_prefix, identity), _login(api_prefix, identity)]
    token = service_call("create_password_reset", identity.email)
    if token is None:
        pytest.fail("Reset service did not create a test token", pytrace=False)
    digest = "sha256:" + hashlib.sha256(token.encode()).hexdigest()
    new_password = secrets.token_urlsafe(24)
    with auth_database.connect() as connection:
        stored = connection.scalar(select(PasswordResetToken.token).where(PasswordResetToken.user_id == identity.id))
        if stored != digest or stored == token:
            pytest.fail("Reset secret was not stored as a digest", pytrace=False)
    response = requests.post(f"{api_prefix}/auth/reset-password", json={
        "token": token, "new_password": new_password,
    }, timeout=15)
    assert response.status_code == 200
    assert response.json() == {"message": "Password reset successful"}
    flags = _cookie_flags(response)
    assert set(flags) == {"access_token", "refresh_token"}
    assert all(cookie["max-age"] == "0" and cookie["httponly"] for cookie in flags.values())
    assert _active_sessions(auth_database, identity) == 0
    for session in sessions:
        assert _me(api_prefix, session.access).status_code == 401
    reused = requests.post(f"{api_prefix}/auth/reset-password", json={
        "token": token, "new_password": secrets.token_urlsafe(24),
    }, timeout=15)
    assert reused.status_code == 400
    old_login = requests.post(f"{api_prefix}/auth/login", json={
        "email": identity.email, "password": identity.password,
    }, timeout=15)
    assert old_login.status_code == 401
    renewed = _login(api_prefix, Identity(identity.id, identity.tenant_id, identity.email, new_password))
    assert _me(api_prefix, renewed.access).status_code == 200
    if token in caplog.text:
        pytest.fail("Reset service logged the plaintext secret", pytrace=False)


def test_expired_and_unknown_reset_tokens_do_not_change_password_or_sessions(
    api_prefix, identity, service_call, auth_database,
):
    tokens = _login(api_prefix, identity)
    token = service_call("create_password_reset", identity.email)
    with auth_database.begin() as connection:
        connection.execute(update(PasswordResetToken).where(PasswordResetToken.user_id == identity.id).values(
            expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        ))
    for candidate, status in ((token, 400), (secrets.token_urlsafe(32), 404)):
        response = requests.post(f"{api_prefix}/auth/reset-password", json={
            "token": candidate, "new_password": secrets.token_urlsafe(24),
        }, timeout=15)
        assert response.status_code == status
    assert _me(api_prefix, tokens.access).status_code == 200
    assert _active_sessions(auth_database, identity) == 1
    assert _login(api_prefix, identity)


def test_reset_digest_is_not_itself_a_redeemable_bearer_secret(api_prefix, identity, service_call, auth_database):
    token = service_call("create_password_reset", identity.email)
    with auth_database.connect() as connection:
        digest = connection.scalar(select(PasswordResetToken.token).where(PasswordResetToken.user_id == identity.id))
    response = requests.post(f"{api_prefix}/auth/reset-password", json={
        "token": digest, "new_password": secrets.token_urlsafe(24),
    }, timeout=15)
    assert response.status_code == 404
    successful = requests.post(f"{api_prefix}/auth/reset-password", json={
        "token": token, "new_password": secrets.token_urlsafe(24),
    }, timeout=15)
    assert successful.status_code == 200


def test_legacy_reset_links_remain_single_use(api_prefix, identity, auth_database):
    token = secrets.token_urlsafe(32)
    with Session(auth_database) as session:
        session.add(PasswordResetToken(user_id=identity.id, token=token,
                                      expires_at=datetime.now(timezone.utc) + timedelta(hours=1)))
        session.commit()
    response = requests.post(f"{api_prefix}/auth/reset-password", json={
        "token": token, "new_password": secrets.token_urlsafe(24),
    }, timeout=15)
    assert response.status_code == 200
    reused = requests.post(f"{api_prefix}/auth/reset-password", json={
        "token": token, "new_password": secrets.token_urlsafe(24),
    }, timeout=15)
    assert reused.status_code == 400


def test_requesting_a_new_reset_invalidates_the_previous_link(api_prefix, identity, service_call):
    first = service_call("create_password_reset", identity.email)
    second = service_call("create_password_reset", identity.email)
    for token, expected in ((first, 400), (second, 200)):
        response = requests.post(f"{api_prefix}/auth/reset-password", json={
            "token": token, "new_password": secrets.token_urlsafe(24),
        }, timeout=15)
        assert response.status_code == expected


@pytest.mark.parametrize("state", [
    "active", "unscoped", "wrong_tenant", "inactive", "used", "expired",
    "cached_email_changed", "customer_contact_changed",
])
def test_reset_email_recipient_uses_current_auth_identity_on_postgres(
    identity, auth_database, service_call, state,
):
    from app.features.auth import repositories
    from app.infrastructure.db.models.customer import Customer

    token = service_call("create_password_reset", identity.email, identity.tenant_id)
    if token is None:
        pytest.fail("Owned reset issuance failed", pytrace=False)
    digest = hashlib.sha256(token.encode()).hexdigest()
    now = datetime.now(timezone.utc)
    with auth_database.begin() as connection:
        if state == "inactive":
            connection.execute(update(User).where(User.id == identity.id).values(is_active=False))
        elif state in {"used", "expired"}:
            values = {"used_at": now} if state == "used" else {"expires_at": now - timedelta(seconds=1)}
            connection.execute(update(PasswordResetToken).where(
                PasswordResetToken.token == f"sha256:{digest}",
            ).values(**values))
        elif state == "customer_contact_changed":
            customer_id = connection.scalar(select(User.customer_id).where(User.id == identity.id))
            if customer_id is None:
                pytest.fail("Owned customer account has no customer binding", pytrace=False)
            connection.execute(update(Customer).where(
                Customer.id == customer_id, Customer.tenant_id == identity.tenant_id,
            ).values(email=f"contact-{uuid.uuid4().hex}@example.com"))

    async def lookup():
        engine = create_async_engine(make_url(os.environ["DATABASE_URL"]), poolclass=NullPool, hide_parameters=True)
        try:
            factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
            async with factory() as session:
                if state == "cached_email_changed":
                    cached_user = await session.get(User, identity.id)
                    with auth_database.begin() as connection:
                        connection.execute(update(User).where(User.id == identity.id).values(
                            email=f"changed-{uuid.uuid4().hex}@example.com",
                        ))
                    if cached_user is None or cached_user.email != identity.email:
                        pytest.fail("Recipient regression did not retain the pre-change ORM identity", pytrace=False)
                tenant = None if state == "unscoped" else (
                    uuid.uuid4() if state == "wrong_tenant" else identity.tenant_id
                )
                return await repositories.password_reset_recipient(
                    session, digest=digest, email=identity.email, tenant_id=tenant, now=now,
                )
        finally:
            await engine.dispose()

    expected = identity.email if state in {"active", "unscoped", "customer_contact_changed"} else None
    if asyncio.run(lookup()) != expected:
        pytest.fail("Reset recipient did not enforce current auth ownership/token state", pytrace=False)


def test_disabled_forgot_password_never_creates_a_token_or_claims_delivery(
    api_prefix, identity, auth_database,
):
    response = requests.post(f"{api_prefix}/auth/forgot-password", json={
        "email": identity.email, "tenant_id": str(identity.tenant_id),
    }, timeout=15)
    assert response.status_code == 503
    with auth_database.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(PasswordResetToken).where(
            PasswordResetToken.user_id == identity.id,
        )) == 0


def test_same_refresh_jti_is_single_use_under_observed_pg_contention(api_prefix, identity, auth_database):
    original = _login(api_prefix, identity)
    second_session = _login(api_prefix, identity)
    responses = _locked_calls(auth_database, User, identity.id, [
        lambda: _refresh(api_prefix, original.refresh), lambda: _refresh(api_prefix, original.refresh),
    ])
    assert sorted(response.status_code for response in responses) == [200, 401]
    winner = next(response for response in responses if response.status_code == 200)
    assert _active_sessions(auth_database, identity) == 0
    assert _me(api_prefix, winner.json()["access_token"]).status_code == 401
    assert _me(api_prefix, second_session.access).status_code == 401
    assert _refresh(api_prefix, winner.cookies["refresh_token"]).status_code == 401


def test_distinct_sessions_rotate_safely_under_observed_pg_contention(api_prefix, identity, auth_database):
    first = _login(api_prefix, identity)
    second = _login(api_prefix, identity)
    responses = _locked_calls(auth_database, User, identity.id, [
        lambda: _refresh(api_prefix, first.refresh), lambda: _refresh(api_prefix, second.refresh),
    ])
    assert [response.status_code for response in responses] == [200, 200]
    assert _active_sessions(auth_database, identity) == 2
    for response in responses:
        assert _me(api_prefix, response.json()["access_token"]).status_code == 200


def test_reset_is_single_use_under_observed_pg_contention(
    api_prefix, identity, service_call, auth_database,
):
    original = _login(api_prefix, identity)
    token = service_call("create_password_reset", identity.email)
    def reset():
        return requests.post(f"{api_prefix}/auth/reset-password", json={
            "token": token, "new_password": secrets.token_urlsafe(24),
        }, timeout=15)
    responses = _locked_calls(auth_database, User, identity.id, [reset, reset])
    assert sorted(response.status_code for response in responses) == [200, 400]
    assert _active_sessions(auth_database, identity) == 0
    assert _me(api_prefix, original.access).status_code == 401
    with auth_database.connect() as connection:
        assert connection.scalar(select(User.session_version).where(User.id == identity.id)) == 1


def test_duplicate_registration_is_atomic_under_observed_pg_contention(
    api_prefix, tenant_id, auth_database, admin_session,
):
    from app.infrastructure.db.models.customer import Customer
    email = f"concurrent-{uuid.uuid4().hex}@example.com"
    payload = {"email": email, "password": secrets.token_urlsafe(24),
               "full_name": "Concurrent customer", "tenant_id": str(tenant_id)}
    headers = {"Authorization": admin_session.headers["Authorization"]}
    def register():
        return requests.post(
            f"{api_prefix}/auth/register-customer", json=payload, headers=headers, timeout=15,
        )
    responses = _locked_calls(auth_database, Tenant, tenant_id, [register, register])
    assert sorted(response.status_code for response in responses) == [201, 409]
    for response in responses:
        assert response.headers["Cache-Control"] == "no-store"
        assert "Set-Cookie" not in response.headers
    with auth_database.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(User).where(User.email == email)) == 1
        assert connection.scalar(select(func.count()).select_from(Customer).where(Customer.email == email)) == 1
        assert connection.scalar(select(User.tenant_id).where(User.email == email)) == tenant_id
        assert connection.scalar(select(Customer.tenant_id).where(Customer.email == email)) == tenant_id


@pytest.mark.parametrize("operation", ["refresh", "reset"])
def test_auth_write_failure_rolls_back_every_session_and_password_change(
    api_prefix, identity, service_call, auth_database, monkeypatch, operation,
):
    from app.features.auth import service
    original = _login(api_prefix, identity)
    token = service_call("create_password_reset", identity.email) if operation == "reset" else None
    async def fail_audit(*args, **kwargs):
        raise RuntimeError("Forced audit failure")
    with monkeypatch.context() as patch:
        patch.setattr(service, "audit", fail_audit)
        with pytest.raises(RuntimeError, match="Forced audit failure"):
            if operation == "refresh":
                service_call("refresh_access", original.refresh)
            else:
                service_call("reset_password", token, secrets.token_urlsafe(24))
    assert _active_sessions(auth_database, identity) == 1
    assert _me(api_prefix, original.access).status_code == 200
    assert _login(api_prefix, identity)
    with auth_database.connect() as connection:
        assert connection.scalar(select(User.session_version).where(User.id == identity.id)) == 0
        if operation == "reset":
            assert connection.scalar(select(PasswordResetToken.used_at).where(
                PasswordResetToken.user_id == identity.id,
            )) is None
    assert _refresh(api_prefix, original.refresh).status_code == 200


def test_auth_audit_metadata_contains_no_credentials_or_tokens(
    api_prefix, identity, service_call, auth_database,
):
    original = _login(api_prefix, identity)
    rotated = _refresh(api_prefix, original.refresh)
    assert rotated.status_code == 200
    assert _refresh(api_prefix, original.refresh).status_code == 401
    token = service_call("create_password_reset", identity.email)
    new_password = secrets.token_urlsafe(24)
    response = requests.post(f"{api_prefix}/auth/reset-password", json={
        "token": token, "new_password": new_password,
    }, timeout=15)
    assert response.status_code == 200
    with auth_database.connect() as connection:
        values = connection.execute(select(AuditLog.metadata_json).where(AuditLog.actor_id == identity.id)).scalars().all()
    serialized = json.dumps(values)
    sensitive = (identity.password, new_password, original.access, original.refresh, token)
    if any(value in serialized for value in sensitive):
        pytest.fail("Auth audit metadata contains a credential or token", pytrace=False)


def test_auth_revision_backfills_legacy_sessions_and_downgrades_without_data_loss(schema_database):
    engine, config = schema_database
    command.upgrade(config, "20261108_0001")
    metadata = MetaData()
    tenants = Table("tenants", metadata, autoload_with=engine)
    users = Table("users", metadata, autoload_with=engine)
    refresh = Table("refresh_tokens", metadata, autoload_with=engine)
    tenant_id, user_id, refresh_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    legacy_hash = bcrypt.hashpw(secrets.token_urlsafe(6).encode(), bcrypt.gensalt(rounds=4)).decode()
    with engine.begin() as connection:
        connection.execute(tenants.insert().values(
            id=tenant_id, name="Legacy auth tenant", currency="INR", is_setup_complete=True, settings={},
        ))
        connection.execute(users.insert().values(
            id=user_id, tenant_id=tenant_id, email="legacy@example.com", password_hash=legacy_hash,
            full_name="Legacy account", role="customer", is_active=True, is_email_verified=False,
            failed_login_attempts=0,
        ))
        connection.execute(refresh.insert().values(
            id=refresh_id, user_id=user_id, jti=str(uuid.uuid4()),
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        ))
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT session_version FROM users")) == 0
        assert connection.scalar(text("SELECT session_id FROM refresh_tokens")) == refresh_id
    command.downgrade(config, "20261108_0001")
    with engine.connect() as connection:
        assert "session_version" not in {column["name"] for column in inspect(connection).get_columns("users")}
        assert "session_id" not in {column["name"] for column in inspect(connection).get_columns("refresh_tokens")}
        if connection.scalar(text("SELECT password_hash FROM users")) != legacy_hash:
            pytest.fail("Auth migration changed an existing password hash", pytrace=False)
        assert connection.scalar(text("SELECT count(*) FROM refresh_tokens")) == 1
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT session_id FROM refresh_tokens")) == refresh_id
