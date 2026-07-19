"""Product, Category, Batch, Barcode."""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import String, Boolean, Numeric, ForeignKey, Index, Integer, Date, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, TimestampMixin, UUIDPKMixin


class Category(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "categories"
    __table_args__ = (Index("ix_categories_tenant_name", "tenant_id", "name", unique=True),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("categories.id", ondelete="SET NULL")
    )


class Product(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "products"
    __table_args__ = (
        Index("ix_products_tenant_sku", "tenant_id", "sku", unique=True),
        Index("ix_products_barcode", "barcode"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    sku: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    barcode: Mapped[str | None] = mapped_column(String(64))
    hsn_code: Mapped[str | None] = mapped_column(String(20))
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("categories.id", ondelete="SET NULL")
    )
    unit: Mapped[str] = mapped_column(String(20), nullable=False, default="pcs")  # kg, ltr, pcs
    pack_size: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=Decimal("1"), nullable=False)

    base_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=Decimal("0"))
    mrp: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    gst_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0"), nullable=False)

    reorder_level: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    low_stock_threshold: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    image_url: Mapped[str | None] = mapped_column(String(500))


class Batch(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "batches"
    __table_args__ = (Index("ix_batches_product_code", "product_id", "batch_code", unique=True),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    batch_code: Mapped[str] = mapped_column(String(64), nullable=False)
    manufacture_date: Mapped[date | None] = mapped_column(Date)
    expiry_date: Mapped[date | None] = mapped_column(Date)
    supplier: Mapped[str | None] = mapped_column(String(200))
    purchase_cost: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
