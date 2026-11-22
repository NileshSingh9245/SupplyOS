from __future__ import annotations

import hashlib
import re
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import Conflict, CreditLimitExceeded, Forbidden, NotFound
from app.features.checkout.proof import encode_quote
from app.features.checkout.schemas import Availability, PriceSnapshot, QuoteClaim, QuoteCreate, QuoteOut, QuotedItem
from app.features.orders import service as orders
from app.features.orders.amounts import calculate_line
from app.features.payments import service as payments
from app.features.pricing import repositories, service as pricing
from app.infrastructure.db.models.inventory import InventoryItem
from app.infrastructure.db.models.user import User
from app.infrastructure.db.models.warehouse import Warehouse


async def customer_context(db: AsyncSession, user: User):
    if user.role != "customer" or not user.is_active or user.customer_id is None:
        raise Forbidden("An active customer account is required")
    context = await payments.lock_context(db, tenant_id=user.tenant_id, customer_id=user.customer_id)
    if not context.customer.is_active:
        raise Forbidden("The customer profile is inactive")
    return context


async def _prices(db: AsyncSession, *, user: User, request: QuoteCreate, customer):
    warehouse = await db.scalar(select(Warehouse.id).where(
        Warehouse.id == request.warehouse_id, Warehouse.tenant_id == user.tenant_id,
        Warehouse.is_active.is_(True),
    ).with_for_update(read=True))
    if warehouse is None:
        raise NotFound("Warehouse not found")
    mode = request.payment_mode or customer.customer_type
    if mode not in {"cash", "credit"} or (mode == "credit" and customer.customer_type != "credit"):
        raise Conflict("The requested customer payment mode is unavailable")
    currency = await repositories.currency(db, user.tenant_id)
    if not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency):
        raise Conflict("The business currency needs reviewed configuration")
    products = await pricing.resolved_products(db, tenant_id=user.tenant_id, customer_id=customer.id,
                                               product_ids={line.product_id for line in request.items})
    items = []
    for line in request.items:
        product = products.get(line.product_id)
        if product is None:
            raise NotFound("An active product is unavailable")
        amounts = calculate_line(product.price, product.gst_rate, quantity=line.quantity)
        items.append(QuotedItem(product_id=product.id, sku=product.sku, name=product.name, unit=product.unit,
                                quantity=line.quantity, unit_price=amounts.unit_price, gst_rate=amounts.gst_rate,
                                subtotal=amounts.subtotal, tax=amounts.tax, total=amounts.total))
    subtotal = payments.validated_decimal(sum((line.subtotal for line in items), Decimal("0")), name="Quote subtotal")
    tax = payments.validated_decimal(sum((line.tax for line in items), Decimal("0")), name="Quote tax")
    snapshot = PriceSnapshot(currency_code=currency, payment_mode=mode, items=tuple(items), subtotal=subtotal,
                             tax_total=tax, grand_total=payments.validated_decimal(subtotal + tax, name="Quote total"))
    return snapshot, products


def price_hash(snapshot: PriceSnapshot) -> str:
    return hashlib.sha256(snapshot.model_dump_json().encode("utf-8")).hexdigest()


async def quote(db: AsyncSession, *, user: User, request: QuoteCreate, identity: uuid.UUID, secret: str) -> QuoteOut:
    context = await customer_context(db, user)
    snapshot, _ = await _prices(db, user=user, request=request, customer=context.customer)
    quantities = {}
    for line in request.items:
        quantities[line.product_id] = quantities.get(line.product_id, Decimal("0")) + line.quantity
    rows = (await db.execute(select(InventoryItem.product_id, func.sum(InventoryItem.quantity - InventoryItem.reserved_qty)).where(
        InventoryItem.tenant_id == user.tenant_id, InventoryItem.warehouse_id == request.warehouse_id,
        InventoryItem.product_id.in_(quantities),
    ).group_by(InventoryItem.product_id))).all()
    available = dict(rows)
    observations = tuple(Availability(product_id=product, required_quantity=amount,
                                     available_quantity=available.get(product, Decimal("0")))
                         for product, amount in quantities.items())
    blockers = []
    if any(row.available_quantity < row.required_quantity for row in observations):
        blockers.append("insufficient_stock")
    if snapshot.payment_mode == "credit":
        try:
            payments.require_credit_capacity(context.customer, additional=snapshot.grand_total)
        except CreditLimitExceeded:
            blockers.append("credit_limit_exceeded")
    claim = QuoteClaim(id=identity, actor_id=user.id, tenant_id=user.tenant_id, customer_id=context.customer.id,
                       authorization_epoch=user.session_version, expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
                       request=request, prices_hash=price_hash(snapshot))
    return QuoteOut(**snapshot.model_dump(), id=identity, quote_proof=encode_quote(claim, secret=secret),
                    warehouse_id=request.warehouse_id, expires_at=claim.expires_at, availability=observations,
                    blockers=tuple(blockers))


def authorize_claim(claim: QuoteClaim, user: User) -> None:
    if (claim.actor_id != user.id or claim.tenant_id != user.tenant_id or claim.customer_id != user.customer_id
            or claim.authorization_epoch != user.session_version or user.role != "customer" or not user.is_active):
        raise Forbidden("This quote does not belong to the current customer authorization")


async def checkout(db: AsyncSession, *, user: User, claim: QuoteClaim):
    authorize_claim(claim, user)
    if claim.expires_at <= datetime.now(timezone.utc):
        raise Conflict("The accepted quote expired; request and review a new quote")
    context = await customer_context(db, user)
    snapshot, products = await _prices(db, user=user, request=claim.request, customer=context.customer)
    if price_hash(snapshot) != claim.prices_hash:
        raise Conflict("The quote terms changed; request and review a new quote")
    row = await orders.create_order(db, tenant_id=user.tenant_id, customer_id=context.customer.id,
                                   warehouse_id=claim.request.warehouse_id,
                                   items=[{"product_id": line.product_id, "quantity": line.quantity} for line in claim.request.items],
                                   payment_mode=snapshot.payment_mode, created_by=user.id, channel="app",
                                   scheduled_delivery_date=claim.request.scheduled_delivery_date,
                                   delivery_address=claim.request.delivery_address, notes=claim.request.notes,
                                   pricing_snapshot=products)
    row.meta = {**(row.meta or {}), "checkout_quote_id": str(claim.id), "checkout_currency": snapshot.currency_code}
    if (row.subtotal, row.tax_total, row.grand_total) != (snapshot.subtotal, snapshot.tax_total, snapshot.grand_total):
        raise Conflict("The accepted pricing snapshot could not be preserved")
    await orders.reserve_order(db, order_id=row.id, tenant_id=user.tenant_id, actor_id=user.id)
    if claim.expires_at <= datetime.now(timezone.utc):
        raise Conflict("The accepted quote expired while awaiting checkout; no order was placed")
    return row
