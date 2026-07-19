"""Application settings loaded from environment. Fails fast on missing critical vars."""
from __future__ import annotations

import os
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()


class Settings:
    """Immutable settings container. Access via `get_settings()`."""

    # App
    app_name: str = os.environ.get("APP_NAME", "Smart Supply Chain OS")
    app_env: str = os.environ.get("APP_ENV", "development")
    api_v1_prefix: str = os.environ.get("API_V1_PREFIX", "/api/v1")

    # Database
    database_url: str = os.environ["DATABASE_URL"]
    database_url_sync: str = os.environ["DATABASE_URL_SYNC"]

    # Redis
    redis_url: str = os.environ["REDIS_URL"]

    # Auth
    jwt_secret: str = os.environ["JWT_SECRET"]
    jwt_algorithm: str = os.environ.get("JWT_ALGORITHM", "HS256")
    access_token_minutes: int = int(os.environ.get("ACCESS_TOKEN_MINUTES", "30"))
    refresh_token_days: int = int(os.environ.get("REFRESH_TOKEN_DAYS", "7"))
    password_reset_hours: int = int(os.environ.get("PASSWORD_RESET_HOURS", "1"))
    account_lock_minutes: int = int(os.environ.get("ACCOUNT_LOCK_MINUTES", "15"))
    max_login_attempts: int = int(os.environ.get("MAX_LOGIN_ATTEMPTS", "5"))

    # AI
    emergent_llm_key: str = os.environ.get("EMERGENT_LLM_KEY", "")
    ai_provider: str = os.environ.get("AI_PROVIDER", "anthropic")
    ai_model: str = os.environ.get("AI_MODEL", "claude-sonnet-4-5-20250929")

    # CORS
    frontend_url: str = os.environ.get("FRONTEND_URL", "*")


@lru_cache
def get_settings() -> Settings:
    return Settings()
