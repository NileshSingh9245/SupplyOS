"""Own-password privacy, durable reauthentication and real PostgreSQL lock races."""
from __future__ import annotations

import asyncio
import os
import secrets
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field, fields
from datetime import datetime, timedelta, timezone
from http.cookies import SimpleCookie

import bcrypt
import httpx
import jwt
import pytest
import requests
from fastapi import FastAPI
from pydantic import ValidationError
from sqlalchemy import create_engine, event, func, select, text, update
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.infrastructure.db.models.tenant import Tenant
from app.infrastructure.db.models.user import AuditLog, LoginAttempt, PasswordResetToken, RefreshToken, User

pytestmark = pytest.mark.integration
ROLES = ("super_admin", "warehouse_manager", "accountant", "delivery_partner", "customer")
INVALID_DATA = {"detail": [{
    "loc": ["body"], "msg": "Invalid request data", "type": "value_error",
}]}
SUCCESS = {"message": "Password changed. Sign in again."}


class PrivateText(str):
    def __repr__(self) -> str:
        return "<redacted>"


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


@dataclass(frozen=True, repr=False)
class Snapshot:
    password_hash: str
    failed_attempts: int
    locked_until: datetime | None
    epoch: int
    sessions: tuple
    resets: tuple
    audits: tuple
    attempts: tuple


@pytest.fixture(autouse=True)
def require_owned_environment():
    if os.environ.get("SUPPLYOS_OWNED_TEST_ENV") != "1":
        pytest.skip("Password change tests require the owned disposable verifier")


@pytest.fixture(scope="module")
def password_database(base_url, admin_session):
    sync = make_url(os.environ.get("DATABASE_URL_SYNC", ""))
    asynchronous = make_url(os.environ.get("DATABASE_URL", ""))
    if (
        os.environ.get("SUPPLYOS_OWNED_TEST_ENV") != "1"
        or os.environ.get("APP_ENV") != "test"
        or os.environ.get("SUPPLYOS_ALLOW_API_WRITE_TESTS") != "1"
        or sync.drivername != "postgresql+psycopg2"
        or asynchronous.drivername != "postgresql+asyncpg"
        or sync.host not in {"127.0.0.1", "localhost", "::1"}
        or not (sync.database or "").startswith("supplyos_test_")
        or (sync.host, sync.port, sync.database)
        != (asynchronous.host, asynchronous.port, asynchronous.database)
    ):
        pytest.fail("Password tests require the matched owned PostgreSQL/API", pytrace=False)
    tenant_id = uuid.UUID(admin_session.admin_user["tenant_id"])
    engine = create_engine(sync, hide_parameters=True)
    try:
        with engine.connect() as connection:
            owner = connection.scalar(select(User.id).where(
                User.id == uuid.UUID(admin_session.admin_user["id"]), User.tenant_id == tenant_id,
                User.email == os.environ["TEST_ADMIN_EMAIL"], User.role == "super_admin",
            ))
            if owner is None:
                pytest.fail("Password database does not match the owned API identity", pytrace=False)
        yield Database(engine, tenant_id)
    finally:
        engine.dispose()


@pytest.fixture
def make_identity(password_database):
    from app.core.security import hash_password

    def create(*, role="warehouse_manager", tenant_id=None, password=None, legacy=False):
        password = PrivateText(password if password is not None else secrets.token_urlsafe(24))
        encoded = (
            bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=4)).decode("utf-8")
            if legacy else hash_password(password)
        )
        with Session(password_database.engine, expire_on_commit=False) as db:
            user = User(
                tenant_id=tenant_id or password_database.tenant_id,
                email=f"own-password-{uuid.uuid4().hex}@example.com", password_hash=encoded,
                full_name="Synthetic own-password holder", role=role, is_active=True,
                is_email_verified=False,
            )
            db.add(user)
            db.commit()
            return Identity(user.id, user.tenant_id, user.email, password)
    return create


@pytest.fixture
def identity(make_identity):
    return make_identity()


@pytest.fixture
def new_password():
    return PrivateText(secrets.token_urlsafe(24))


def _login(api, identity, password=None):
    response = requests.post(f"{api}/auth/login", json={
        "email": identity.email, "password": identity.password if password is None else password,
        "tenant_id": str(identity.tenant_id),
    }, timeout=20)
    if response.status_code != 200:
        pytest.fail(f"Synthetic holder login failed (HTTP {response.status_code})", pytrace=False)
    return Tokens(response.json()["access_token"], response.cookies["refresh_token"])


def _body(identity, replacement, **changes):
    return {"current_password": identity.password, "new_password": replacement, **changes}


def _change(api, tokens, payload, **options):
    headers = options.pop("headers", {})
    if tokens is not None:
        headers.setdefault("Authorization", f"Bearer {tokens.access}")
    return requests.post(f"{api}/auth/change-password", json=payload, headers=headers,
                         timeout=20, **options)


def _me(api, tokens):
    return requests.get(f"{api}/auth/me", headers={
        "Authorization": f"Bearer {tokens.access}",
    }, timeout=15)


def _refresh(api, tokens):
    return requests.post(f"{api}/auth/refresh", cookies={
        "refresh_token": tokens.refresh,
    }, timeout=20)


def _safe(response, *private_inputs, clears=False):
    assert response.headers["Cache-Control"] == "no-store"
    if any(value and value in response.text for value in private_inputs if isinstance(value, str)):
        pytest.fail("Own-password response exposed a private input", pytrace=False)
    if not clears:
        assert "set-cookie" not in response.headers
        return
    cookies = SimpleCookie()
    headers = (
        response.headers.get_list("set-cookie") if isinstance(response, httpx.Response)
        else response.raw.headers.getlist("Set-Cookie")
    )
    for header in headers:
        cookies.load(header)
    assert set(cookies) == {"access_token", "refresh_token"}
    for cookie in cookies.values():
        assert cookie.value == "" and cookie["max-age"] == "0"
        assert cookie["httponly"] is True and cookie["samesite"] == "lax"
        assert cookie["path"] == "/"


def _expect(response, code, body=None):
    if response.status_code != code:
        pytest.fail(f"Expected HTTP {code}, received HTTP {response.status_code}", pytrace=False)
    if body is not None and response.json() != body:
        pytest.fail("Unexpected own-password response body (redacted)", pytrace=False)


