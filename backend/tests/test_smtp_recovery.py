"""Offline SMTP, admission and recovery contracts; no live accounts or request DB reuse."""
from __future__ import annotations

import asyncio
import ast
import hashlib
import hmac
import importlib
import inspect
import json
import secrets
import smtplib
import ssl
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from http.cookies import SimpleCookie
from types import SimpleNamespace
from urllib.parse import parse_qs, quote, urlsplit

import anyio
import httpx
import pytest
from fastapi import BackgroundTasks, FastAPI
from sqlalchemy.dialects import postgresql

from app.core import config

ACKNOWLEDGEMENT = {
    "message": "If an eligible account exists, check its email for a password reset link.",
}
UNAVAILABLE = {"detail": "Password reset is temporarily unavailable. Try again later."}
LIMITED = {"detail": "Too many password reset requests. Try again later."}


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    for field_info in config.Settings.model_fields.values():
        if isinstance(field_info.validation_alias, str):
            monkeypatch.delenv(field_info.validation_alias, raising=False)


@pytest.fixture
def settings_factory():
    def build(**overrides):
        values = {
            "_env_file": None, "app_env": "test",
            "free_only_mode": True, "approved_free_smtp": True,
            "database_url": "postgresql+asyncpg://unused@127.0.0.1/supplyos_test_smtp",
            "database_url_sync": "postgresql+psycopg2://unused@127.0.0.1/supplyos_test_smtp",
            "redis_url": "redis://127.0.0.1:6379/0", "jwt_secret": secrets.token_urlsafe(48),
            "anthropic_api_key": "", "frontend_url": "http://localhost:3000",
            "cookie_secure": False, "cookie_samesite": "lax",
            "smtp_enabled": False, "smtp_host": "", "smtp_port": 587,
            "smtp_username": "", "smtp_password": "", "smtp_from": "",
            "smtp_from_name": "SupplyOS", "smtp_tls_mode": "starttls",
            "smtp_timeout_seconds": 10, "password_reset_url": "",
            "password_reset_capacity": 4, "password_reset_window_seconds": 3600,
            "password_reset_max_requests_per_ip": 3,
            "password_reset_max_requests_per_identity": 3,
            "password_reset_cooldown_seconds": 60,
            "password_reset_rate_limit_timeout_seconds": 0.05,
            "password_reset_work_timeout_seconds": 1,
        }
        values.update(overrides)
        return config.Settings(**values)
    return build


@pytest.fixture
def modules(monkeypatch, settings_factory):
    settings = settings_factory()
    # _env_file=None alone does not neutralize ambient environment, and imports must not
    # invoke the normal file-backed settings factory before the offline injection.
    monkeypatch.setattr(config, "get_settings", lambda: settings)
    smtp_module = importlib.import_module("app.infrastructure.external.smtp")
    recovery_module = importlib.import_module("app.features.auth.recovery")
    router_module = importlib.import_module("app.features.auth.router")
    monkeypatch.setattr(router_module, "settings", settings)
    monkeypatch.setattr(recovery_module.service, "settings", settings)
    return SimpleNamespace(smtp=smtp_module, recovery=recovery_module, router=router_module)


@pytest.fixture
def smtp_settings(settings_factory):
    return settings_factory(
        smtp_enabled=True, smtp_host="relay.example.com", smtp_from="recovery@example.com",
        smtp_username=secrets.token_urlsafe(24), smtp_password=secrets.token_urlsafe(32),
        password_reset_url="https://app.example.com/reset-password",
    )


def _no_private_values(text, *values):
    if any(value and value in text for value in values):
        pytest.fail("Recovery exposed private data", pytrace=False)


class FakeSMTP:
    def __init__(self, *, mode, events, options, failures, messages, contexts, credentials):
        self.events = events
        self.failures = failures
        self.messages = messages
        self.contexts = contexts
        self.credentials = credentials
        self._event("connect_" + mode)
        assert options["timeout"] > 0
        if "context" in options:
            contexts.append(options["context"])

    def _event(self, stage):
        if threading.current_thread() is threading.main_thread():
            pytest.fail("Blocking SMTP ran on the event loop thread", pytrace=False)
        self.events.append(stage)
        failure = self.failures.get(stage)
        if callable(failure):
            failure()
        elif failure is not None:
            raise failure

    def __enter__(self):
        self._event("enter")
        return self

    def __exit__(self, *_):
        self._event("quit")

    def set_debuglevel(self, level):
        assert level == 0
        self._event("debug_off")

    def ehlo(self):
        self._event("ehlo")

    def starttls(self, *, context):
        self._event("starttls")
        self.contexts.append(context)

    def login(self, username, password):
        self._event("login")
        self.credentials.extend([username, password])

    def send_message(self, message, *, from_addr, to_addrs):
        self._event("send")
        self.messages.append(message)
        assert from_addr == message["From"].addresses[0].addr_spec
        assert to_addrs == [message["To"].addresses[0].addr_spec]
        return self.failures.get("refused", {})


