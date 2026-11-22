"""Delivery endpoints — assignment, OTP verification, proof capture, cash/UPI collect."""
from __future__ import annotations

import uuid
import secrets
from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.enums import OrderStatus, Role
from app.core.exceptions import Conflict, Forbidden, NotFound
from app.features.orders import service as order_service
from app.features.payments.schemas import CollectRequest
from app.features.proofs.service import lock_delivery_order
from app.infrastructure.db.models.order import Delivery, Order
from app.infrastructure.db.models.user import User
from app.shared.audit import audit
from app.shared import idempotency
from app.shared.deps import get_current_user, lock_current_user, require_admin_or_manager, require_roles
from app.shared.private_route import PrivateInputRoute
from app.shared.schemas import ORMModel

router = APIRouter(prefix="/deliveries", tags=["deliveries"], route_class=PrivateInputRoute)
require_delivery_reader = require_roles(
    Role.SUPER_ADMIN, Role.WAREHOUSE_MANAGER, Role.ACCOUNTANT, Role.DELIVERY_PARTNER, Role.CUSTOMER,
)
require_delivery_operator = require_roles(
    Role.SUPER_ADMIN, Role.WAREHOUSE_MANAGER, Role.DELIVERY_PARTNER,
)


class DeliveryOut(ORMModel):
    id: uuid.UUID
    order_id: uuid.UUID
    partner_id: uuid.UUID | None
    scheduled_date: date | None
    priority: int
    otp_verified: bool
    signature_url: str | None
    proof_photo_url: str | None
    cash_collected: Decimal
    upi_collected: Decimal
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime


class AssignRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    partner_id: uuid.UUID
    scheduled_date: date | None = None
    priority: int = Field(5, ge=1, le=10)


class VerifyOTPRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    otp_code: str = Field(
        min_length=4, max_length=10, pattern=r"^[0-9]{4,10}$", repr=False, exclude=True,
    )


async def _lock_delivery_operator(request: Request, db: AsyncSession) -> User:
    user = await lock_current_user(request, db)
    if user.role not in {
        Role.SUPER_ADMIN.value, Role.WAREHOUSE_MANAGER.value, Role.DELIVERY_PARTNER.value,
    }:
        raise Forbidden("Delivery operation is not permitted")
    return user


