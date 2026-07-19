"""Order service — state machine, reservation, partial fulfillment, credit check.

The order state machine:
    PENDING → CONFIRMED → RESERVED → PICKED → PACKED
        → OUT_FOR_DELIVERY → DELIVERED → PAID → COMPLETED

Reservation happens on PENDING→CONFIRMED. Stock is locked via `SELECT ... FOR UPDATE`
across all affected inventory rows in a single transaction.
"""
from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import OrderStatus, StockMovementType
from app.core.exceptions import (
    Conflict, CreditLimitExceeded, DomainError, InsufficientStock, NotFound,
)
from app.features.inventory import service as inv_service
from app.features.pricing.service import resolve_price
from app.infrastructure.db.models.customer import Customer, LedgerEntry
from app.infrastructure.db.models.order import (
    Order, OrderItem, OrderReservation, OrderStatusHistory,
)
from app.infrastructure.db.models.product import Product


# Valid transitions
TRANSITIONS: dict[str, set[str]] = {
    OrderStatus.PENDING.value: {OrderStatus.CONFIRMED.value, OrderStatus.RESERVED.value, OrderStatus.CANCELLED.value},
    OrderStatus.CONFIRMED.value: {OrderStatus.RESERVED.value, OrderStatus.CANCELLED.value},
    OrderStatus.RESERVED.value: {OrderStatus.PICKED.value, OrderStatus.CANCELLED.value},
    OrderStatus.PICKED.value: {OrderStatus.PACKED.value, OrderStatus.CANCELLED.value},
    OrderStatus.PACKED.value: {OrderStatus.OUT_FOR_DELIVERY.value, OrderStatus.CANCELLED.value},
    OrderStatus.OUT_FOR_DELIVERY.value: {OrderStatus.DELIVERED.value, OrderStatus.CANCELLED.value},
    OrderStatus.DELIVERED.value: {OrderStatus.PAID.value, OrderStatus.COMPLETED.value},
    OrderStatus.PAID.value: {OrderStatus.COMPLETED.value},
    OrderStatus.COMPLETED.value: set(),
    OrderStatus.CANCELLED.value: set(),
}


def _next_order_number() -> str:
    return f"SO-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{secrets.token_hex(3).upper()}"


async def _record_status(
    db: AsyncSession, *, order: Order, to_status: str, actor_id: uuid.UUID | None,
    note: str | None = None,
) -> None:
    hist = OrderStatusHistory(
        tenant_id=order.tenant_id, order_id=order.id,
        from_status=order.status, to_status=to_status,
        actor_id=actor_id, note=note,
    )
    db.add(hist)


async def create_order(
    db: AsyncSession, *, tenant_id: uuid.UUID, customer_id: uuid.UUID,
    warehouse_id: uuid.UUID, items: list[dict], channel: str = "app",
    scheduled_delivery_date=None, delivery_address: str | None = None,
    notes: str | None = None, created_by: uuid.UUID | None = None,
    is_credit: bool = False,
) -> Order:
    """items: [{product_id: UUID, quantity: Decimal}, ...]

    Creates Order + OrderItems with pricing snapshot. Status = PENDING.
    Does not reserve stock yet — that happens on confirm().
    """
    customer = (await db.execute(
        select(Customer).where(Customer.id == customer_id, Customer.tenant_id == tenant_id)
    )).scalar_one_or_none()
    if not customer:
        raise NotFound("Customer not found")

    order = Order(
        tenant_id=tenant_id, order_number=_next_order_number(),
        customer_id=customer_id, warehouse_id=warehouse_id,
        status=OrderStatus.PENDING.value, channel=channel,
        scheduled_delivery_date=scheduled_delivery_date,
        delivery_address=delivery_address or customer.address,
        notes=notes, created_by=created_by,
    )
    db.add(order)
    await db.flush()

    subtotal = Decimal("0")
    tax_total = Decimal("0")
    for line in items:
        product_id = line["product_id"]
        qty = Decimal(str(line["quantity"]))
        if qty <= 0:
            raise DomainError("Quantity must be positive")

        product = (await db.execute(
            select(Product).where(Product.id == product_id, Product.tenant_id == tenant_id)
        )).scalar_one_or_none()
        if not product:
            raise NotFound(f"Product {product_id} not found")

        unit_price = await resolve_price(
            db, tenant_id=tenant_id, customer_id=customer_id, product_id=product_id
        )
        line_sub = (unit_price * qty).quantize(Decimal("0.01"))
        line_tax = (line_sub * Decimal(str(product.gst_rate)) / Decimal("100")).quantize(Decimal("0.01"))
        line_total = line_sub + line_tax

        item = OrderItem(
            tenant_id=tenant_id, order_id=order.id, product_id=product.id,
            product_sku=product.sku, product_name=product.name,
            quantity=qty, unit_price=unit_price, gst_rate=product.gst_rate,
            line_subtotal=line_sub, line_tax=line_tax, line_total=line_total,
        )
        db.add(item)
        subtotal += line_sub
        tax_total += line_tax

    order.subtotal = subtotal
    order.tax_total = tax_total
    order.grand_total = subtotal + tax_total

    # Credit check for credit orders
    if is_credit and customer.customer_type == "credit":
        projected = Decimal(str(customer.outstanding)) + order.grand_total
        if projected > Decimal(str(customer.credit_limit)):
            raise CreditLimitExceeded(
                f"Would exceed credit limit ({projected} > {customer.credit_limit})"
            )

    await _record_status(db, order=order, to_status=OrderStatus.PENDING.value, actor_id=created_by)
    return order