@pytest.fixture
def fake_smtp(monkeypatch, modules):
    state = SimpleNamespace(events=[], failures={}, messages=[], contexts=[], credentials=[])

    def connect(mode, **options):
        return FakeSMTP(mode=mode, events=state.events, options=options, failures=state.failures,
                        messages=state.messages, contexts=state.contexts,
                        credentials=state.credentials)

    monkeypatch.setattr(modules.smtp.smtplib, "SMTP", lambda **options: connect("smtp", **options))
    monkeypatch.setattr(modules.smtp.smtplib, "SMTP_SSL", lambda **options: connect("tls", **options))
    return state


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["starttls", "tls", "plain"])
async def test_smtp_transport_uses_verified_tls_and_canonical_fragment(
    modules, settings_factory, smtp_settings, fake_smtp, mode,
):
    values = {**smtp_settings.model_dump(), "smtp_username": smtp_settings.smtp_username,
              "smtp_password": smtp_settings.smtp_password, "smtp_tls_mode": mode}
    if mode == "plain":
        values.update(smtp_host="127.0.0.1", smtp_username="", smtp_password="")
    settings = settings_factory(**values)
    token = secrets.token_urlsafe(32) + "+/=&?#%"
    result = await modules.smtp.SMTPPasswordResetSender(settings).send(
        recipient="owner@example.com", token=token,
    )
    assert result is True
    assert fake_smtp.events[-1] == "quit"
    assert fake_smtp.events.count("ehlo") == (2 if mode == "starttls" else 1)
    assert ("starttls" in fake_smtp.events) == (mode == "starttls")
    assert ("login" in fake_smtp.events) == (mode != "plain")
    if mode == "plain":
        assert fake_smtp.contexts == []
    else:
        for context in fake_smtp.contexts:
            assert context.check_hostname is True
            assert context.verify_mode == ssl.CERT_REQUIRED
        if fake_smtp.credentials != [settings.smtp_username, settings.smtp_password]:
            pytest.fail("SMTP authentication omitted the configured pair", pytrace=False)
    message = fake_smtp.messages[0]
    assert message["To"].addresses[0].addr_spec == "owner@example.com"
    assert message["From"].addresses[0].display_name == "SupplyOS"
    body = message.get_content()
    links = [word for word in body.split() if word.startswith("https://")]
    assert len(links) == 1
    link = links[0]
    if link != settings.password_reset_url + "#token=" + quote(token, safe=""):
        pytest.fail("Reset link did not use the configured canonical fragment", pytrace=False)
    parsed = urlsplit(link)
    assert parsed.query == ""
    if parse_qs(parsed.fragment).get("token") != [token]:
        pytest.fail("Reset fragment did not preserve the opaque secret", pytrace=False)
    assert message.get_content_type() == "text/plain"


@pytest.mark.asyncio
async def test_disabled_smtp_never_connects(modules, settings_factory, fake_smtp):
    result = await modules.smtp.SMTPPasswordResetSender(settings_factory()).send(
        recipient="owner@example.com", token=secrets.token_urlsafe(32),
    )
    assert result is False
    assert fake_smtp.events == []


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [
    "connection", "tls", "auth", "recipient", "data", "timeout", "disconnect", "quit", "partial",
])
async def test_smtp_failure_never_claims_success_or_exposes_server_replies(
    modules, smtp_settings, fake_smtp, caplog, failure,
):
    token = secrets.token_urlsafe(32)
    recipient = "owner@example.com"
    private_reply = " ".join([token, recipient, smtp_settings.smtp_username, smtp_settings.smtp_password])
    if failure == "connection":
        fake_smtp.failures["connect_smtp"] = OSError(private_reply)
    elif failure == "tls":
        fake_smtp.failures["starttls"] = ssl.SSLCertVerificationError(private_reply)
    elif failure == "auth":
        fake_smtp.failures["login"] = smtplib.SMTPAuthenticationError(535, private_reply.encode())
    elif failure == "recipient":
        fake_smtp.failures["send"] = smtplib.SMTPRecipientsRefused({recipient: (550, private_reply)})
    elif failure == "data":
        fake_smtp.failures["send"] = smtplib.SMTPDataError(554, private_reply.encode())
    elif failure == "timeout":
        fake_smtp.failures["send"] = TimeoutError(private_reply)
    elif failure == "disconnect":
        fake_smtp.failures["send"] = smtplib.SMTPServerDisconnected(private_reply)
    elif failure == "quit":
        fake_smtp.failures["quit"] = smtplib.SMTPResponseException(500, private_reply.encode())
    else:
        fake_smtp.failures["refused"] = {recipient: (550, private_reply)}
    result = await modules.smtp.SMTPPasswordResetSender(smtp_settings).send(
        recipient=recipient, token=token,
    )
    assert result is False
    assert "Password reset SMTP failed (" in caplog.text
    _no_private_values(caplog.text, token, recipient, smtp_settings.smtp_username,
                       smtp_settings.smtp_password, smtp_settings.password_reset_url)
    assert all(record.exc_info is None for record in caplog.records)


@pytest.mark.asyncio
async def test_smtp_rejects_recipient_header_injection_before_connecting(
    modules, smtp_settings, fake_smtp, caplog,
):
    token = secrets.token_urlsafe(32)
    result = await modules.smtp.SMTPPasswordResetSender(smtp_settings).send(
        recipient="owner@example.com\r\nBcc: other@example.com", token=token,
    )
    assert result is False
    assert fake_smtp.events == []
    _no_private_values(caplog.text, token, "owner@example.com", "other@example.com")


@pytest.mark.asyncio
async def test_smtp_cancellation_waits_for_thread_and_quit(
    modules, smtp_settings, fake_smtp,
):
    started, release = threading.Event(), threading.Event()

    def block_send():
        started.set()
        if not release.wait(2):
            raise TimeoutError("Offline SMTP gate expired")

    fake_smtp.failures["send"] = block_send
    task = asyncio.create_task(modules.smtp.SMTPPasswordResetSender(smtp_settings).send(
        recipient="owner@example.com", token=secrets.token_urlsafe(32),
    ))
    try:
        assert await asyncio.to_thread(started.wait, 1)
        task.cancel()
        await asyncio.sleep(0)
        assert task.done() is False
        task.cancel()
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 2)
    assert fake_smtp.events[-1] == "quit"


def test_smtp_credentials_are_excluded_from_all_settings_exports(smtp_settings):
    for exported in (repr(smtp_settings), smtp_settings.model_dump_json(),
                     json.dumps(smtp_settings.model_dump(by_alias=True), default=str)):
        _no_private_values(exported, smtp_settings.smtp_username, smtp_settings.smtp_password)


@pytest.mark.asyncio
async def test_asgi_level_cancellation_waits_without_spinning_until_smtp_closes(
    modules, smtp_settings, fake_smtp, monkeypatch,
):
    started, release = threading.Event(), threading.Event()
    shield = asyncio.shield
    waits = 0

    def record_wait(worker):
        nonlocal waits
        if isinstance(worker, asyncio.Task) and worker.get_coro().cr_code.co_name == "to_thread":
            waits += 1
        return shield(worker)

    def block_send():
        started.set()
        if not release.wait(2):
            raise TimeoutError("Offline SMTP gate expired")

    monkeypatch.setattr(modules.smtp.asyncio, "shield", record_wait)
    fake_smtp.failures["send"] = block_send
    sender = modules.smtp.SMTPPasswordResetSender(smtp_settings)

    async def deliver():
        await sender.send(recipient="owner@example.com", token=secrets.token_urlsafe(32))

    try:
        async with anyio.create_task_group() as group:
            group.start_soon(deliver)
            assert await asyncio.to_thread(started.wait, 1)
            asyncio.get_running_loop().call_later(0.03, release.set)
            group.cancel_scope.cancel()
    finally:
        release.set()
    assert fake_smtp.events[-1] == "quit"
    assert waits <= 2


