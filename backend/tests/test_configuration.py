"""Configuration and metadata regressions that never contact live services."""
from __future__ import annotations

import secrets

import pytest
from pydantic import ValidationError
from sqlalchemy.engine import make_url

from app.core.config import DatabaseSettings, Settings


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    for field in Settings.model_fields.values():
        if isinstance(field.validation_alias, str):
            monkeypatch.delenv(field.validation_alias, raising=False)


@pytest.fixture
def config_values():
    return {
        "_env_file": None,
        "free_only_mode": True, "approved_free_smtp": False,
        "app_env": "test",
        "database_url": "postgresql+asyncpg://test_user@127.0.0.1/supplyos_test_config",
        "database_url_sync": "postgresql+psycopg2://test_user@127.0.0.1/supplyos_test_config",
        "redis_url": "redis://127.0.0.1:6379/0",
        "jwt_secret": secrets.token_urlsafe(48),
        "anthropic_api_key": "",
        "smtp_enabled": False, "smtp_host": "", "smtp_username": "", "smtp_password": "",
        "smtp_from": "", "password_reset_url": "",
    }


def test_missing_configuration_lists_names_without_inputs():
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None)
    missing = {item["loc"][0] for item in error.value.errors(include_input=False)}
    assert {"DATABASE_URL_SYNC", "DATABASE_URL", "REDIS_URL", "JWT_SECRET"} <= missing
    assert "input_value" not in str(error.value)


def test_migrations_need_only_sync_database_configuration():
    settings = DatabaseSettings(
        _env_file=None,
        database_url_sync="postgresql+psycopg2://test_user@127.0.0.1/supplyos_test_config",
    )
    assert settings.app_env == "development"
    assert "jwt_secret" not in settings.model_fields


