"""Tenant-scoped lookups; a product-price batch shares one PostgreSQL snapshot."""
from __future__ import annotations

import uuid
from collections.abc import Collection
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models.customer import Customer, CustomerPrice, PriceTier
from app.infrastructure.db.models.product import Product
from app.infrastructure.db.models.tenant import Tenant


@dataclass(frozen=True)
class PriceRow:
    id: uuid.UUID
    sku: str
    name: str
    unit: str
    base_price: Decimal
    gst_rate: Decimal
    override_price: Decimal | None
    discount_pct: Decimal | None


def _products(tenant_id: uuid.UUID, q: str | None = None):
    query = select(Product.id).where(Product.tenant_id == tenant_id, Product.is_active.is_(True))
    if q:
        like = f"%{q.lower()}%"
        query = query.where(or_(func.lower(Product.name).like(like), func.lower(Product.sku).like(like)))
    return query


async def priced_rows(
    db: AsyncSession, *, tenant_id: uuid.UUID, customer_id: uuid.UUID,
    product_ids: Collection[uuid.UUID] | None = None, q: str | None = None,
    offset: int = 0, limit: int = 200,
) -> list[PriceRow]:
    query = select(
        Product.id, Product.sku, Product.name, Product.unit, Product.base_price, Product.gst_rate,
        CustomerPrice.price, PriceTier.discount_pct,
    ).select_from(Product).join(Customer,
        (Customer.id == customer_id) & (Customer.tenant_id == tenant_id) & Customer.is_active.is_(True),
    ).outerjoin(CustomerPrice,
        (CustomerPrice.tenant_id == tenant_id) & (CustomerPrice.customer_id == customer_id)
        & (CustomerPrice.product_id == Product.id),
    ).outerjoin(PriceTier, (PriceTier.tenant_id == tenant_id) & (PriceTier.name == Customer.price_tier))
    query = query.where(Product.id.in_(_products(tenant_id, q)))
    if product_ids is not None:
        query = query.where(Product.id.in_(product_ids))
    rows = (await db.execute(query.order_by(Product.name, Product.id).offset(offset).limit(limit))).all()
    return [PriceRow(*row) for row in rows]


async def product_count(db: AsyncSession, tenant_id: uuid.UUID, q: str | None) -> int:
    return await db.scalar(select(func.count()).select_from(_products(tenant_id, q).subquery()))


async def active_customer(db: AsyncSession, tenant_id: uuid.UUID, customer_id: uuid.UUID) -> bool:
    # Preserve eligibility through catalog authorization without blocking other readers.
    return await db.scalar(select(Customer.id).where(
        Customer.id == customer_id, Customer.tenant_id == tenant_id, Customer.is_active.is_(True),
    ).with_for_update(read=True)) is not None


async def currency(db: AsyncSession, tenant_id: uuid.UUID) -> str | None:
    return await db.scalar(select(Tenant.currency).where(Tenant.id == tenant_id).with_for_update(read=True))


async def tiers(db: AsyncSession, tenant_id: uuid.UUID) -> list[PriceTier]:
    return list((await db.scalars(select(PriceTier).where(
        PriceTier.tenant_id == tenant_id,
    ).order_by(PriceTier.name, PriceTier.id))).all())


async def tier(db: AsyncSession, tenant_id: uuid.UUID, tier_id: uuid.UUID, *, lock=False) -> PriceTier | None:
    query = select(PriceTier).where(PriceTier.id == tier_id, PriceTier.tenant_id == tenant_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    return await db.scalar(query)


async def customer(db: AsyncSession, tenant_id: uuid.UUID, customer_id: uuid.UUID) -> Customer | None:
    return await db.scalar(select(Customer).where(
        Customer.id == customer_id, Customer.tenant_id == tenant_id,
    ).with_for_update().execution_options(populate_existing=True))


async def override(db: AsyncSession, tenant_id: uuid.UUID, customer_id: uuid.UUID, product_id: uuid.UUID):
    return await db.scalar(select(CustomerPrice).where(
        CustomerPrice.tenant_id == tenant_id, CustomerPrice.customer_id == customer_id,
        CustomerPrice.product_id == product_id,
    ).with_for_update().execution_options(populate_existing=True))
