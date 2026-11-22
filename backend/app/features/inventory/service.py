"""Inventory service: stock adjustments, transfers, movements, reservation primitives.

The reservation logic uses `SELECT ... FOR UPDATE` on inventory rows to prevent
race conditions (two customers cannot claim the same physical stock).
"""
from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert

from app.core.enums import StockMovementType
from app.core.exceptions import Conflict, DomainError, InsufficientStock, NotFound
from app.infrastructure.db.models.inventory import InventoryItem, StockMovement
from app.infrastructure.db.models.product import Batch, Product
from app.infrastructure.db.models.warehouse import Rack, Shelf, Warehouse


async def get_or_create_inventory_row(
    db: AsyncSession, *, tenant_id: uuid.UUID, product_id: uuid.UUID,
    warehouse_id: uuid.UUID, rack_id: uuid.UUID | None = None,
    shelf_id: uuid.UUID | None = None, batch_id: uuid.UUID | None = None,
) -> InventoryItem:
    product = (await db.execute(select(Product.id).where(
        Product.id == product_id, Product.tenant_id == tenant_id, Product.is_active.is_(True),
    ))).scalar_one_or_none()
    warehouse = (await db.execute(select(Warehouse.id).where(
        Warehouse.id == warehouse_id, Warehouse.tenant_id == tenant_id, Warehouse.is_active.is_(True),
    ))).scalar_one_or_none()
    if product is None or warehouse is None:
        raise NotFound("Active product or warehouse not found")
    if rack_id is not None:
        rack = (await db.execute(select(Rack.id).where(
            Rack.id == rack_id, Rack.tenant_id == tenant_id, Rack.warehouse_id == warehouse_id,
        ))).scalar_one_or_none()
        if rack is None:
            raise NotFound("Rack not found in this warehouse")
    if shelf_id is not None:
        if rack_id is None:
            raise DomainError("shelf_id requires its parent rack_id")
        shelf = (await db.execute(select(Shelf.id).where(
            Shelf.id == shelf_id, Shelf.tenant_id == tenant_id,
            Shelf.warehouse_id == warehouse_id, Shelf.rack_id == rack_id,
        ))).scalar_one_or_none()
        if shelf is None:
            raise NotFound("Shelf not found in this rack and warehouse")
    if batch_id is not None:
        batch = (await db.execute(select(Batch.id).where(
            Batch.id == batch_id, Batch.tenant_id == tenant_id, Batch.product_id == product_id,
        ))).scalar_one_or_none()
        if batch is None:
            raise NotFound("Batch not found for this product")
    stmt = select(InventoryItem).where(
        InventoryItem.tenant_id == tenant_id,
        InventoryItem.product_id == product_id,
        InventoryItem.warehouse_id == warehouse_id,
        InventoryItem.rack_id.is_(rack_id) if rack_id is None else InventoryItem.rack_id == rack_id,
        InventoryItem.shelf_id.is_(shelf_id) if shelf_id is None else InventoryItem.shelf_id == shelf_id,
        InventoryItem.batch_id.is_(batch_id) if batch_id is None else InventoryItem.batch_id == batch_id,
    ).with_for_update()
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing:
        return existing
    await db.execute(insert(InventoryItem).values(
        tenant_id=tenant_id, product_id=product_id, warehouse_id=warehouse_id,
        rack_id=rack_id, shelf_id=shelf_id, batch_id=batch_id,
    ).on_conflict_do_nothing(index_elements=[
        InventoryItem.tenant_id, InventoryItem.product_id, InventoryItem.warehouse_id,
        InventoryItem.rack_id, InventoryItem.shelf_id, InventoryItem.batch_id,
    ]))
    return (await db.execute(stmt)).scalar_one()


async def adjust_stock(
    db: AsyncSession, *, tenant_id: uuid.UUID, product_id: uuid.UUID,
    warehouse_id: uuid.UUID, delta_qty: Decimal, actor_id: uuid.UUID | None,
    rack_id: uuid.UUID | None = None, shelf_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None, movement_type: StockMovementType = StockMovementType.ADJUSTMENT,
    reference_type: str | None = None, reference_id: uuid.UUID | None = None,
    note: str | None = None,
) -> InventoryItem:
    row = await get_or_create_inventory_row(
        db, tenant_id=tenant_id, product_id=product_id, warehouse_id=warehouse_id,
        rack_id=rack_id, shelf_id=shelf_id, batch_id=batch_id,
    )
    new_qty = row.quantity + delta_qty
    if new_qty < 0:
        raise InsufficientStock()
    if new_qty < row.reserved_qty:
        raise InsufficientStock("Would drop below reserved quantity")
    row.quantity = new_qty
    mv = StockMovement(
        tenant_id=tenant_id, product_id=product_id, warehouse_id=warehouse_id,
        inventory_item_id=row.id, movement_type=movement_type.value,
        quantity=delta_qty, reference_type=reference_type, reference_id=reference_id,
        actor_id=actor_id, note=note,
    )
    db.add(mv)
    return row


