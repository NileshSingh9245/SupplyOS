"""Locked customer accounting and payment allocation without transaction commits."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import OrderStatus, PaymentMode
from app.core.exceptions import Conflict, CreditLimitExceeded, DomainError, NotFound
from app.infrastructure.db.models.customer import Customer, LedgerEntry
from app.infrastructure.db.models.order import Order, OrderStatusHistory, Payment
from app.shared.audit import audit
from app.shared.decimal_values import validated_decimal

LIVE_STATUSES = ("pending", "confirmed", "reserved", "picked", "packed", "out_for_delivery")
FUNDED_MODES = ("cash", "upi", "bank_transfer")


@dataclass(frozen=True)
class FinancialContext:
    """Rows held by the caller's transaction in Order -> Customer order."""
    customer: Customer
    order: Order | None = None


async def validate_commitments(db: AsyncSession, *, customer: Customer) -> None:
    held, cash_pending = (await db.execute(select(
        func.coalesce(func.sum(Order.credit_hold_amount), 0),
        func.coalesce(func.sum(case((Order.payment_mode == "cash", Order.amount_paid), else_=0)), 0),
    ).where(
        Order.tenant_id == customer.tenant_id, Order.customer_id == customer.id,
        Order.status.in_(LIVE_STATUSES),
    ))).one()
    if held != customer.credit_held or cash_pending != customer.cash_funded_pending:
        raise Conflict("Customer financial commitments need reviewed reconciliation")
    for name in ("credit_limit", "credit_held", "cash_funded_pending"):
        validated_decimal(getattr(customer, name), name=name)
    validated_decimal(customer.outstanding, name="Customer balance", minimum=None)


