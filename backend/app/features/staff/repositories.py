"""Tenant-scoped staff reads and FK-compatible canonical user locks."""
from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.staff.schemas import STAFF_ROLES, StaffListQuery
from app.infrastructure.db.models.user import User


async def lock_users(
    db: AsyncSession, *, tenant_id: uuid.UUID, user_ids: tuple[uuid.UUID, ...],
) -> dict[uuid.UUID, User]:
    # Lock every existing actor/target before any session lock. KEY SHARE FK checks stay compatible.
    rows = (await db.execute(
        select(User).where(User.tenant_id == tenant_id, User.id.in_(user_ids))
        .order_by(User.id).with_for_update(key_share=True)
        .execution_options(populate_existing=True)
    )).scalars().all()
    return {row.id: row for row in rows}


async def list_staff(
    db: AsyncSession, *, tenant_id: uuid.UUID, query: StaffListQuery,
) -> tuple[list[User], int]:
    scope = (
        User.tenant_id == tenant_id, User.role.in_(STAFF_ROLES), User.customer_id.is_(None),
    )
    total = (await db.execute(select(func.count()).select_from(User).where(*scope))).scalar_one()
    rows = (await db.execute(
        select(User).where(*scope).order_by(User.created_at.desc(), User.id)
        .offset((query.page - 1) * query.page_size).limit(query.page_size)
    )).scalars().all()
    return list(rows), total


def is_email_conflict(error: IntegrityError) -> bool:
    """Recognize only the existing tenant/email uniqueness constraint, never unrelated failures."""
    original = error.orig
    sqlstate = getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)
    cause = getattr(original, "__cause__", None)
    diagnostic = getattr(original, "diag", None)
    constraint = (
        getattr(original, "constraint_name", None)
        or getattr(cause, "constraint_name", None)
        or getattr(diagnostic, "constraint_name", None)
    )
    return sqlstate == "23505" and constraint == "ix_users_tenant_email"
