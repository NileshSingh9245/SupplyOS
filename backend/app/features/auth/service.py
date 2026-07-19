"""Auth service: login, register-customer, refresh, logout, forgot/reset password."""
from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.enums import Role
from app.core.exceptions import Conflict, DomainError, NotFound, Unauthorized
from app.core.security import (
    create_access_token, create_refresh_token, hash_password, verify_password,
)
from app.features.auth.schemas import LoginRequest, RegisterCustomerRequest
from app.infrastructure.db.models.customer import Customer
from app.infrastructure.db.models.tenant import Tenant
from app.infrastructure.db.models.user import (
    LoginAttempt, PasswordResetToken, RefreshToken, User,
)
from app.shared.audit import audit

settings = get_settings()


async def _identifier(ip: str, email: str) -> str:
    return f"{ip}:{email.lower()}"


async def _is_locked(db: AsyncSession, user: User) -> bool:
    if user.locked_until and user.locked_until > datetime.now(timezone.utc):
        return True
    return False


async def authenticate(
    db: AsyncSession, req: LoginRequest, ip: str, device_info: str
) -> tuple[User, str, str, str]:
    """Returns (user, access_token, refresh_token, refresh_jti)."""
    email = req.email.lower().strip()
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    # Record attempt regardless (for analytics + rate limiting)
    attempt = LoginAttempt(
        identifier=await _identifier(ip, email),
        email=email,
        ip_address=ip,
        success=False,
    )
    db.add(attempt)

    if not user or not user.is_active:
        await db.commit()
        raise Unauthorized("Invalid credentials")

    if await _is_locked(db, user):
        await db.commit()
        raise Unauthorized("Account temporarily locked. Try again later.")

    if not verify_password(req.password, user.password_hash):
        user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
        if user.failed_login_attempts >= settings.max_login_attempts:
            user.locked_until = datetime.now(timezone.utc) + timedelta(
                minutes=settings.account_lock_minutes
            )
        await db.commit()
        raise Unauthorized("Invalid credentials")

    # Success
    user.failed_login_attempts = 0
    user.locked_until = None
    user.last_login_at = datetime.now(timezone.utc)
    attempt.success = True

    access, _ = create_access_token(str(user.id), str(user.tenant_id), user.role)
    refresh, refresh_jti = create_refresh_token(str(user.id), str(user.tenant_id), user.role)

    rt = RefreshToken(
        user_id=user.id,
        jti=refresh_jti,
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_days),
        device_info=device_info[:250],
        ip_address=ip,
    )
    db.add(rt)
    await audit(
        db,
        tenant_id=user.tenant_id,
        actor_id=user.id,
        actor_email=user.email,
        action="auth.login",
        ip_address=ip,
    )
    await db.commit()
    await db.refresh(user)
    return user, access, refresh, refresh_jti


async def register_customer(
    db: AsyncSession, req: RegisterCustomerRequest, tenant_id: uuid.UUID, ip: str
) -> User:
    email = req.email.lower().strip()
    existing = await db.execute(
        select(User).where(User.tenant_id == tenant_id, User.email == email)
    )
    if existing.scalar_one_or_none():
        raise Conflict("Email already registered")

    # Create linked customer record
    # Use short unique code
    code = f"CUS-{secrets.token_hex(3).upper()}"
    customer = Customer(
        tenant_id=tenant_id,
        code=code,
        name=req.full_name,
        business_name=req.business_name,
        phone=req.phone,
        email=email,
        customer_type="cash",
    )
    db.add(customer)
    await db.flush()

    user = User(
        tenant_id=tenant_id,
        email=email,
        password_hash=hash_password(req.password),
        full_name=req.full_name,
        phone=req.phone,
        role=Role.CUSTOMER.value,
        customer_id=customer.id,
    )
    db.add(user)
    await audit(
        db,
        tenant_id=tenant_id,
        actor_id=None,
        actor_email=email,
        action="auth.register_customer",
        resource_type="user",
        ip_address=ip,
    )
    await db.commit()
    await db.refresh(user)
    return user


async def refresh_access(db: AsyncSession, refresh_token_str: str) -> tuple[str, User]:
    from app.core.security import decode_token

    try:
        payload = decode_token(refresh_token_str)
    except Exception:
        raise Unauthorized("Invalid refresh token")
    if payload.get("type") != "refresh":
        raise Unauthorized("Invalid token type")

    jti = payload.get("jti")
    result = await db.execute(select(RefreshToken).where(RefreshToken.jti == jti))
    stored = result.scalar_one_or_none()
    if not stored or stored.revoked_at is not None:
        raise Unauthorized("Refresh token revoked")
    if stored.expires_at < datetime.now(timezone.utc):
        raise Unauthorized("Refresh token expired")

    user = (await db.execute(select(User).where(User.id == stored.user_id))).scalar_one_or_none()
    if not user or not user.is_active:
        raise Unauthorized("User not found")

    access, _ = create_access_token(str(user.id), str(user.tenant_id), user.role)
    return access, user


async def logout(db: AsyncSession, user: User, refresh_jti: str | None) -> None:
    if refresh_jti:
        await db.execute(
            delete(RefreshToken).where(
                RefreshToken.user_id == user.id, RefreshToken.jti == refresh_jti
            )
        )
    await audit(
        db, tenant_id=user.tenant_id, actor_id=user.id, actor_email=user.email,
        action="auth.logout",
    )
    await db.commit()


async def create_password_reset(db: AsyncSession, email: str) -> str | None:
    """Returns token or None if email doesn't exist (do not leak)."""
    result = await db.execute(select(User).where(User.email == email.lower().strip()))
    user = result.scalar_one_or_none()
    if not user:
        return None
    token = secrets.token_urlsafe(32)
    entry = PasswordResetToken(
        user_id=user.id,
        token=token,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=settings.password_reset_hours),
    )
    db.add(entry)
    await db.commit()
    return token


async def reset_password(db: AsyncSession, token: str, new_password: str) -> None:
    result = await db.execute(
        select(PasswordResetToken).where(PasswordResetToken.token == token)
    )
    row = result.scalar_one_or_none()
    if not row:
        raise NotFound("Invalid reset token")
    if row.used_at is not None:
        raise DomainError("Token already used")
    if row.expires_at < datetime.now(timezone.utc):
        raise DomainError("Token expired")
    user = (await db.execute(select(User).where(User.id == row.user_id))).scalar_one_or_none()
    if not user:
        raise NotFound("User not found")
    user.password_hash = hash_password(new_password)
    row.used_at = datetime.now(timezone.utc)
    user.failed_login_attempts = 0
    user.locked_until = None
    await audit(
        db, tenant_id=user.tenant_id, actor_id=user.id, actor_email=user.email,
        action="auth.password_reset",
    )
    await db.commit()