async def _transition(order: Order, to_status: str) -> None:
    allowed = TRANSITIONS.get(order.status, set())
    if to_status not in allowed:
        raise Conflict(f"Cannot transition {order.status} → {to_status}")
    order.status = to_status


async def confirm_order(
    db: AsyncSession, *, order_id: uuid.UUID, tenant_id: uuid.UUID,
    actor_id: uuid.UUID | None,
) -> Order:
    order = (await db.execute(
        select(Order).where(Order.id == order_id, Order.tenant_id == tenant_id).with_for_update()
    )).scalar_one_or_none()
    if not order:
        raise NotFound("Order not found")
    if order.status != OrderStatus.PENDING.value:
        raise Conflict(f"Order is {order.status}")
    await _record_status(db, order=order, to_status=OrderStatus.CONFIRMED.value, actor_id=actor_id)
    await _transition(order, OrderStatus.CONFIRMED.value)
    order.confirmed_at = datetime.now(timezone.utc)
    return order


async def reserve_order(
    db: AsyncSession, *, order_id: uuid.UUID, tenant_id: uuid.UUID,
    actor_id: uuid.UUID | None,
) -> Order:
    order = (await db.execute(
        select(Order).where(Order.id == order_id, Order.tenant_id == tenant_id).with_for_update()
    )).scalar_one_or_none()
    if not order:
        raise NotFound("Order not found")
    if order.status not in (OrderStatus.CONFIRMED.value, OrderStatus.PENDING.value):
        raise Conflict(f"Order is {order.status}")

    items = (await db.execute(
        select(OrderItem).where(OrderItem.order_id == order.id)
    )).scalars().all()

    for it in items:
        allocations = await inv_service.reserve_stock(
            db, tenant_id=tenant_id, product_id=it.product_id,
            warehouse_id=order.warehouse_id, qty_needed=Decimal(str(it.quantity)),
        )
        for inv_row, qty in allocations:
            db.add(OrderReservation(
                tenant_id=tenant_id, order_id=order.id, order_item_id=it.id,
                inventory_item_id=inv_row.id, quantity=qty,
            ))

    await _record_status(db, order=order, to_status=OrderStatus.RESERVED.value, actor_id=actor_id)
    await _transition(order, OrderStatus.RESERVED.value)
    return order


