"""Warehouses / racks / shelves CRUD."""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import Conflict, NotFound
from app.infrastructure.db.models.warehouse import Warehouse, Rack, Shelf
from app.shared.deps import get_current_user, require_admin_or_manager
from app.shared.schemas import ORMModel

router = APIRouter(prefix="/warehouses", tags=["warehouses"])


class WarehouseOut(ORMModel):
    id: uuid.UUID
    code: str
    name: str
    address: str | None
    city: str | None
    state: str | None
    pincode: str | None
    is_active: bool


class WarehouseCreate(BaseModel):
    code: str = Field(min_length=1, max_length=30)
    name: str = Field(min_length=1, max_length=200)
    address: str | None = None
    city: str | None = None
    state: str | None = None
    pincode: str | None = None


class RackOut(ORMModel):
    id: uuid.UUID
    warehouse_id: uuid.UUID
    code: str
    label: str


class RackCreate(BaseModel):
    warehouse_id: uuid.UUID
    code: str = Field(min_length=1, max_length=30)
    label: str = Field(min_length=1, max_length=120)


class ShelfOut(ORMModel):
    id: uuid.UUID
    warehouse_id: uuid.UUID
    rack_id: uuid.UUID
    code: str
    label: str


class ShelfCreate(BaseModel):
    rack_id: uuid.UUID
    code: str = Field(min_length=1, max_length=30)
    label: str = Field(min_length=1, max_length=120)


@router.get("", response_model=list[WarehouseOut])
async def list_warehouses(db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    rows = (await db.execute(
        select(Warehouse).where(Warehouse.tenant_id == user.tenant_id).order_by(Warehouse.name)
    )).scalars().all()
    return rows


@router.post("", response_model=WarehouseOut, status_code=201)
async def create_warehouse(
    payload: WarehouseCreate,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_admin_or_manager),
):
    dup = await db.execute(
        select(Warehouse).where(Warehouse.tenant_id == user.tenant_id, Warehouse.code == payload.code)
    )
    if dup.scalar_one_or_none():
        raise Conflict("Warehouse code already exists")
    wh = Warehouse(tenant_id=user.tenant_id, **payload.model_dump())
    db.add(wh)
    await db.commit()
    await db.refresh(wh)
    return wh


@router.get("/{warehouse_id}/racks", response_model=list[RackOut])
async def list_racks(warehouse_id: uuid.UUID, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    rows = (await db.execute(
        select(Rack).where(Rack.tenant_id == user.tenant_id, Rack.warehouse_id == warehouse_id)
        .order_by(Rack.code)
    )).scalars().all()
    return rows


@router.post("/racks", response_model=RackOut, status_code=201)
async def create_rack(
    payload: RackCreate,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_admin_or_manager),
):
    wh = (await db.execute(
        select(Warehouse).where(Warehouse.id == payload.warehouse_id, Warehouse.tenant_id == user.tenant_id)
    )).scalar_one_or_none()
    if not wh:
        raise NotFound("Warehouse not found")
    rack = Rack(
        tenant_id=user.tenant_id,
        warehouse_id=payload.warehouse_id,
        code=payload.code,
        label=payload.label,
    )
    db.add(rack)
    await db.commit()
    await db.refresh(rack)
    return rack


@router.get("/racks/{rack_id}/shelves", response_model=list[ShelfOut])
async def list_shelves(rack_id: uuid.UUID, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    rows = (await db.execute(
        select(Shelf).where(Shelf.tenant_id == user.tenant_id, Shelf.rack_id == rack_id).order_by(Shelf.code)
    )).scalars().all()
    return rows


@router.post("/shelves", response_model=ShelfOut, status_code=201)
async def create_shelf(
    payload: ShelfCreate,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_admin_or_manager),
):
    rack = (await db.execute(
        select(Rack).where(Rack.id == payload.rack_id, Rack.tenant_id == user.tenant_id)
    )).scalar_one_or_none()
    if not rack:
        raise NotFound("Rack not found")
    shelf = Shelf(
        tenant_id=user.tenant_id, warehouse_id=rack.warehouse_id, rack_id=rack.id,
        code=payload.code, label=payload.label,
    )
    db.add(shelf)
    await db.commit()
    await db.refresh(shelf)
    return shelf