def _snapshot(database, identifier):
    with database.engine.connect() as connection:
        user = connection.execute(select(
            User.password_hash, User.failed_login_attempts, User.locked_until, User.session_version,
        ).where(User.id == identifier)).one()
        sessions = tuple(connection.execute(select(
            RefreshToken.id, RefreshToken.expires_at, RefreshToken.revoked_at,
        ).where(RefreshToken.user_id == identifier).order_by(RefreshToken.id)).all())
        resets = tuple(connection.execute(select(
            PasswordResetToken.id, PasswordResetToken.used_at,
        ).where(PasswordResetToken.user_id == identifier).order_by(PasswordResetToken.id)).all())
        audits = tuple(connection.execute(select(AuditLog.id, AuditLog.action).where(
            AuditLog.actor_id == identifier, AuditLog.action.like("auth.password_change%"),
        ).order_by(AuditLog.id)).all())
        attempts = tuple(connection.execute(select(LoginAttempt.id, LoginAttempt.success).where(
            LoginAttempt.email == connection.scalar(select(User.email).where(User.id == identifier)),
        ).order_by(LoginAttempt.id)).all())
    return Snapshot(*user, sessions, resets, audits, attempts)


def _unchanged(database, identifier, before, *, ignore=()):
    after = _snapshot(database, identifier)
    if any(getattr(before, item.name) != getattr(after, item.name)
           for item in fields(Snapshot) if item.name not in ignore):
        pytest.fail("Denied/failed own-password request changed durable effects", pytrace=False)
    return after


def _verify_replacement(database, identity, new_password):
    from app.core.security import verify_password

    with database.engine.connect() as connection:
        encoded = connection.scalar(select(User.password_hash).where(User.id == identity.id))
    if int(encoded.split("$")[2]) < 12:
        pytest.fail("Replacement bcrypt cost is below the required minimum", pytrace=False)
    if not verify_password(new_password, encoded) or verify_password(identity.password, encoded):
        pytest.fail("Committed password did not replace the old bcrypt credential", pytrace=False)


def _reset_link(identity):
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
        pytest.fail("Synthetic reset issuance failed", pytrace=False)
    return token


def _signed(tokens, **changes):
    from app.core.security import decode_token, settings

    payload = {**decode_token(tokens.access, verify_exp=False), **changes}
    return Tokens(jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm),
                  tokens.refresh)


@dataclass(repr=False)
class Case:
    app: FastAPI
    database: Database
    identity: Identity
    tokens: Tokens
    password: str
    factory: async_sessionmaker

    async def request(self, *, payload=None, path="/auth/change-password", method="POST", tokens=None):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app, raise_app_exceptions=False),
            base_url="http://owned-asgi",
        ) as client:
            return await client.request(method, "/api/v1" + path,
                                        json=_body(self.identity, self.password) if payload is None else payload,
                                        headers={"Authorization": f"Bearer {(tokens or self.tokens).access}"})


@pytest.fixture
def case(api_prefix, password_database, identity, new_password):
    from app.core.database import get_db
    from app.features.auth.router import router
    from app.features.staff.router import router as staff_router

    engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool,
                                 hide_parameters=True, connect_args={
                                     "server_settings": {"statement_timeout": "18000"},
                                 })
    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.include_router(staff_router, prefix="/api/v1")

    async def session():
        async with factory() as db:
            try:
                yield db
            except BaseException:
                await db.rollback()
                raise

    app.dependency_overrides[get_db] = session
    try:
        yield Case(app, password_database, identity, _login(api_prefix, identity), new_password, factory)
    finally:
        asyncio.run(engine.dispose())


def _wait_for_lock(database, holder_pid, count=1):
    deadline = time.monotonic() + 8
    with database.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as observer:
        while time.monotonic() < deadline:
            waiting = observer.scalar(text(
                "WITH RECURSIVE waiters(pid) AS ("
                "SELECT pid FROM pg_stat_activity WHERE wait_event_type='Lock' "
                "AND :holder = ANY(pg_blocking_pids(pid)) UNION "
                "SELECT activity.pid FROM pg_stat_activity activity JOIN waiters "
                "ON waiters.pid = ANY(pg_blocking_pids(activity.pid)) "
                "WHERE activity.wait_event_type='Lock') SELECT count(*) FROM waiters"
            ), {"holder": holder_pid})
            if waiting >= count:
                return
            time.sleep(0.01)
    pytest.fail("Password request did not reach the real PostgreSQL lock wait", pytrace=False)


@contextmanager
def _held_requests(database, model, condition, calls):
    with database.engine.connect() as holder, ThreadPoolExecutor(max_workers=len(calls)) as workers:
        holder.execute(select(model.id).where(condition).with_for_update())
        pid = holder.scalar(select(func.pg_backend_pid()))
        pending = [workers.submit(call) for call in calls]
        try:
            _wait_for_lock(database, pid, len(calls))
            yield holder, pending
        finally:
            holder.rollback()


def _expire_at(database, tokens, expires):
    from app.core.security import decode_token

    sid = uuid.UUID(decode_token(tokens.access)["sid"])
    with database.engine.begin() as connection:
        connection.execute(update(RefreshToken).where(RefreshToken.session_id == sid).values(
            expires_at=expires,
        ))


def _wait_until(expires):
    while datetime.now(timezone.utc) <= expires:
        time.sleep(0.02)


def test_dto_accepts_only_two_required_fields_and_redacts_repr_exports_and_errors(new_password):
    from app.features.auth.schemas import ChangePasswordRequest

    current = secrets.token_urlsafe(24)
    dto = ChangePasswordRequest(current_password=current, new_password=new_password)
    assert set(dto.model_fields) == {"current_password", "new_password"}
    if dto.model_dump() != {} or dto.model_dump_json() != "{}":
        pytest.fail("Own-password DTO export exposed a credential", pytrace=False)
    if current in repr(dto) or new_password in repr(dto):
        pytest.fail("Own-password DTO repr exposed a credential", pytrace=False)
    with pytest.raises(ValidationError) as failure:
        ChangePasswordRequest(current_password=current, new_password=new_password, role=current)
    if current in str(failure.value) or new_password in str(failure.value):
        pytest.fail("Own-password DTO validation exposed a credential", pytrace=False)