def test_explicit_values_override_aliased_environment(config_values, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DATABASE_URL_SYNC", "postgresql+psycopg2://ambient@127.0.0.1/ambient")
    monkeypatch.setenv("ANTHROPIC_API_KEY", secrets.token_urlsafe(24))
    settings = Settings(**config_values)
    assert settings.app_env == "test"
    assert settings.database_url_sync == config_values["database_url_sync"]
    if settings.anthropic_api_key:
        pytest.fail("Explicit empty provider configuration was overridden by ambient credentials", pytrace=False)


def test_conflicting_explicit_aliases_are_rejected(config_values):
    with pytest.raises(ValueError, match="Conflicting explicit configuration"):
        Settings(**config_values, APP_ENV="production")


def test_development_defaults_and_immutability(config_values):
    settings = Settings(**config_values)
    assert settings.api_v1_prefix == "/api/v1"
    assert settings.cors_origins == ["http://localhost:3000"]
    assert settings.secure_cookies is False
    assert settings.smtp_enabled is False
    assert settings.password_reset_url == ""
    with pytest.raises(ValidationError):
        settings.app_env = "production"


def test_sensitive_settings_do_not_appear_in_repr_or_exports(config_values):
    config_values["smtp_username"] = secrets.token_urlsafe(24)
    config_values["smtp_password"] = secrets.token_urlsafe(32)
    settings = Settings(**config_values)
    exported = settings.model_dump()
    hidden_fields = {
        "database_url", "database_url_sync", "redis_url", "jwt_secret",
        "anthropic_api_key", "smtp_username", "smtp_password",
    }
    if hidden_fields & exported.keys():
        pytest.fail("Sensitive settings were exported", pytrace=False)
    if any(config_values[field] in repr(settings) for field in (
        "jwt_secret", "smtp_username", "smtp_password",
    )):
        pytest.fail("Sensitive settings appeared in repr", pytrace=False)


@pytest.mark.parametrize("field", [
    "access_token_minutes", "refresh_token_days", "password_reset_hours",
    "account_lock_minutes", "max_login_attempts",
    "password_reset_capacity", "password_reset_window_seconds",
    "password_reset_max_requests_per_ip", "password_reset_max_requests_per_identity",
    "password_reset_cooldown_seconds", "password_reset_rate_limit_timeout_seconds",
    "password_reset_work_timeout_seconds", "smtp_port", "smtp_timeout_seconds",
])
def test_auth_limits_must_be_positive(config_values, field):
    config_values[field] = 0
    with pytest.raises(ValidationError):
        Settings(**config_values)


@pytest.mark.parametrize("url", ["sqlite:///temporary.db", "https://example.test/database"])
def test_async_database_rejects_non_postgres_urls(config_values, url):
    config_values["database_url"] = url
    with pytest.raises(ValidationError):
        Settings(**config_values)


def test_sync_database_rejects_async_driver(config_values):
    config_values["database_url_sync"] = config_values["database_url"]
    with pytest.raises(ValidationError):
        Settings(**config_values)


def test_redis_rest_url_is_not_a_tcp_connector(config_values):
    config_values["redis_url"] = "https://redis.example.test"
    with pytest.raises(ValidationError):
        Settings(**config_values)


def test_async_database_normalizes_provider_sslmode(config_values):
    config_values["database_url"] += "?sslmode=require"
    settings = Settings(**config_values)
    assert make_url(settings.database_url).query == {"ssl": "require"}


def test_conflicting_ssl_parameters_are_rejected(config_values):
    config_values["database_url"] += "?ssl=require&sslmode=disable"
    with pytest.raises(ValidationError):
        Settings(**config_values)


def production_values(config_values):
    return {
        **config_values,
        "app_env": "production",
        "database_url": config_values["database_url"] + "?ssl=require",
        "database_url_sync": config_values["database_url_sync"] + "?sslmode=require",
        "frontend_url": "https://app.example.test",
    }


def test_production_uses_secure_cookies_and_tls(config_values):
    settings = Settings(**production_values(config_values))
    assert settings.secure_cookies is True


@pytest.mark.parametrize("field,value", [
    ("cookie_secure", False),
    ("frontend_url", "*"),
    ("frontend_url", "http://app.example.test"),
    ("database_url", "postgresql+asyncpg://test_user@127.0.0.1/supplyos_test_config"),
    ("database_url_sync", "postgresql+psycopg2://test_user@127.0.0.1/supplyos_test_config"),
])
def test_production_rejects_insecure_configuration(config_values, field, value):
    values = production_values(config_values)
    values[field] = value
    with pytest.raises(ValidationError):
        Settings(**values)


def test_same_site_none_requires_secure_cookies(config_values):
    config_values["cookie_samesite"] = "none"
    with pytest.raises(ValidationError):
        Settings(**config_values)


def test_origins_are_explicit_and_normalized(config_values):
    config_values["frontend_url"] = "http://localhost:3000/, http://127.0.0.1:3000"
    settings = Settings(**config_values)
    assert settings.cors_origins == ["http://localhost:3000", "http://127.0.0.1:3000"]
    config_values["frontend_url"] = "http://localhost:3000/path"
    with pytest.raises(ValidationError):
        Settings(**config_values)


def test_models_share_metadata_without_loading_runtime_settings():
    from app.infrastructure.db.base import Base
    from app.infrastructure.db import models  # noqa: F401

    assert {"tenants", "users", "orders", "inventory_items", "audit_logs"} <= Base.metadata.tables.keys()


@pytest.fixture
def smtp_values(config_values):
    return {
        **config_values, "smtp_enabled": True, "smtp_host": "relay.example.com",
        "smtp_username": secrets.token_urlsafe(24), "smtp_password": secrets.token_urlsafe(32),
        "smtp_from": "recovery@example.com", "smtp_from_name": "SupplyOS",
        "smtp_port": 587, "smtp_tls_mode": "starttls", "smtp_timeout_seconds": 10,
        "password_reset_url": "https://app.example.com/reset-password",
    }


@pytest.mark.parametrize("mode", ["starttls", "tls"])
def test_complete_authenticated_smtp_configuration(smtp_values, mode):
    smtp_values["smtp_tls_mode"] = mode
    smtp_values["frontend_url"] = "https://one.example.com,https://two.example.com"
    settings = Settings(**smtp_values)
    assert settings.smtp_enabled is True
    assert settings.smtp_tls_mode == mode
    assert settings.password_reset_url == "https://app.example.com/reset-password"
    assert len(settings.cors_origins) == 2


@pytest.mark.parametrize("field", ["smtp_host", "smtp_from", "password_reset_url"])
def test_enabled_smtp_requires_complete_public_configuration(smtp_values, field):
    smtp_values[field] = ""
    with pytest.raises(ValidationError):
        Settings(**smtp_values)


@pytest.mark.parametrize("field", ["smtp_username", "smtp_password"])
def test_remote_smtp_requires_a_complete_authentication_pair(smtp_values, field):
    smtp_values[field] = ""
    with pytest.raises(ValidationError):
        Settings(**smtp_values)


def test_remote_smtp_cannot_be_an_unauthenticated_relay(smtp_values):
    smtp_values.update(smtp_username="", smtp_password="")
    with pytest.raises(ValidationError):
        Settings(**smtp_values)


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "127.0.0.2", "::1"])
@pytest.mark.parametrize("environment", ["development", "test"])
def test_plain_smtp_is_only_unauthenticated_development_loopback(smtp_values, host, environment):
    smtp_values.update(
        app_env=environment, smtp_host=host, smtp_tls_mode="plain",
        smtp_username="", smtp_password="",
        password_reset_url="http://localhost:3000/reset-password",
    )
    assert Settings(**smtp_values).smtp_tls_mode == "plain"


