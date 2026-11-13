"""Validated, immutable settings; secret values stay out of errors and reprs."""
from __future__ import annotations

import os
import re
from functools import lru_cache
from ipaddress import ip_address
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import EmailStr, Field, TypeAdapter, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

BACKEND_ROOT = Path(__file__).resolve().parents[2]
ENV_FILES = (BACKEND_ROOT.parent / ".env", BACKEND_ROOT / ".env")


def _valid_network_host(value: str) -> bool:
    if not value or any(char.isspace() or char in "%/\\@,;*[]?#" for char in value):
        return False
    try:
        ip_address(value)
        return True
    except ValueError:
        return len(value) <= 253 and bool(re.fullmatch(
            r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
            r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*", value,
        ))


def _is_loopback_host(value: str) -> bool:
    if value == "localhost":
        return True
    try:
        return ip_address(value).is_loopback
    except ValueError:
        return False


class DatabaseSettings(BaseSettings):
    """Migration configuration does not require application or AI credentials."""

    model_config = SettingsConfigDict(
        env_file=None if os.environ.get("SUPPLYOS_OWNED_TEST_ENV") == "1" else ENV_FILES,
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
        populate_by_name=True,
        hide_input_in_errors=True,
    )

    def __init__(self, **values):
        canonical = {}
        for name, value in values.items():
            field = type(self).model_fields.get(name)
            alias = field.validation_alias if field is not None else name
            key = alias if isinstance(alias, str) else name
            if key != name and key in values and value != values[key]:
                raise ValueError(f"Conflicting explicit configuration for {key}")
            canonical[key] = value
        super().__init__(**canonical)

    app_env: Literal["development", "test", "staging", "production"] = Field(
        default="development", validation_alias="APP_ENV"
    )
    database_url_sync: str = Field(
        validation_alias="DATABASE_URL_SYNC", repr=False, exclude=True
    )

    @field_validator("database_url_sync")
    @classmethod
    def validate_sync_database_url(cls, value: str) -> str:
        try:
            url = make_url(value)
        except Exception:
            raise ValueError("DATABASE_URL_SYNC must be a PostgreSQL connection URL") from None
        if url.drivername not in {"postgresql", "postgresql+psycopg2"} or not url.database:
            raise ValueError("DATABASE_URL_SYNC needs a PostgreSQL database and psycopg2 driver")
        return value

    @model_validator(mode="after")
    def require_sync_database_tls(self) -> "DatabaseSettings":
        if self.app_env in {"staging", "production"}:
            if make_url(self.database_url_sync).query.get("sslmode") not in {
                "require", "verify-ca", "verify-full"
            }:
                raise ValueError("Production DATABASE_URL_SYNC must require TLS with sslmode")
        return self