@pytest.mark.parametrize("role", ROLES)
def test_all_current_active_roles_change_only_their_own_password_and_must_sign_in_again(
    api_prefix, password_database, make_identity, new_password, role,
):
    identity = make_identity(role=role)
    tokens = _login(api_prefix, identity)
    response = _change(api_prefix, tokens, _body(identity, new_password))
    _expect(response, 200, SUCCESS)
    _safe(response, identity.password, new_password, tokens.access, tokens.refresh, clears=True)
    _verify_replacement(password_database, identity, new_password)
    assert _me(api_prefix, tokens).status_code == 401
    old_login = requests.post(f"{api_prefix}/auth/login", json={
        "email": identity.email, "password": identity.password,
        "tenant_id": str(identity.tenant_id),
    }, timeout=20)
    assert old_login.status_code == 401
    fresh = _login(api_prefix, identity, new_password)
    assert _me(api_prefix, fresh).status_code == 200
    with Session(password_database.engine) as db:
        user = db.get(User, identity.id)
        assert user.role == role and user.is_active is True and user.is_email_verified is False
        assert user.failed_login_attempts == 0 and user.locked_until is None and user.session_version == 1
        entry = db.scalar(select(AuditLog).where(
            AuditLog.actor_id == identity.id, AuditLog.action == "auth.password_change",
        ))
        assert entry.tenant_id == identity.tenant_id and entry.resource_id == str(identity.id)
        assert entry.actor_email is None and entry.metadata_json == {}


@pytest.mark.parametrize("prefix", ["/api/v1", "/api"])
def test_canonical_and_existing_alias_keep_cookie_identity_and_clear_both_cookies(
    base_url, api_prefix, identity, new_password, prefix,
):
    tokens = _login(api_prefix, identity)
    response = _change(base_url + prefix, None, _body(identity, new_password), cookies={
        "access_token": tokens.access, "refresh_token": tokens.refresh,
    })
    _expect(response, 200, SUCCESS)
    _safe(response, identity.password, new_password, tokens.access, tokens.refresh, clears=True)


@pytest.mark.parametrize("overpost", [
    "target", "target_id", "user_id", "tenant_id", "email", "role", "password_hash",
    "session_id", "session_version", "refresh_token", "reset_token", "private-key-as-field",
])
def test_foreign_authority_extra_fields_are_redacted_and_cannot_target_any_user(
    api_prefix, password_database, identity, make_identity, new_password, overpost,
):
    with Session(password_database.engine, expire_on_commit=False) as db:
        tenant = Tenant(name="Synthetic foreign password tenant", is_setup_complete=True)
        db.add(tenant)
        db.commit()
        tenant_id = tenant.id
    foreign = make_identity(tenant_id=tenant_id)
    tokens = _login(api_prefix, identity)
    own_before = _snapshot(password_database, identity.id)
    foreign_before = _snapshot(password_database, foreign.id)
    marker = f"Private-overpost-{uuid.uuid4().hex}"
    key = marker if overpost == "private-key-as-field" else overpost
    response = _change(api_prefix, tokens, {**_body(identity, new_password), key: marker})
    _expect(response, 422, INVALID_DATA)
    _safe(response, identity.password, new_password, marker, tokens.access)
    _unchanged(password_database, identity.id, own_before)
    _unchanged(password_database, foreign.id, foreign_before)


@pytest.mark.parametrize("query", ["user_id", "tenant_id", "email", "role", "current_password"])
def test_query_authority_or_credentials_are_not_accepted(case, query):
    before = _snapshot(case.database, case.identity.id)
    marker = secrets.token_urlsafe(24)
    response = asyncio.run(case.request(path=f"/auth/change-password?{query}={marker}"))
    assert response.status_code == 422
    _safe(response, marker, case.identity.password, case.password)
    _unchanged(case.database, case.identity.id, before)


@pytest.mark.parametrize("bad_field,value", [
    ("current_password", "x" * 5), ("current_password", "x" * 201),
    ("current_password", None), ("current_password", 123),
    ("new_password", "x" * 11), ("new_password", "x" * 73),
    ("new_password", "\u00e9" * 37), ("new_password", "\ud800" * 12),
    ("new_password", None), ("new_password", 123),
], ids=["short_current", "long_current", "null_current", "numeric_current", "short_new",
        "long_new", "utf8_byte_limit", "invalid_utf8", "null_new", "numeric_new"])
def test_invalid_password_input_is_redacted_no_store_and_has_no_effects(
    api_prefix, password_database, identity, new_password, bad_field, value,
):
    tokens = _login(api_prefix, identity)
    before = _snapshot(password_database, identity.id)
    response = _change(api_prefix, tokens, _body(identity, new_password, **{bad_field: value}))
    _expect(response, 422, INVALID_DATA)
    _safe(response, identity.password, new_password, value)
    _unchanged(password_database, identity.id, before)


@pytest.mark.parametrize("missing", ["current_password", "new_password", "both"])
def test_both_password_fields_are_required(api_prefix, identity, new_password, missing):
    tokens = _login(api_prefix, identity)
    payload = _body(identity, new_password)
    if missing == "both":
        payload = {}
    else:
        payload.pop(missing)
    response = _change(api_prefix, tokens, payload)
    _expect(response, 422, INVALID_DATA)
    _safe(response, identity.password, new_password)


@pytest.mark.parametrize("value", ["x" * 12, "x" * 72, "\u00e9" * 36],
                         ids=["minimum", "maximum_ascii", "maximum_utf8"])
def test_new_password_preserves_full_bcrypt_input(api_prefix, password_database, identity, value):
    response = _change(api_prefix, _login(api_prefix, identity), _body(identity, value))
    _expect(response, 200, SUCCESS)
    _safe(response, identity.password, value, clears=True)
    _verify_replacement(password_database, identity, value)
    _login(api_prefix, identity, value)


@pytest.mark.parametrize("value", ["x" * 6, "x" * 11, "x" * 72, "x" * 200, "\u00e9" * 6],
                         ids=["legacy_minimum", "legacy_short", "maximum_bcrypt", "legacy_long", "legacy_utf8"])