@pytest.mark.parametrize("host,authenticated", [
    ("relay.example.com", False), ("relay.example.com", True), ("127.0.0.1", True),
    ("localhost.example.com", False), ("192.168.0.1", False),
])
def test_plain_smtp_never_carries_credentials_or_remote_traffic(smtp_values, host, authenticated):
    smtp_values.update(smtp_host=host, smtp_tls_mode="plain")
    if not authenticated:
        smtp_values.update(smtp_username="", smtp_password="")
    with pytest.raises(ValidationError):
        Settings(**smtp_values)


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_production_reset_requires_https_and_authenticated_tls(smtp_values, environment):
    values = production_values(smtp_values)
    values["app_env"] = environment
    assert Settings(**values).smtp_enabled is True
    values["password_reset_url"] = "http://app.example.com/reset-password"
    with pytest.raises(ValidationError):
        Settings(**values)
    values["password_reset_url"] = smtp_values["password_reset_url"]
    values.update(smtp_host="127.0.0.1", smtp_username="", smtp_password="", smtp_tls_mode="plain")
    with pytest.raises(ValidationError):
        Settings(**values)


@pytest.mark.parametrize("url", [
    "https://user:password@app.example.com/reset-password",
    "https://app.example.com/reset-password?token=unused",
    "https://app.example.com/reset-password#token=unused",
    "https://app.example.com/reset-password?", "https://app.example.com/reset-password#",
    "https://*.example.com/reset-password",
    "https://app.example.com/reset-password,https://other.example.com/reset-password",
    "https://app,other.example.com/reset-password",
    "https://app.example.com/other", "https://app.example.com/reset-password/",
    " https://app.example.com/reset-password", "https://app.example.com/reset-password\n",
    "https://app.example.com\r\nX-Injected: value/reset-password",
    "https://app%0d%0a.example.com/reset-password",
    "https://app.example.com/reset-password%0a", "https://app example.com/reset-password",
    "https://app.example.com\\other/reset-password",
    "https://app.example.com:0/reset-password", "https://app.example.com:65536/reset-password",
    "https://app.example.com:/reset-password", "https://[not-an-ip]/reset-password",
    "//app.example.com/reset-password", "javascript:reset-password",
])
def test_reset_url_rejects_noncanonical_or_injected_links(smtp_values, url):
    smtp_values["password_reset_url"] = url
    with pytest.raises(ValidationError):
        Settings(**smtp_values)


@pytest.mark.parametrize("url", [
    "http://localhost:3000/reset-password", "https://app.example.com/reset-password",
    "http://[::1]:3000/reset-password",
])
def test_development_canonical_reset_url_is_separate_from_cors(smtp_values, url):
    smtp_values.update(frontend_url="*", password_reset_url=url)
    assert Settings(**smtp_values).password_reset_url == url


@pytest.mark.parametrize("field,value", [
    ("smtp_host", "smtp://relay.example.com"), ("smtp_host", "relay.example.com\n"),
    ("smtp_host", "relay.example.com:587"), ("smtp_host", "relay,other.example.com"),
    ("smtp_host", "relay.example.com/path"),
    ("smtp_from", "Name <recovery@example.com>"),
    ("smtp_from", "recovery@example.com,other@example.com"), ("smtp_from", "not-an-email"),
    ("smtp_from", "recovery@example.com\r\nBcc: other@example.com"),
    ("smtp_from_name", "SupplyOS\r\nBcc: other@example.com"),
    ("smtp_from_name", "SupplyOS\x00"), ("smtp_from_name", "SupplyOS\t"),
    ("smtp_tls_mode", "unverified"),
    ("smtp_username", " "), ("smtp_password", " "),
    ("smtp_timeout_seconds", 31), ("smtp_timeout_seconds", float("inf")),
    ("password_reset_capacity", 33), ("password_reset_rate_limit_timeout_seconds", 6),
    ("password_reset_work_timeout_seconds", 61), ("password_reset_window_seconds", 86401),
])
def test_smtp_headers_transport_and_capacity_are_bounded(smtp_values, field, value):
    smtp_values[field] = value
    with pytest.raises(ValidationError) as error:
        Settings(**smtp_values)
    if any(smtp_values[name].strip() and smtp_values[name] in str(error.value)
           for name in ("smtp_username", "smtp_password")):
        pytest.fail("SMTP configuration error exposed credentials", pytrace=False)


def test_reset_cooldown_cannot_outlive_the_configured_window(smtp_values):
    smtp_values.update(password_reset_window_seconds=60, password_reset_cooldown_seconds=61)
    with pytest.raises(ValidationError):
        Settings(**smtp_values)


def test_explicit_disabled_smtp_cannot_inherit_ambient_credentials(config_values, monkeypatch):
    monkeypatch.setenv("SMTP_ENABLED", "true")
    monkeypatch.setenv("SMTP_HOST", "relay.example.com")
    monkeypatch.setenv("SMTP_USERNAME", secrets.token_urlsafe(24))
    monkeypatch.setenv("SMTP_PASSWORD", secrets.token_urlsafe(32))
    settings = Settings(**config_values)
    assert settings.smtp_enabled is False
    if settings.smtp_username or settings.smtp_password:
        pytest.fail("Disabled test configuration inherited SMTP credentials", pytrace=False)