async def _locked_delivery(
    db: AsyncSession, *, user: User, delivery_id: uuid.UUID, require_open: bool = False,
) -> Delivery:
    order = await lock_delivery_order(db, tenant_id=user.tenant_id, delivery_id=delivery_id)
    delivery = (await db.execute(select(Delivery).where(
        Delivery.id == delivery_id, Delivery.tenant_id == user.tenant_id,
        Delivery.order_id == order.id,
    ).with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()
    if delivery is None:
        raise NotFound("Delivery not found")
    if user.role == Role.DELIVERY_PARTNER.value and delivery.partner_id != user.id:
        raise Forbidden("Not your delivery")
    if order.status == OrderStatus.CANCELLED.value:
        raise Conflict("Cancelled order delivery cannot be operated")
    if require_open and order.status != OrderStatus.OUT_FOR_DELIVERY.value:
        raise Conflict("Order must be out_for_delivery")
    return delivery


async def _commit_delivery_response(
    db: AsyncSession, request: Request, delivery: Delivery,
) -> DeliveryOut:
    await db.flush()
    response = DeliveryOut.model_validate(delivery)
    await get_current_user(request, db)
    await db.commit()
    return response


@router.get("", response_model=list[DeliveryOut])
async def list_deliveries(
    partner_id: uuid.UUID | None = None,
    scheduled_date: date | None = None,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_delivery_reader),
):
    stmt = select(Delivery).where(Delivery.tenant_id == user.tenant_id)
    if user.role == Role.DELIVERY_PARTNER.value:
        stmt = stmt.where(Delivery.partner_id == user.id)
    elif user.role == Role.CUSTOMER.value:
        if not user.customer_id:
            raise Forbidden("Customer profile missing")
        stmt = stmt.where(select(Order.id).where(
            Order.id == Delivery.order_id, Order.tenant_id == user.tenant_id,
            Order.customer_id == user.customer_id,
        ).exists())
    elif partner_id:
        stmt = stmt.where(Delivery.partner_id == partner_id)
    if scheduled_date:
        stmt = stmt.where(Delivery.scheduled_date == scheduled_date)
    stmt = stmt.order_by(Delivery.priority.asc(), Delivery.created_at.desc())
    return (await db.execute(stmt)).scalars().all()


@router.get("/my-route", response_model=list[DeliveryOut])
async def my_route(db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    if user.role != Role.DELIVERY_PARTNER.value:
        raise Forbidden("Only delivery partners")
    today = datetime.now(timezone.utc).date()
    return (await db.execute(
        select(Delivery).where(
            Delivery.tenant_id == user.tenant_id,
            Delivery.partner_id == user.id,
            (Delivery.scheduled_date == today) | (Delivery.scheduled_date.is_(None)),
            Delivery.completed_at.is_(None),
        ).order_by(Delivery.priority.asc())
    )).scalars().all()


@router.post("/{delivery_id}/assign", response_model=DeliveryOut)
async def assign(
    delivery_id: uuid.UUID, payload: AssignRequest, request: Request,
    db: AsyncSession = Depends(get_db), user=Depends(require_admin_or_manager),
):
    # Staff lifecycle and assignment share sorted non-key User locks before business rows.
    parents = {}
    for identifier in sorted({user.id, payload.partner_id}, key=lambda value: value.hex):
        current = (await db.execute(select(User).where(
            User.id == identifier, User.tenant_id == user.tenant_id,
        ).with_for_update(key_share=True).execution_options(populate_existing=True))).scalar_one_or_none()
        if current is not None:
            parents[identifier] = current
    user = await lock_current_user(request, db)
    if user.role not in {Role.SUPER_ADMIN.value, Role.WAREHOUSE_MANAGER.value}:
        raise Forbidden("Delivery assignment is not permitted")
    partner = parents.get(payload.partner_id)
    if (
        partner is None or partner.role != Role.DELIVERY_PARTNER.value
        or not partner.is_active or partner.customer_id is not None
    ):
        raise NotFound("Active delivery partner not found")
    d = (await db.execute(
        select(Delivery).where(
            Delivery.id == delivery_id, Delivery.tenant_id == user.tenant_id,
        ).with_for_update().execution_options(populate_existing=True)
    )).scalar_one_or_none()
    if not d:
        raise NotFound("Delivery not found")
    if d.completed_at is not None:
        raise Conflict("Completed delivery cannot be reassigned")
    d.partner_id = payload.partner_id
    d.scheduled_date = payload.scheduled_date or datetime.now(timezone.utc).date()
    d.priority = payload.priority
    await audit(db, tenant_id=user.tenant_id, actor_id=user.id, actor_email=user.email,
                action="deliveries.assign", resource_type="delivery", resource_id=str(d.id),
                 meta={"partner_id": str(payload.partner_id)})
    return await _commit_delivery_response(db, request, d)


@router.post("/{delivery_id}/start", response_model=DeliveryOut)
async def start(
    delivery_id: uuid.UUID, request: Request,
    db: AsyncSession = Depends(get_db), user=Depends(require_delivery_operator)
):
    user = await _lock_delivery_operator(request, db)
    d = await _locked_delivery(db, user=user, delivery_id=delivery_id, require_open=True)
    if d.completed_at is not None:
        raise Conflict("Delivery already completed")
    d.started_at = d.started_at or datetime.now(timezone.utc)
    await audit(db, tenant_id=user.tenant_id, actor_id=user.id, actor_email=user.email,
                action="deliveries.start", resource_type="delivery", resource_id=str(d.id))
    return await _commit_delivery_response(db, request, d)


@router.post("/{delivery_id}/verify-otp", response_model=DeliveryOut)
async def verify_otp(
    delivery_id: uuid.UUID, payload: VerifyOTPRequest, request: Request,
    db: AsyncSession = Depends(get_db), user=Depends(require_delivery_operator),
):
    user = await _lock_delivery_operator(request, db)
    d = await _locked_delivery(db, user=user, delivery_id=delivery_id, require_open=True)
    if d.completed_at is not None:
        raise Conflict("Delivery already completed")
    if not d.otp_code or not secrets.compare_digest(d.otp_code, payload.otp_code):
        raise Conflict("Invalid OTP")
    d.otp_verified = True
    await audit(db, tenant_id=user.tenant_id, actor_id=user.id, actor_email=user.email,
                action="deliveries.verify_otp", resource_type="delivery", resource_id=str(d.id))
    return await _commit_delivery_response(db, request, d)


@router.post("/{delivery_id}/complete", response_model=DeliveryOut)
async def complete(
    delivery_id: uuid.UUID, payload: CollectRequest, request: Request,
    db: AsyncSession = Depends(get_db), user=Depends(require_delivery_operator),
    idempotency_key: uuid.UUID | None = Header(default=None, alias="X-Idempotency-Key"),
):
    user = await _lock_delivery_operator(request, db)
    await _assert_completion_access(db, user=user, delivery_id=delivery_id)
    claim = await idempotency.claim(
        db, tenant_id=user.tenant_id, actor_id=user.id, operation="deliveries.complete",
        key=idempotency_key, payload={"delivery_id": delivery_id, "request": payload},
    )
    if claim is not None and claim.response_body is not None:
        await _locked_delivery(db, user=user, delivery_id=claim.resource_id)
        response = DeliveryOut.model_validate(claim.response_body)
        await get_current_user(request, db)
        return response
    _, delivery = await order_service.finalize_delivery(
        db, tenant_id=user.tenant_id, delivery_id=delivery_id,
        actor_id=user.id, actor_role=user.role, actor_email=user.email, **payload.model_dump(),
    )
    await db.flush()
    response = DeliveryOut.model_validate(delivery)
    idempotency.remember(
        claim, response=response, status_code=200, resource_type="delivery", resource_id=delivery.id,
    )
    await db.flush()
    await get_current_user(request, db)
    await db.commit()
    return response


async def _assert_completion_access(
    db: AsyncSession, *, user: User, delivery_id: uuid.UUID,
) -> None:
    if user.role not in {
        Role.SUPER_ADMIN.value, Role.WAREHOUSE_MANAGER.value, Role.DELIVERY_PARTNER.value,
    }:
        raise Forbidden("Delivery operation is not permitted")
    visible = (await db.execute(select(Delivery.id, Delivery.partner_id).where(
        Delivery.id == delivery_id, Delivery.tenant_id == user.tenant_id,
    ))).one_or_none()
    if visible is None:
        raise NotFound("Delivery not found")
    if user.role == Role.DELIVERY_PARTNER.value and visible.partner_id != user.id:
        raise Forbidden("Not your delivery")