def test_existing_password_compatibility_is_not_replaced_by_new_password_policy(
    api_prefix, password_database, make_identity, new_password, value,
):
    identity = make_identity(password=value, legacy=True)
    response = _change(api_prefix, _login(api_prefix, identity), _body(identity, new_password))
    assert response.status_code == 200
    _safe(response, value, new_password, clears=True)
    _verify_replacement(password_database, identity, new_password)


@pytest.mark.parametrize("legacy", [False, True])
def test_same_or_bcrypt_equivalent_legacy_password_is_rejected_without_resetting_counters(
    api_prefix, password_database, make_identity, legacy,
):
    identity = make_identity(password="x" * 200, legacy=True) if legacy else make_identity()
    tokens = _login(api_prefix, identity)
    with password_database.engine.begin() as connection:
        connection.execute(update(User).where(User.id == identity.id).values(failed_login_attempts=2))
    before = _snapshot(password_database, identity.id)
    response = _change(api_prefix, tokens, _body(identity, "x" * 72 if legacy else identity.password))
    _expect(response, 400, {"detail": "New password must differ from the current password"})
    _safe(response, identity.password, tokens.access, tokens.refresh)
    _unchanged(password_database, identity.id, before)


@pytest.mark.parametrize("change", [
    "anonymous", "refresh_cookie_only", "refresh_as_access", "invalid_signature", "legacy",
    "foreign_session", "tenant", "role", "version", "expired_access", "revoked",
    "expired_session", "inactive", "persisted_role", "persisted_version", "malformed",
])
def test_only_a_current_signed_access_identity_and_persisted_session_may_mutate(
    api_prefix, password_database, identity, new_password, change,
):
    tokens = _login(api_prefix, identity)
    candidate, options = tokens, {}
    if change == "anonymous":
        candidate = None
    elif change == "refresh_cookie_only":
        candidate, options = None, {"cookies": {"refresh_token": tokens.refresh}}
    elif change == "refresh_as_access":
        candidate = Tokens(tokens.refresh, tokens.refresh)
    elif change == "invalid_signature":
        from app.core.security import decode_token
        candidate = Tokens(jwt.encode(decode_token(tokens.access), secrets.token_urlsafe(48),
                                      algorithm="HS256"), tokens.refresh)
    elif change == "legacy":
        from app.core.security import decode_token, settings
        payload = {key: value for key, value in decode_token(tokens.access).items()
                   if key not in {"sid", "ver"}}
        candidate = Tokens(jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm),
                           tokens.refresh)
    elif change in {"foreign_session", "tenant", "role", "version", "expired_access", "malformed"}:
        altered = {
            "foreign_session": {"sid": str(uuid.uuid4())}, "tenant": {"tenant_id": str(uuid.uuid4())},
            "role": {"role": "super_admin"}, "version": {"ver": 1},
            "expired_access": {"exp": int(time.time()) - 1}, "malformed": {"sub": "invalid-uuid"},
        }[change]
        candidate = _signed(tokens, **altered)
    else:
        with password_database.engine.begin() as connection:
            if change in {"revoked", "expired_session"}:
                values = {"revoked_at": datetime.now(timezone.utc)} if change == "revoked" else {
                    "expires_at": datetime.now(timezone.utc) - timedelta(seconds=1),
                }
                connection.execute(update(RefreshToken).where(RefreshToken.user_id == identity.id).values(**values))
            else:
                values = {"inactive": {"is_active": False}, "persisted_role": {"role": "accountant"},
                          "persisted_version": {"session_version": 1}}[change]
                connection.execute(update(User).where(User.id == identity.id).values(**values))
    before = _snapshot(password_database, identity.id)
    response = _change(api_prefix, candidate, _body(identity, new_password), **options)
    assert response.status_code == 401
    _safe(response, identity.password, new_password, tokens.access, tokens.refresh)
    _unchanged(password_database, identity.id, before)


def test_cookie_precedence_cannot_fall_back_from_a_bad_cookie_to_valid_bearer(
    api_prefix, password_database, identity, new_password,
):
    tokens = _login(api_prefix, identity)
    before = _snapshot(password_database, identity.id)
    response = _change(api_prefix, tokens, _body(identity, new_password), cookies={"access_token": "invalid"})
    assert response.status_code == 401
    _safe(response, identity.password, new_password, tokens.access)
    _unchanged(password_database, identity.id, before)


def test_wrong_current_password_is_400_and_commits_only_redacted_failure_state(
    api_prefix, password_database, identity, make_identity, new_password,
):
    tokens = _login(api_prefix, identity)
    foreign = make_identity()
    foreign_before = _snapshot(password_database, foreign.id)
    reset = _reset_link(identity)
    before = _snapshot(password_database, identity.id)
    wrong = secrets.token_urlsafe(24)
    response = _change(api_prefix, tokens, _body(identity, new_password, current_password=wrong))
    _expect(response, 400, {"detail": "Current password is incorrect"})
    _safe(response, wrong, new_password, reset, tokens.access, tokens.refresh)
    after = _unchanged(password_database, identity.id, before, ignore={"failed_attempts", "audits", "attempts"})
    assert after.failed_attempts == 1 and len(after.audits) == 1 and len(after.attempts) == len(before.attempts) + 1
    _unchanged(password_database, foreign.id, foreign_before)
    assert _me(api_prefix, tokens).status_code == 200
    with Session(password_database.engine) as db:
        entry = db.scalar(select(AuditLog).where(
            AuditLog.actor_id == identity.id, AuditLog.action == "auth.password_change_failed",
        ))
        assert entry.metadata_json == {} and entry.actor_email is None


