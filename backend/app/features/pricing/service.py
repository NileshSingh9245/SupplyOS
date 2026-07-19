"""Pricing engine — resolves the price for (customer, product) using:
1. Explicit customer override (`customer_prices`).
2. Tier discount (`price_tiers`) applied to product.base_price.
3. Fallback to `product.base_price`.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models.customer import Customer, CustomerPrice, PriceTier
from app.infrastructure.db.models.product import Product


async def resolve_price(
    db: AsyncSession, *, tenant_id: uuid.UUID, customer_id: uuid.UUID,
    product_id: uuid.UUID,
) -> Decimal:
    override = (await db.execute(
        select(CustomerPrice.price).where(
            CustomerPrice.tenant_id == tenant_id,
            CustomerPrice.customer_id == customer_id,
            CustomerPrice.product_id == product_id,
        )
    )).scalar_one_or_none()
    if override is not None:
        return Decimal(str(override))

    customer = (await db.execute(
        select(Customer).where(Customer.id == customer_id, Customer.tenant_id == tenant_id)
    )).scalar_one_or_none()
    product = (await db.execute(
        select(Product).where(Product.id == product_id, Product.tenant_id == tenant_id)
    )).scalar_one_or_none()
    if not product:
        raise ValueError(f"Product {product_id} not found")

    base = Decimal(str(product.base_price))
    if customer and customer.price_tier:
        tier = (await db.execute(
            select(PriceTier).where(
                PriceTier.tenant_id == tenant_id, PriceTier.name == customer.price_tier
            )
        )).scalar_one_or_none()
        if tier and tier.discount_pct:
            discount = Decimal(str(tier.discount_pct)) / Decimal("100")
            return (base * (Decimal("1") - discount)).quantize(Decimal("0.01"))
    return base
