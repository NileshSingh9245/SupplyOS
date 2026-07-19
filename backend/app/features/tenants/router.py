"""Tenant / first-launch setup wizard."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.enums import Role
from app.core.exceptions import Conflict
from app.core.security import hash_password
from app.infrastructure.db.models.tenant import Tenant
from app.infrastructure.db.models.user import User
from app.infrastructure.db.models.warehouse import Warehouse
from app.shared.audit import audit

router = APIRouter(prefix="/setup", tags=["setup"])


class WarehouseInit(BaseModel):
    code: str = Field(min_length=1, max_length=30)
    name: str = Field(min_length=1, max_length=200)
    address: str | None = None
    city: str | None = None
    state: str | None = None
    pincode: str | None = None


class SetupRequest(BaseModel):
    company_name: str = Field(min_length=2, max_length=200)
    legal_name: str | None = None
    gstin: str | None = None
    address: str | None = None
    phone: str | None = None
    email: EmailStr | None = None
    currency: str = "INR"

    admin_email: EmailStr
    admin_password: str = Field(min_length=8, max_length=200)
    admin_full_name: str = Field(min_length=2, max_length=200)

    warehouses: list[WarehouseInit] = Field(min_length=1, max_length=50)


class SetupStatus(BaseModel):
    is_setup_complete: bool
    tenant_id: str | None = None
    company_name: str | None = None


@router.get("/status", response_model=SetupStatus)
async def status_endpoint(db: AsyncSession = Depends(get_db)):
    t = (await db.execute(select(Tenant).limit(1))).scalar_one_or_none()
    if not t:
        return SetupStatus(is_setup_complete=False)
    return SetupStatus(
        is_setup_complete=t.is_setup_complete,
        tenant_id=str(t.id),
        company_name=t.name,
    )


@router.post("/initialize", response_model=SetupStatus, status_code=status.HTTP_201_CREATED)
async def initialize(payload: SetupRequest, db: AsyncSession = Depends(get_db)):
    existing = (await db.execute(select(Tenant).limit(1))).scalar_one_or_none()
    if existing and existing.is_setup_complete:
        raise Conflict("System already initialized")

    if existing:
        tenant = existing
        tenant.name = payload.company_name
        tenant.legal_name = payload.legal_name
        tenant.gstin = payload.gstin
        tenant.address = payload.address
        tenant.phone = payload.phone
        tenant.email = payload.email
        tenant.currency = payload.currency
    else:
        tenant = Tenant(
            name=payload.company_name,
            legal_name=payload.legal_name,
            gstin=payload.gstin,
            address=payload.address,
            phone=payload.phone,
            email=payload.email,
            currency=payload.currency,
        )
        db.add(tenant)
        await db.flush()

    # Create super admin
    admin_email = payload.admin_email.lower().strip()
    dup = await db.execute(
        select(User).where(User.tenant_id == tenant.id, User.email == admin_email)
    )
    if dup.scalar_one_or_none():
        raise Conflict("Admin email already exists")
    admin = User(
        tenant_id=tenant.id,
        email=admin_email,
        password_hash=hash_password(payload.admin_password),
        full_name=payload.admin_full_name,
        role=Role.SUPER_ADMIN.value,
        is_email_verified=True,
    )
    db.add(admin)
    await db.flush()

    # Create warehouses
    for w in payload.warehouses:
        wh = Warehouse(
            tenant_id=tenant.id,
            code=w.code, name=w.name, address=w.address,
            city=w.city, state=w.state, pincode=w.pincode,
            manager_id=admin.id,
        )
        db.add(wh)

    tenant.is_setup_complete = True
    await audit(
        db, tenant_id=tenant.id, actor_id=admin.id, actor_email=admin.email,
        action="setup.initialize", resource_type="tenant", resource_id=str(tenant.id),
    )
    await db.commit()
    return SetupStatus(
        is_setup_complete=True, tenant_id=str(tenant.id), company_name=tenant.name
    )