def test_durable_lockout_budget_is_shared_across_sessions_and_cannot_be_ip_evaded(
    api_prefix, password_database, identity, new_password,
):
    first, second = _login(api_prefix, identity), _login(api_prefix, identity)
    for index in range(5):
        response = _change(api_prefix, first if index % 2 else second,
                           _body(identity, new_password, current_password=secrets.token_urlsafe(24)),
                           headers={"X-Forwarded-For": f"203.0.113.{index + 1}"})
        assert response.status_code == 400
        _safe(response, identity.password, new_password)
    locked = _snapshot(password_database, identity.id)
    assert locked.failed_attempts == 5
    assert 0 < (locked.locked_until - datetime.now(timezone.utc)).total_seconds() <= 900
    for token in (first, second):
        response = _change(api_prefix, token, _body(identity, new_password))
        _expect(response, 429, {"detail": "Too many password attempts. Try again later."})
        assert 1 <= int(response.headers["Retry-After"]) <= 900
        _safe(response, identity.password, new_password, token.access)
        _unchanged(password_database, identity.id, locked)
        assert _me(api_prefix, token).status_code == 200
    login = requests.post(f"{api_prefix}/auth/login", json={
        "email": identity.email, "password": identity.password,
        "tenant_id": str(identity.tenant_id),
    }, timeout=20)
    assert login.status_code == 401


def test_existing_login_failures_consume_the_same_reauthentication_budget(
    api_prefix, password_database, identity, new_password,
):
    tokens = _login(api_prefix, identity)
    with password_database.engine.begin() as connection:
        connection.execute(update(User).where(User.id == identity.id).values(failed_login_attempts=4))
    response = _change(api_prefix, tokens, _body(identity, new_password,
                                               current_password=secrets.token_urlsafe(24)))
    _expect(response, 400)
    assert _snapshot(password_database, identity.id).failed_attempts == 5
    _expect(_change(api_prefix, tokens, _body(identity, new_password)), 429)


def test_expired_lockout_resets_budget_and_success_clears_failure_state(case):
    with case.database.engine.begin() as connection:
        connection.execute(update(User).where(User.id == case.identity.id).values(
            failed_login_attempts=5, locked_until=datetime.now(timezone.utc) - timedelta(seconds=1),
        ))
    wrong = asyncio.run(case.request(payload=_body(case.identity, case.password,
                                                  current_password=secrets.token_urlsafe(24))))
    assert wrong.status_code == 400
    state = _snapshot(case.database, case.identity.id)
    assert state.failed_attempts == 1 and state.locked_until is None
    _expect(asyncio.run(case.request()), 200)
    state = _snapshot(case.database, case.identity.id)
    assert state.failed_attempts == 0 and state.locked_until is None


@pytest.mark.parametrize("limit,minutes", [(1, 1), (1000000, 1000000)])
def test_reauthentication_policy_settings_cannot_create_an_unbounded_budget_or_retry_after(
    case, monkeypatch, limit, minutes,
):
    from app.features.auth import service

    monkeypatch.setattr(service, "settings", service.settings.model_copy(update={
        "max_login_attempts": limit, "account_lock_minutes": minutes,
    }))
    for _ in range(min(limit, 5)):
        response = asyncio.run(case.request(payload=_body(
            case.identity, case.password, current_password=secrets.token_urlsafe(24),
        )))
        _expect(response, 400)
    state = _snapshot(case.database, case.identity.id)
    assert state.failed_attempts == min(limit, 5)
    assert 0 < (state.locked_until - datetime.now(timezone.utc)).total_seconds() <= min(minutes, 15) * 60
    response = asyncio.run(case.request())
    assert response.status_code == 429 and 1 <= int(response.headers["Retry-After"]) <= 900


def test_success_retires_every_session_and_reset_link_without_affecting_other_users(
    api_prefix, password_database, identity, make_identity, new_password,
):
    first, second = _login(api_prefix, identity), _login(api_prefix, identity)
    rotated = _refresh(api_prefix, first)
    assert rotated.status_code == 200
    replacement = Tokens(rotated.json()["access_token"], rotated.cookies["refresh_token"])
    reset = _reset_link(identity)
    legacy = secrets.token_urlsafe(32)
    other = make_identity()
    _login(api_prefix, other)
    other_reset = _reset_link(other)
    other_before = _snapshot(password_database, other.id)
    with Session(password_database.engine) as db:
        db.add(PasswordResetToken(user_id=identity.id, token=legacy,
                                 expires_at=datetime.now(timezone.utc) + timedelta(hours=1)))
        db.commit()
    response = _change(api_prefix, replacement, _body(identity, new_password))
    _expect(response, 200, SUCCESS)
    _safe(response, identity.password, new_password, reset, legacy, other_reset, clears=True)
    state = _snapshot(password_database, identity.id)
    assert state.epoch == 1 and all(row.revoked_at is not None for row in state.sessions)
    assert len(state.resets) == 2 and all(row.used_at is not None for row in state.resets)
    for tokens in (first, second, replacement):
        assert _me(api_prefix, tokens).status_code == 401
        assert _refresh(api_prefix, tokens).status_code == 401
    for token in (reset, legacy):
        denied = requests.post(f"{api_prefix}/auth/reset-password", json={
            "token": token, "new_password": secrets.token_urlsafe(24),
        }, timeout=20)
        assert denied.status_code == 400
    _unchanged(password_database, other.id, other_before)


def test_old_refresh_replay_cannot_kill_a_new_login_after_password_change(
    api_prefix, password_database, identity, new_password,
):
    from app.core.security import decode_token, settings

    old = _login(api_prefix, identity)
    _expect(_change(api_prefix, old, _body(identity, new_password)), 200)
    fresh = _login(api_prefix, identity, new_password)
    payload = decode_token(old.refresh)
    expired = {**payload, "exp": int(time.time()) - 1}
    legacy = {key: value for key, value in expired.items() if key not in {"sid", "ver"}}
    replays = [old, Tokens(old.access, jwt.encode(expired, settings.jwt_secret,
                                                 algorithm=settings.jwt_algorithm)),
               Tokens(old.access, jwt.encode(legacy, settings.jwt_secret,
                                              algorithm=settings.jwt_algorithm)), old]
    for replay in replays:
        assert _refresh(api_prefix, replay).status_code == 401
        assert _me(api_prefix, fresh).status_code == 200
        assert _snapshot(password_database, identity.id).epoch == 1
    assert _refresh(api_prefix, fresh).status_code == 200