@pytest.mark.parametrize("module_name", ["tools.verify_backend", "tools.run_preview"])
def test_owned_runners_disable_smtp_even_with_an_unsafe_synthetic_dotenv(
    settings_factory, tmp_path, module_name,
):
    module = importlib.import_module(module_name)
    tree = ast.parse(inspect.getsource(module.main))
    safe = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and isinstance(value, ast.Constant):
                    if str(key.value).startswith(("SMTP_", "PASSWORD_RESET_")):
                        safe[key.value] = value.value
    assert safe["SMTP_ENABLED"] == "false"
    assert all(safe[field] == "" for field in (
        "SMTP_HOST", "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_FROM", "PASSWORD_RESET_URL",
    ))
    # This file is owned test data, not either of the workspace's private .env files.
    path = tmp_path / "synthetic-smtp.env"
    path.write_text("\n".join([
        "SMTP_ENABLED=true", "SMTP_HOST=not a host", "SMTP_PORT=99999",
        "SMTP_USERNAME=synthetic", "SMTP_PASSWORD=synthetic", "SMTP_FROM=not-an-email",
        "SMTP_FROM_NAME=synthetic", "SMTP_TLS_MODE=unverified", "SMTP_TIMEOUT_SECONDS=999",
        "PASSWORD_RESET_URL=http://unsafe.example.com/other", "PASSWORD_RESET_CAPACITY=0",
        "PASSWORD_RESET_WINDOW_SECONDS=0", "PASSWORD_RESET_MAX_REQUESTS_PER_IP=0",
        "PASSWORD_RESET_MAX_REQUESTS_PER_IDENTITY=0", "PASSWORD_RESET_COOLDOWN_SECONDS=0",
        "PASSWORD_RESET_RATE_LIMIT_TIMEOUT_SECONDS=0", "PASSWORD_RESET_WORK_TIMEOUT_SECONDS=0",
    ]), encoding="utf-8")
    base = settings_factory()
    settings = config.Settings(
        _env_file=path, app_env="test", database_url=base.database_url,
        database_url_sync=base.database_url_sync, redis_url=base.redis_url,
        jwt_secret=base.jwt_secret, anthropic_api_key="", **safe,
    )
    assert settings.smtp_enabled is False
    if settings.smtp_username or settings.smtp_password:
        pytest.fail("Owned runner inherited synthetic SMTP credentials", pytrace=False)


def test_initializer_keeps_smtp_opt_in_without_filling_extra_service_credentials(tmp_path):
    from tools.init_env import initialize

    path = tmp_path / "synthetic-private.env"
    assert initialize(path) is True
    values = dict(line.split("=", 1) for line in path.read_text(encoding="utf-8").splitlines()
                  if line and not line.startswith("#"))
    assert values["SMTP_ENABLED"] == "false"
    assert all(values[field] == "" for field in (
        "SMTP_HOST", "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_FROM", "PASSWORD_RESET_URL",
    ))


class FakeRedis:
    def __init__(self, *, events=None, error=None, reply=None, gate=None):
        self.events = events if events is not None else []
        self.error = error
        self.reply = reply
        self.gate = gate
        self.calls = []
        self.counts = {}
        self.expiry = {}
        self.now = 0

    async def eval(self, script, number_of_keys, *values):
        self.events.append("limiter")
        self.calls.append((script, number_of_keys, values))
        if self.gate is not None:
            await self.gate.wait()
        if self.error is not None:
            raise self.error
        if self.reply is not None:
            return self.reply
        assert number_of_keys == 3
        ip_key, identity_key, cooldown_key, window, ip_max, identity_max, cooldown = values
        for key in (ip_key, identity_key, cooldown_key):
            if self.expiry.get(key, 0) <= self.now:
                self.counts.pop(key, None)
        for key, limit in ((ip_key, ip_max), (identity_key, identity_max)):
            self.counts[key] = self.counts.get(key, 0) + 1
            if self.counts[key] == 1:
                self.expiry[key] = self.now + window
            if self.counts[key] > limit:
                return [0, max(self.expiry[key] - self.now, 1)]
        if cooldown_key in self.counts:
            return [0, max(self.expiry[cooldown_key] - self.now, 1)]
        self.counts[cooldown_key] = 1
        self.expiry[cooldown_key] = self.now + cooldown
        return [1, 0]


@pytest.mark.asyncio
async def test_exhausted_peer_does_not_allocate_more_identity_keys(modules, smtp_settings):
    settings = smtp_settings.model_copy(update={"password_reset_max_requests_per_ip": 1})
    cache = FakeRedis()
    recovery = modules.recovery.PasswordRecovery(settings, cache=cache)
    first = await recovery.enqueue(
        email="first@example.com", tenant_id=None, client_host="127.0.0.1",
        background_tasks=BackgroundTasks(),
    )
    second = await recovery.enqueue(
        email="another@example.com", tenant_id=None, client_host="127.0.0.1",
        background_tasks=BackgroundTasks(),
    )
    assert first.state == "accepted" and second.state == "limited"
    _, _, keys = cache.calls[-1]
    assert keys[1] not in cache.counts and keys[2] not in cache.counts


class FakeTransaction:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        assert self.session.active is False
        self.session.active = True
        self.session.pending = []
        self.session.store.events.append("transaction")

    async def __aexit__(self, error_type, *_):
        self.session.active = False
        if error_type is None:
            self.session.store.tokens.extend(self.session.pending)
            self.session.commits += 1
            self.session.store.events.append("commit")
        else:
            self.session.store.events.append("rollback")
        self.session.pending = []


class FakeSession:
    def __init__(self, store):
        self.store = store
        self.active = False
        self.closed = False
        self.commits = 0
        self.pending = []

    async def __aenter__(self):
        self.store.events.append("session_open")
        return self

    async def __aexit__(self, *_):
        assert self.active is False
        self.closed = True
        self.store.events.append("session_closed")

    def begin(self):
        return FakeTransaction(self)

    def add(self, row):
        assert self.active is True
        self.pending.append(row)


