"""Password hashing, JWT encode/decode, and token payload contracts."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

import bcrypt
import jwt

from app.core.config import get_settings

settings = get_settings()

TokenType = Literal["access", "refresh"]


@dataclass
class TokenPayload:
    sub: str  # user_id
    tenant_id: str
    role: str
    type: TokenType
    jti: str
    exp: datetime


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


def _encode(payload: dict) -> str:
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(user_id: str, tenant_id: str, role: str) -> tuple[str, str]:
    jti = str(uuid.uuid4())
    exp = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_minutes)
    token = _encode(
        {
            "sub": user_id,
            "tenant_id": tenant_id,
            "role": role,
            "type": "access",
            "jti": jti,
            "exp": exp,
        }
    )
    return token, jti


def create_refresh_token(user_id: str, tenant_id: str, role: str) -> tuple[str, str]:
    jti = str(uuid.uuid4())
    exp = datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_days)
    token = _encode(
        {
            "sub": user_id,
            "tenant_id": tenant_id,
            "role": role,
            "type": "refresh",
            "jti": jti,
            "exp": exp,
        }
    )
    return token, jti


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
