"""InventoryItem — the critical stock table with row-locking support.

Uniqueness: one row per (tenant, product, warehouse, rack, shelf, batch).
Every quantity change goes through StockMovement for audit.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import Numeric, ForeignKey, Index, String, CheckConstraint, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, TimestampMixin, UUIDPKMixin


class InventoryItem(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "inventory_items"
    __table_args__ = (
        Index(
            "ix_inv_unique_location",
            "tenant_id", "product_id", "warehouse_id", "rack_id", "shelf_id", "batch_id",
            unique=True,
        ),
        Index("ix_inv_tenant_product", "tenant_id", "product_id"),
        Index("ix_inv_tenant_warehouse", "tenant_id", "warehouse_id"),
        CheckConstraint("quantity >= 0", name="quantity_nonneg"),
        CheckConstraint("reserved_qty >= 0", name="reserved_nonneg"),
        CheckConstraint("reserved_qty <= quantity", name="reserved_le_quantity"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=False
    )
    rack_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("racks.id", ondelete="SET NULL")
    )
    shelf_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shelves.id", ondelete="SET NULL")
    )
    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("batches.id", ondelete="SET NULL")
    )

    quantity: Mapped[Decimal] = mapped_column(Numeric(16, 3), default=Decimal("0"), nullable=False)
    reserved_qty: Mapped[Decimal] = mapped_column(Numeric(16, 3), default=Decimal("0"), nullable=False)
    in_transit_qty: Mapped[Decimal] = mapped_column(Numeric(16, 3), default=Decimal("0"), nullable=False)
    damaged_qty: Mapped[Decimal] = mapped_column(Numeric(16, 3), default=Decimal("0"), nullable=False)


class StockMovement(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "stock_movements"
    __table_args__ = (
        Index("ix_stock_mov_tenant_created", "tenant_id", "created_at"),
        Index("ix_stock_mov_product", "product_id"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    warehouse_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    inventory_item_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    movement_type: Mapped[str] = mapped_column(String(30), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(16, 3), nullable=False)
    reference_type: Mapped[str | None] = mapped_column(String(30))  # order/transfer/adjustment
    reference_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    note: Mapped[str | None] = mapped_column(String(500))
    meta: Mapped[dict | None] = mapped_column(JSON, default=dict)