async def advance_status(
    db: AsyncSession, *, order_id: uuid.UUID, tenant_id: uuid.UUID,
    to_status: str, actor_id: uuid.UUID | None, note: str | None = None,
) -> Order:
    order = (await db.execute(
        select(Order).where(Order.id == order_id, Order.tenant_id == tenant_id).with_for_update()
    )).scalar_one_or_none()
    if not order:
        raise NotFound("Order not found")
    await _record_status(db, order=order, to_status=to_status, actor_id=actor_id, note=note)
    await _transition(order, to_status)
    if to_status == OrderStatus.DELIVERED.value:
        order.delivered_at = datetime.now(timezone.utc)
    if to_status == OrderStatus.COMPLETED.value:
        order.completed_at = datetime.now(timezone.utc)
    if to_status == OrderStatus.CANCELLED.value:
        order.cancelled_at = datetime.now(timezone.utc)
    return order


async def cancel_order(
    db: AsyncSession, *, order_id: uuid.UUID, tenant_id: uuid.UUID,
    actor_id: uuid.UUID | None, note: str | None = None,
) -> Order:
    order = (await db.execute(
        select(Order).where(Order.id == order_id, Order.tenant_id == tenant_id).with_for_update()
    )).scalar_one_or_none()
    if not order:
        raise NotFound("Order not found")
    if order.status in (OrderStatus.COMPLETED.value, OrderStatus.CANCELLED.value):
        raise Conflict(f"Order already {order.status}")
    # Release reservations
    reservations = (await db.execute(
        select(OrderReservation).where(
            OrderReservation.order_id == order.id, OrderReservation.released_at.is_(None),
            OrderReservation.fulfilled_at.is_(None),
        )
    )).scalars().all()
    for res in reservations:
        await inv_service.release_reservation(
            db, inventory_item_id=res.inventory_item_id, qty=Decimal(str(res.quantity))
        )
        res.released_at = datetime.now(timezone.utc)
    await _record_status(db, order=order, to_status=OrderStatus.CANCELLED.value, actor_id=actor_id, note=note)
    await _transition(order, OrderStatus.CANCELLED.value)
    order.cancelled_at = datetime.now(timezone.utc)
    return order


async def deliver_order(
    db: AsyncSession, *, order_id: uuid.UUID, tenant_id: uuid.UUID,
    actor_id: uuid.UUID | None,
) -> Order:
    """Finalize physical delivery: consume reservations + adjust inventory + update ledger if credit."""
    order = (await db.execute(
        select(Order).where(Order.id == order_id, Order.tenant_id == tenant_id).with_for_update()
    )).scalar_one_or_none()
    if not order:
        raise NotFound("Order not found")
    if order.status != OrderStatus.OUT_FOR_DELIVERY.value:
        raise Conflict(f"Order must be out_for_delivery, is {order.status}")

    reservations = (await db.execute(
        select(OrderReservation).where(
            OrderReservation.order_id == order.id,
            OrderReservation.fulfilled_at.is_(None),
            OrderReservation.released_at.is_(None),
        )
    )).scalars().all()

    items_by_id = {
        it.id: it for it in (await db.execute(
            select(OrderItem).where(OrderItem.order_id == order.id)
        )).scalars().all()
    }

    for res in reservations:
        item = items_by_id[res.order_item_id]
        await inv_service.consume_reservation(
            db, inventory_item_id=res.inventory_item_id, qty=Decimal(str(res.quantity)),
            tenant_id=tenant_id, product_id=item.product_id, warehouse_id=order.warehouse_id,
            reference_type="order", reference_id=order.id, actor_id=actor_id,
        )
        res.fulfilled_at = datetime.now(timezone.utc)

    # If credit customer, add outstanding + ledger debit
    customer = (await db.execute(
        select(Customer).where(Customer.id == order.customer_id).with_for_update()
    )).scalar_one_or_none()
    if customer and customer.customer_type == "credit":
        customer.outstanding = Decimal(str(customer.outstanding)) + Decimal(str(order.grand_total))
        db.add(LedgerEntry(
            tenant_id=tenant_id, customer_id=customer.id,
            debit=Decimal(str(order.grand_total)), credit=Decimal("0"),
            balance_after=customer.outstanding,
            reference_type="order", reference_id=order.id,
            note=f"Delivery {order.order_number}",
        ))

    await _record_status(db, order=order, to_status=OrderStatus.DELIVERED.value, actor_id=actor_id)
    await _transition(order, OrderStatus.DELIVERED.value)
    order.delivered_at = datetime.now(timezone.utc)
    return order
