"""Tenant-aware identity lookup and PostgreSQL auth row locking."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models.tenant import Tenant
from app.infrastructure.db.models.user import PasswordResetToken, RefreshToken, User


async def find_user(
    db: AsyncSession, email: str, tenant_id: uuid.UUID | None = None
) -> User | None:
    query = select(User).where(func.lower(User.email) == email).limit(2)
    if tenant_id is not None:
        query = query.where(User.tenant_id == tenant_id)
    users = list((await db.execute(query)).scalars())
    return users[0] if len(users) == 1 else None


async def find_user_by_id(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def email_exists(db: AsyncSession, email: str, tenant_id: uuid.UUID) -> bool:
    result = await db.execute(
        select(User.id).where(User.tenant_id == tenant_id, func.lower(User.email) == email).limit(1)
    )
    return result.scalar_one_or_none() is not None


async def lock_user(
    db: AsyncSession, user_id: uuid.UUID, tenant_id: uuid.UUID
) -> User | None:
    result = await db.execute(
        select(User).where(User.id == user_id, User.tenant_id == tenant_id)
        .with_for_update().execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


async def registration_tenants(
    db: AsyncSession, tenant_id: uuid.UUID | None
) -> list[Tenant]:
    query = select(Tenant).order_by(Tenant.id).limit(2).with_for_update()
    if tenant_id is not None:
        query = query.where(Tenant.id == tenant_id)
    return list((await db.execute(query)).scalars())


async def lock_refresh_token(
    db: AsyncSession, user_id: uuid.UUID, jti: str
) -> RefreshToken | None:
    result = await db.execute(
        select(RefreshToken).where(RefreshToken.user_id == user_id, RefreshToken.jti == jti)
        .with_for_update().execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


async def lock_session(
    db: AsyncSession, user_id: uuid.UUID, session_id: uuid.UUID
) -> RefreshToken | None:
    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.user_id == user_id, RefreshToken.session_id == session_id,
        ).order_by(RefreshToken.created_at.desc(), RefreshToken.id).limit(1)
        .with_for_update().execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


async def revoke_sessions(
    db: AsyncSession, *, user_id: uuid.UUID, now: datetime,
    session_id: uuid.UUID | None = None,
) -> None:
    query = update(RefreshToken).where(
        RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None),
    )
    if session_id is not None:
        query = query.where(RefreshToken.session_id == session_id)
    await db.execute(query.values(revoked_at=now).execution_options(synchronize_session=False))


async def lock_active_sessions(db: AsyncSession, user_id: uuid.UUID) -> None:
    await db.execute(select(RefreshToken.id).where(
        RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None),
    ).order_by(RefreshToken.id).with_for_update())


async def lock_outstanding_password_resets(db: AsyncSession, user_id: uuid.UUID) -> None:
    await db.execute(select(PasswordResetToken.id).where(
        PasswordResetToken.user_id == user_id, PasswordResetToken.used_at.is_(None),
    ).order_by(PasswordResetToken.id).with_for_update())


async def find_password_reset(db: AsyncSession, digest: str) -> PasswordResetToken | None:
    result = await db.execute(
        select(PasswordResetToken).where(PasswordResetToken.token == f"sha256:{digest}")
    )
    row = result.scalar_one_or_none()
    if row is not None:
        return row
    # Existing issued links remain redeemable without placing their secret in SQL parameters.
    legacy_digest = func.encode(
        func.sha256(func.convert_to(PasswordResetToken.token, "UTF8")), "hex",
    )
    result = await db.execute(
        select(PasswordResetToken).where(
            ~PasswordResetToken.token.startswith("sha256:"), legacy_digest == digest,
        ).limit(2)
    )
    rows = list(result.scalars())
    return rows[0] if len(rows) == 1 else None


async def password_reset_recipient(
    db: AsyncSession, *, digest: str, email: str, tenant_id: uuid.UUID | None, now: datetime,
) -> str | None:
    query = select(User.email).join(
        PasswordResetToken, PasswordResetToken.user_id == User.id,
    ).where(
        PasswordResetToken.token == f"sha256:{digest}",
        PasswordResetToken.used_at.is_(None), PasswordResetToken.expires_at > now,
        User.is_active.is_(True), func.lower(User.email) == email,
    )
    if tenant_id is not None:
        query = query.where(User.tenant_id == tenant_id)
    # Select the current scalar, not the possibly cached pre-commit ORM identity.
    return (await db.execute(query)).scalar_one_or_none()


async def lock_password_reset(
    db: AsyncSession, token_id: uuid.UUID, user_id: uuid.UUID
) -> PasswordResetToken | None:
    result = await db.execute(
        select(PasswordResetToken).where(
            PasswordResetToken.id == token_id, PasswordResetToken.user_id == user_id,
        ).with_for_update().execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


async def invalidate_password_resets(
    db: AsyncSession, user_id: uuid.UUID, now: datetime
) -> None:
    await db.execute(
        update(PasswordResetToken).where(
            PasswordResetToken.user_id == user_id, PasswordResetToken.used_at.is_(None),
        ).values(used_at=now).execution_options(synchronize_session=False)
    )
