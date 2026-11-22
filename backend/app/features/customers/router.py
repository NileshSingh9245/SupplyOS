"""Customer CRUD + credit info + per-customer pricing."""
from __future__ import annotations

import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, EmailStr, Field, StrictBool, field_validator
from sqlalchemy import select, or_, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.core.database import get_db
from app.core.enums import CustomerType, Role
from app.core.exceptions import Conflict, DomainError, NotFound
from app.features.pricing import service as pricing_service
from app.features.pricing.schemas import TierAssignment
from app.infrastructure.db.models.customer import Customer, CustomerPrice, LedgerEntry
from app.infrastructure.db.models.product import Product
from app.shared.audit import audit
from app.shared.deps import get_current_user, lock_current_user, require_admin_or_manager, require_roles, require_staff
from app.shared.private_route import PrivateInputRoute
from app.shared.schemas import ORMModel, Paginated

router = APIRouter(prefix="/customers", tags=["customers"], route_class=PrivateInputRoute)
require_customer_writer = require_roles(Role.SUPER_ADMIN, Role.ACCOUNTANT)
require_customer_reader = require_roles(
    Role.SUPER_ADMIN, Role.WAREHOUSE_MANAGER, Role.ACCOUNTANT, Role.CUSTOMER,
)


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
    credit_held: Decimal
    cash_funded_pending: Decimal
    credit_exposure: Decimal
    available_credit: Decimal
    advance_balance: Decimal
    price_tier: str | None
    is_active: bool


class CustomerCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, hide_input_in_errors=True)
    code: str | None = Field(default=None, max_length=30)
    name: str = Field(min_length=1, max_length=200)
    business_name: str | None = Field(default=None, max_length=200)
    gstin: str | None = Field(default=None, max_length=20)
    phone: str | None = Field(default=None, max_length=30)
    email: EmailStr | None = Field(default=None, max_length=200)
    address: str | None = Field(default=None, max_length=500)
    city: str | None = Field(default=None, max_length=120)
    state: str | None = Field(default=None, max_length=120)
    pincode: str | None = Field(default=None, max_length=15)
    customer_type: CustomerType = CustomerType.CASH
    credit_limit: Decimal = Field(default=Decimal("0"), ge=0, max_digits=14, decimal_places=2)
    price_tier: str | None = Field(default=None, max_length=30)

    @field_validator("code", "business_name", "gstin", "phone", "email", "address", "city", "state", "pincode", "price_tier", mode="before")
    @classmethod
    def blank_optional(cls, value):
        return (value.strip() or None) if isinstance(value, str) else value


class CustomerUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, hide_input_in_errors=True)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    business_name: str | None = Field(default=None, max_length=200)
    gstin: str | None = Field(default=None, max_length=20)
    phone: str | None = Field(default=None, max_length=30)
    email: EmailStr | None = Field(default=None, max_length=200)
    address: str | None = Field(default=None, max_length=500)
    city: str | None = Field(default=None, max_length=120)
    state: str | None = Field(default=None, max_length=120)
    pincode: str | None = Field(default=None, max_length=15)
    customer_type: CustomerType | None = None
    credit_limit: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    price_tier: str | None = Field(default=None, max_length=30)
    is_active: StrictBool | None = None

    @field_validator("business_name", "gstin", "phone", "email", "address", "city", "state", "pincode", "price_tier", mode="before")
    @classmethod
    def blank_optional(cls, value):
        return (value.strip() or None) if isinstance(value, str) else value

    @field_validator("name", "customer_type", "credit_limit", "is_active", mode="before")
    @classmethod
    def reject_null_required_fields(cls, value):
        if value is None:
            raise ValueError("This customer field cannot be null")
        return value


class CustomerPriceOut(ORMModel):
    id: uuid.UUID
    customer_id: uuid.UUID
    product_id: uuid.UUID
    price: Decimal


class CustomerPriceUpsert(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_id: uuid.UUID
    price: Decimal = Field(ge=0, max_digits=14, decimal_places=2)


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


async def _visible_customer(db: AsyncSession, user, customer_id: uuid.UUID) -> Customer:
    if user.role == Role.CUSTOMER.value and customer_id != user.customer_id:
        raise NotFound("Customer not found")
    customer = (await db.execute(select(Customer).where(
        Customer.id == customer_id, Customer.tenant_id == user.tenant_id,
    ))).scalar_one_or_none()
    if not customer:
        raise NotFound("Customer not found")
    return customer


@router.get("", response_model=Paginated[CustomerOut])
async def list_customers(
    q: str | None = None,
    customer_type: CustomerType | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    user=Depends(require_customer_reader),
):
    stmt = select(Customer).where(Customer.tenant_id == user.tenant_id)
    if user.role == Role.CUSTOMER.value:
        stmt = stmt.where(Customer.id == user.customer_id)
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
    payload: CustomerCreate, request: Request, db: AsyncSession = Depends(get_db),
    user=Depends(require_customer_writer),
):
    user = await lock_current_user(request, db)
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
    try:
        await db.flush()
    except IntegrityError as error:
        await db.rollback()
        if getattr(error.orig, "sqlstate", getattr(error.orig, "pgcode", None)) == "23505":
            raise Conflict("Customer code already exists") from None
        raise
    await audit(db, tenant_id=user.tenant_id, actor_id=user.id, actor_email=user.email,
                action="customers.create", resource_type="customer", resource_id=str(c.id))
    await get_current_user(request, db)
    await db.commit()
    await db.refresh(c)
    return c