@pytest.mark.parametrize("failure", ["verify", "hash", "revoke", "resets", "audit", "constraint", "commit"])
def test_unexpected_failures_roll_back_password_epoch_links_audit_and_prior_counters(
    case, api_prefix, monkeypatch, caplog, failure,
):
    from app.core.database import get_db
    from app.features.auth import service

    _login(api_prefix, case.identity)
    reset = _reset_link(case.identity)
    with case.database.engine.begin() as connection:
        connection.execute(update(User).where(User.id == case.identity.id).values(failed_login_attempts=2))
    before = _snapshot(case.database, case.identity.id)
    message = f"Injected private failure {case.identity.password} {case.password} {reset}"
    if failure in {"verify", "hash"}:
        def broken(*args):
            raise RuntimeError(message)
        monkeypatch.setattr(service, "verify_password" if failure == "verify" else "hash_password", broken)
    elif failure in {"revoke", "resets"}:
        name = "revoke_sessions" if failure == "revoke" else "invalidate_password_resets"
        original = getattr(service.repositories, name)

        async def broken(*args, **kwargs):
            await original(*args, **kwargs)
            raise RuntimeError(message)
        monkeypatch.setattr(service.repositories, name, broken)
    elif failure in {"audit", "constraint"}:
        original = service.audit

        async def broken(db, **kwargs):
            await original(db, **kwargs)
            if failure == "audit":
                raise RuntimeError(message)
            for entry in db.new:
                if isinstance(entry, AuditLog):
                    entry.action = None
        monkeypatch.setattr(service, "audit", broken)
    else:
        class BrokenCommit(AsyncSession):
            async def commit(self):
                await self.flush()
                raise RuntimeError(message)

        async def session():
            async with BrokenCommit(bind=case.factory.kw["bind"], expire_on_commit=False,
                                    autoflush=False) as db:
                yield db
        case.app.dependency_overrides[get_db] = session
    response = asyncio.run(case.request())
    _expect(response, 500, {"detail": "Request could not be completed"})
    _safe(response, case.identity.password, case.password, reset)
    _unchanged(case.database, case.identity.id, before)
    if any(value in caplog.text for value in (case.identity.password, case.password, reset)):
        pytest.fail("Unexpected password failure logged private inputs", pytrace=False)
    assert _me(api_prefix, case.tokens).status_code == 200


@pytest.mark.parametrize("failure", ["audit", "constraint", "commit"])
def test_failure_counter_commit_is_not_allowed_to_swallow_audit_or_commit_failure(case, monkeypatch, failure):
    from app.core.database import get_db
    from app.features.auth import service

    before = _snapshot(case.database, case.identity.id)
    original = service.audit

    async def broken(db, **kwargs):
        await original(db, **kwargs)
        if failure == "audit":
            raise RuntimeError("Synthetic reauthentication audit failure")
        if failure == "constraint":
            for entry in db.new:
                if isinstance(entry, AuditLog):
                    entry.action = None

    if failure == "commit":
        class BrokenCommit(AsyncSession):
            async def commit(self):
                await self.flush()
                raise RuntimeError("Synthetic reauthentication commit failure")

        async def session():
            async with BrokenCommit(bind=case.factory.kw["bind"], expire_on_commit=False,
                                    autoflush=False) as db:
                yield db
        case.app.dependency_overrides[get_db] = session
    else:
        monkeypatch.setattr(service, "audit", broken)
    response = asyncio.run(case.request(payload=_body(
        case.identity, case.password, current_password=secrets.token_urlsafe(24),
    )))
    assert response.status_code == 500
    _safe(response, case.password, case.identity.password)
    _unchanged(case.database, case.identity.id, before)


def test_lost_commit_acknowledgement_returns_no_success_or_tokens_and_keeps_atomic_effects(case, api_prefix):
    from app.core.database import get_db

    class LostAcknowledgement(AsyncSession):
        async def commit(self):
            await super().commit()
            raise RuntimeError("Synthetic lost commit acknowledgement")

    async def session():
        async with LostAcknowledgement(bind=case.factory.kw["bind"], expire_on_commit=False,
                                       autoflush=False) as db:
            yield db
    case.app.dependency_overrides[get_db] = session
    response = asyncio.run(case.request())
    assert response.status_code == 500
    _safe(response, case.password, case.identity.password)
    state = _snapshot(case.database, case.identity.id)
    assert state.epoch == 1 and len(state.audits) == 1
    assert all(row.revoked_at is not None for row in state.sessions)
    _verify_replacement(case.database, case.identity, case.password)
    assert _me(api_prefix, case.tokens).status_code == 401
    fresh = _login(api_prefix, case.identity, case.password)
    assert _me(api_prefix, fresh).status_code == 200


def test_concurrent_own_password_changes_commit_exactly_one_serialized_effect(
    api_prefix, password_database, identity,
):
    tokens = _login(api_prefix, identity)
    reset = _reset_link(identity)
    passwords = [secrets.token_urlsafe(24), secrets.token_urlsafe(24)]
    calls = [lambda password=password: _change(api_prefix, tokens, _body(identity, password))
             for password in passwords]
    with _held_requests(password_database, User, User.id == identity.id, calls) as (holder, pending):
        holder.commit()
        responses = [future.result(timeout=20) for future in pending]
    assert sorted(response.status_code for response in responses) == [200, 401]
    winner = next(index for index, response in enumerate(responses) if response.status_code == 200)
    for response in responses:
        _safe(response, identity.password, reset, *passwords, clears=response.status_code == 200)
    _verify_replacement(password_database, identity, passwords[winner])
    state = _snapshot(password_database, identity.id)
    assert state.epoch == 1 and len(state.audits) == 1
    assert all(row.used_at is not None for row in state.resets)


def test_concurrent_bad_current_password_attempts_cannot_lose_updates_or_exceed_budget(
    api_prefix, password_database, identity, new_password,
):
    tokens = _login(api_prefix, identity)
    calls = [lambda: _change(api_prefix, tokens, _body(
        identity, new_password, current_password=secrets.token_urlsafe(24),
    )) for _ in range(6)]
    with _held_requests(password_database, User, User.id == identity.id, calls) as (holder, pending):
        holder.commit()
        responses = [future.result(timeout=20) for future in pending]
    assert sorted(response.status_code for response in responses) == [400] * 5 + [429]
    state = _snapshot(password_database, identity.id)
    assert state.failed_attempts == 5 and state.epoch == 0 and len(state.audits) == 5
    assert all(row.revoked_at is None for row in state.sessions)


