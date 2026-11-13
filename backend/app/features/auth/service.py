"""Transactional authentication, single-use refresh rotation, and password reset."""
from __future__ import annotations

import hashlib
import math
import secrets
import uuid
from asyncio import to_thread
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import AsyncIterator, Awaitable, Callable

import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.enums import Role
from app.core.exceptions import Conflict, DomainError, Forbidden, NotFound, Unauthorized
from app.core.security import (
    create_access_token, create_refresh_token, decode_session_token, hash_password, verify_password,
)
from app.features.auth import repositories
from app.features.auth.schemas import ChangePasswordRequest, LoginRequest, RegisterCustomerRequest
from app.infrastructure.db.models.customer import Customer
from app.infrastructure.db.models.user import LoginAttempt, PasswordResetToken, RefreshToken, User
from app.shared.audit import audit

settings = get_settings()


@asynccontextmanager
async def _auth_transaction(db: AsyncSession) -> AsyncIterator[None]:
    # Lockout counters and compromise revocation must survive the eventual HTTP 401.
    failure = None
    async with db.begin():
        try:
            yield
        except Unauthorized as error:
            failure = error
    if failure is not None:
        raise failure


async def _issue_tokens(
    db: AsyncSession, user: User, *, session_id: uuid.UUID, device_info: str | None, ip: str | None,
) -> tuple[str, str, str]:
    claims = {"session_id": session_id, "session_version": user.session_version}
    access, _ = create_access_token(str(user.id), str(user.tenant_id), user.role, **claims)
    refresh, jti = create_refresh_token(str(user.id), str(user.tenant_id), user.role, **claims)
    db.add(RefreshToken(
        user_id=user.id, session_id=session_id, jti=jti,
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_days),
        device_info=device_info[:250] if device_info else None,
        ip_address=ip[:64] if ip else None,
    ))
    return access, refresh, jti


async def _revoke_all_sessions(db: AsyncSession, user: User, now: datetime) -> None:
    # All lifecycle writers acquire the User lock before token locks.
    user.session_version += 1
    await repositories.revoke_sessions(db, user_id=user.id, now=now)


async def authenticate(
    db: AsyncSession, req: LoginRequest, ip: str, device_info: str
) -> tuple[User, str, str, str]:
    """Return (user, access token, refresh token, refresh jti) after a durable login."""
    email = req.email.lower().strip()
    ip = ip[:64]
    async with _auth_transaction(db):
        candidate = await repositories.find_user(db, email, req.tenant_id)
        user = await repositories.lock_user(db, candidate.id, candidate.tenant_id) if candidate else None
        identifier = hashlib.sha256(f"{ip}:{req.tenant_id or '*'}:{email}".encode()).hexdigest()
        attempt = LoginAttempt(identifier=identifier, email=email, ip_address=ip, success=False)
        db.add(attempt)
        if not user or not user.is_active or user.email.lower().strip() != email:
            raise Unauthorized("Invalid credentials")
        now = datetime.now(timezone.utc)
        if user.locked_until and user.locked_until > now:
            raise Unauthorized("Account temporarily locked. Try again later.")
        if user.locked_until:
            user.failed_login_attempts = 0
            user.locked_until = None
        if not await to_thread(verify_password, req.password, user.password_hash):
            user.failed_login_attempts += 1
            if user.failed_login_attempts >= settings.max_login_attempts:
                user.locked_until = now + timedelta(minutes=settings.account_lock_minutes)
            raise Unauthorized("Invalid credentials")
        user.failed_login_attempts = 0
        user.locked_until = None
        user.last_login_at = now
        attempt.success = True
        access, refresh, jti = await _issue_tokens(
            db, user, session_id=uuid.uuid4(), device_info=device_info, ip=ip,
        )
        await audit(
            db, tenant_id=user.tenant_id, actor_id=user.id, actor_email=user.email,
            action="auth.login", ip_address=ip,
        )
    return user, access, refresh, jti


async def register_customer(
    db: AsyncSession, req: RegisterCustomerRequest, ip: str, *, actor: User,
) -> User:
    email = req.email.lower().strip()
    password_hash = await to_thread(hash_password, req.password)
    current = (await db.execute(select(User).where(
        User.id == actor.id, User.tenant_id == actor.tenant_id, User.is_active.is_(True),
        User.role == actor.role, User.session_version == actor.session_version,
        User.role.in_([Role.SUPER_ADMIN.value, Role.ACCOUNTANT.value]),
    ).with_for_update(key_share=True).execution_options(populate_existing=True))).scalar_one_or_none()
    if current is None:
        raise Forbidden("Only the owner or accountant may provision customer accounts")
    if req.tenant_id is not None and req.tenant_id != current.tenant_id:
        raise Forbidden("Customer intake is restricted to your organization")
    tenants = await repositories.registration_tenants(db, current.tenant_id)
    if not tenants or not tenants[0].is_setup_complete:
        raise DomainError("Tenant unavailable or setup not complete. Contact the administrator.")
    tenant_id = tenants[0].id
    if await repositories.email_exists(db, email, tenant_id):
        raise Conflict("Email already registered")
    customer = Customer(
        tenant_id=tenant_id, code=f"CUS-{secrets.token_hex(6).upper()}", name=req.full_name,
        business_name=req.business_name, phone=req.phone, email=email, customer_type="cash",
    )
    db.add(customer)
    await db.flush()
    user = User(
        tenant_id=tenant_id, email=email, password_hash=password_hash, full_name=req.full_name,
        phone=req.phone, role=Role.CUSTOMER.value, customer_id=customer.id, is_email_verified=False,
    )
    db.add(user)
    await db.flush()
    await audit(
        db, tenant_id=tenant_id, actor_id=current.id, actor_email=current.email,
        action="auth.register_customer", resource_type="user", resource_id=str(user.id),
        ip_address=ip[:64],
    )
    return user


