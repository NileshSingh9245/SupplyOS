"""Inventory API routes."""
from __future__ import annotations

import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.enums import StockMovementType
from app.core.exceptions import NotFound
from app.features.inventory import service as inv_service
from app.infrastructure.db.models.inventory import InventoryItem, StockMovement
from app.infrastructure.db.models.product import Product
from app.infrastructure.db.models.warehouse import Warehouse
from app.shared.audit import audit
from app.shared.deps import get_current_user, require_admin_or_manager
from app.shared.schemas import ORMModel

router = APIRouter(prefix="/inventory", tags=["inventory"])


class InventoryRowOut(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID
    product_sku: str
    product_name: str
    warehouse_id: uuid.UUID
    warehouse_name: str
    rack_id: uuid.UUID | None
    shelf_id: uuid.UUID | None
    batch_id: uuid.UUID | None
    quantity: Decimal
    reserved_qty: Decimal
    available_qty: Decimal
    in_transit_qty: Decimal
    damaged_qty: Decimal
    low_stock: bool


class StockAdjustRequest(BaseModel):
    product_id: uuid.UUID
    warehouse_id: uuid.UUID
    rack_id: uuid.UUID | None = None
    shelf_id: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None
    delta_qty: Decimal = Field(description="Positive to add, negative to remove")
    note: str | None = None


class InventoryStats(BaseModel):
    total_products: int
    low_stock: int
    out_of_stock: int
    total_inventory_value: Decimal
    total_reserved: Decimal


@router.get("", response_model=list[InventoryRowOut])
async def list_inventory(
    product_id: uuid.UUID | None = None,
    warehouse_id: uuid.UUID | None = None,
    q: str | None = None,
    low_stock_only: bool = False,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    stmt = (
        select(InventoryItem, Product, Warehouse)
        .join(Product, Product.id == InventoryItem.product_id)
        .join(Warehouse, Warehouse.id == InventoryItem.warehouse_id)
        .where(InventoryItem.tenant_id == user.tenant_id)
    )
    if product_id:
        stmt = stmt.where(InventoryItem.product_id == product_id)
    if warehouse_id:
        stmt = stmt.where(InventoryItem.warehouse_id == warehouse_id)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(func.lower(Product.name).like(like) | func.lower(Product.sku).like(like))
    rows = (await db.execute(stmt.order_by(Product.name))).all()
    out: list[InventoryRowOut] = []
    for inv, prod, wh in rows:
        avail = inv.quantity - inv.reserved_qty
        low = avail <= Decimal(prod.low_stock_threshold)
        if low_stock_only and not low:
            continue
        out.append(InventoryRowOut(
            id=inv.id, product_id=prod.id, product_sku=prod.sku, product_name=prod.name,
            warehouse_id=wh.id, warehouse_name=wh.name,
            rack_id=inv.rack_id, shelf_id=inv.shelf_id, batch_id=inv.batch_id,
            quantity=inv.quantity, reserved_qty=inv.reserved_qty, available_qty=avail,
            in_transit_qty=inv.in_transit_qty, damaged_qty=inv.damaged_qty,
            low_stock=low,
        ))
    return out


@router.get("/stats", response_model=InventoryStats)
async def inventory_stats(db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    # totals
    tot_prod = (await db.execute(
        select(func.count()).select_from(Product).where(Product.tenant_id == user.tenant_id, Product.is_active == True)  # noqa
    )).scalar_one()
    reserved_total = (await db.execute(
        select(func.coalesce(func.sum(InventoryItem.reserved_qty), 0)).where(
            InventoryItem.tenant_id == user.tenant_id
        )
    )).scalar_one()
    # value = sum(quantity * base_price)
    val = (await db.execute(
        select(func.coalesce(func.sum(InventoryItem.quantity * Product.base_price), 0))
        .join(Product, Product.id == InventoryItem.product_id)
        .where(InventoryItem.tenant_id == user.tenant_id)
    )).scalar_one()

    # low stock / out of stock counts (per-product)
    per_product = (await db.execute(
        select(
            Product.id, Product.low_stock_threshold,
            func.coalesce(func.sum(InventoryItem.quantity - InventoryItem.reserved_qty), 0).label("avail"),
        )
        .join(InventoryItem, InventoryItem.product_id == Product.id, isouter=True)
        .where(Product.tenant_id == user.tenant_id, Product.is_active == True)  # noqa
        .group_by(Product.id, Product.low_stock_threshold)
    )).all()
    low = sum(1 for _, thr, av in per_product if Decimal(av) > 0 and Decimal(av) <= Decimal(thr))
    out = sum(1 for _, _, av in per_product if Decimal(av) <= 0)

    return InventoryStats(
        total_products=tot_prod,
        low_stock=low,
        out_of_stock=out,
        total_inventory_value=Decimal(str(val)),
        total_reserved=Decimal(str(reserved_total)),
    )


@router.post("/adjust", response_model=InventoryRowOut)
async def adjust(
    payload: StockAdjustRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_admin_or_manager),
):
    prod = (await db.execute(
        select(Product).where(Product.id == payload.product_id, Product.tenant_id == user.tenant_id)
    )).scalar_one_or_none()
    if not prod:
        raise NotFound("Product not found")
    wh = (await db.execute(
        select(Warehouse).where(Warehouse.id == payload.warehouse_id, Warehouse.tenant_id == user.tenant_id)
    )).scalar_one_or_none()
    if not wh:
        raise NotFound("Warehouse not found")

    row = await inv_service.adjust_stock(
        db,
        tenant_id=user.tenant_id, product_id=payload.product_id, warehouse_id=payload.warehouse_id,
        rack_id=payload.rack_id, shelf_id=payload.shelf_id, batch_id=payload.batch_id,
        delta_qty=payload.delta_qty, actor_id=user.id,
        movement_type=StockMovementType.INBOUND if payload.delta_qty > 0 else StockMovementType.ADJUSTMENT,
        note=payload.note,
    )
    await audit(
        db, tenant_id=user.tenant_id, actor_id=user.id, actor_email=user.email,
        action="inventory.adjust", resource_type="product", resource_id=str(payload.product_id),
        meta={"delta": str(payload.delta_qty), "warehouse_id": str(payload.warehouse_id)},
    )
    await db.commit()
    await db.refresh(row)
    avail = row.quantity - row.reserved_qty
    return InventoryRowOut(
        id=row.id, product_id=prod.id, product_sku=prod.sku, product_name=prod.name,
        warehouse_id=wh.id, warehouse_name=wh.name,
        rack_id=row.rack_id, shelf_id=row.shelf_id, batch_id=row.batch_id,
        quantity=row.quantity, reserved_qty=row.reserved_qty, available_qty=avail,
        in_transit_qty=row.in_transit_qty, damaged_qty=row.damaged_qty,
        low_stock=avail <= Decimal(prod.low_stock_threshold),
    )


class MovementOut(ORMModel):
    id: uuid.UUID
    product_id: uuid.UUID
    warehouse_id: uuid.UUID
    movement_type: str
    quantity: Decimal
    reference_type: str | None
    reference_id: uuid.UUID | None
    note: str | None
    created_at: object  # datetime


@router.get("/movements", response_model=list[MovementOut])
async def list_movements(
    product_id: uuid.UUID | None = None,
    limit: int = Query(50, le=200),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    stmt = select(StockMovement).where(StockMovement.tenant_id == user.tenant_id)
    if product_id:
        stmt = stmt.where(StockMovement.product_id == product_id)
    stmt = stmt.order_by(StockMovement.created_at.desc()).limit(limit)
    return (await db.execute(stmt)).scalars().all()