@pytest.mark.parametrize("change", ["inactive", "role", "version", "revoked", "expiry"])
def test_user_lock_wait_rechecks_committed_eligibility_and_session_changes(case, change):
    before = _snapshot(case.database, case.identity.id)
    with _held_requests(case.database, User, User.id == case.identity.id,
                        [lambda: asyncio.run(case.request())]) as (holder, pending):
        if change in {"revoked", "expiry"}:
            values = {"revoked_at": datetime.now(timezone.utc)} if change == "revoked" else {
                "expires_at": datetime.now(timezone.utc) - timedelta(seconds=1),
            }
            holder.execute(update(RefreshToken).where(RefreshToken.user_id == case.identity.id).values(**values))
        else:
            values = {"inactive": {"is_active": False}, "role": {"role": "accountant"},
                      "version": {"session_version": 1}}[change]
            holder.execute(update(User).where(User.id == case.identity.id).values(**values))
        holder.commit()
        response = pending[0].result(timeout=20)
    assert response.status_code == 401
    _safe(response, case.identity.password, case.password)
    _unchanged(case.database, case.identity.id, before, ignore={
        "sessions" if change in {"revoked", "expiry"} else "epoch" if change == "version" else "unused",
    })


@pytest.mark.parametrize("change", ["revoke", "expiry", "clock_expiry", "access_clock_expiry"])
def test_active_session_lock_wait_rechecks_revocation_and_both_expiries(case, change):
    expires = datetime.now(timezone.utc) + timedelta(seconds=3)
    if change == "clock_expiry":
        _expire_at(case.database, case.tokens, expires)
    elif change == "access_clock_expiry":
        case.tokens = _signed(case.tokens, exp=expires)
    before = _snapshot(case.database, case.identity.id)
    with _held_requests(case.database, RefreshToken, RefreshToken.user_id == case.identity.id,
                        [lambda: asyncio.run(case.request())]) as (holder, pending):
        if change in {"clock_expiry", "access_clock_expiry"}:
            _wait_until(expires)
        else:
            values = {"revoked_at": datetime.now(timezone.utc)} if change == "revoke" else {
                "expires_at": datetime.now(timezone.utc) - timedelta(seconds=1),
            }
            holder.execute(update(RefreshToken).where(RefreshToken.user_id == case.identity.id).values(**values))
        holder.commit()
        response = pending[0].result(timeout=20)
    assert response.status_code == 401
    _safe(response, case.password, case.identity.password)
    _unchanged(case.database, case.identity.id, before,
               ignore={"sessions"} if change in {"revoke", "expiry"} else ())


@pytest.mark.parametrize("dependency", ["other_session", "reset"])
def test_expiry_during_later_retirement_lock_wait_prevents_hash_and_all_effects(
    case, api_prefix, monkeypatch, dependency,
):
    from app.core.security import decode_token
    from app.features.auth import service

    other = _login(api_prefix, case.identity)
    _reset_link(case.identity)
    if dependency == "other_session":
        model = RefreshToken
        condition = RefreshToken.session_id == uuid.UUID(decode_token(other.access)["sid"])
    else:
        model = PasswordResetToken
        condition = PasswordResetToken.user_id == case.identity.id
    expires = datetime.now(timezone.utc) + timedelta(seconds=3)
    _expire_at(case.database, case.tokens, expires)
    before = _snapshot(case.database, case.identity.id)

    def forbidden_hash(*args):
        pytest.fail("Password hashing began before post-wait eligibility was rechecked", pytrace=False)
    monkeypatch.setattr(service, "hash_password", forbidden_hash)
    with _held_requests(case.database, model, condition,
                        [lambda: asyncio.run(case.request())]) as (holder, pending):
        _wait_until(expires)
        holder.commit()
        response = pending[0].result(timeout=20)
    assert response.status_code == 401
    _safe(response, case.password, case.identity.password)
    _unchanged(case.database, case.identity.id, before)


@pytest.mark.parametrize("wait_at", ["verify", "hash", "audit", "flush"])
def test_expiry_after_offloaded_work_or_flush_rolls_back_before_self_revocation(case, monkeypatch, wait_at):
    from app.core.database import get_db
    from app.features.auth import service

    expires = datetime.now(timezone.utc) + timedelta(seconds=3)
    _expire_at(case.database, case.tokens, expires)
    before = _snapshot(case.database, case.identity.id)
    ready, release = threading.Event(), threading.Event()
    if wait_at in {"verify", "hash"}:
        name = "verify_password" if wait_at == "verify" else "hash_password"
        original = getattr(service, name)

        def paused(*args):
            ready.set()
            if not release.wait(timeout=10):
                raise RuntimeError("Synthetic password work barrier timed out")
            return original(*args)
        monkeypatch.setattr(service, name, paused)
    elif wait_at == "audit":
        original = service.audit

        async def paused(db, **kwargs):
            await original(db, **kwargs)
            ready.set()
            if not await asyncio.to_thread(release.wait, 10):
                raise RuntimeError("Synthetic password audit barrier timed out")
        monkeypatch.setattr(service, "audit", paused)
    else:
        class PausedFlush(AsyncSession):
            async def flush(self, *args, **kwargs):
                await super().flush(*args, **kwargs)
                ready.set()
                if not await asyncio.to_thread(release.wait, 10):
                    raise RuntimeError("Synthetic password flush barrier timed out")

        async def session():
            async with PausedFlush(bind=case.factory.kw["bind"], expire_on_commit=False,
                                   autoflush=False) as db:
                yield db
        case.app.dependency_overrides[get_db] = session
    with ThreadPoolExecutor(max_workers=1) as workers:
        pending = workers.submit(lambda: asyncio.run(case.request()))
        try:
            assert ready.wait(timeout=10)
            _wait_until(expires)
        finally:
            release.set()
        response = pending.result(timeout=20)
    assert response.status_code == 401
    _safe(response, case.password, case.identity.password)
    _unchanged(case.database, case.identity.id, before)