async def refresh_access(db: AsyncSession, refresh_token_str: str) -> tuple[str, str, User]:
    try:
        # Expiry forbids renewal, but a signed, previously consumed JTI still signals reuse.
        payload = decode_session_token(refresh_token_str, verify_exp=False)
    except jwt.InvalidTokenError:
        raise Unauthorized("Invalid or expired refresh token") from None
    if payload.type != "refresh":
        raise Unauthorized("Invalid token type")
    async with _auth_transaction(db):
        user = await repositories.lock_user(db, uuid.UUID(payload.sub), uuid.UUID(payload.tenant_id))
        if not user:
            raise Unauthorized("Invalid refresh token")
        stored = await repositories.lock_refresh_token(db, user.id, payload.jti)
        if not stored or (payload.sid is not None and payload.sid != stored.session_id):
            raise Unauthorized("Invalid refresh token")
        now = datetime.now(timezone.utc)
        # A retired epoch cannot revoke sessions established after reset/reauthentication.
        if (payload.ver or 0) != user.session_version:
            if stored.revoked_at is None:
                stored.revoked_at = now
            raise Unauthorized("Session renewal required")
        if stored.revoked_at is not None:
            await _revoke_all_sessions(db, user, now)
            await audit(
                db, tenant_id=user.tenant_id, actor_id=user.id, actor_email=user.email,
                action="auth.refresh_reuse", resource_type="user", resource_id=str(user.id),
            )
            raise Unauthorized("Refresh token revoked")
        if payload.exp <= now or stored.expires_at <= now:
            stored.revoked_at = now
            await audit(
                db, tenant_id=user.tenant_id, actor_id=user.id, actor_email=user.email,
                action="auth.session_expired",
            )
            raise Unauthorized("Refresh token expired")
        # Only already-issued legacy refresh tokens may omit sid/ver, at initial version zero.
        if not user.is_active or payload.role != user.role:
            await _revoke_all_sessions(db, user, now)
            await audit(
                db, tenant_id=user.tenant_id, actor_id=user.id, actor_email=user.email,
                action="auth.session_invalidated", resource_type="user", resource_id=str(user.id),
            )
            raise Unauthorized("Session renewal required")
        stored.revoked_at = now
        await db.flush()
        access, refresh, _ = await _issue_tokens(
            db, user, session_id=stored.session_id, device_info=stored.device_info, ip=stored.ip_address,
        )
        await audit(
            db, tenant_id=user.tenant_id, actor_id=user.id, actor_email=user.email,
            action="auth.refresh", resource_type="user", resource_id=str(user.id),
        )
    return access, refresh, user


async def logout(
    db: AsyncSession, *, refresh_token_str: str | None, access_token_str: str | None, ip: str,
) -> None:
    candidates = []
    for token, expected_type in ((refresh_token_str, "refresh"), (access_token_str, "access")):
        if not token:
            continue
        try:
            payload = decode_session_token(token, verify_exp=False)
        except jwt.InvalidTokenError:
            continue
        if payload.type == expected_type and (expected_type == "refresh" or payload.sid is not None):
            candidates.append(payload)
    async with db.begin():
        seen = set()
        for payload in sorted(candidates, key=lambda candidate: candidate.sub):
            user = await repositories.lock_user(db, uuid.UUID(payload.sub), uuid.UUID(payload.tenant_id))
            if not user:
                continue
            if payload.type == "refresh":
                stored = await repositories.lock_refresh_token(db, user.id, payload.jti)
            elif payload.sid is not None:
                stored = await repositories.lock_session(db, user.id, payload.sid)
            else:
                continue
            if not stored or (payload.sid is not None and payload.sid != stored.session_id):
                continue
            identity = (user.id, stored.session_id)
            if identity in seen:
                continue
            seen.add(identity)
            await repositories.revoke_sessions(
                db, user_id=user.id, session_id=stored.session_id, now=datetime.now(timezone.utc),
            )
            await audit(
                db, tenant_id=user.tenant_id, actor_id=user.id, actor_email=user.email,
                action="auth.logout", ip_address=ip[:64],
            )


def _reset_digest(token: str) -> str:
    try:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()
    except UnicodeEncodeError:
        raise NotFound("Invalid reset token") from None


