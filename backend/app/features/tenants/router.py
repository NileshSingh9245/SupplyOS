"""Tenant / first-launch setup wizard."""
from __future__ import annotations

from asyncio import to_thread

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.config import get_settings
from app.core.enums import Role
from app.core.exceptions import Conflict, Unauthorized
from app.core.security import hash_password, validate_new_password
from app.features.tenants.security import require_setup_authorization
from app.infrastructure.db.models.tenant import Tenant
from app.infrastructure.db.models.user import User
from app.infrastructure.db.models.warehouse import Warehouse
from app.shared.audit import audit
from app.shared.deps import access_token_from_request, get_current_user
from app.shared.private_route import PrivateInputRoute

router = APIRouter(prefix="/setup", tags=["setup"], route_class=PrivateInputRoute)


class WarehouseInit(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, hide_input_in_errors=True)
    code: str = Field(min_length=1, max_length=30)
    name: str = Field(min_length=1, max_length=200)
    address: str | None = Field(default=None, max_length=500)
    city: str | None = Field(default=None, max_length=120)
    state: str | None = Field(default=None, max_length=120)
    pincode: str | None = Field(default=None, max_length=15)

    @field_validator("address", "city", "state", "pincode", mode="before")
    @classmethod
    def blank_optional(cls, value):
        return None if isinstance(value, str) and not value.strip() else value


class SetupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    company_name: str = Field(min_length=2, max_length=200)
    legal_name: str | None = Field(default=None, max_length=200)
    gstin: str | None = Field(default=None, max_length=20)
    address: str | None = Field(default=None, max_length=500)
    phone: str | None = Field(default=None, max_length=30)
    email: EmailStr | None = Field(default=None, max_length=200)
    currency: str = Field(default="INR", pattern=r"^[A-Z]{3}$")

    admin_email: EmailStr = Field(max_length=200)
    admin_password: str = Field(min_length=12, max_length=72, repr=False, exclude=True)
    admin_full_name: str = Field(min_length=2, max_length=200)

    warehouses: list[WarehouseInit] = Field(min_length=1, max_length=50)

    @field_validator("company_name", "admin_full_name", mode="before")
    @classmethod
    def trim_name(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("legal_name", "gstin", "address", "phone", "email", mode="before")
    @classmethod
    def optional_contact(cls, value):
        return value.strip() or None if isinstance(value, str) else value

    @field_validator("admin_password")
    @classmethod
    def strong_password(cls, value: str) -> str:
        return validate_new_password(value)

    @model_validator(mode="after")
    def unique_warehouses(self) -> "SetupRequest":
        if len({warehouse.code for warehouse in self.warehouses}) != len(self.warehouses):
            raise ValueError("Warehouse codes must be unique")
        return self


class SetupStatus(BaseModel):
    is_setup_complete: bool
    is_initialized: bool = False
    authorization_configured: bool = False
    tenant_id: str | None = None
    company_name: str | None = None


@router.get("/status", response_model=SetupStatus)
async def status_endpoint(request: Request, db: AsyncSession = Depends(get_db)):
    initialized, ready = (await db.execute(select(
        select(Tenant.id).exists(),
        select(Tenant.id).where(Tenant.is_setup_complete.is_(True)).exists(),
    ))).one()
    result = SetupStatus(
        is_setup_complete=ready, is_initialized=initialized,
        authorization_configured=bool(get_settings().setup_authorization_token),
    )
    if access_token_from_request(request):
        try:
            user = await get_current_user(request, db)
        except Unauthorized:
            return result
        tenant = (await db.execute(select(Tenant).where(Tenant.id == user.tenant_id))).scalar_one_or_none()
        if tenant is not None:
            result.tenant_id, result.company_name = str(tenant.id), tenant.name
    return result


@router.post("/initialize", response_model=SetupStatus, status_code=status.HTTP_201_CREATED)
async def initialize(
    payload: SetupRequest, db: AsyncSession = Depends(get_db),
    authorization=Depends(require_setup_authorization),
):
    password_hash = await to_thread(hash_password, payload.admin_password)
    # There is no row to lock on a first launch; serialize the empty-database decision.
    await db.execute(text("SELECT pg_advisory_xact_lock(:namespace, :resource)"), {
        "namespace": 0x53555050, "resource": 1,
    })
    if (await db.execute(select(Tenant.id).limit(1))).scalar_one_or_none() is not None:
        raise Conflict("System already initialized; existing setup requires administrator review")
    tenant = Tenant(
        name=payload.company_name, legal_name=payload.legal_name, gstin=payload.gstin,
        address=payload.address, phone=payload.phone, email=payload.email, currency=payload.currency,
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
        password_hash=password_hash,
        full_name=payload.admin_full_name,
        role=Role.SUPER_ADMIN.value,
        is_email_verified=False,
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
        is_setup_complete=True, is_initialized=True, authorization_configured=True,
        tenant_id=str(tenant.id), company_name=tenant.name,
    )
