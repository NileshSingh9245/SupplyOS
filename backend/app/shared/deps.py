"""FastAPI dependencies: current user, tenant, role guards, audit context."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Callable

import jwt
from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.enums import Role
from app.core.exceptions import Forbidden, Unauthorized
from app.core.security import decode_session_token
from app.infrastructure.db.models.user import RefreshToken, User


def access_token_from_request(request: Request) -> str | None:
    token = request.cookies.get("access_token")
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth[7:]
    return token


async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    """Validate the signed identity and its active persisted session."""
    token = access_token_from_request(request)
    if not token:
        raise Unauthorized()
    try:
        payload = decode_session_token(token)
    except jwt.InvalidTokenError:
        raise Unauthorized("Invalid or expired token") from None
    if payload.type != "access":
        raise Unauthorized("Invalid token type")
    if payload.sid is None or payload.ver is None:
        raise Unauthorized("Session renewal required")

    result = await db.execute(
        select(User).join(RefreshToken, RefreshToken.user_id == User.id).where(
            User.id == uuid.UUID(payload.sub),
            User.tenant_id == uuid.UUID(payload.tenant_id),
            User.role == payload.role,
            User.session_version == payload.ver,
            User.is_active.is_(True),
            RefreshToken.session_id == payload.sid,
            RefreshToken.revoked_at.is_(None),
            RefreshToken.expires_at > datetime.now(timezone.utc),
        )
    )
    user = result.scalar_one_or_none()
    if not user:
        raise Unauthorized("Session revoked or user inactive")
    return user


async def lock_current_user(request: Request, db: AsyncSession) -> User:
    """Serialize a sensitive commit with auth revocation: User then active session."""
    user = await get_current_user(request, db)
    token = access_token_from_request(request)
    if token is None:
        raise Unauthorized("Not authenticated")
    try:
        payload = decode_session_token(token)
    except jwt.InvalidTokenError:
        raise Unauthorized("Invalid or expired token") from None
    # Non-key auth updates serialize; partner FK checks must not deadlock assignment.
    locked = (await db.execute(select(User).where(
        User.id == user.id, User.tenant_id == user.tenant_id,
    ).with_for_update(key_share=True).execution_options(populate_existing=True))).scalar_one_or_none()
    if locked is None:
        raise Unauthorized("Session revoked or user inactive")
    session = (await db.execute(select(RefreshToken.id).where(
        RefreshToken.user_id == locked.id, RefreshToken.session_id == payload.sid,
        RefreshToken.revoked_at.is_(None),
        RefreshToken.expires_at > datetime.now(timezone.utc),
    ).with_for_update())).scalar_one_or_none()
    if session is None:
        raise Unauthorized("Session revoked or user inactive")
    # Lock waits can cross token expiry or a committed role/session-version change.
    return await get_current_user(request, db)


def require_roles(*allowed: Role) -> Callable:
    allowed_values = {r.value for r in allowed}

    async def _guard(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed_values:
            raise Forbidden(f"Role '{user.role}' not permitted")
        return user

    return _guard


require_admin = require_roles(Role.SUPER_ADMIN)
require_admin_or_manager = require_roles(Role.SUPER_ADMIN, Role.WAREHOUSE_MANAGER)
require_staff = require_roles(
    Role.SUPER_ADMIN, Role.WAREHOUSE_MANAGER, Role.ACCOUNTANT
)
require_customer = require_roles(Role.CUSTOMER)
require_delivery = require_roles(Role.DELIVERY_PARTNER)


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
