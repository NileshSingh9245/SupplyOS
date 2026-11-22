"""Order state machine, gross credit commitments, and guarded delivery finalization.

The order state machine:
    PENDING → CONFIRMED → RESERVED → PICKED → PACKED
        → OUT_FOR_DELIVERY → DELIVERED → PAID → COMPLETED

Reservation is a separate operation after creation/confirmation. Stock uses `SELECT ... FOR UPDATE`
across all affected inventory rows in a single transaction.
"""
from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timezone
from decimal import Decimal, localcontext

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import OrderStatus, Role, StockMovementType
from app.core.exceptions import (
    Conflict, DomainError, Forbidden, NotFound,
)
from app.features.inventory import service as inv_service
from app.features.payments import service as payment_service
from app.features.pricing.service import resolved_products
from app.infrastructure.db.models.inventory import InventoryItem, StockMovement
from app.infrastructure.db.models.order import (
    Delivery, Order, OrderItem, OrderReservation, OrderStatusHistory,
)
from app.infrastructure.db.models.warehouse import Warehouse
from app.shared.audit import audit


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
    is_credit: bool = False, payment_mode: str | None = None,
) -> Order:
    """items: [{product_id: UUID, quantity: Decimal}, ...]

    Creates Order + OrderItems with pricing snapshot. Status = PENDING.
    Stock is reserved by the separate reservation action, not confirmation.
    """
    if not items or len(items) > 200:
        raise DomainError("An order requires between 1 and 200 lines")
    quantities = [payment_service.validated_decimal(
        line["quantity"], name="Quantity", precision=16, scale=3, minimum=Decimal("0.001"),
    ) for line in items]
    # No published Order exists yet; take the customer lock before inserting its FK reference.
    context = await payment_service.lock_context(db, tenant_id=tenant_id, customer_id=customer_id)
    customer = context.customer
    if not customer.is_active:
        raise NotFound("Customer not found")
    resolved_mode = payment_mode or customer.customer_type
    if resolved_mode not in {"cash", "credit"}:
        raise Conflict("Customer payment mode needs reviewed reconciliation")
    if is_credit and resolved_mode != "credit":
        raise Conflict("Conflicting requested payment modes")
    if resolved_mode == "credit" and customer.customer_type != "credit":
        raise Conflict("Credit is not enabled for this customer")
    for value, maximum, name in ((channel, 20, "Channel"), (notes, 500, "Notes"),
                                  (delivery_address, 500, "Delivery address")):
        if value is not None and len(value) > maximum:
            raise DomainError(f"{name} is too long")
    warehouse = (await db.execute(select(Warehouse.id).where(
        Warehouse.id == warehouse_id, Warehouse.tenant_id == tenant_id, Warehouse.is_active.is_(True),
    ))).scalar_one_or_none()
    if warehouse is None:
        raise NotFound("Warehouse not found")

    # Mutable product/tier/override values must not be reread between order lines.
    pricing = await resolved_products(
        db, tenant_id=tenant_id, customer_id=customer_id,
        product_ids={line["product_id"] for line in items},
    )

    order = Order(
        tenant_id=tenant_id, order_number=_next_order_number(),
        customer_id=customer_id, warehouse_id=warehouse_id,
        status=OrderStatus.PENDING.value, channel=channel,
        payment_mode=resolved_mode,
        scheduled_delivery_date=scheduled_delivery_date,
        delivery_address=delivery_address or customer.address,
        notes=notes, created_by=created_by,
    )
    db.add(order)
    await db.flush()

    subtotal = Decimal("0")
    tax_total = Decimal("0")
    for line, qty in zip(items, quantities):
        product_id = line["product_id"]

        product = pricing.get(product_id)
        if not product:
            raise NotFound(f"Product {product_id} not found")

        unit_price = payment_service.validated_decimal(product.price, name="Resolved unit price")
        gst_rate = payment_service.validated_decimal(
            product.gst_rate, name="GST rate", precision=5,
        )
        with localcontext() as decimal_context:
            decimal_context.prec = 50
            line_sub = (unit_price * qty).quantize(Decimal("0.01"))
            line_tax = (line_sub * gst_rate / Decimal("100")).quantize(Decimal("0.01"))
            line_total = line_sub + line_tax
        for amount in (line_sub, line_tax, line_total):
            payment_service.validated_decimal(amount, name="Line amount")

        item = OrderItem(
            tenant_id=tenant_id, order_id=order.id, product_id=product.id,
            product_sku=product.sku, product_name=product.name,
            quantity=qty, unit_price=unit_price, gst_rate=gst_rate,
            line_subtotal=line_sub, line_tax=line_tax, line_total=line_total,
        )
        db.add(item)
        subtotal += line_sub
        tax_total += line_tax

    order.subtotal = payment_service.validated_decimal(subtotal, name="Order subtotal")
    order.tax_total = payment_service.validated_decimal(tax_total, name="Order tax")
    order.grand_total = payment_service.validated_decimal(subtotal + tax_total, name="Order total")
    if resolved_mode == "credit":
        payment_service.require_credit_capacity(customer, additional=order.grand_total)
        order.credit_hold_amount = order.grand_total
        customer.credit_held = payment_service.validated_decimal(
            customer.credit_held + order.grand_total, name="Gross credit commitments",
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
        select(Order).where(Order.id == order_id, Order.tenant_id == tenant_id)
        .with_for_update().execution_options(populate_existing=True)
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
    context = await payment_service.lock_context(db, tenant_id=tenant_id, order_id=order_id)
    order = context.order
    assert order is not None
    if order.status not in (OrderStatus.CONFIRMED.value, OrderStatus.PENDING.value):
        raise Conflict(f"Order is {order.status}")
    if order.payment_mode == "credit":
        if context.customer.customer_type != "credit":
            raise Conflict("Credit is not enabled for this customer")
        payment_service.require_credit_capacity(context.customer)

    items = await _priced_items(db, order=order)
    for it in items:
        quantity = payment_service.validated_decimal(
            it.quantity, name="Quantity", precision=16, scale=3, minimum=Decimal("0.001"),
        )
        allocations = await inv_service.reserve_stock(
            db, tenant_id=tenant_id, product_id=it.product_id,
            warehouse_id=order.warehouse_id, qty_needed=quantity,
        )
        for inv_row, qty in allocations:
            db.add(OrderReservation(
                tenant_id=tenant_id, order_id=order.id, order_item_id=it.id,
                inventory_item_id=inv_row.id, quantity=qty,
            ))

    await _record_status(db, order=order, to_status=OrderStatus.RESERVED.value, actor_id=actor_id)
    await _transition(order, OrderStatus.RESERVED.value)
    return order


async def _priced_items(db: AsyncSession, *, order: Order) -> list[OrderItem]:
    items = list((await db.execute(select(OrderItem).where(
        OrderItem.order_id == order.id, OrderItem.tenant_id == order.tenant_id,
    ).order_by(OrderItem.product_id, OrderItem.id))).scalars().all())
    subtotal = sum((item.line_subtotal for item in items), Decimal("0"))
    tax_total = sum((item.line_tax for item in items), Decimal("0"))
    if (
        not items or any(item.line_total != item.line_subtotal + item.line_tax for item in items)
        or order.subtotal != subtotal or order.tax_total != tax_total
        or order.grand_total != subtotal + tax_total - order.discount_total
    ):
        raise Conflict("Order pricing snapshot needs reviewed reconciliation")
    return items


async def _active_reservations(db: AsyncSession, *, order: Order) -> list[OrderReservation]:
    rows = (await db.execute(select(
        OrderReservation, InventoryItem.tenant_id, InventoryItem.product_id,
        InventoryItem.warehouse_id, OrderItem.tenant_id, OrderItem.order_id, OrderItem.product_id,
    ).join(InventoryItem, InventoryItem.id == OrderReservation.inventory_item_id)
      .join(OrderItem, OrderItem.id == OrderReservation.order_item_id).where(
        OrderReservation.order_id == order.id, OrderReservation.tenant_id == order.tenant_id,
        OrderReservation.released_at.is_(None), OrderReservation.fulfilled_at.is_(None),
    ).order_by(InventoryItem.product_id, InventoryItem.id, OrderReservation.id))).all()
    for _, stock_tenant, stock_product, warehouse, item_tenant, item_order, item_product in rows:
        if (
            stock_tenant != order.tenant_id or item_tenant != order.tenant_id
            or item_order != order.id or stock_product != item_product
            or warehouse != order.warehouse_id
        ):
            raise Conflict("Reservation references need reviewed reconciliation")
    return [row[0] for row in rows]


async def advance_status(
    db: AsyncSession, *, order_id: uuid.UUID, tenant_id: uuid.UUID,
    to_status: str, actor_id: uuid.UUID | None, note: str | None = None,
) -> Order:
    if to_status not in {
        OrderStatus.PICKED.value, OrderStatus.PACKED.value, OrderStatus.OUT_FOR_DELIVERY.value,
    }:
        raise Conflict("Use the guarded reservation, cancellation, or delivery operation")
    order = (await db.execute(
        select(Order).where(Order.id == order_id, Order.tenant_id == tenant_id)
        .with_for_update().execution_options(populate_existing=True)
    )).scalar_one_or_none()
    if not order:
        raise NotFound("Order not found")
    await _record_status(db, order=order, to_status=to_status, actor_id=actor_id, note=note)
    await _transition(order, to_status)
    return order


async def cancel_order(
    db: AsyncSession, *, order_id: uuid.UUID, tenant_id: uuid.UUID,
    actor_id: uuid.UUID | None, note: str | None = None,
) -> Order:
    context = await payment_service.lock_context(db, tenant_id=tenant_id, order_id=order_id)
    order, customer = context.order, context.customer
    assert order is not None
    if order.status not in payment_service.LIVE_STATUSES:
        raise Conflict(f"Order cannot be cancelled from {order.status}")
    customer.credit_held = payment_service.validated_decimal(
        customer.credit_held - order.credit_hold_amount, name="Gross credit commitments",
    )
    order.credit_hold_amount = Decimal("0")
    if order.payment_mode == "cash":
        customer.cash_funded_pending = payment_service.validated_decimal(
            customer.cash_funded_pending - order.amount_paid, name="Pending cash funding",
        )
    reservations = await _active_reservations(db, order=order)
    for res in reservations:
        quantity = payment_service.validated_decimal(
            res.quantity, name="Reservation quantity", precision=16, scale=3,
            minimum=Decimal("0.001"),
        )
        await inv_service.release_reservation(
            db, inventory_item_id=res.inventory_item_id, qty=quantity, tenant_id=tenant_id,
        )
        stock = (await db.execute(select(InventoryItem).where(
            InventoryItem.id == res.inventory_item_id, InventoryItem.tenant_id == tenant_id,
        ))).scalar_one()
        db.add(StockMovement(
            tenant_id=tenant_id, inventory_item_id=stock.id, product_id=stock.product_id,
            warehouse_id=stock.warehouse_id, movement_type=StockMovementType.RELEASE.value,
            quantity=quantity, reference_type="order", reference_id=order.id,
            actor_id=actor_id, note="Order cancelled",
        ))
        res.released_at = datetime.now(timezone.utc)
    await _record_status(db, order=order, to_status=OrderStatus.CANCELLED.value, actor_id=actor_id, note=note)
    await _transition(order, OrderStatus.CANCELLED.value)
    order.cancelled_at = datetime.now(timezone.utc)
    return order


async def _deliver_locked(
    db: AsyncSession, *, context: payment_service.FinancialContext, actor_id: uuid.UUID,
) -> Order:
    order, customer = context.order, context.customer
    assert order is not None
    tenant_id = order.tenant_id
    if order.status != OrderStatus.OUT_FOR_DELIVERY.value:
        raise Conflict(f"Order must be out_for_delivery, is {order.status}")

    reservations = await _active_reservations(db, order=order)

    items_by_id = {item.id: item for item in await _priced_items(db, order=order)}

    allocated = {identifier: Decimal("0") for identifier in items_by_id}
    for res in reservations:
        if res.order_item_id not in allocated:
            raise Conflict("Reservation does not belong to this order")
        allocated[res.order_item_id] += res.quantity
    if not items_by_id or any(allocated[it.id] != it.quantity for it in items_by_id.values()):
        raise Conflict("Delivery reservations do not cover the complete order")

    for res in reservations:
        item = items_by_id[res.order_item_id]
        quantity = payment_service.validated_decimal(
            res.quantity, name="Reservation quantity", precision=16, scale=3,
            minimum=Decimal("0.001"),
        )
        await inv_service.consume_reservation(
            db, inventory_item_id=res.inventory_item_id, qty=quantity,
            tenant_id=tenant_id, product_id=item.product_id, warehouse_id=order.warehouse_id,
            reference_type="order", reference_id=order.id, actor_id=actor_id,
        )
        res.fulfilled_at = datetime.now(timezone.utc)

    # Every sale absorbs its payment credits; only credit sales had gross credit holds.
    customer.outstanding = payment_service.validated_decimal(
        customer.outstanding + order.grand_total, name="Customer balance", minimum=None,
    )
    customer.credit_held = payment_service.validated_decimal(
        customer.credit_held - order.credit_hold_amount, name="Gross credit commitments",
    )
    order.credit_hold_amount = Decimal("0")
    if order.payment_mode == "cash":
        customer.cash_funded_pending = payment_service.validated_decimal(
            customer.cash_funded_pending - order.amount_paid, name="Pending cash funding",
        )
    await payment_service.append_ledger(
        db, customer=customer, debit=order.grand_total, reference_type="order",
        reference_id=order.id, note=f"Delivery {order.order_number}",
    )

    await _record_status(db, order=order, to_status=OrderStatus.DELIVERED.value, actor_id=actor_id)
    await _transition(order, OrderStatus.DELIVERED.value)
    order.delivered_at = datetime.now(timezone.utc)
    payment_service.mark_paid(db, order=order, actor_id=actor_id)
    return order


async def finalize_delivery(
    db: AsyncSession, *, tenant_id: uuid.UUID, actor_id: uuid.UUID, actor_role: str,
    actor_email: str | None = None, order_id: uuid.UUID | None = None,
    delivery_id: uuid.UUID | None = None, cash_amount: Decimal = Decimal("0"),
    upi_amount: Decimal = Decimal("0"), signature_url: str | None = None,
    proof_photo_url: str | None = None,
) -> tuple[Order, Delivery]:
    """OTP/POD, collection, stock, ledger, and delivery share one caller-owned transaction."""
    if actor_role not in {Role.SUPER_ADMIN.value, Role.WAREHOUSE_MANAGER.value,
                          Role.DELIVERY_PARTNER.value}:
        raise Forbidden("Delivery operation is not permitted")
    cash_amount = payment_service.validated_decimal(cash_amount, name="Cash collection")
    upi_amount = payment_service.validated_decimal(upi_amount, name="UPI collection")
    collected = payment_service.validated_decimal(cash_amount + upi_amount, name="Total collection")
    scope = [Delivery.tenant_id == tenant_id]
    scope.append(Delivery.id == delivery_id if delivery_id is not None else Delivery.order_id == order_id)
    identity = (await db.execute(select(
        Delivery.id, Delivery.order_id, Delivery.partner_id,
    ).where(*scope))).one_or_none()
    if identity is None:
        raise NotFound("Delivery not found")
    if actor_role == Role.DELIVERY_PARTNER.value and identity.partner_id != actor_id:
        raise Forbidden("Not your delivery")
    context = await payment_service.lock_context(db, tenant_id=tenant_id, order_id=identity.order_id)
    order = context.order
    assert order is not None
    delivery = (await db.execute(select(Delivery).where(
        Delivery.id == identity.id, Delivery.tenant_id == tenant_id,
        Delivery.order_id == order.id,
    ).with_for_update().execution_options(populate_existing=True))).scalar_one()
    if actor_role == Role.DELIVERY_PARTNER.value and delivery.partner_id != actor_id:
        raise Forbidden("Not your delivery")
    if delivery.completed_at is not None:
        raise Conflict("Delivery already completed")
    if order.status != OrderStatus.OUT_FOR_DELIVERY.value:
        raise Conflict(f"Order must be out_for_delivery, is {order.status}")
    if not delivery.otp_verified:
        raise Conflict("OTP not verified")
    signature_url = signature_url if signature_url is not None else delivery.signature_url
    proof_photo_url = proof_photo_url if proof_photo_url is not None else delivery.proof_photo_url
    if not any(value and value.strip() for value in (signature_url, proof_photo_url)):
        raise Conflict("Delivery proof is required")
    from app.features.proofs.service import validate_delivery_proofs

    await validate_delivery_proofs(
        db, tenant_id=tenant_id, delivery_id=delivery.id,
        signature_url=signature_url, proof_photo_url=proof_photo_url,
    )
    if collected > order.grand_total - order.amount_paid:
        raise Conflict("Collection exceeds the order's remaining amount")
    if order.payment_mode == "cash" and order.amount_paid + collected != order.grand_total:
        raise Conflict("Cash-mode delivery requires full allocated funding")
    for amount, mode in ((cash_amount, "cash"), (upi_amount, "upi")):
        if amount > 0:
            await payment_service.record_payment(
                db, tenant_id=tenant_id, customer_id=order.customer_id, order_id=order.id,
                amount=amount, mode=mode, actor_id=actor_id, actor_email=actor_email,
                context=context, delivery_id=delivery.id, note=f"Delivery collection {order.order_number}",
            )
    if order.payment_mode == "credit":
        payment_service.require_credit_capacity(context.customer)
    order = await _deliver_locked(db, context=context, actor_id=actor_id)
    delivery.cash_collected = cash_amount
    delivery.upi_collected = upi_amount
    delivery.signature_url = signature_url
    delivery.proof_photo_url = proof_photo_url
    delivery.completed_at = datetime.now(timezone.utc)
    await audit(
        db, tenant_id=tenant_id, actor_id=actor_id, actor_email=actor_email,
        action="orders.deliver", resource_type="order", resource_id=str(order.id),
    )
    await audit(
        db, tenant_id=tenant_id, actor_id=actor_id, actor_email=actor_email,
        action="deliveries.complete", resource_type="delivery", resource_id=str(delivery.id),
        meta={"cash": str(cash_amount), "upi": str(upi_amount)},
    )
    return order, delivery


async def deliver_order(
    db: AsyncSession, *, order_id: uuid.UUID, tenant_id: uuid.UUID, actor_id: uuid.UUID,
    actor_role: str, actor_email: str | None = None,
    cash_amount: Decimal = Decimal("0"), upi_amount: Decimal = Decimal("0"),
    signature_url: str | None = None, proof_photo_url: str | None = None,
) -> Order:
    order, _ = await finalize_delivery(
        db, tenant_id=tenant_id, order_id=order_id, actor_id=actor_id, actor_role=actor_role,
        actor_email=actor_email, cash_amount=cash_amount, upi_amount=upi_amount,
        signature_url=signature_url, proof_photo_url=proof_photo_url,
    )
    return order
