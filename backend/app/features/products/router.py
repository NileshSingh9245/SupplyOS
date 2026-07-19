"""Products & categories CRUD."""
from __future__ import annotations

import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, or_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import Conflict, NotFound
from app.infrastructure.db.models.product import Category, Product
from app.shared.deps import get_current_user, require_admin_or_manager
from app.shared.schemas import ORMModel, Paginated

router = APIRouter(prefix="/products", tags=["products"])


class CategoryOut(ORMModel):
    id: uuid.UUID
    name: str
    parent_id: uuid.UUID | None


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    parent_id: uuid.UUID | None = None


class ProductOut(ORMModel):
    id: uuid.UUID
    sku: str
    name: str
    description: str | None
    barcode: str | None
    hsn_code: str | None
    category_id: uuid.UUID | None
    unit: str
    pack_size: Decimal
    base_price: Decimal
    mrp: Decimal | None
    gst_rate: Decimal
    reorder_level: int
    low_stock_threshold: int
    is_active: bool
    image_url: str | None


class ProductCreate(BaseModel):
    sku: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    barcode: str | None = None
    hsn_code: str | None = None
    category_id: uuid.UUID | None = None
    unit: str = "pcs"
    pack_size: Decimal = Decimal("1")
    base_price: Decimal
    mrp: Decimal | None = None
    gst_rate: Decimal = Decimal("0")
    reorder_level: int = 0
    low_stock_threshold: int = 10
    image_url: str | None = None


class ProductUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    barcode: str | None = None
    hsn_code: str | None = None
    category_id: uuid.UUID | None = None
    unit: str | None = None
    pack_size: Decimal | None = None
    base_price: Decimal | None = None
    mrp: Decimal | None = None
    gst_rate: Decimal | None = None
    reorder_level: int | None = None
    low_stock_threshold: int | None = None
    is_active: bool | None = None
    image_url: str | None = None


# Categories
@router.get("/categories", response_model=list[CategoryOut])
async def list_categories(db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    return (await db.execute(
        select(Category).where(Category.tenant_id == user.tenant_id).order_by(Category.name)
    )).scalars().all()


@router.post("/categories", response_model=CategoryOut, status_code=201)
async def create_category(
    payload: CategoryCreate, db: AsyncSession = Depends(get_db),
    user=Depends(require_admin_or_manager),
):
    dup = await db.execute(
        select(Category).where(Category.tenant_id == user.tenant_id, Category.name == payload.name)
    )
    if dup.scalar_one_or_none():
        raise Conflict("Category name already exists")
    cat = Category(tenant_id=user.tenant_id, **payload.model_dump())
    db.add(cat)
    await db.commit()
    await db.refresh(cat)
    return cat


# Products
@router.get("", response_model=Paginated[ProductOut])
async def list_products(
    q: str | None = None,
    category_id: uuid.UUID | None = None,
    active_only: bool = True,
    page: int = 1,
    page_size: int = 50,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    stmt = select(Product).where(Product.tenant_id == user.tenant_id)
    if active_only:
        stmt = stmt.where(Product.is_active == True)  # noqa
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(
            func.lower(Product.name).like(like),
            func.lower(Product.sku).like(like),
            func.coalesce(Product.barcode, "").like(like),
        ))
    if category_id:
        stmt = stmt.where(Product.category_id == category_id)
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (await db.execute(
        stmt.order_by(Product.name).offset((page - 1) * page_size).limit(page_size)
    )).scalars().all()
    return Paginated(items=rows, total=total, page=page, page_size=page_size)


@router.post("", response_model=ProductOut, status_code=201)
async def create_product(
    payload: ProductCreate, db: AsyncSession = Depends(get_db),
    user=Depends(require_admin_or_manager),
):
    dup = await db.execute(
        select(Product).where(Product.tenant_id == user.tenant_id, Product.sku == payload.sku)
    )
    if dup.scalar_one_or_none():
        raise Conflict("SKU already exists")
    p = Product(tenant_id=user.tenant_id, **payload.model_dump())
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return p


@router.get("/{product_id}", response_model=ProductOut)
async def get_product(
    product_id: uuid.UUID, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)
):
    p = (await db.execute(
        select(Product).where(Product.id == product_id, Product.tenant_id == user.tenant_id)
    )).scalar_one_or_none()
    if not p:
        raise NotFound("Product not found")
    return p


@router.patch("/{product_id}", response_model=ProductOut)
async def update_product(
    product_id: uuid.UUID, payload: ProductUpdate,
    db: AsyncSession = Depends(get_db), user=Depends(require_admin_or_manager),
):
    p = (await db.execute(
        select(Product).where(Product.id == product_id, Product.tenant_id == user.tenant_id)
    )).scalar_one_or_none()
    if not p:
        raise NotFound("Product not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(p, k, v)
    await db.commit()
    await db.refresh(p)
    return p
