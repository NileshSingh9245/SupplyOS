"""Delivery endpoints — assignment, OTP verification, proof capture, cash/UPI collect."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.enums import Role
from app.core.exceptions import Conflict, Forbidden, NotFound
from app.infrastructure.db.models.order import Delivery, Order
from app.shared.audit import audit
from app.shared.deps import get_current_user, require_admin_or_manager
from app.shared.schemas import ORMModel

router = APIRouter(prefix="/deliveries", tags=["deliveries"])


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
    partner_id: uuid.UUID
    scheduled_date: date | None = None
    priority: int = Field(5, ge=1, le=10)


class VerifyOTPRequest(BaseModel):
    otp_code: str = Field(min_length=4, max_length=10)


class CollectRequest(BaseModel):
    cash_amount: Decimal = Field(ge=0, default=Decimal("0"))
    upi_amount: Decimal = Field(ge=0, default=Decimal("0"))
    signature_url: str | None = None
    proof_photo_url: str | None = None


@router.get("", response_model=list[DeliveryOut])
async def list_deliveries(
    partner_id: uuid.UUID | None = None,
    scheduled_date: date | None = None,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    stmt = select(Delivery).where(Delivery.tenant_id == user.tenant_id)
    if user.role == Role.DELIVERY_PARTNER.value:
        stmt = stmt.where(Delivery.partner_id == user.id)
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
    delivery_id: uuid.UUID, payload: AssignRequest,
    db: AsyncSession = Depends(get_db), user=Depends(require_admin_or_manager),
):
    d = (await db.execute(
        select(Delivery).where(Delivery.id == delivery_id, Delivery.tenant_id == user.tenant_id)
    )).scalar_one_or_none()
    if not d:
        raise NotFound("Delivery not found")
    d.partner_id = payload.partner_id
    d.scheduled_date = payload.scheduled_date or datetime.now(timezone.utc).date()
    d.priority = payload.priority
    await audit(db, tenant_id=user.tenant_id, actor_id=user.id, actor_email=user.email,
                action="deliveries.assign", resource_type="delivery", resource_id=str(d.id),
                meta={"partner_id": str(payload.partner_id)})
    await db.commit()
    await db.refresh(d)
    return d


@router.post("/{delivery_id}/start", response_model=DeliveryOut)
async def start(
    delivery_id: uuid.UUID, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)
):
    d = (await db.execute(
        select(Delivery).where(Delivery.id == delivery_id, Delivery.tenant_id == user.tenant_id)
    )).scalar_one_or_none()
    if not d:
        raise NotFound("Delivery not found")
    if user.role == Role.DELIVERY_PARTNER.value and d.partner_id != user.id:
        raise Forbidden("Not your delivery")
    d.started_at = datetime.now(timezone.utc)
    await audit(db, tenant_id=user.tenant_id, actor_id=user.id, actor_email=user.email,
                action="deliveries.start", resource_type="delivery", resource_id=str(d.id))
    await db.commit()
    await db.refresh(d)
    return d


@router.post("/{delivery_id}/verify-otp", response_model=DeliveryOut)
async def verify_otp(
    delivery_id: uuid.UUID, payload: VerifyOTPRequest,
    db: AsyncSession = Depends(get_db), user=Depends(get_current_user),
):
    d = (await db.execute(
        select(Delivery).where(Delivery.id == delivery_id, Delivery.tenant_id == user.tenant_id)
    )).scalar_one_or_none()
    if not d:
        raise NotFound("Delivery not found")
    if user.role == Role.DELIVERY_PARTNER.value and d.partner_id != user.id:
        raise Forbidden("Not your delivery")
    if not d.otp_code or d.otp_code != payload.otp_code:
        raise Conflict("Invalid OTP")
    d.otp_verified = True
    await audit(db, tenant_id=user.tenant_id, actor_id=user.id, actor_email=user.email,
                action="deliveries.verify_otp", resource_type="delivery", resource_id=str(d.id))
    await db.commit()
    await db.refresh(d)
    return d


@router.post("/{delivery_id}/complete", response_model=DeliveryOut)
async def complete(
    delivery_id: uuid.UUID, payload: CollectRequest,
    db: AsyncSession = Depends(get_db), user=Depends(get_current_user),
):
    from app.features.orders import service as order_service
    from app.infrastructure.db.models.customer import Customer, LedgerEntry
    from app.infrastructure.db.models.order import Payment

    d = (await db.execute(
        select(Delivery).where(Delivery.id == delivery_id, Delivery.tenant_id == user.tenant_id).with_for_update()
    )).scalar_one_or_none()
    if not d:
        raise NotFound("Delivery not found")
    if user.role == Role.DELIVERY_PARTNER.value and d.partner_id != user.id:
        raise Forbidden("Not your delivery")
    if not d.otp_verified:
        raise Conflict("OTP not verified")

    d.cash_collected = payload.cash_amount
    d.upi_collected = payload.upi_amount
    d.signature_url = payload.signature_url
    d.proof_photo_url = payload.proof_photo_url
    d.completed_at = datetime.now(timezone.utc)

    # Advance order to DELIVERED (which consumes reservations)
    order = await order_service.deliver_order(
        db, order_id=d.order_id, tenant_id=user.tenant_id, actor_id=user.id
    )

    # Record payments if any collected
    total_collected = payload.cash_amount + payload.upi_amount
    if payload.cash_amount > 0:
        db.add(Payment(
            tenant_id=user.tenant_id, order_id=order.id, customer_id=order.customer_id,
            amount=payload.cash_amount, mode="cash", collected_by=user.id,
        ))
    if payload.upi_amount > 0:
        db.add(Payment(
            tenant_id=user.tenant_id, order_id=order.id, customer_id=order.customer_id,
            amount=payload.upi_amount, mode="upi", collected_by=user.id,
        ))
    if total_collected > 0:
        order.amount_paid = Decimal(str(order.amount_paid)) + total_collected
        # Reduce customer outstanding + ledger credit
        customer = (await db.execute(
            select(Customer).where(Customer.id == order.customer_id).with_for_update()
        )).scalar_one()
        customer.outstanding = max(Decimal("0"), Decimal(str(customer.outstanding)) - total_collected)
        db.add(LedgerEntry(
            tenant_id=user.tenant_id, customer_id=customer.id,
            debit=Decimal("0"), credit=total_collected,
            balance_after=customer.outstanding,
            reference_type="delivery_payment", reference_id=d.id,
            note=f"Delivery collection for {order.order_number}",
        ))

    await audit(db, tenant_id=user.tenant_id, actor_id=user.id, actor_email=user.email,
                action="deliveries.complete", resource_type="delivery", resource_id=str(d.id),
                meta={"cash": str(payload.cash_amount), "upi": str(payload.upi_amount)})
    await db.commit()
    await db.refresh(d)
    return d
