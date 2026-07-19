"""FastAPI dependencies: current user, tenant, role guards, audit context."""
from __future__ import annotations

import uuid
from typing import Callable

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.enums import Role
from app.core.exceptions import Forbidden, Unauthorized
from app.core.security import decode_token
from app.infrastructure.db.models.user import User


async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    """Extract JWT from cookie or Authorization header, validate, return User row."""
    token = request.cookies.get("access_token")
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth[7:]
    if not token:
        raise Unauthorized()
    try:
        payload = decode_token(token)
    except Exception:
        raise Unauthorized("Invalid or expired token")
    if payload.get("type") != "access":
        raise Unauthorized("Invalid token type")
    try:
        user_id = uuid.UUID(payload["sub"])
    except Exception:
        raise Unauthorized("Malformed token")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise Unauthorized("User not found or inactive")
    return user


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