async def available_qty(
    db: AsyncSession, *, tenant_id: uuid.UUID, product_id: uuid.UUID,
    warehouse_id: uuid.UUID | None = None,
) -> Decimal:
    stmt = select(
        func.coalesce(func.sum(InventoryItem.quantity - InventoryItem.reserved_qty), 0)
    ).where(
        InventoryItem.tenant_id == tenant_id,
        InventoryItem.product_id == product_id,
    )
    if warehouse_id:
        stmt = stmt.where(InventoryItem.warehouse_id == warehouse_id)
    result = await db.execute(stmt)
    return Decimal(str(result.scalar_one()))


async def reserve_stock(
    db: AsyncSession, *, tenant_id: uuid.UUID, product_id: uuid.UUID,
    warehouse_id: uuid.UUID, qty_needed: Decimal,
) -> list[tuple[InventoryItem, Decimal]]:
    """Lock rows for update, allocate qty_needed across them (FIFO by created_at).

    Returns list of (row, allocated_qty). Raises InsufficientStock if not enough.
    Caller is responsible for creating OrderReservation records and committing.
    """
    if qty_needed <= 0:
        raise DomainError("Reservation quantity must be positive")
    stmt = (
        select(InventoryItem)
        .where(
            InventoryItem.tenant_id == tenant_id,
            InventoryItem.product_id == product_id,
            InventoryItem.warehouse_id == warehouse_id,
            (InventoryItem.quantity - InventoryItem.reserved_qty) > 0,
        )
        .order_by(InventoryItem.id.asc())
        .with_for_update()
    )
    rows = (await db.execute(stmt)).scalars().all()
    # Locks use canonical IDs; FIFO is an allocation policy, not a lock order.
    rows = sorted(rows, key=lambda row: (row.created_at, row.id))
    allocations: list[tuple[InventoryItem, Decimal]] = []
    remaining = qty_needed
    for row in rows:
        avail = row.quantity - row.reserved_qty
        if avail <= 0:
            continue
        take = min(avail, remaining)
        row.reserved_qty = row.reserved_qty + take
        allocations.append((row, take))
        remaining -= take
        if remaining <= 0:
            break
    if remaining > 0:
        raise InsufficientStock(
            f"Only {(qty_needed - remaining)} of {qty_needed} available"
        )
    return allocations


async def release_reservation(
    db: AsyncSession, *, inventory_item_id: uuid.UUID, qty: Decimal, tenant_id: uuid.UUID,
) -> None:
    row = (await db.execute(
        select(InventoryItem).where(
            InventoryItem.id == inventory_item_id, InventoryItem.tenant_id == tenant_id,
        ).with_for_update()
    )).scalar_one_or_none()
    if not row:
        raise NotFound("Inventory row not found")
    if qty <= 0 or qty > row.reserved_qty:
        raise Conflict("Reservation release does not match reserved stock")
    row.reserved_qty -= qty


async def consume_reservation(
    db: AsyncSession, *, inventory_item_id: uuid.UUID, qty: Decimal,
    tenant_id: uuid.UUID, product_id: uuid.UUID, warehouse_id: uuid.UUID,
    reference_type: str | None, reference_id: uuid.UUID | None,
    actor_id: uuid.UUID | None,
) -> None:
    """On DELIVERED — reduce both quantity and reserved_qty."""
    row = (await db.execute(
        select(InventoryItem).where(
            InventoryItem.id == inventory_item_id, InventoryItem.tenant_id == tenant_id,
            InventoryItem.product_id == product_id, InventoryItem.warehouse_id == warehouse_id,
        ).with_for_update()
    )).scalar_one_or_none()
    if not row:
        raise NotFound("Inventory row not found")
    if qty <= 0 or row.reserved_qty < qty or row.quantity < qty:
        raise InsufficientStock("Reservation inconsistent")
    row.reserved_qty -= qty
    row.quantity -= qty
    mv = StockMovement(
        tenant_id=tenant_id, product_id=product_id, warehouse_id=warehouse_id,
        inventory_item_id=row.id, movement_type=StockMovementType.OUTBOUND.value,
        quantity=-qty, reference_type=reference_type, reference_id=reference_id,
        actor_id=actor_id, note="Delivered",
    )
    db.add(mv)