class FakeStore:
    def __init__(self):
        self.events = []
        self.users = []
        self.tokens = []
        self.sessions = []
        self.invalidations = 0
        self.before_recipient = None
        self.lock_change = None

    def session_factory(self):
        session = FakeSession(self)
        self.sessions.append(session)
        return session

    def add_user(self, *, email="owner@example.com", tenant_id=None, active=True):
        user = SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant_id or uuid.uuid4(), email=email,
                               is_active=active, customer_email="different-contact@example.com")
        self.users.append(user)
        return user


@pytest.fixture
def store(monkeypatch, modules):
    state = FakeStore()

    async def find_user(db, email, tenant_id=None):
        state.events.append("lookup")
        assert db.active is True
        users = [user for user in state.users if user.email.lower() == email
                 and (tenant_id is None or user.tenant_id == tenant_id)]
        return users[0] if len(users) == 1 else None

    async def lock_user(db, user_id, tenant_id):
        state.events.append("user_lock")
        user = next((user for user in state.users
                     if user.id == user_id and user.tenant_id == tenant_id), None)
        if user is not None and state.lock_change is not None:
            state.lock_change(user)
        return user

    async def invalidate(db, user_id, now):
        assert db.active is True
        state.invalidations += 1
        for row in state.tokens:
            if row.user_id == user_id and row.used_at is None:
                row.used_at = now

    async def recipient(db, *, digest, email, tenant_id, now):
        assert db.commits == 1
        assert db.active is True
        if state.before_recipient is not None:
            state.before_recipient()
        state.events.append("recipient_check")
        row = next((row for row in state.tokens if row.token == "sha256:" + digest), None)
        if row is None or row.used_at is not None or row.expires_at <= now:
            return None
        user = next((user for user in state.users if user.id == row.user_id), None)
        if user is None or not user.is_active or user.email.lower() != email:
            return None
        if tenant_id is not None and user.tenant_id != tenant_id:
            return None
        return user.email

    async def audit(db, **values):
        assert db.active is True
        assert values["action"] == "auth.password_reset_requested"
        assert "metadata" not in values
        state.events.append("audit")

    monkeypatch.setattr(modules.recovery.repositories, "find_user", find_user)
    monkeypatch.setattr(modules.recovery.repositories, "lock_user", lock_user)
    monkeypatch.setattr(modules.recovery.repositories, "invalidate_password_resets", invalidate)
    monkeypatch.setattr(modules.recovery.repositories, "password_reset_recipient", recipient)
    monkeypatch.setattr(modules.recovery.service, "audit", audit)
    return state


@dataclass(frozen=True)
class SentReset:
    recipient: str = field(repr=False)
    token: str = field(repr=False)


class SpySender:
    def __init__(self, store, *, error=None):
        self.store = store
        self.error = error
        self.sent = []

    async def send(self, *, recipient, token):
        assert all(session.closed and not session.active for session in self.store.sessions)
        assert self.store.tokens
        if self.store.tokens[-1].token != "sha256:" + hashlib.sha256(token.encode()).hexdigest():
            pytest.fail("SMTP did not follow committed digest-only issuance", pytrace=False)
        self.store.events.append("smtp")
        self.sent.append(SentReset(recipient, token))
        if self.error is not None:
            raise self.error
        return True


def _app(monkeypatch, modules, settings, recovery):
    monkeypatch.setattr(modules.router, "settings", settings)
    app = FastAPI()
    app.state.password_recovery = recovery
    app.add_middleware(modules.recovery.RecoveryCapacityRelease)
    app.include_router(modules.router.router, prefix="/api/v1")
    app.include_router(modules.router.router, prefix="/api")

    async def forbidden_request_session():
        pytest.fail("Forgot-password retained or opened a request dependency session", pytrace=False)
        yield

    app.dependency_overrides[modules.router.get_db] = forbidden_request_session
    return app


async def _post(app, payload, *, path="/api/v1/auth/forgot-password", peer="203.0.113.20",
                headers=(), events=None, abort_response=False):
    messages = []
    body = json.dumps(payload).encode()
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": "POST", "scheme": "http", "path": path, "raw_path": path.encode(),
        "root_path": "", "query_string": b"", "client": (peer, 12345) if peer else None,
        "server": ("untrusted.example.com", 80),
        "headers": [(b"content-type", b"application/json"), *headers],
    }

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):
        if abort_response and message["type"] == "http.response.start":
            raise RuntimeError("Offline ASGI response aborted")
        messages.append(message)
        if message["type"] == "http.response.body" and not message.get("more_body", False):
            if events is not None:
                events.append("response_sent")

    await app(scope, receive, send)
    start = next(message for message in messages if message["type"] == "http.response.start")
    content = b"".join(message.get("body", b"") for message in messages
                       if message["type"] == "http.response.body")
    return start["status"], json.loads(content), dict(start["headers"])


@pytest.mark.asyncio
@pytest.mark.parametrize("eligibility", ["known", "unknown", "inactive", "ambiguous", "wrong_tenant"])
@pytest.mark.parametrize("prefix", ["/api/v1", "/api"])
async def test_every_valid_identity_gets_the_same_ack_before_lookup(
    modules, smtp_settings, store, monkeypatch, eligibility, prefix,
):
    email = "owner@example.com"
    payload = {"email": email}
    if eligibility != "unknown":
        user = store.add_user(email=email, active=eligibility != "inactive")
        if eligibility == "ambiguous":
            store.add_user(email=email)
        elif eligibility == "wrong_tenant":
            payload["tenant_id"] = str(uuid.uuid4())
        elif eligibility == "known":
            payload["tenant_id"] = str(user.tenant_id)
    cache, sender = FakeRedis(events=store.events), SpySender(store)
    recovery = modules.recovery.PasswordRecovery(
        smtp_settings, cache=cache, session_factory=store.session_factory, sender=sender,
    )
    app = _app(monkeypatch, modules, smtp_settings, recovery)
    status_code, response, headers = await _post(
        app, payload, path=prefix + "/auth/forgot-password", events=store.events,
    )
    assert status_code == 200
    assert response == ACKNOWLEDGEMENT
    assert headers[b"cache-control"] == b"no-store"
    assert store.events.index("limiter") < store.events.index("response_sent")
    assert store.events.index("response_sent") < store.events.index("lookup")
    assert len(cache.calls) == 1
    assert len(store.sessions) == 1
    assert store.sessions[0].closed is True
    assert len(sender.sent) == (1 if eligibility == "known" else 0)
    if eligibility == "known":
        assert store.events.index("commit") < store.events.index("recipient_check")
        assert store.events.index("session_closed") < store.events.index("smtp")
        assert store.sessions[0].commits == 2
        _no_private_values(json.dumps(response), sender.sent[0].token, email)