async def lock_context(
    db: AsyncSession, *, tenant_id: uuid.UUID, customer_id: uuid.UUID | None = None,
    order_id: uuid.UUID | None = None,
) -> FinancialContext:
    await db.flush()
    order = None
    if order_id is not None:
        order = (await db.execute(select(Order).where(
            Order.id == order_id, Order.tenant_id == tenant_id,
        ).with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()
        if order is None or (customer_id is not None and order.customer_id != customer_id):
            raise NotFound("Order not found for this customer")
        customer_id = order.customer_id
    customer = (await db.execute(select(Customer).where(
        Customer.id == customer_id, Customer.tenant_id == tenant_id,
    ).with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()
    if customer is None:
        raise NotFound("Customer not found")
    await validate_commitments(db, customer=customer)
    if order is not None:
        allocated = (await db.execute(select(func.coalesce(func.sum(Payment.amount), 0)).where(
            Payment.tenant_id == tenant_id, Payment.customer_id == customer.id,
            Payment.order_id == order.id, Payment.mode.in_(FUNDED_MODES),
        ))).scalar_one()
        if order.amount_paid != allocated:
            raise Conflict("Order funding needs reviewed reconciliation")
    return FinancialContext(customer=customer, order=order)


def require_credit_capacity(customer: Customer, *, additional: Decimal = Decimal("0")) -> None:
    projected = customer.outstanding + customer.credit_held + customer.cash_funded_pending + additional
    if projected > customer.credit_limit:
        raise CreditLimitExceeded("Customer balance and live commitments would exceed the credit limit")


def mark_paid(db: AsyncSession, *, order: Order, actor_id: uuid.UUID | None) -> None:
    if order.status == OrderStatus.DELIVERED.value and order.amount_paid == order.grand_total:
        db.add(OrderStatusHistory(
            tenant_id=order.tenant_id, order_id=order.id, from_status=order.status,
            to_status=OrderStatus.PAID.value, actor_id=actor_id,
            note="Order fully funded after physical delivery",
        ))
        order.status = OrderStatus.PAID.value


async def append_ledger(
    db: AsyncSession, *, customer: Customer, debit: Decimal = Decimal("0"),
    credit: Decimal = Decimal("0"), reference_type: str, reference_id: uuid.UUID,
    note: str | None = None,
) -> LedgerEntry:
    """Preserve running-balance order despite coarse clocks and delayed transaction starts."""
    debit = validated_decimal(debit, name="Ledger debit")
    credit = validated_decimal(credit, name="Ledger credit")
    validated_decimal(customer.outstanding, name="Customer balance", minimum=None)
    if debit and credit:
        raise DomainError("A ledger entry cannot debit and credit at once")
    latest = (await db.execute(select(func.max(LedgerEntry.created_at)).where(
        LedgerEntry.customer_id == customer.id, LedgerEntry.tenant_id == customer.tenant_id,
    ))).scalar_one()
    pending = [
        entry.created_at for entry in db.new if isinstance(entry, LedgerEntry)
        and entry.customer_id == customer.id and entry.tenant_id == customer.tenant_id
        and entry.created_at is not None
    ]
    previous = max([latest, *pending] if latest is not None else pending, default=None)
    created_at = datetime.now(timezone.utc)
    if previous is not None:
        created_at = max(created_at, previous + timedelta(microseconds=1))
    entry = LedgerEntry(
        tenant_id=customer.tenant_id, customer_id=customer.id, debit=debit, credit=credit,
        balance_after=customer.outstanding, reference_type=reference_type,
        reference_id=reference_id, note=note, created_at=created_at,
    )
    db.add(entry)
    return entry


async def record_payment(
    db: AsyncSession, *, tenant_id: uuid.UUID, customer_id: uuid.UUID, amount: Decimal,
    mode: str, actor_id: uuid.UUID, actor_email: str | None, order_id: uuid.UUID | None = None,
    reference: str | None = None, note: str | None = None,
    context: FinancialContext | None = None, delivery_id: uuid.UUID | None = None,
) -> Payment:
    """Stage one payment, one ledger credit, allocation, and audit in the outer transaction."""
    amount = validated_decimal(amount, name="Payment amount", minimum=Decimal("0.01"))
    if mode not in {item.value for item in PaymentMode}:
        raise DomainError("Invalid payment mode")
    if mode == "credit" and order_id is not None:
        raise Conflict("Credit notes are not collected funds; they cannot fund an order")
    if reference is not None and len(reference) > 120:
        raise DomainError("Payment reference is too long")
    if note is not None and len(note) > 500:
        raise DomainError("Payment note is too long")
    context = context or await lock_context(
        db, tenant_id=tenant_id, customer_id=customer_id, order_id=order_id,
    )
    customer, order = context.customer, context.order
    if customer.id != customer_id or customer.tenant_id != tenant_id:
        raise NotFound("Customer not found")
    if order_id is not None:
        if order is None or order.id != order_id or order.customer_id != customer_id:
            raise NotFound("Order not found for this customer")
        if order.status == OrderStatus.CANCELLED.value:
            raise Conflict("Cancelled orders cannot receive allocated payments")
        if amount > order.grand_total - order.amount_paid:
            raise Conflict("Payment exceeds the order's remaining amount")
        order.amount_paid = validated_decimal(order.amount_paid + amount, name="Order funding")
        if order.payment_mode == "cash" and order.status in LIVE_STATUSES:
            customer.cash_funded_pending = validated_decimal(
                customer.cash_funded_pending + amount, name="Pending cash funding",
            )
        mark_paid(db, order=order, actor_id=actor_id)
    customer.outstanding = validated_decimal(
        customer.outstanding - amount, name="Customer balance", minimum=None,
    )
    payment = Payment(
        id=uuid.uuid4(), tenant_id=tenant_id, customer_id=customer_id, order_id=order_id,
        amount=amount, mode=mode, reference=reference, collected_by=actor_id, note=note,
    )
    db.add(payment)
    await append_ledger(
        db, customer=customer, credit=amount, reference_type="payment",
        reference_id=payment.id, note=note,
    )
    await audit(
        db, tenant_id=tenant_id, actor_id=actor_id, actor_email=actor_email,
        action="payments.record", resource_type="payment", resource_id=str(payment.id),
        meta={
            "customer_id": str(customer_id), "amount": str(amount), "mode": mode,
            "allocation_kind": payment.allocation_kind,
            "order_id": str(order_id) if order_id else None,
            "delivery_id": str(delivery_id) if delivery_id else None,
        },
    )
    return payment
