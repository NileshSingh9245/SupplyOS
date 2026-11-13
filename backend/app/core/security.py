"""Password hashing, JWT encode/decode, and token payload contracts."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Literal

import bcrypt
import jwt

from app.core.config import get_settings
from app.core.exceptions import DomainError

settings = get_settings()

TokenType = Literal["access", "refresh"]


@dataclass(frozen=True)
class TokenPayload:
    sub: str  # user_id
    tenant_id: str
    role: str
    type: TokenType
    jti: str = field(repr=False)
    exp: datetime
    sid: uuid.UUID | None
    ver: int | None


def validate_new_password(plain: str) -> str:
    if len(plain) < 12:
        raise ValueError("Password must contain at least 12 characters")
    try:
        encoded = plain.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError("Password must be valid UTF-8") from None
    if len(encoded) > 72:
        raise ValueError("Password must not exceed 72 UTF-8 bytes")
    return plain


def hash_password(plain: str) -> str:
    try:
        validate_new_password(plain)
    except ValueError as error:
        raise DomainError(str(error)) from None
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


def _encode(payload: dict) -> str:
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(
    user_id: str, tenant_id: str, role: str, *, session_id: uuid.UUID, session_version: int
) -> tuple[str, str]:
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
            "sid": str(session_id),
            "ver": session_version,
        }
    )
    return token, jti


def create_refresh_token(
    user_id: str, tenant_id: str, role: str, *, session_id: uuid.UUID, session_version: int
) -> tuple[str, str]:
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
            "sid": str(session_id),
            "ver": session_version,
        }
    )
    return token, jti


def decode_token(token: str, *, verify_exp: bool = True) -> dict:
    try:
        return jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            options={
                "verify_exp": verify_exp,
                "require": ["sub", "tenant_id", "role", "type", "jti", "exp"],
            },
        )
    except (ValueError, TypeError, OverflowError):
        raise jwt.InvalidTokenError("Malformed token") from None


def decode_session_token(token: str, *, verify_exp: bool = True) -> TokenPayload:
    payload = decode_token(token, verify_exp=verify_exp)
    try:
        user_id = str(uuid.UUID(payload["sub"]))
        tenant_id = str(uuid.UUID(payload["tenant_id"]))
        token_type = payload["type"]
        if token_type not in {"access", "refresh"}:
            raise ValueError
        if not isinstance(payload["role"], str) or not payload["role"]:
            raise ValueError
        if not isinstance(payload["jti"], str) or not payload["jti"]:
            raise ValueError
        sid = uuid.UUID(payload["sid"]) if "sid" in payload else None
        version = payload.get("ver")
        if (sid is None) != (version is None):
            raise ValueError
        if version is not None and (type(version) is not int or version < 0):
            raise ValueError
        if isinstance(payload["exp"], bool) or not isinstance(payload["exp"], (int, float)):
            raise ValueError
        expires_at = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError, OSError):
        raise jwt.InvalidTokenError("Malformed session token") from None
    return TokenPayload(
        sub=user_id, tenant_id=tenant_id, role=payload["role"], type=token_type,
        jti=payload["jti"], exp=expires_at, sid=sid, ver=version,
    )