@pytest.mark.asyncio
async def test_sends_only_the_current_auth_email_not_the_customer_contact(
    modules, smtp_settings, store, monkeypatch,
):
    user = store.add_user(email="Owner@example.com")
    sender = SpySender(store)
    recovery = modules.recovery.PasswordRecovery(
        smtp_settings, cache=FakeRedis(), session_factory=store.session_factory, sender=sender,
    )
    app = _app(monkeypatch, modules, smtp_settings, recovery)
    status_code, response, _ = await _post(app, {"email": "OWNER@example.com"})
    assert (status_code, response) == (200, ACKNOWLEDGEMENT)
    assert sender.sent[0].recipient == user.email
    assert sender.sent[0].recipient != user.customer_email


@pytest.mark.asyncio
async def test_disabled_request_never_attempts_admission_or_issuance(
    modules, settings_factory, store, monkeypatch,
):
    settings = settings_factory()
    store.add_user()
    cache, sender = FakeRedis(), SpySender(store)
    recovery = modules.recovery.PasswordRecovery(
        settings, cache=cache, session_factory=store.session_factory, sender=sender,
    )
    app = _app(monkeypatch, modules, settings, recovery)
    status_code, response, headers = await _post(app, {"email": "owner@example.com"})
    assert status_code == 503
    assert set(response) == {"detail"}
    assert headers[b"cache-control"] == b"no-store"
    assert cache.calls == store.sessions == store.tokens == sender.sent == []


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["inactive", "changed", "deleted", "invalidated", "expired", "tenant"])
async def test_recheck_suppresses_accounts_or_tokens_changed_after_commit(
    modules, smtp_settings, store, change,
):
    user = store.add_user()

    def alter():
        if change == "inactive":
            user.is_active = False
        elif change == "changed":
            user.email = "changed@example.com"
        elif change == "deleted":
            store.users.clear()
        elif change == "invalidated":
            store.tokens[0].used_at = datetime.now(timezone.utc)
        elif change == "expired":
            store.tokens[0].expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        else:
            user.tenant_id = uuid.uuid4()

    store.before_recipient = alter
    sender = SpySender(store)
    recovery = modules.recovery.PasswordRecovery(
        smtp_settings, cache=FakeRedis(), session_factory=store.session_factory, sender=sender,
    )
    background = BackgroundTasks()
    await recovery.enqueue(email="owner@example.com", tenant_id=user.tenant_id,
                           client_host="203.0.113.20", background_tasks=background)
    await background()
    assert sender.sent == []
    assert store.sessions[0].closed is True


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["inactive", "email"])
async def test_existing_issuance_rechecks_the_locked_account(modules, smtp_settings, store, change):
    store.add_user()
    store.lock_change = lambda user: setattr(
        user, "is_active" if change == "inactive" else "email",
        False if change == "inactive" else "changed@example.com",
    )
    sender = SpySender(store)
    recovery = modules.recovery.PasswordRecovery(
        smtp_settings, cache=FakeRedis(), session_factory=store.session_factory, sender=sender,
    )
    background = BackgroundTasks()
    await recovery.enqueue(email="owner@example.com", tenant_id=None,
                           client_host="203.0.113.20", background_tasks=background)
    await background()
    assert store.tokens == sender.sent == []
    assert store.invalidations == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["exception", "timeout", "denied", "malformed", "boolean"])
async def test_admission_fails_closed_with_generic_ack_and_no_lookup(
    modules, smtp_settings, store, monkeypatch, caplog, failure,
):
    private = secrets.token_urlsafe(32)
    cache = FakeRedis(
        error=RuntimeError(private) if failure == "exception" else None,
        gate=asyncio.Event() if failure == "timeout" else None,
        reply={"denied": [0, 60], "malformed": "1", "boolean": [True, 0]}.get(failure),
    )
    recovery = modules.recovery.PasswordRecovery(
        smtp_settings, cache=cache, session_factory=store.session_factory, sender=SpySender(store),
    )
    app = _app(monkeypatch, modules, smtp_settings, recovery)
    status_code, response, headers = await _post(app, {"email": "owner@example.com"})
    assert (status_code, response) == ((429, LIMITED) if failure == "denied" else (503, UNAVAILABLE))
    assert headers[b"cache-control"] == b"no-store"
    if failure == "denied":
        assert headers[b"retry-after"] == b"60"
    assert store.sessions == store.tokens == []
    _no_private_values(caplog.text, private, "owner@example.com")
    assert all(record.exc_info is None for record in caplog.records)
    cache.error = cache.gate = None
    cache.reply = [1, 0]
    background = BackgroundTasks()
    await recovery.enqueue(email="owner@example.com", tenant_id=None,
                           client_host="203.0.113.20", background_tasks=background)
    assert len(background.tasks) == 1
    await background()


@pytest.mark.asyncio
async def test_capacity_is_no_wait_even_while_limiting_and_releases_on_cancellation(
    modules, smtp_settings, settings_factory, store,
):
    settings = settings_factory(**{**smtp_settings.model_dump(), "password_reset_capacity": 1,
                                  "smtp_username": smtp_settings.smtp_username,
                                  "smtp_password": smtp_settings.smtp_password})
    cache = FakeRedis(gate=asyncio.Event(), reply=[1, 0])
    recovery = modules.recovery.PasswordRecovery(
        settings, cache=cache, session_factory=store.session_factory, sender=SpySender(store),
    )
    first, second = BackgroundTasks(), BackgroundTasks()
    pending = asyncio.create_task(recovery.enqueue(
        email="owner@example.com", tenant_id=None, client_host="203.0.113.20",
        background_tasks=first,
    ))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    await recovery.enqueue(email="other@example.com", tenant_id=None,
                           client_host="203.0.113.20", background_tasks=second)
    assert len(cache.calls) == 1
    assert second.tasks == []
    assert store.sessions == []
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    cache.gate = None
    await recovery.enqueue(email="owner@example.com", tenant_id=None,
                           client_host="203.0.113.20", background_tasks=second)
    assert len(second.tasks) == 1
    await second()