@pytest.mark.parametrize("writer", ["logout", "reset", "role", "inactive", "revoke"])
@pytest.mark.parametrize("winner", ["writer", "change"])
def test_logout_reset_and_staff_lifecycle_races_follow_user_first_serialization(
    case, api_prefix, make_identity, monkeypatch, writer, winner,
):
    from app.features.auth import service
    from app.features.staff import service as staff_service

    owner_tokens = _login(api_prefix, make_identity(role="super_admin"))
    reset = _reset_link(case.identity)
    reset_password = secrets.token_urlsafe(24)
    original_auth_audit, original_staff_audit = service.audit, staff_service.audit
    writer_action = {"logout": "auth.logout", "reset": "auth.password_reset", "role": "staff.update",
                     "inactive": "staff.update", "revoke": "staff.revoke_sessions"}[writer]

    async def race():
        ready, release = asyncio.Event(), asyncio.Event()
        holder_pid = None

        async def barrier(db, **kwargs):
            nonlocal holder_pid
            original = original_staff_audit if kwargs["action"].startswith("staff.") else original_auth_audit
            await original(db, **kwargs)
            expected = "auth.password_change" if winner == "change" else writer_action
            if kwargs["action"] == expected:
                holder_pid = await db.scalar(select(func.pg_backend_pid()))
                ready.set()
                await asyncio.wait_for(release.wait(), timeout=10)

        monkeypatch.setattr(service, "audit", barrier)
        monkeypatch.setattr(staff_service, "audit", barrier)

        async def write():
            if writer == "logout":
                return await case.request(path="/auth/logout", payload={})
            if writer == "reset":
                return await case.request(path="/auth/reset-password", payload={
                    "token": reset, "new_password": reset_password,
                })
            path = f"/staff/{case.identity.id}"
            if writer == "revoke":
                return await case.request(path=path + "/revoke-sessions", payload={}, tokens=owner_tokens)
            return await case.request(path=path, method="PATCH", tokens=owner_tokens,
                                      payload={"role": "accountant"} if writer == "role" else {"is_active": False})

        first = asyncio.create_task(case.request() if winner == "change" else write())
        second = None
        try:
            await asyncio.wait_for(ready.wait(), timeout=10)
            second = asyncio.create_task(write() if winner == "change" else case.request())
            await asyncio.to_thread(_wait_for_lock, case.database, holder_pid)
        finally:
            release.set()
        results = await asyncio.gather(first, second)
        return results if winner == "writer" else list(reversed(results))

    written, changed = asyncio.run(race())
    assert written.status_code == (400 if writer == "reset" and winner == "change" else 200)
    assert changed.status_code == (200 if winner == "change" else 401)
    _safe(changed, case.password, case.identity.password, reset, reset_password,
          clears=changed.status_code == 200)
    state = _snapshot(case.database, case.identity.id)
    assert sum(action == "auth.password_change" for _, action in state.audits) == (winner == "change")
    if winner == "change":
        _verify_replacement(case.database, case.identity, case.password)
        assert all(row.revoked_at is not None for row in state.sessions)
        assert all(row.used_at is not None for row in state.resets)
    elif writer == "reset":
        _verify_replacement(case.database, case.identity, reset_password)
    else:
        from app.core.security import verify_password
        if not verify_password(case.identity.password, state.password_hash):
            pytest.fail("A lifecycle-winning race unexpectedly changed the password", pytrace=False)


def test_user_session_and_reset_locks_are_retained_until_commit_without_fk_upgrade(case):
    from app.core.database import get_db

    _reset_link(case.identity)
    committing, release = threading.Event(), threading.Event()
    statements = []

    class PausedCommit(AsyncSession):
        async def commit(self):
            committing.set()
            if not await asyncio.to_thread(release.wait, 10):
                raise RuntimeError("Synthetic password commit barrier timed out")
            await super().commit()

    async def session():
        async with PausedCommit(bind=case.factory.kw["bind"], expire_on_commit=False,
                                autoflush=False) as db:
            yield db

    def observe(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    case.app.dependency_overrides[get_db] = session
    event.listen(case.factory.kw["bind"].sync_engine, "before_cursor_execute", observe)
    try:
        with ThreadPoolExecutor(max_workers=1) as workers:
            pending = workers.submit(lambda: asyncio.run(case.request()))
            try:
                assert committing.wait(timeout=10)
                with case.database.engine.connect() as foreign_key:
                    assert foreign_key.scalar(select(User.id).where(User.id == case.identity.id)
                                              .with_for_update(read=True, key_share=True, nowait=True)) == case.identity.id
                    foreign_key.rollback()
                for model, condition, values in (
                    (User, User.id == case.identity.id, {"is_active": False}),
                    (RefreshToken, RefreshToken.user_id == case.identity.id,
                     {"revoked_at": datetime.now(timezone.utc)}),
                    (PasswordResetToken, PasswordResetToken.user_id == case.identity.id,
                     {"used_at": datetime.now(timezone.utc)}),
                ):
                    with case.database.engine.connect() as revoker:
                        revoker.execute(text("SET LOCAL lock_timeout='150ms'"))
                        with pytest.raises(DBAPIError) as error:
                            revoker.execute(update(model).where(condition).values(**values))
                        assert error.value.orig.pgcode == "55P03"
                        revoker.rollback()
            finally:
                release.set()
            response = pending.result(timeout=20)
    finally:
        event.remove(case.factory.kw["bind"].sync_engine, "before_cursor_execute", observe)
    _expect(response, 200, SUCCESS)
    user_lock = next(index for index, sql in enumerate(statements)
                     if "FROM users" in sql and "FOR NO KEY UPDATE" in sql)
    session_lock = next(index for index, sql in enumerate(statements)
                        if "FROM refresh_tokens" in sql and "FOR UPDATE" in sql)
    reset_lock = next(index for index, sql in enumerate(statements)
                      if "FROM password_reset_tokens" in sql and "FOR UPDATE" in sql)
    password_write = next(index for index, sql in enumerate(statements) if sql.startswith("UPDATE users"))
    revoke_write = next(index for index, sql in enumerate(statements) if sql.startswith("UPDATE refresh_tokens"))
    final_auth = max(index for index, sql in enumerate(statements) if "JOIN refresh_tokens" in sql)
    assert user_lock < session_lock < reset_lock < password_write < final_auth < revoke_write
    assert not any(sql.startswith("UPDATE " + table) for sql in statements for table in (
        "customers", "orders", "deliveries", "warehouses", "ledger_entries", "tenants",
    ))
