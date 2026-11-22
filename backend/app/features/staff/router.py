"""Owner-only staff routes with a private validation and final authorization boundary."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import DomainError
from app.features.staff import repositories, service
from app.features.staff.schemas import (
    RevokeStaffSessionsRequest, StaffCreate, StaffListQuery, StaffOut, StaffPatch,
)
from app.infrastructure.db.models.user import User
from app.shared.deps import get_current_user, lock_current_user
from app.shared.private_route import PrivateInputRoute
from app.shared.schemas import MessageResponse, Paginated

router = APIRouter(prefix="/staff", tags=["staff"], route_class=PrivateInputRoute)


async def _owner(user: User = Depends(get_current_user)) -> User:
    service.require_owner(user)
    return user


async def _lock_owner(
    request: Request, db: AsyncSession, actor: User, target_id: uuid.UUID | None = None,
) -> tuple[User, User | None]:
    if request.method != "GET" and request.query_params:
        raise DomainError("Staff query parameters are not supported", code=422)
    ids = (actor.id,) if target_id is None else (actor.id, target_id)
    users = await repositories.lock_users(db, tenant_id=actor.tenant_id, user_ids=ids)
    current = await lock_current_user(request, db)
    service.require_owner(current)
    return current, users.get(target_id) if target_id is not None else None


async def _commit(request: Request, db: AsyncSession) -> None:
    # Flush every staged effect before the last fresh auth read, retaining all locks until COMMIT.
    await db.flush()
    service.require_owner(await get_current_user(request, db))
    await db.commit()


@router.get(
    "", response_model=Paginated[StaffOut], summary="List tenant staff",
    description="Owner-only staff pagination; owner and customer accounts are excluded.",
)
async def list_staff(
    request: Request, query: Annotated[StaffListQuery, Query()],
    db: AsyncSession = Depends(get_db), user: User = Depends(_owner),
) -> Paginated[StaffOut]:
    try:
        actor, _ = await _lock_owner(request, db, user)
        response = await service.list_staff(db, actor=actor, query=query)
        await _commit(request, db)
        return response
    except BaseException:
        await db.rollback()
        raise


@router.post(
    "", response_model=StaffOut, status_code=201, summary="Create an individual staff account",
    description="Requires the account holder's selected password. No invitation, email "
                "verification or login is performed.",
)
async def create_staff(
    payload: StaffCreate, request: Request, db: AsyncSession = Depends(get_db),
    user: User = Depends(_owner),
) -> StaffOut:
    try:
        actor, _ = await _lock_owner(request, db, user)
        response = await service.create_staff(db, actor=actor, payload=payload)
        await _commit(request, db)
        return response
    except BaseException:
        await db.rollback()
        raise


@router.patch(
    "/{staff_id}", response_model=StaffOut, summary="Update a staff account",
    description="Only name, phone, staff role and activity can change. Role/activity "
                "changes revoke all sessions and reset links atomically.",
)
async def patch_staff(
    staff_id: uuid.UUID, payload: StaffPatch, request: Request,
    db: AsyncSession = Depends(get_db), user: User = Depends(_owner),
) -> StaffOut:
    try:
        actor, target = await _lock_owner(request, db, user, staff_id)
        response = await service.patch_staff(db, actor=actor, target=target, payload=payload)
        await _commit(request, db)
        return response
    except BaseException:
        await db.rollback()
        raise


@router.post(
    "/{staff_id}/revoke-sessions", response_model=MessageResponse,
    summary="Revoke every staff session",
    description="Revokes all refresh families and reset links, and advances the session "
                "epoch. The account password and activity are unchanged.",
)
async def revoke_sessions(
    staff_id: uuid.UUID, request: Request, payload: RevokeStaffSessionsRequest | None = None,
    db: AsyncSession = Depends(get_db), user: User = Depends(_owner),
) -> MessageResponse:
    try:
        actor, target = await _lock_owner(request, db, user, staff_id)
        await service.revoke_sessions(db, actor=actor, target=target)
        await _commit(request, db)
        return MessageResponse(message="Staff sessions revoked")
    except BaseException:
        await db.rollback()
        raise