@pytest.mark.asyncio
async def test_capacity_exhaustion_and_shutdown_keep_generic_ack_without_issuance(
    modules, smtp_settings, settings_factory, store, monkeypatch,
):
    settings = settings_factory(**{**smtp_settings.model_dump(), "password_reset_capacity": 1,
                                  "smtp_username": smtp_settings.smtp_username,
                                  "smtp_password": smtp_settings.smtp_password})
    cache = FakeRedis(reply=[1, 0])
    recovery = modules.recovery.PasswordRecovery(
        settings, cache=cache, session_factory=store.session_factory, sender=SpySender(store),
    )
    reserved = BackgroundTasks()
    await recovery.enqueue(email="owner@example.com", tenant_id=None,
                           client_host="203.0.113.20", background_tasks=reserved)
    app = _app(monkeypatch, modules, settings, recovery)
    status_code, response, _ = await _post(app, {"email": "other@example.com"})
    assert (status_code, response) == (503, UNAVAILABLE)
    assert len(cache.calls) == 1
    assert store.sessions == []
    recovery.close()
    await reserved()
    status_code, response, _ = await _post(app, {"email": "owner@example.com"})
    assert (status_code, response) == (503, UNAVAILABLE)
    assert len(cache.calls) == 1
    assert store.sessions == []


@pytest.mark.asyncio
async def test_capacity_remains_reserved_until_cancelled_smtp_has_really_closed(
    modules, smtp_settings, settings_factory, store, fake_smtp,
):
    store.add_user()
    settings = settings_factory(**{**smtp_settings.model_dump(), "password_reset_capacity": 1,
                                  "smtp_username": smtp_settings.smtp_username,
                                  "smtp_password": smtp_settings.smtp_password})
    started, release = threading.Event(), threading.Event()

    def block_send():
        started.set()
        if not release.wait(2):
            raise TimeoutError("Offline SMTP gate expired")

    fake_smtp.failures["send"] = block_send
    cache = FakeRedis(reply=[1, 0])
    recovery = modules.recovery.PasswordRecovery(
        settings, cache=cache, session_factory=store.session_factory,
        sender=modules.smtp.SMTPPasswordResetSender(settings),
    )
    first, rejected = BackgroundTasks(), BackgroundTasks()
    await recovery.enqueue(email="owner@example.com", tenant_id=None,
                           client_host="203.0.113.20", background_tasks=first)
    pending = asyncio.create_task(first())
    try:
        assert await asyncio.to_thread(started.wait, 1)
        pending.cancel()
        await asyncio.sleep(0)
        admission = await recovery.enqueue(email="owner@example.com", tenant_id=None,
                                           client_host="203.0.113.20", background_tasks=rejected)
        assert admission.state == "unavailable"
        assert rejected.tasks == []
        assert len(cache.calls) == 1
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(pending, 2)
    assert fake_smtp.events[-1] == "quit"
    await recovery.enqueue(email="owner@example.com", tenant_id=None,
                           client_host="203.0.113.20", background_tasks=rejected)
    assert len(rejected.tasks) == 1
    await rejected()


@pytest.mark.asyncio
async def test_aborted_response_releases_capacity_without_starting_background_issuance(
    modules, smtp_settings, settings_factory, store, monkeypatch,
):
    store.add_user()
    settings = settings_factory(**{**smtp_settings.model_dump(), "password_reset_capacity": 1,
                                  "smtp_username": smtp_settings.smtp_username,
                                  "smtp_password": smtp_settings.smtp_password})
    cache, sender = FakeRedis(reply=[1, 0]), SpySender(store)
    recovery = modules.recovery.PasswordRecovery(
        settings, cache=cache, session_factory=store.session_factory, sender=sender,
    )
    app = _app(monkeypatch, modules, settings, recovery)
    with pytest.raises(RuntimeError, match="Offline ASGI response aborted"):
        await _post(app, {"email": "owner@example.com"}, abort_response=True)
    assert store.sessions == store.tokens == sender.sent == []
    result = await _post(app, {"email": "owner@example.com"})
    assert result[:2] == (200, ACKNOWLEDGEMENT)
    assert len(cache.calls) == 2
    assert len(sender.sent) == 1


@pytest.mark.asyncio
async def test_shutdown_during_recipient_check_prevents_a_new_smtp_connection(
    modules, smtp_settings, store,
):
    store.add_user()
    sender = SpySender(store)
    recovery = modules.recovery.PasswordRecovery(
        smtp_settings, cache=FakeRedis(), session_factory=store.session_factory, sender=sender,
    )
    store.before_recipient = recovery.close
    background = BackgroundTasks()
    await recovery.enqueue(email="owner@example.com", tenant_id=None,
                           client_host="203.0.113.20", background_tasks=background)
    await background()
    assert store.sessions[0].closed is True
    assert sender.sent == []


@pytest.mark.asyncio
async def test_forwarded_header_spoofing_cannot_change_the_asgi_ip_counter(
    modules, smtp_settings, settings_factory, store, monkeypatch,
):
    store.add_user()
    settings = settings_factory(**{**smtp_settings.model_dump(),
                                  "password_reset_max_requests_per_ip": 1,
                                  "smtp_username": smtp_settings.smtp_username,
                                  "smtp_password": smtp_settings.smtp_password})
    cache, sender = FakeRedis(), SpySender(store)
    recovery = modules.recovery.PasswordRecovery(
        settings, cache=cache, session_factory=store.session_factory, sender=sender,
    )
    app = _app(monkeypatch, modules, settings, recovery)
    for index, (email, spoof) in enumerate((("owner@example.com", b"198.51.100.1"),
                                          ("unknown@example.com", b"198.51.100.2"))):
        result = await _post(app, {"email": email}, headers=[(b"x-forwarded-for", spoof)])
        assert result[:2] == ((200, ACKNOWLEDGEMENT) if index == 0 else (429, LIMITED))
        if index == 1:
            assert result[2][b"retry-after"] == b"3600"
    first, second = [call[2] for call in cache.calls]
    assert first[0] == second[0]
    assert first[1] != second[1]
    assert len(sender.sent) == 1
    serialized = json.dumps(cache.calls)
    _no_private_values(serialized, "owner@example.com", "unknown@example.com", "203.0.113.20",
                       "198.51.100.1", "198.51.100.2", sender.sent[0].token, settings.jwt_secret)


