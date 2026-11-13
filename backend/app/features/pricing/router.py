"""Pricing tiers CRUD + resolve-price convenience endpoint."""
from __future__ import annotations

import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.enums import Role
from app.core.exceptions import DomainError, Forbidden, NotFound
from app.features.pricing import repositories, service
from app.features.pricing.schemas import CatalogProduct, TierCreate, TierOut, TierUpdate
from app.shared.deps import get_current_user, lock_current_user, require_admin_or_manager, require_roles, require_staff
from app.shared.private_route import PrivateInputRoute
from app.shared.schemas import Paginated

router = APIRouter(prefix="/pricing", tags=["pricing"], route_class=PrivateInputRoute)
catalog_router = APIRouter(prefix="/catalog", tags=["customer-catalog"], route_class=PrivateInputRoute)
require_price_reader = require_roles(
    Role.SUPER_ADMIN, Role.WAREHOUSE_MANAGER, Role.ACCOUNTANT, Role.CUSTOMER,
)


class PriceResolveResponse(BaseModel):
    customer_id: uuid.UUID
    product_id: uuid.UUID
    price: Decimal


@router.get("/tiers", response_model=list[TierOut])
async def list_tiers(db: AsyncSession = Depends(get_db), user=Depends(require_staff)):
    return await repositories.tiers(db, user.tenant_id)


@router.post("/tiers", response_model=TierOut, status_code=201)
async def create_tier(
    payload: TierCreate, request: Request, db: AsyncSession = Depends(get_db),
    user=Depends(require_admin_or_manager),
):
    actor = await lock_current_user(request, db)
    t = await service.create_tier(db, actor, payload)
    await db.flush()
    await get_current_user(request, db)
    await db.commit()
    return t


@router.patch("/tiers/{tier_id}", response_model=TierOut)
async def update_tier(tier_id: uuid.UUID, payload: TierUpdate, request: Request,
                      db: AsyncSession = Depends(get_db), user=Depends(require_admin_or_manager)):
    actor = await lock_current_user(request, db)
    tier = await service.update_tier(db, actor, tier_id, payload)
    await db.flush()
    await get_current_user(request, db)
    await db.commit()
    return tier


@router.get("/resolve", response_model=PriceResolveResponse)
async def resolve(
    customer_id: uuid.UUID, product_id: uuid.UUID,
    db: AsyncSession = Depends(get_db), user=Depends(require_price_reader),
):
    if user.role == Role.CUSTOMER.value and customer_id != user.customer_id:
        raise NotFound("Customer not found")
    price = await service.resolve_price(
        db, tenant_id=user.tenant_id, customer_id=customer_id, product_id=product_id
    )
    return PriceResolveResponse(customer_id=customer_id, product_id=product_id, price=price)


@catalog_router.get("", response_model=Paginated[CatalogProduct])
async def customer_catalog(
    request: Request, q: str | None = Query(None, max_length=100),
    page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db), user=Depends(require_roles(Role.CUSTOMER)),
):
    allowed = {"q", "page", "page_size"}
    if set(request.query_params) - allowed or any(len(request.query_params.getlist(key)) > 1 for key in allowed):
        raise DomainError("Unsupported catalog query parameters", code=422)
    if user.customer_id is None:
        raise Forbidden("No customer profile linked")
    result = await service.catalog(db, tenant_id=user.tenant_id, customer_id=user.customer_id,
                                   q=q, page=page, page_size=page_size)
    await get_current_user(request, db)
    return result
