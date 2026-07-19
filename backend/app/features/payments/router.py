"""Payments — record standalone payments (independent of delivery collection)."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.enums import PaymentMode
from app.core.exceptions import NotFound
from app.infrastructure.db.models.customer import Customer, LedgerEntry
from app.infrastructure.db.models.order import Payment
from app.shared.audit import audit
from app.shared.deps import require_staff
from app.shared.schemas import ORMModel

router = APIRouter(prefix="/payments", tags=["payments"])


class PaymentCreate(BaseModel):
    customer_id: uuid.UUID
    order_id: uuid.UUID | None = None
    amount: Decimal = Field(gt=0)
    mode: PaymentMode
    reference: str | None = None
    note: str | None = None


class PaymentOut(ORMModel):
    id: uuid.UUID
    customer_id: uuid.UUID
    order_id: uuid.UUID | None
    amount: Decimal
    mode: str
    reference: str | None
    note: str | None
    created_at: datetime


@router.post("", response_model=PaymentOut, status_code=201)
async def record_payment(
    payload: PaymentCreate, db: AsyncSession = Depends(get_db), user=Depends(require_staff)
):
    customer = (await db.execute(
        select(Customer).where(
            Customer.id == payload.customer_id, Customer.tenant_id == user.tenant_id
        ).with_for_update()
    )).scalar_one_or_none()
    if not customer:
        raise NotFound("Customer not found")

    p = Payment(
        tenant_id=user.tenant_id, customer_id=customer.id, order_id=payload.order_id,
        amount=payload.amount, mode=payload.mode.value, reference=payload.reference,
        collected_by=user.id, note=payload.note,
    )
    db.add(p)

    # Reduce outstanding + ledger credit
    customer.outstanding = max(Decimal("0"), Decimal(str(customer.outstanding)) - payload.amount)
    db.add(LedgerEntry(
        tenant_id=user.tenant_id, customer_id=customer.id,
        debit=Decimal("0"), credit=payload.amount,
        balance_after=customer.outstanding,
        reference_type="payment", note=payload.note,
    ))

    await audit(
        db, tenant_id=user.tenant_id, actor_id=user.id, actor_email=user.email,
        action="payments.record", resource_type="payment",
        meta={"customer_id": str(customer.id), "amount": str(payload.amount), "mode": payload.mode.value},
    )
    await db.commit()
    await db.refresh(p)
    return p


@router.get("", response_model=list[PaymentOut])
async def list_payments(
    customer_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db), user=Depends(require_staff),
):
    stmt = select(Payment).where(Payment.tenant_id == user.tenant_id)
    if customer_id:
        stmt = stmt.where(Payment.customer_id == customer_id)
    stmt = stmt.order_by(Payment.created_at.desc()).limit(200)
    return (await db.execute(stmt)).scalars().all()