@pytest.mark.asyncio
@pytest.mark.parametrize("peer", [None, "not-a-trusted-ip"])
async def test_missing_or_invalid_asgi_peer_cannot_issue(
    modules, smtp_settings, store, monkeypatch, peer,
):
    cache = FakeRedis()
    recovery = modules.recovery.PasswordRecovery(
        smtp_settings, cache=cache, session_factory=store.session_factory, sender=SpySender(store),
    )
    result = await _post(_app(monkeypatch, modules, smtp_settings, recovery),
                         {"email": "owner@example.com"}, peer=peer,
                         headers=[(b"x-forwarded-for", b"203.0.113.1")])
    assert result[:2] == (503, UNAVAILABLE)
    assert cache.calls == store.sessions == []


@pytest.mark.asyncio
async def test_identity_cooldown_and_window_include_nonexistent_and_cross_tenant_requests(
    modules, smtp_settings, settings_factory, store,
):
    settings = settings_factory(**{**smtp_settings.model_dump(),
                                  "password_reset_max_requests_per_ip": 100,
                                  "smtp_username": smtp_settings.smtp_username,
                                  "smtp_password": smtp_settings.smtp_password})
    cache = FakeRedis()
    recovery = modules.recovery.PasswordRecovery(
        settings, cache=cache, session_factory=store.session_factory, sender=SpySender(store),
    )
    queued = []
    for index in range(5):
        background = BackgroundTasks()
        await recovery.enqueue(email=" UNKNown@example.com ", tenant_id=uuid.uuid4(),
                               client_host=f"203.0.113.{index + 1}", background_tasks=background)
        queued.append(len(background.tasks))
        await background()
        cache.now += 60
    assert queued == [1, 1, 1, 0, 0]
    identity_keys = [call[2][1] for call in cache.calls]
    assert len(set(identity_keys)) == 1
    expected = hmac.new(settings.jwt_secret.encode(),
                        b"supplyos/password-reset/rate/v1\0identity\0unknown@example.com",
                        hashlib.sha256).hexdigest()
    assert identity_keys[0].endswith(":" + expected)
    assert len(store.sessions) == 3
    cache.now = 3600
    background = BackgroundTasks()
    await recovery.enqueue(email="unknown@example.com", tenant_id=None,
                           client_host="203.0.113.20", background_tasks=background)
    assert len(background.tasks) == 1
    await background()


@pytest.mark.asyncio
async def test_cooldown_blocks_immediate_repeats_before_any_lookup(modules, smtp_settings, store):
    cache = FakeRedis()
    recovery = modules.recovery.PasswordRecovery(
        smtp_settings, cache=cache, session_factory=store.session_factory, sender=SpySender(store),
    )
    for _ in range(2):
        background = BackgroundTasks()
        await recovery.enqueue(email="unknown@example.com", tenant_id=None,
                               client_host="203.0.113.20", background_tasks=background)
        await background()
    assert len(cache.calls) == 2
    assert len(store.sessions) == 1


@pytest.mark.asyncio
async def test_cooldown_returns_generic_retry_after_for_known_and_unknown_identities(
    modules, smtp_settings, store, monkeypatch,
):
    store.add_user()
    cache = FakeRedis()
    recovery = modules.recovery.PasswordRecovery(
        smtp_settings, cache=cache, session_factory=store.session_factory, sender=SpySender(store),
    )
    app = _app(monkeypatch, modules, smtp_settings, recovery)
    for index, email in enumerate(("owner@example.com", "unknown@example.com")):
        peer = f"203.0.113.{index + 1}"
        first = await _post(app, {"email": email}, peer=peer)
        second = await _post(app, {"email": email}, peer=peer)
        assert first[:2] == (200, ACKNOWLEDGEMENT)
        assert second[:2] == (429, LIMITED)
        assert second[2][b"retry-after"] == b"60"
        assert second[2][b"cache-control"] == b"no-store"


@pytest.mark.asyncio
async def test_unexpected_sender_failure_preserves_ack_and_only_sanitized_logs(
    modules, smtp_settings, store, monkeypatch, caplog,
):
    store.add_user()
    private = secrets.token_urlsafe(32)
    sender = SpySender(store, error=RuntimeError(private))
    recovery = modules.recovery.PasswordRecovery(
        smtp_settings, cache=FakeRedis(), session_factory=store.session_factory, sender=sender,
    )
    result = await _post(_app(monkeypatch, modules, smtp_settings, recovery),
                         {"email": "owner@example.com"})
    assert result[:2] == (200, ACKNOWLEDGEMENT)
    assert store.invalidations == 1
    assert store.tokens[0].used_at is None
    _no_private_values(caplog.text, private, sender.sent[0].token, sender.sent[0].recipient,
                       smtp_settings.smtp_password, smtp_settings.password_reset_url)
    assert all(record.exc_info is None for record in caplog.records)


@pytest.mark.asyncio
async def test_older_failed_delivery_cannot_invalidate_a_newer_committed_reset(
    modules, smtp_settings, store,
):
    store.add_user()
    started, release = asyncio.Event(), asyncio.Event()
    sent = []

    class ConcurrentSender:
        async def send(self, *, recipient, token):
            sent.append(SentReset(recipient, token))
            if len(sent) == 1:
                started.set()
                await release.wait()
                return False
            return True

    cache = FakeRedis()
    recovery = modules.recovery.PasswordRecovery(
        smtp_settings, cache=cache, session_factory=store.session_factory, sender=ConcurrentSender(),
    )
    first, second = BackgroundTasks(), BackgroundTasks()
    await recovery.enqueue(email="owner@example.com", tenant_id=None,
                           client_host="203.0.113.20", background_tasks=first)
    pending = asyncio.create_task(first())
    try:
        await asyncio.wait_for(started.wait(), 1)
        cache.now = 60
        await recovery.enqueue(email="owner@example.com", tenant_id=None,
                               client_host="203.0.113.20", background_tasks=second)
        await second()
    finally:
        release.set()
        await pending
    assert len(sent) == 2
    assert store.invalidations == 2
    assert store.tokens[0].used_at is not None
    assert store.tokens[1].used_at is None