@router.get("/{customer_id}", response_model=CustomerOut)
async def get_customer(customer_id: uuid.UUID, db: AsyncSession = Depends(get_db), user=Depends(require_customer_reader)):
    return await _visible_customer(db, user, customer_id)


@router.patch("/{customer_id}", response_model=CustomerOut)
async def update_customer(
    customer_id: uuid.UUID, payload: CustomerUpdate, request: Request,
    db: AsyncSession = Depends(get_db), user=Depends(require_customer_writer),
):
    user = await lock_current_user(request, db)
    c = (await db.execute(select(Customer).where(
        Customer.id == customer_id, Customer.tenant_id == user.tenant_id,
    ).with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()
    if not c:
        raise NotFound("Customer not found")
    data = payload.model_dump(exclude_unset=True)
    if not data:
        raise DomainError("No customer changes supplied")
    if "customer_type" in data and data["customer_type"] is not None:
        data["customer_type"] = data["customer_type"].value
    if {"credit_limit", "customer_type"} & data.keys():
        new_type = data.get("customer_type", c.customer_type)
        if new_type == "credit" and data.get("credit_limit", c.credit_limit) < c.credit_exposure:
            raise Conflict("Credit limit cannot be below existing commitments")
        if new_type == "cash" and c.customer_type == "credit" and (c.outstanding > 0 or c.credit_held > 0):
            raise Conflict("Existing credit debt or commitments must be resolved first")
    for k, v in data.items():
        setattr(c, k, v)
    await audit(db, tenant_id=user.tenant_id, actor_id=user.id, actor_email=user.email,
                action="customers.update", resource_type="customer", resource_id=str(c.id),
                meta={"changed_fields": sorted(data)})
    await get_current_user(request, db)
    await db.commit()
    await db.refresh(c)
    return c


@router.get("/{customer_id}/prices", response_model=list[CustomerPriceOut])
async def list_customer_prices(
    customer_id: uuid.UUID, db: AsyncSession = Depends(get_db), user=Depends(require_customer_reader)
):
    await _visible_customer(db, user, customer_id)
    return (await db.execute(
        select(CustomerPrice).where(
            CustomerPrice.tenant_id == user.tenant_id, CustomerPrice.customer_id == customer_id
        )
    )).scalars().all()


@router.patch("/{customer_id}/pricing-tier", response_model=CustomerOut)
async def assign_pricing_tier(
    customer_id: uuid.UUID, payload: TierAssignment, request: Request,
    db: AsyncSession = Depends(get_db), user=Depends(require_customer_writer),
):
    actor = await lock_current_user(request, db)
    customer = await pricing_service.assign_tier(db, actor, customer_id, payload.tier_id)
    await db.flush()
    await get_current_user(request, db)
    await db.commit()
    return customer


@router.delete("/{customer_id}/prices/{product_id}", status_code=204)
async def remove_customer_price(
    customer_id: uuid.UUID, product_id: uuid.UUID, request: Request,
    db: AsyncSession = Depends(get_db), user=Depends(require_customer_writer),
):
    actor = await lock_current_user(request, db)
    await pricing_service.remove_override(db, actor, customer_id, product_id)
    await db.flush()
    await get_current_user(request, db)
    await db.commit()


@router.post("/{customer_id}/prices", response_model=CustomerPriceOut)
async def upsert_customer_price(
    customer_id: uuid.UUID, payload: CustomerPriceUpsert, request: Request,
    db: AsyncSession = Depends(get_db), user=Depends(require_customer_writer),
):
    user = await lock_current_user(request, db)
    customer = (await db.execute(select(Customer.id).where(
        Customer.id == customer_id, Customer.tenant_id == user.tenant_id,
    ).with_for_update())).scalar_one_or_none()
    if customer is None:
        raise NotFound("Customer not found")
    product = (await db.execute(select(Product.id).where(
        Product.id == payload.product_id, Product.tenant_id == user.tenant_id,
    ))).scalar_one_or_none()
    if product is None:
        raise NotFound("Product not found")
    existing = (await db.execute(
        select(CustomerPrice).where(
            CustomerPrice.tenant_id == user.tenant_id,
            CustomerPrice.customer_id == customer_id,
            CustomerPrice.product_id == payload.product_id,
        )
    )).scalar_one_or_none()
    if existing:
        existing.price = payload.price
        await audit(db, tenant_id=user.tenant_id, actor_id=user.id, actor_email=user.email,
                    action="customers.price_update", resource_type="customer", resource_id=str(customer_id))
        await get_current_user(request, db)
        await db.commit()
        await db.refresh(existing)
        return existing
    row = CustomerPrice(
        tenant_id=user.tenant_id, customer_id=customer_id,
        product_id=payload.product_id, price=payload.price,
    )
    db.add(row)
    await audit(db, tenant_id=user.tenant_id, actor_id=user.id, actor_email=user.email,
                action="customers.price_create", resource_type="customer", resource_id=str(customer_id))
    await get_current_user(request, db)
    await db.commit()
    await db.refresh(row)
    return row


@router.get("/{customer_id}/ledger", response_model=list[LedgerEntryOut])
async def customer_ledger(
    customer_id: uuid.UUID, limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db), user=Depends(require_customer_reader),
):
    await _visible_customer(db, user, customer_id)
    return (await db.execute(
        select(LedgerEntry).where(
            LedgerEntry.tenant_id == user.tenant_id, LedgerEntry.customer_id == customer_id
        ).order_by(LedgerEntry.created_at.desc()).limit(limit)
    )).scalars().all()
