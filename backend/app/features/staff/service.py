"""Stage staff/account/session/audit effects in the caller's existing transaction."""
from __future__ import annotations

import uuid
from asyncio import to_thread
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import Role
from app.core.exceptions import Conflict, DomainError, Forbidden, NotFound
from app.core.security import hash_password
from app.features.auth import repositories as auth_repository
from app.features.staff import repositories
from app.features.staff.schemas import (
    STAFF_ROLES, StaffCreate, StaffListQuery, StaffOut, StaffPatch,
)
from app.infrastructure.db.models.user import User
from app.shared.audit import audit
from app.shared.schemas import Paginated


def require_owner(actor: User) -> None:
    if not actor.is_active or actor.role != Role.SUPER_ADMIN.value:
        raise Forbidden("Only the owner may manage staff")


def require_target(actor: User, target: User | None) -> User:
    require_owner(actor)
    if (
        target is None or target.id == actor.id or target.tenant_id != actor.tenant_id
        or target.role not in STAFF_ROLES or target.customer_id is not None
    ):
        raise NotFound("Staff member not found")
    return target


async def list_staff(
    db: AsyncSession, *, actor: User, query: StaffListQuery,
) -> Paginated[StaffOut]:
    require_owner(actor)
    rows, total = await repositories.list_staff(db, tenant_id=actor.tenant_id, query=query)
    return Paginated[StaffOut](
        items=[StaffOut.model_validate(row) for row in rows], total=total,
        page=query.page, page_size=query.page_size,
    )


async def create_staff(db: AsyncSession, *, actor: User, payload: StaffCreate) -> StaffOut:
    require_owner(actor)
    email = str(payload.email)
    if await auth_repository.email_exists(db, email, actor.tenant_id):
        raise Conflict("Email already registered")
    target = User(
        id=uuid.uuid4(), tenant_id=actor.tenant_id, email=email, full_name=payload.full_name,
        phone=payload.phone, role=payload.role.value,
        password_hash=await to_thread(hash_password, payload.password),
        customer_id=None, is_active=True, is_email_verified=False, session_version=0,
    )
    db.add(target)
    try:
        await db.flush()
    except IntegrityError as error:
        if repositories.is_email_conflict(error):
            raise Conflict("Email already registered") from None
        raise
    await _audit_staff(
        db, actor=actor, target=target, action="staff.create",
        changed_fields=["email", "full_name", "phone", "role"],
    )
    return StaffOut.model_validate(target)


async def patch_staff(
    db: AsyncSession, *, actor: User, target: User | None, payload: StaffPatch,
) -> StaffOut:
    target = require_target(actor, target)
    values = payload.model_dump(exclude_unset=True, mode="json")
    if not values:
        raise DomainError("No staff changes supplied")
    changed_fields = sorted(
        name for name, value in values.items() if getattr(target, name) != value
    )
    for name in changed_fields:
        setattr(target, name, values[name])
    if {"role", "is_active"}.intersection(changed_fields):
        await _invalidate_access(db, target)
    await _audit_staff(
        db, actor=actor, target=target, action="staff.update", changed_fields=changed_fields,
    )
    await db.flush()
    return StaffOut.model_validate(target)


async def revoke_sessions(db: AsyncSession, *, actor: User, target: User | None) -> None:
    target = require_target(actor, target)
    await _invalidate_access(db, target)
    await _audit_staff(
        db, actor=actor, target=target, action="staff.revoke_sessions", changed_fields=[],
    )


async def _invalidate_access(db: AsyncSession, target: User) -> None:
    # Advancing the epoch on reactivation too prevents old access/refresh resurrection.
    target.session_version += 1
    now = datetime.now(timezone.utc)
    await auth_repository.revoke_sessions(db, user_id=target.id, now=now)
    await auth_repository.invalidate_password_resets(db, target.id, now)


async def _audit_staff(
    db: AsyncSession, *, actor: User, target: User, action: str, changed_fields: list[str],
) -> None:
    await audit(
        db, tenant_id=actor.tenant_id, actor_id=actor.id, actor_email=None,
        action=action, resource_type="user", resource_id=str(target.id),
        meta={"changed_fields": changed_fields},
    )