@pytest.mark.asyncio
async def test_database_failure_rolls_back_and_releases_capacity_without_smtp(
    modules, smtp_settings, store, monkeypatch, caplog,
):
    store.add_user()
    private = secrets.token_urlsafe(32)

    async def fail_audit(*_, **__):
        raise RuntimeError(private)

    monkeypatch.setattr(modules.recovery.service, "audit", fail_audit)
    sender = SpySender(store)
    recovery = modules.recovery.PasswordRecovery(
        smtp_settings, cache=FakeRedis(reply=[1, 0]), session_factory=store.session_factory, sender=sender,
    )
    for _ in range(smtp_settings.password_reset_capacity + 1):
        background = BackgroundTasks()
        await recovery.enqueue(email="owner@example.com", tenant_id=None,
                               client_host="203.0.113.20", background_tasks=background)
        assert len(background.tasks) == 1
        await background()
    assert store.tokens == sender.sent == []
    assert all(session.closed for session in store.sessions)
    assert "rollback" in store.events
    _no_private_values(caplog.text, private, "owner@example.com")


@pytest.mark.asyncio
async def test_recovery_database_wait_has_a_deadline_and_closes_its_session(
    modules, smtp_settings, store, monkeypatch, caplog,
):
    async def blocked_lookup(*_):
        await asyncio.Event().wait()

    monkeypatch.setattr(modules.recovery.repositories, "find_user", blocked_lookup)
    sender = SpySender(store)
    recovery = modules.recovery.PasswordRecovery(
        smtp_settings, cache=FakeRedis(), session_factory=store.session_factory, sender=sender,
    )
    background = BackgroundTasks()
    await recovery.enqueue(email="owner@example.com", tenant_id=None,
                           client_host="203.0.113.20", background_tasks=background)
    await asyncio.wait_for(background(), 2)
    assert store.sessions[0].closed is True
    assert "rollback" in store.events
    assert store.tokens == sender.sent == []
    assert "background work failed (recovery)" in caplog.text


@pytest.mark.asyncio
async def test_recipient_repository_queries_only_active_current_auth_identity(
    modules,
):
    query = None
    digest = hashlib.sha256(secrets.token_bytes(32)).hexdigest()
    tenant = uuid.uuid4()

    class Database:
        async def execute(self, statement):
            nonlocal query
            query = statement
            return SimpleNamespace(scalar_one_or_none=lambda: "owner@example.com")

    value = await modules.recovery.repositories.password_reset_recipient(
        Database(), digest=digest, email="owner@example.com", tenant_id=tenant,
        now=datetime.now(timezone.utc),
    )
    assert value == "owner@example.com"
    compiled = query.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert "SELECT users.email" in sql
    assert "customers" not in sql
    assert "users.tenant_id" in sql and "users.is_active IS true" in sql
    assert "password_reset_tokens.used_at IS NULL" in sql
    assert "password_reset_tokens.expires_at >" in sql
    if "sha256:" + digest not in compiled.params.values():
        pytest.fail("Recipient lookup did not use the reset digest", pytrace=False)


@pytest.mark.asyncio
@pytest.mark.parametrize("success", [True, False])
async def test_reset_clears_old_cookies_only_on_success_and_never_authenticates(
    modules, settings_factory, monkeypatch, success,
):
    from app.core.exceptions import NotFound

    app = _app(monkeypatch, modules, settings_factory(), None)
    dependency_session = object()
    received = []
    token, password = secrets.token_urlsafe(32), secrets.token_urlsafe(24)

    async def session():
        yield dependency_session

    async def reset(db, supplied_token, supplied_password):
        if db is not dependency_session or supplied_token != token or supplied_password != password:
            pytest.fail("Reset route changed the existing service contract", pytrace=False)
        received.append(True)
        if not success:
            raise NotFound("Invalid reset token")

    async def forbidden_authentication(*_, **__):
        pytest.fail("Reset automatically authenticated the user", pytrace=False)

    app.dependency_overrides[modules.router.get_db] = session
    monkeypatch.setattr(modules.router.service, "reset_password", reset)
    monkeypatch.setattr(modules.router.service, "authenticate", forbidden_authentication)
    result = await _post(app, {"token": token, "new_password": password},
                         path="/api/auth/reset-password")
    assert received == [True]
    assert result[0] == (200 if success else 404)
    assert result[2][b"cache-control"] == b"no-store"
    _no_private_values(json.dumps(result[1]), token, password)
    if success:
        assert result[1] == {"message": "Password reset successful"}
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/v1/auth/reset-password",
                                         json={"token": token, "new_password": password})
        cookies = SimpleCookie()
        for header in response.headers.get_list("set-cookie"):
            cookies.load(header)
        assert set(cookies) == {"access_token", "refresh_token"}
        for cookie in cookies.values():
            assert cookie["max-age"] == "0"
            assert cookie["path"] == "/"
            assert cookie["httponly"] is True
            assert cookie["samesite"] == "lax"
    else:
        assert b"set-cookie" not in result[2]


@pytest.mark.asyncio
async def test_forgot_validation_remains_redacted_and_no_store(
    modules, smtp_settings, store, monkeypatch,
):
    cache = FakeRedis()
    recovery = modules.recovery.PasswordRecovery(
        smtp_settings, cache=cache, session_factory=store.session_factory, sender=SpySender(store),
    )
    app = _app(monkeypatch, modules, smtp_settings, recovery)
    status_code, response, headers = await _post(
        app, {"email": "owner@example.com", "tenant_id": "invalid-tenant", "role": "super_admin"},
    )
    assert status_code == 422
    assert headers[b"cache-control"] == b"no-store"
    assert all("input" not in error and "ctx" not in error for error in response["detail"])
    _no_private_values(json.dumps(response), "owner@example.com", "invalid-tenant")
    assert cache.calls == store.sessions == []
