"""Pricing tiers CRUD + resolve-price convenience endpoint."""
from __future__ import annotations

import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import Conflict, NotFound
from app.features.pricing.service import resolve_price
from app.infrastructure.db.models.customer import PriceTier
from app.shared.deps import get_current_user, require_admin_or_manager
from app.shared.schemas import ORMModel

router = APIRouter(prefix="/pricing", tags=["pricing"])


class TierOut(ORMModel):
    id: uuid.UUID
    name: str
    discount_pct: Decimal


class TierCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    discount_pct: Decimal = Field(ge=0, le=100)


class PriceResolveResponse(BaseModel):
    customer_id: uuid.UUID
    product_id: uuid.UUID
    price: Decimal


@router.get("/tiers", response_model=list[TierOut])
async def list_tiers(db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    return (await db.execute(
        select(PriceTier).where(PriceTier.tenant_id == user.tenant_id).order_by(PriceTier.name)
    )).scalars().all()


@router.post("/tiers", response_model=TierOut, status_code=201)
async def create_tier(
    payload: TierCreate, db: AsyncSession = Depends(get_db),
    user=Depends(require_admin_or_manager),
):
    dup = await db.execute(
        select(PriceTier).where(PriceTier.tenant_id == user.tenant_id, PriceTier.name == payload.name)
    )
    if dup.scalar_one_or_none():
        raise Conflict("Tier name already exists")
    t = PriceTier(tenant_id=user.tenant_id, **payload.model_dump())
    db.add(t)
    await db.commit()
    await db.refresh(t)
    return t


@router.get("/resolve", response_model=PriceResolveResponse)
async def resolve(
    customer_id: uuid.UUID, product_id: uuid.UUID,
    db: AsyncSession = Depends(get_db), user=Depends(get_current_user),
):
    price = await resolve_price(
        db, tenant_id=user.tenant_id, customer_id=customer_id, product_id=product_id
    )
    return PriceResolveResponse(customer_id=customer_id, product_id=product_id, price=price)