async def create_password_reset(
    db: AsyncSession, email: str, tenant_id: uuid.UUID | None = None,
) -> str | None:
    """Return an opaque link secret only to a future sender; never log or store it raw."""
    email = email.lower().strip()
    async with db.begin():
        candidate = await repositories.find_user(db, email, tenant_id)
        if not candidate:
            return None
        user = await repositories.lock_user(db, candidate.id, candidate.tenant_id)
        if not user or not user.is_active or user.email.lower().strip() != email:
            return None
        now = datetime.now(timezone.utc)
        await repositories.invalidate_password_resets(db, user.id, now)
        token = secrets.token_urlsafe(32)
        db.add(PasswordResetToken(
            user_id=user.id, token=f"sha256:{_reset_digest(token)}",
            expires_at=now + timedelta(hours=settings.password_reset_hours),
        ))
        await audit(
            db, tenant_id=user.tenant_id, actor_id=user.id, actor_email=user.email,
            action="auth.password_reset_requested",
        )
    return token


async def reset_password(db: AsyncSession, token: str, new_password: str) -> None:
    async with db.begin():
        candidate = await repositories.find_password_reset(db, _reset_digest(token))
        if not candidate:
            raise NotFound("Invalid reset token")
        # Resolve the owner without locking the token first, preserving User -> token lock order.
        owner = await repositories.find_user_by_id(db, candidate.user_id)
        if not owner:
            raise NotFound("Invalid reset token")
        user = await repositories.lock_user(db, owner.id, owner.tenant_id)
        row = await repositories.lock_password_reset(db, candidate.id, candidate.user_id)
        if not user or not user.is_active or not row:
            raise NotFound("Invalid reset token")
        if row.used_at is not None:
            raise DomainError("Token already used")
        now = datetime.now(timezone.utc)
        if row.expires_at <= now:
            raise DomainError("Token expired")
        user.password_hash = await to_thread(hash_password, new_password)
        user.failed_login_attempts = 0
        user.locked_until = None
        await _revoke_all_sessions(db, user, datetime.now(timezone.utc))
        await repositories.invalidate_password_resets(db, user.id, datetime.now(timezone.utc))
        await audit(
            db, tenant_id=user.tenant_id, actor_id=user.id, actor_email=user.email,
            action="auth.password_reset",
        )


def _password_change_lockout(locked_until: datetime, now: datetime) -> DomainError:
    error = DomainError("Too many password attempts. Try again later.", code=429)
    error.headers = {"Retry-After": str(min(900, max(1, math.ceil(
        (locked_until - now).total_seconds(),
    ))))}
    return error


async def change_password(
    db: AsyncSession, *, actor: User, payload: ChangePasswordRequest,
    recheck: Callable[[], Awaitable[User]], ip: str,
) -> DomainError | None:
    """Stage an own-password change or a durable rejection in the caller's locked transaction."""
    if not actor.is_active or actor.role not in {role.value for role in Role}:
        raise Forbidden("Password change is not permitted")
    now = datetime.now(timezone.utc)
    if actor.locked_until and actor.locked_until > now:
        return _password_change_lockout(actor.locked_until, now)
    valid = await to_thread(verify_password, payload.current_password, actor.password_hash)
    await recheck()
    if not valid:
        now = datetime.now(timezone.utc)
        limit = min(settings.max_login_attempts, 5)
        previous = 0 if actor.locked_until else actor.failed_login_attempts
        actor.failed_login_attempts = min(max(0, previous) + 1, limit)
        if actor.failed_login_attempts >= limit:
            actor.locked_until = now + timedelta(minutes=min(settings.account_lock_minutes, 15))
        else:
            actor.locked_until = None
        db.add(LoginAttempt(
            identifier=hashlib.sha256(f"password-change:{actor.tenant_id}:{actor.id}".encode()).hexdigest(),
            email=actor.email, ip_address=ip[:64], success=False,
        ))
        await audit(
            db, tenant_id=actor.tenant_id, actor_id=actor.id, actor_email=None,
            action="auth.password_change_failed", resource_type="user", resource_id=str(actor.id),
            ip_address=ip[:64],
        )
        await db.flush()
        await recheck()
        return DomainError("Current password is incorrect")
    reused = await to_thread(verify_password, payload.new_password, actor.password_hash)
    await recheck()
    if reused:
        return DomainError("New password must differ from the current password")
    # User-first writers cannot add/rotate links while these locks are held. Take all
    # remaining row waits before the last eligibility check and self-revocation.
    await repositories.lock_active_sessions(db, actor.id)
    await recheck()
    await repositories.lock_outstanding_password_resets(db, actor.id)
    await recheck()
    replacement = await to_thread(hash_password, payload.new_password)
    await recheck()
    actor.password_hash = replacement
    actor.failed_login_attempts = 0
    actor.locked_until = None
    await audit(
        db, tenant_id=actor.tenant_id, actor_id=actor.id, actor_email=None,
        action="auth.password_change", resource_type="user", resource_id=str(actor.id),
        ip_address=ip[:64],
    )
    await db.flush()
    await recheck()
    now = datetime.now(timezone.utc)
    await _revoke_all_sessions(db, actor, now)
    await repositories.invalidate_password_resets(db, actor.id, now)
    await db.flush()
    return None
