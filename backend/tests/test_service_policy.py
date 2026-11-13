"""Fee policy contracts: hosted configuration is valid, paid work is never implicit."""
from __future__ import annotations

import importlib
import secrets
import uuid
from types import SimpleNamespace

import httpx
import pytest
from fastapi import BackgroundTasks, FastAPI

from app.core import config


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    for field in config.Settings.model_fields.values():
        if isinstance(field.validation_alias, str):
            monkeypatch.delenv(field.validation_alias, raising=False)


@pytest.fixture
def values():
    return {
        "_env_file": None, "app_env": "test",
        "database_url": "postgresql+asyncpg://test_user@127.0.0.1/supplyos_test_policy",
        "database_url_sync": "postgresql+psycopg2://test_user@127.0.0.1/supplyos_test_policy",
        "redis_url": "redis://127.0.0.1:6379/0", "jwt_secret": secrets.token_urlsafe(48),
        "anthropic_api_key": "", "smtp_enabled": False, "smtp_host": "",
        "smtp_username": "", "smtp_password": "", "smtp_from": "",
        "password_reset_url": "", "approved_free_smtp": False,
    }


@pytest.fixture
def modules(values, monkeypatch):
    settings = config.Settings(**values)
    monkeypatch.setattr(config, "get_settings", lambda: settings)
    provider = importlib.import_module("app.infrastructure.external.ai_provider")
    smtp = importlib.import_module("app.infrastructure.external.smtp")
    recovery = importlib.import_module("app.features.auth.recovery")
    router = importlib.import_module("app.features.ai_supervisor.router")
    monkeypatch.setattr(provider, "settings", settings)
    monkeypatch.setattr(router, "get_settings", lambda: settings)
    return SimpleNamespace(settings=settings, provider=provider, smtp=smtp, recovery=recovery, router=router)


def smtp_values(values, **changes):
    return {
        **values, "smtp_enabled": True, "smtp_host": "relay.example.com",
        "smtp_from": "recovery@example.com", "smtp_username": secrets.token_urlsafe(24),
        "smtp_password": secrets.token_urlsafe(32),
        "password_reset_url": "https://app.example.com/reset-password", **changes,
    }


def test_free_mode_is_default_and_never_implies_paid_transport(values):
    settings = config.Settings(**values)
    assert settings.free_only_mode is True
    assert settings.approved_free_smtp is False
    assert settings.can_send_password_reset is False


def test_hosted_database_and_cache_are_not_rejected_by_free_mode(values):
    settings = config.Settings(**{
        **values,
        "database_url": "postgresql+asyncpg://test_user@db.example.com/project?ssl=require",
        "database_url_sync": "postgresql+psycopg2://test_user@db.example.com/project?sslmode=require",
        "redis_url": "rediss://cache.example.com:6380/0",
    })
    assert settings.free_only_mode is True
    assert "db.example.com" in settings.database_url
    assert settings.redis_url.startswith("rediss://")


@pytest.mark.parametrize("approval", [False, True])
def test_remote_smtp_requires_an_explicit_free_account_approval(values, approval):
    settings = config.Settings(**smtp_values(values, approved_free_smtp=approval))
    assert settings.can_send_password_reset is approval


@pytest.mark.parametrize("environment", ["development", "test", "staging", "production"])
def test_local_capture_is_not_misrepresented_as_production_email(values, environment):
    configured = smtp_values(values, app_env=environment, smtp_host="127.0.0.1")
    if environment in {"staging", "production"}:
        configured.update(
            database_url=values["database_url"] + "?ssl=require",
            database_url_sync=values["database_url_sync"] + "?sslmode=require",
            frontend_url="https://app.example.com",
        )
    settings = config.Settings(**configured)
    assert settings.can_send_password_reset is (environment in {"development", "test"})


@pytest.mark.asyncio
async def test_existing_ai_credentials_cannot_trigger_a_paid_request(modules, values, monkeypatch):
    key = secrets.token_urlsafe(32)
    settings = config.Settings(**{**values, "anthropic_api_key": key})
    monkeypatch.setattr(modules.provider, "settings", settings)

    def forbidden_client(**_):
        pytest.fail("Free policy constructed an external AI client", pytrace=False)

    monkeypatch.setattr(modules.provider.httpx, "AsyncClient", forbidden_client)
    assert modules.provider.get_ai_provider() is None
    with pytest.raises(RuntimeError, match="on hold") as error:
        await modules.provider.AnthropicProvider(key, "unapproved-model").analyze(
            system_prompt="Policy test", user_prompt="No customer data",
        )
    if key in str(error.value):
        pytest.fail("Policy failure exposed a private key", pytrace=False)


@pytest.mark.asyncio
async def test_unapproved_smtp_is_blocked_at_both_transport_entrypoints(modules, values, monkeypatch):
    settings = config.Settings(**smtp_values(values))

    def forbidden_client(*_, **__):
        pytest.fail("Free policy constructed an unapproved SMTP client", pytrace=False)

    monkeypatch.setattr(modules.smtp.smtplib, "SMTP", forbidden_client)
    monkeypatch.setattr(modules.smtp.smtplib, "SMTP_SSL", forbidden_client)
    sender = modules.smtp.SMTPPasswordResetSender(settings)
    assert await sender.send(recipient="owner@example.com", token=secrets.token_urlsafe(32)) is False
    assert sender._send("owner@example.com", secrets.token_urlsafe(32)) is False


@pytest.mark.asyncio
async def test_blocked_smtp_cannot_use_cache_or_issue_a_reset_token(modules, values):
    class ForbiddenCache:
        async def eval(self, *_):
            pytest.fail("Blocked recovery contacted the limiter", pytrace=False)

    def forbidden_session():
        pytest.fail("Blocked recovery opened a database session", pytrace=False)

    recovery = modules.recovery.PasswordRecovery(
        config.Settings(**smtp_values(values)), cache=ForbiddenCache(), session_factory=forbidden_session,
    )
    tasks = BackgroundTasks()
    admission = await recovery.enqueue(
        email="owner@example.com", tenant_id=None, client_host="127.0.0.1", background_tasks=tasks,
    )
    assert admission.state == "unavailable" and not tasks.tasks


@pytest.mark.asyncio
async def test_ai_capabilities_expose_only_safe_policy_fields(modules):
    app = FastAPI()
    app.include_router(modules.router.router, prefix="/api/v1")
    app.include_router(modules.router.router, prefix="/api")
    app.dependency_overrides[modules.router.require_staff] = lambda: SimpleNamespace(tenant_id=uuid.uuid4())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        for prefix in ("/api/v1", "/api"):
            response = await client.get(f"{prefix}/ai/capabilities")
            assert response.status_code == 200
            assert response.json() == {
                "free_only_mode": True, "can_request_summary": False, "summary_status": "held_free_only",
            }


@pytest.mark.asyncio
async def test_requested_summary_is_held_without_queuing_or_replacing_rule_results(modules, monkeypatch):
    async def rule_checks(_, __):
        return {"low_stock": 2, "credit_risk": 1}

    monkeypatch.setattr(modules.router.ai_service, "run_all_analyses", rule_checks)
    tasks = BackgroundTasks()
    result = await modules.router.run_analyze(
        db=None, user=SimpleNamespace(tenant_id=uuid.uuid4()), background_tasks=tasks, include_summary=True,
    )
    assert result.counts == {"low_stock": 2, "credit_risk": 1}
    assert result.summary_status == "held_free_only" and not tasks.tasks
