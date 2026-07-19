"""Customer CRUD + credit info + per-customer pricing."""
from __future__ import annotations

import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select, or_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.enums import CustomerType
from app.core.exceptions import Conflict, NotFound
from app.infrastructure.db.models.customer import Customer, CustomerPrice, LedgerEntry
from app.shared.deps import get_current_user, require_admin_or_manager, require_staff
from app.shared.schemas import ORMModel, Paginated

router = APIRouter(prefix="/customers", tags=["customers"])


class CustomerOut(ORMModel):
    id: uuid.UUID
    code: str
    name: str
    business_name: str | None
    gstin: str | None
    phone: str | None
    email: str | None
    address: str | None
    city: str | None
    state: str | None
    pincode: str | None
    customer_type: str
    credit_limit: Decimal
    outstanding: Decimal
    price_tier: str | None
    is_active: bool


class CustomerCreate(BaseModel):
    code: str | None = None
    name: str = Field(min_length=1, max_length=200)
    business_name: str | None = None
    gstin: str | None = None
    phone: str | None = None
    email: EmailStr | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    pincode: str | None = None
    customer_type: CustomerType = CustomerType.CASH
    credit_limit: Decimal = Decimal("0")
    price_tier: str | None = None


class CustomerUpdate(BaseModel):
    name: str | None = None
    business_name: str | None = None
    gstin: str | None = None
    phone: str | None = None
    email: EmailStr | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    pincode: str | None = None
    customer_type: CustomerType | None = None
    credit_limit: Decimal | None = None
    price_tier: str | None = None
    is_active: bool | None = None


class CustomerPriceOut(ORMModel):
    id: uuid.UUID
    customer_id: uuid.UUID
    product_id: uuid.UUID
    price: Decimal


class CustomerPriceUpsert(BaseModel):
    product_id: uuid.UUID
    price: Decimal


class LedgerEntryOut(ORMModel):
    id: uuid.UUID
    debit: Decimal
    credit: Decimal
    balance_after: Decimal
    reference_type: str | None
    reference_id: uuid.UUID | None
    note: str | None
    created_at: object


def _next_code() -> str:
    import secrets
    return f"CUS-{secrets.token_hex(3).upper()}"


@router.get("", response_model=Paginated[CustomerOut])
async def list_customers(
    q: str | None = None,
    customer_type: CustomerType | None = None,
    page: int = 1,
    page_size: int = 50,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    stmt = select(Customer).where(Customer.tenant_id == user.tenant_id)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(
            func.lower(Customer.name).like(like),
            func.lower(Customer.code).like(like),
            func.coalesce(Customer.phone, "").like(like),
            func.lower(func.coalesce(Customer.business_name, "")).like(like),
        ))
    if customer_type:
        stmt = stmt.where(Customer.customer_type == customer_type.value)
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (await db.execute(
        stmt.order_by(Customer.name).offset((page - 1) * page_size).limit(page_size)
    )).scalars().all()
    return Paginated(items=rows, total=total, page=page, page_size=page_size)


@router.post("", response_model=CustomerOut, status_code=201)
async def create_customer(
    payload: CustomerCreate, db: AsyncSession = Depends(get_db),
    user=Depends(require_admin_or_manager),
):
    code = payload.code or _next_code()
    dup = await db.execute(
        select(Customer).where(Customer.tenant_id == user.tenant_id, Customer.code == code)
    )
    if dup.scalar_one_or_none():
        raise Conflict("Customer code already exists")
    c = Customer(
        tenant_id=user.tenant_id, code=code,
        **payload.model_dump(exclude={"code", "customer_type"}),
        customer_type=payload.customer_type.value,
    )
    db.add(c)
    await db.commit()
    await db.refresh(c)
    return c


@router.get("/{customer_id}", response_model=CustomerOut)
async def get_customer(customer_id: uuid.UUID, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    c = (await db.execute(
        select(Customer).where(Customer.id == customer_id, Customer.tenant_id == user.tenant_id)
    )).scalar_one_or_none()
    if not c:
        raise NotFound("Customer not found")
    return c


@router.patch("/{customer_id}", response_model=CustomerOut)
async def update_customer(
    customer_id: uuid.UUID, payload: CustomerUpdate,
    db: AsyncSession = Depends(get_db), user=Depends(require_admin_or_manager),
):
    c = (await db.execute(
        select(Customer).where(Customer.id == customer_id, Customer.tenant_id == user.tenant_id)
    )).scalar_one_or_none()
    if not c:
        raise NotFound("Customer not found")
    data = payload.model_dump(exclude_unset=True)
    if "customer_type" in data and data["customer_type"] is not None:
        data["customer_type"] = data["customer_type"].value
    for k, v in data.items():
        setattr(c, k, v)
    await db.commit()
    await db.refresh(c)
    return c


@router.get("/{customer_id}/prices", response_model=list[CustomerPriceOut])
async def list_customer_prices(
    customer_id: uuid.UUID, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)
):
    return (await db.execute(
        select(CustomerPrice).where(
            CustomerPrice.tenant_id == user.tenant_id, CustomerPrice.customer_id == customer_id
        )
    )).scalars().all()


@router.post("/{customer_id}/prices", response_model=CustomerPriceOut)
async def upsert_customer_price(
    customer_id: uuid.UUID, payload: CustomerPriceUpsert,
    db: AsyncSession = Depends(get_db), user=Depends(require_admin_or_manager),
):
    existing = (await db.execute(
        select(CustomerPrice).where(
            CustomerPrice.tenant_id == user.tenant_id,
            CustomerPrice.customer_id == customer_id,
            CustomerPrice.product_id == payload.product_id,
        )
    )).scalar_one_or_none()
    if existing:
        existing.price = payload.price
        await db.commit()
        await db.refresh(existing)
        return existing
    row = CustomerPrice(
        tenant_id=user.tenant_id, customer_id=customer_id,
        product_id=payload.product_id, price=payload.price,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


@router.get("/{customer_id}/ledger", response_model=list[LedgerEntryOut])
async def customer_ledger(
    customer_id: uuid.UUID, limit: int = Query(100, le=500),
    db: AsyncSession = Depends(get_db), user=Depends(require_staff),
):
    return (await db.execute(
        select(LedgerEntry).where(
            LedgerEntry.tenant_id == user.tenant_id, LedgerEntry.customer_id == customer_id
        ).order_by(LedgerEntry.created_at.desc()).limit(limit)
    )).scalars().all()