class Settings(DatabaseSettings):
    """Application configuration. Construct only at startup or via get_settings."""

    app_name: str = Field(default="Smart Supply Chain OS", validation_alias="APP_NAME")
    api_v1_prefix: str = Field(default="/api/v1", validation_alias="API_V1_PREFIX")
    free_only_mode: bool = Field(default=True, validation_alias="FREE_ONLY_MODE")
    approved_free_smtp: bool = Field(default=False, validation_alias="APPROVED_FREE_SMTP")
    setup_authorization_token: str = Field(
        default="", max_length=256, validation_alias="SETUP_AUTHORIZATION_TOKEN", repr=False, exclude=True,
    )

    @field_validator("setup_authorization_token")
    @classmethod
    def validate_setup_authorization(cls, value: str) -> str:
        if value and (
            len(value) < 32 or len(set(value)) < 12
            or not re.fullmatch(r"[A-Za-z0-9_-]+", value)
        ):
            raise ValueError("Setup authorization requires a private high-entropy URL-safe token")
        return value

    database_url: str = Field(validation_alias="DATABASE_URL", repr=False, exclude=True)
    redis_url: str = Field(validation_alias="REDIS_URL", repr=False, exclude=True)

    jwt_secret: str = Field(
        validation_alias="JWT_SECRET", min_length=32, repr=False, exclude=True
    )
    jwt_algorithm: Literal["HS256", "HS384", "HS512"] = Field(
        default="HS256", validation_alias="JWT_ALGORITHM"
    )
    access_token_minutes: int = Field(default=30, ge=1, validation_alias="ACCESS_TOKEN_MINUTES")
    refresh_token_days: int = Field(default=7, ge=1, validation_alias="REFRESH_TOKEN_DAYS")
    password_reset_hours: int = Field(default=1, ge=1, validation_alias="PASSWORD_RESET_HOURS")
    password_reset_url: str = Field(default="", validation_alias="PASSWORD_RESET_URL")
    password_reset_capacity: int = Field(
        default=4, ge=1, le=32, validation_alias="PASSWORD_RESET_CAPACITY"
    )
    password_reset_window_seconds: int = Field(
        default=3600, ge=60, le=86400, validation_alias="PASSWORD_RESET_WINDOW_SECONDS"
    )
    password_reset_max_requests_per_ip: int = Field(
        default=3, ge=1, le=1000, validation_alias="PASSWORD_RESET_MAX_REQUESTS_PER_IP"
    )
    password_reset_max_requests_per_identity: int = Field(
        default=3, ge=1, le=1000, validation_alias="PASSWORD_RESET_MAX_REQUESTS_PER_IDENTITY"
    )
    password_reset_cooldown_seconds: int = Field(
        default=60, ge=1, le=3600, validation_alias="PASSWORD_RESET_COOLDOWN_SECONDS"
    )
    password_reset_rate_limit_timeout_seconds: float = Field(
        default=0.5, ge=0.05, le=5, allow_inf_nan=False,
        validation_alias="PASSWORD_RESET_RATE_LIMIT_TIMEOUT_SECONDS",
    )
    password_reset_work_timeout_seconds: float = Field(
        default=10, ge=1, le=60, allow_inf_nan=False,
        validation_alias="PASSWORD_RESET_WORK_TIMEOUT_SECONDS",
    )
    account_lock_minutes: int = Field(default=15, ge=1, validation_alias="ACCOUNT_LOCK_MINUTES")
    max_login_attempts: int = Field(default=5, ge=1, validation_alias="MAX_LOGIN_ATTEMPTS")
    cookie_secure: bool | None = Field(default=None, validation_alias="COOKIE_SECURE")
    cookie_samesite: Literal["lax", "strict", "none"] = Field(
        default="lax", validation_alias="COOKIE_SAMESITE"
    )

    smtp_enabled: bool = Field(default=False, validation_alias="SMTP_ENABLED")
    smtp_host: str = Field(default="", validation_alias="SMTP_HOST")
    smtp_port: int = Field(default=587, ge=1, le=65535, validation_alias="SMTP_PORT")
    smtp_username: str = Field(
        default="", max_length=512, validation_alias="SMTP_USERNAME", repr=False, exclude=True
    )
    smtp_password: str = Field(
        default="", max_length=4096, validation_alias="SMTP_PASSWORD", repr=False, exclude=True
    )
    smtp_from: str = Field(default="", max_length=254, validation_alias="SMTP_FROM")
    smtp_from_name: str = Field(
        default="SupplyOS", max_length=120, validation_alias="SMTP_FROM_NAME"
    )
    smtp_tls_mode: Literal["starttls", "tls", "plain"] = Field(
        default="starttls", validation_alias="SMTP_TLS_MODE"
    )
    smtp_timeout_seconds: float = Field(
        default=10, ge=1, le=30, allow_inf_nan=False, validation_alias="SMTP_TIMEOUT_SECONDS"
    )

    anthropic_api_key: str = Field(
        default="", validation_alias="ANTHROPIC_API_KEY", repr=False, exclude=True
    )
    ai_provider: Literal["anthropic"] = Field(
        default="anthropic", validation_alias="AI_PROVIDER"
    )
    ai_model: str = Field(
        default="claude-sonnet-4-5-20250929", validation_alias="AI_MODEL"
    )
    frontend_url: str = Field(default="http://localhost:3000", validation_alias="FRONTEND_URL")
    proof_storage_dir: Path = Field(default=BACKEND_ROOT / ".runtime" / "proofs", validation_alias="PROOF_STORAGE_DIR")
    proof_storage_backend: Literal["local", "supabase"] = Field(
        default="local", validation_alias="PROOF_STORAGE_BACKEND"
    )
    approved_free_storage: bool = Field(default=False, validation_alias="APPROVED_FREE_STORAGE")
    supabase_versioning_verified: bool = Field(
        default=False, validation_alias="SUPABASE_VERSIONING_VERIFIED"
    )
    supabase_storage_origin: str = Field(default="", validation_alias="SUPABASE_STORAGE_ORIGIN")
    supabase_storage_bucket: str = Field(default="", validation_alias="SUPABASE_STORAGE_BUCKET")
    supabase_storage_key: str = Field(
        default="", max_length=4096, validation_alias="SUPABASE_STORAGE_KEY", repr=False, exclude=True
    )
    proof_storage_timeout_seconds: float = Field(
        default=10, ge=0.1, le=30, allow_inf_nan=False,
        validation_alias="PROOF_STORAGE_TIMEOUT_SECONDS",
    )
    proof_storage_capacity: int = Field(
        default=4, ge=1, le=16, validation_alias="PROOF_STORAGE_CAPACITY"
    )

    @field_validator("supabase_storage_origin")
    @classmethod
    def validate_storage_origin(cls, value: str) -> str:
        if value and not re.fullmatch(r"https://[a-z0-9-]{3,63}\.supabase\.co", value):
            raise ValueError("Storage needs a canonical HTTPS Supabase project origin")
        return value

    @field_validator("supabase_storage_bucket")
    @classmethod
    def validate_storage_bucket(cls, value: str) -> str:
        if value and not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,62}", value):
            raise ValueError("Storage bucket name is invalid")
        return value

    @field_validator("supabase_storage_key")
    @classmethod
    def validate_storage_key(cls, value: str) -> str:
        if value and (len(value) < 32 or any(char.isspace() or ord(char) < 32 for char in value)):
            raise ValueError("Storage needs a private service credential")
        return value

    @model_validator(mode="after")
    def validate_hosted_storage(self) -> "Settings":
        if self.proof_storage_backend == "supabase" and not (
            self.supabase_storage_origin and self.supabase_storage_bucket and self.supabase_storage_key
        ):
            raise ValueError("Hosted proofs require storage origin, bucket and private credential")
        return self

    @field_validator("database_url")
    @classmethod
    def validate_async_database_url(cls, value: str) -> str:
        try:
            url = make_url(value)
        except Exception:
            raise ValueError("DATABASE_URL must be a PostgreSQL asyncpg connection URL") from None
        if url.drivername != "postgresql+asyncpg" or not url.database:
            raise ValueError("DATABASE_URL needs a PostgreSQL database and the asyncpg driver")
        query = dict(url.query)
        if "sslmode" in query:
            if "ssl" in query and query["ssl"] != query["sslmode"]:
                raise ValueError("DATABASE_URL has conflicting ssl and sslmode parameters")
            query["ssl"] = query.pop("sslmode")
            return url.set(query=query).render_as_string(hide_password=False)
        return value

    @field_validator("redis_url")
    @classmethod
    def validate_redis_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme not in {"redis", "rediss"} or not parsed.hostname:
            raise ValueError("REDIS_URL must use redis:// or rediss://, not a REST endpoint")
        return value

    @field_validator("api_v1_prefix")
    @classmethod
    def validate_api_prefix(cls, value: str) -> str:
        if not value.startswith("/") or value.endswith("/") or "?" in value or "#" in value:
            raise ValueError("API_V1_PREFIX must be an absolute path without a trailing slash")
        return value

    @field_validator("frontend_url")
    @classmethod
    def validate_frontend_origins(cls, value: str) -> str:
        if value == "*":
            return value
        origins = [origin.strip() for origin in value.split(",")]
        for origin in origins:
            parsed = urlsplit(origin)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.path not in {"", "/"}
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("FRONTEND_URL must contain explicit HTTP(S) origins, not paths")
        return ",".join(origin.rstrip("/") for origin in origins)

    @field_validator("smtp_host")
    @classmethod
    def validate_smtp_host(cls, value: str) -> str:
        if value and not _valid_network_host(value):
            raise ValueError("SMTP_HOST must be a single hostname or IP address")
        return value.lower()

    @field_validator("smtp_from")
    @classmethod
    def validate_smtp_from(cls, value: str) -> str:
        if not value:
            return value
        if any(char.isspace() or ord(char) < 32 or char in ",;<>" for char in value):
            raise ValueError("SMTP_FROM must be one email address without a display name")
        try:
            return str(TypeAdapter(EmailStr).validate_python(value))
        except ValueError:
            raise ValueError("SMTP_FROM must be one valid email address") from None

    @field_validator("smtp_from_name")
    @classmethod
    def validate_smtp_from_name(cls, value: str) -> str:
        if any(ord(char) < 32 or ord(char) == 127 or char in "\u2028\u2029" for char in value):
            raise ValueError("SMTP_FROM_NAME must not contain header control characters")
        return value

    @field_validator("password_reset_url")
    @classmethod
    def validate_password_reset_url(cls, value: str) -> str:
        if not value:
            return value
        invalid = any(
            char.isspace() or ord(char) < 32 or ord(char) == 127 or char in "\\,;*?#"
            for char in value
        )
        try:
            parsed = urlsplit(value)
            invalid = invalid or (
                parsed.scheme not in {"http", "https"}
                or not _valid_network_host(parsed.hostname or "")
                or parsed.username is not None or parsed.password is not None
                or parsed.path != "/reset-password" or parsed.netloc.endswith(":")
                or (parsed.port is not None and not 1 <= parsed.port <= 65535)
            )
        except ValueError:
            invalid = True
        if invalid:
            raise ValueError("PASSWORD_RESET_URL must be one canonical HTTP(S) /reset-password URL")
        return value

    @property
    def secure_cookies(self) -> bool:
        if self.cookie_secure is not None:
            return self.cookie_secure
        return self.app_env in {"staging", "production"}

    @property
    def cors_origins(self) -> list[str]:
        return self.frontend_url.split(",")

    @property
    def can_send_password_reset(self) -> bool:
        return self.smtp_enabled and (
            not self.free_only_mode or self.approved_free_smtp or (
                self.app_env in {"development", "test"} and _is_loopback_host(self.smtp_host)
            )
        )

    @model_validator(mode="after")
    def validate_transport_security(self) -> "Settings":
        if self.cookie_samesite == "none" and not self.secure_cookies:
            raise ValueError("COOKIE_SAMESITE=none requires secure cookies")
        if self.app_env in {"staging", "production"}:
            if not self.secure_cookies:
                raise ValueError("Production cookies must be secure")
            if self.frontend_url == "*" or any(
                not origin.startswith("https://") for origin in self.cors_origins
            ):
                raise ValueError("Production FRONTEND_URL must contain explicit HTTPS origins")
            if make_url(self.database_url).query.get("ssl") not in {
                "require", "verify-ca", "verify-full"
            }:
                raise ValueError("Production DATABASE_URL must require TLS with ssl")
        return self

    @model_validator(mode="after")
    def validate_password_reset_delivery(self) -> "Settings":
        if self.password_reset_cooldown_seconds > self.password_reset_window_seconds:
            raise ValueError("Password reset cooldown must not exceed its rate-limit window")
        if self.password_reset_url and self.app_env in {"staging", "production"}:
            if urlsplit(self.password_reset_url).scheme != "https":
                raise ValueError("Production PASSWORD_RESET_URL must use HTTPS")
        if not self.smtp_enabled:
            return self
        if not self.smtp_host or not self.smtp_from or not self.password_reset_url:
            raise ValueError("Enabled SMTP requires SMTP_HOST, SMTP_FROM and PASSWORD_RESET_URL")
        if bool(self.smtp_username) != bool(self.smtp_password):
            raise ValueError("SMTP authentication requires both SMTP_USERNAME and SMTP_PASSWORD")
        if self.smtp_username and not (self.smtp_username.strip() and self.smtp_password.strip()):
            raise ValueError("SMTP authentication credentials must not be blank")
        local_development = (
            self.app_env in {"development", "test"} and _is_loopback_host(self.smtp_host)
        )
        if self.smtp_tls_mode == "plain":
            if not local_development or self.smtp_username or self.smtp_password:
                raise ValueError("Plain SMTP is only allowed unauthenticated on development loopback")
        elif not local_development and not self.smtp_username:
            raise ValueError("Remote SMTP requires authenticated, verified TLS")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
