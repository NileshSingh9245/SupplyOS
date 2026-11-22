"""Payments — record standalone payments (independent of delivery collection)."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.enums import PaymentMode, Role
from app.core.exceptions import NotFound
from app.features.payments import service as payment_service
from app.infrastructure.db.models.order import Payment
from app.shared.deps import require_roles
from app.shared import idempotency
from app.shared.schemas import ORMModel

router = APIRouter(prefix="/payments", tags=["payments"])
require_finance_writer = require_roles(Role.SUPER_ADMIN, Role.ACCOUNTANT)
require_payment_reader = require_roles(Role.SUPER_ADMIN, Role.ACCOUNTANT, Role.CUSTOMER)


class PaymentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    customer_id: uuid.UUID
    order_id: uuid.UUID | None = None
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2, allow_inf_nan=False)
    mode: PaymentMode
    reference: str | None = Field(default=None, max_length=120)
    note: str | None = Field(default=None, max_length=500)


class PaymentOut(ORMModel):
    id: uuid.UUID
    customer_id: uuid.UUID
    order_id: uuid.UUID | None
    amount: Decimal
    mode: str
    reference: str | None
    note: str | None
    created_at: datetime
    allocation_kind: str


@router.post("", response_model=PaymentOut, status_code=201)
async def record_payment(
    payload: PaymentCreate, db: AsyncSession = Depends(get_db), user=Depends(require_finance_writer),
    idempotency_key: uuid.UUID | None = Header(default=None, alias="X-Idempotency-Key"),
):
    claim = await idempotency.claim(
        db, tenant_id=user.tenant_id, actor_id=user.id, operation="payments.record",
        key=idempotency_key, payload=payload,
    )
    if claim is not None and claim.response_body is not None:
        visible = (await db.execute(select(Payment.id).where(
            Payment.id == claim.resource_id, Payment.tenant_id == user.tenant_id,
            Payment.customer_id == payload.customer_id,
        ))).scalar_one_or_none()
        if visible is None:
            raise NotFound("Payment not found")
        return PaymentOut.model_validate(claim.response_body)
    payment = await payment_service.record_payment(
        db, tenant_id=user.tenant_id, customer_id=payload.customer_id,
        order_id=payload.order_id, amount=payload.amount, mode=payload.mode.value,
        actor_id=user.id, actor_email=user.email, reference=payload.reference, note=payload.note,
    )
    await db.flush()
    response = PaymentOut.model_validate(payment)
    idempotency.remember(
        claim, response=response, status_code=201, resource_type="payment", resource_id=payment.id,
    )
    await db.commit()
    return response


@router.get("", response_model=list[PaymentOut])
async def list_payments(
    customer_id: uuid.UUID | None = None,
    order_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db), user=Depends(require_payment_reader),
):
    stmt = select(Payment).where(Payment.tenant_id == user.tenant_id)
    if user.role == Role.CUSTOMER.value:
        stmt = stmt.where(Payment.customer_id == user.customer_id)
    if customer_id:
        stmt = stmt.where(Payment.customer_id == customer_id)
    if order_id:
        stmt = stmt.where(Payment.order_id == order_id)
    stmt = stmt.order_by(Payment.created_at.desc()).limit(200)
    return (await db.execute(stmt)).scalars().all()
