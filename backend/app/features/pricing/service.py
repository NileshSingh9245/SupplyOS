"""Pricing engine resolves the price for (customer, product) using:
1. Explicit customer override (`customer_prices`).
2. Tier discount (`price_tiers`) applied to product.base_price.
3. Fallback to `product.base_price`.
"""
from __future__ import annotations

import uuid
import re
from collections.abc import Collection
from decimal import Decimal, localcontext

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import Conflict, DomainError, NotFound
from app.features.pricing import repositories
from app.features.pricing.schemas import CatalogProduct, ResolvedProduct, TierCreate, TierUpdate
from app.infrastructure.db.models.customer import PriceTier
from app.infrastructure.db.models.user import User
from app.shared.audit import audit
from app.shared.decimal_values import validated_decimal
from app.shared.schemas import Paginated


def _resolved(row: repositories.PriceRow) -> ResolvedProduct:
    if row.override_price is not None:
        price = validated_decimal(row.override_price, name="Customer price")
    else:
        price = validated_decimal(row.base_price, name="Product base price")
        if row.discount_pct is not None:
            discount = validated_decimal(row.discount_pct, name="Tier discount", precision=5)
            if discount > 100:
                raise Conflict("Pricing tier needs reviewed reconciliation")
            with localcontext() as context:
                context.prec = 50
                price = (price * (Decimal("1") - discount / Decimal("100"))).quantize(Decimal("0.01"))
    gst = validated_decimal(row.gst_rate, name="GST rate", precision=5)
    if gst > 100:
        raise Conflict("Product tax needs reviewed reconciliation")
    return ResolvedProduct(id=row.id, sku=row.sku, name=row.name, unit=row.unit, price=price, gst_rate=gst)


async def resolved_products(
    db: AsyncSession, *, tenant_id: uuid.UUID, customer_id: uuid.UUID,
    product_ids: Collection[uuid.UUID],
) -> dict[uuid.UUID, ResolvedProduct]:
    rows = await repositories.priced_rows(
        db, tenant_id=tenant_id, customer_id=customer_id, product_ids=product_ids,
    )
    return {row.id: _resolved(row) for row in rows}


async def resolve_price(
    db: AsyncSession, *, tenant_id: uuid.UUID, customer_id: uuid.UUID,
    product_id: uuid.UUID,
) -> Decimal:
    products = await resolved_products(
        db, tenant_id=tenant_id, customer_id=customer_id, product_ids={product_id},
    )
    if product_id not in products:
        raise NotFound("Active customer or product not found")
    return products[product_id].price


async def catalog(db: AsyncSession, *, tenant_id: uuid.UUID, customer_id: uuid.UUID,
                  q: str | None, page: int, page_size: int) -> Paginated[CatalogProduct]:
    if not await repositories.active_customer(db, tenant_id, customer_id):
        raise NotFound("Customer catalog is unavailable")
    currency = await repositories.currency(db, tenant_id)
    if not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency):
        raise Conflict("Customer catalog currency needs reviewed settings")
    total = await repositories.product_count(db, tenant_id, q)
    rows = await repositories.priced_rows(
        db, tenant_id=tenant_id, customer_id=customer_id, q=q,
        offset=(page - 1) * page_size, limit=page_size,
    )
    return Paginated(items=[CatalogProduct(**_resolved(row).model_dump(), currency_code=currency) for row in rows],
                     total=total, page=page, page_size=page_size)


async def create_tier(db: AsyncSession, actor: User, payload: TierCreate) -> PriceTier:
    row = PriceTier(tenant_id=actor.tenant_id, **payload.model_dump())
    db.add(row)
    try:
        await db.flush()
    except IntegrityError as error:
        if getattr(error.orig, "sqlstate", None) == "23505":
            raise Conflict("Tier name already exists") from None
        raise
    await audit(db, tenant_id=actor.tenant_id, actor_id=actor.id, actor_email=actor.email,
                action="pricing.tier_create", resource_type="price_tier", resource_id=str(row.id))
    return row


async def update_tier(db: AsyncSession, actor: User, tier_id: uuid.UUID, payload: TierUpdate) -> PriceTier:
    row = await repositories.tier(db, actor.tenant_id, tier_id, lock=True)
    if row is None:
        raise NotFound("Pricing tier not found")
    before = row.discount_pct
    row.discount_pct = payload.discount_pct
    await audit(db, tenant_id=actor.tenant_id, actor_id=actor.id, actor_email=actor.email,
                action="pricing.tier_update", resource_type="price_tier", resource_id=str(row.id),
                meta={"before_discount_pct": str(before), "discount_pct": str(row.discount_pct)})
    return row


async def assign_tier(db: AsyncSession, actor: User, customer_id: uuid.UUID, tier_id: uuid.UUID | None):
    row = await repositories.customer(db, actor.tenant_id, customer_id)
    if row is None:
        raise NotFound("Customer not found")
    selected = await repositories.tier(db, actor.tenant_id, tier_id) if tier_id is not None else None
    if tier_id is not None and selected is None:
        raise NotFound("Pricing tier not found")
    if selected is not None and len(selected.name) > 30:
        raise DomainError("This legacy tier name is too long for customer assignment")
    before = row.price_tier
    row.price_tier = selected.name if selected else None
    await audit(db, tenant_id=actor.tenant_id, actor_id=actor.id, actor_email=actor.email,
                action="pricing.customer_tier", resource_type="customer", resource_id=str(row.id),
                meta={"before_tier": before, "tier": row.price_tier})
    return row


async def remove_override(db: AsyncSession, actor: User, customer_id: uuid.UUID, product_id: uuid.UUID):
    if await repositories.customer(db, actor.tenant_id, customer_id) is None:
        raise NotFound("Customer not found")
    row = await repositories.override(db, actor.tenant_id, customer_id, product_id)
    if row is not None:
        await db.delete(row)
        await audit(db, tenant_id=actor.tenant_id, actor_id=actor.id, actor_email=actor.email,
                    action="pricing.customer_price_remove", resource_type="customer", resource_id=str(customer_id),
                    meta={"product_id": str(product_id), "price": str(row.price)})
