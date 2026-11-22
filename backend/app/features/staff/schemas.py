"""Strict staff inputs and credential-free response contracts."""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StrictBool, field_validator

from app.core.enums import Role
from app.core.security import validate_new_password
from app.shared.schemas import ORMModel


class StaffRole(str, Enum):
    WAREHOUSE_MANAGER = Role.WAREHOUSE_MANAGER.value
    ACCOUNTANT = Role.ACCOUNTANT.value
    DELIVERY_PARTNER = Role.DELIVERY_PARTNER.value


STAFF_ROLES = tuple(role.value for role in StaffRole)


class StaffCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    email: EmailStr = Field(max_length=200)
    full_name: str = Field(min_length=2, max_length=200, strict=True)
    phone: str | None = Field(default=None, max_length=30, strict=True)
    role: StaffRole
    password: str = Field(min_length=12, max_length=72, strict=True, repr=False, exclude=True)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.lower().strip()

    @field_validator("full_name", "phone", mode="before")
    @classmethod
    def normalize_contact(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("phone")
    @classmethod
    def optional_phone(cls, value: str | None) -> str | None:
        return value or None

    @field_validator("password")
    @classmethod
    def valid_password(cls, value: str) -> str:
        return validate_new_password(value)


class StaffPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    full_name: str = Field(default=None, min_length=2, max_length=200, strict=True)
    phone: str | None = Field(default=None, max_length=30, strict=True)
    role: StaffRole = Field(default=None)
    is_active: StrictBool = Field(default=None)

    @field_validator("full_name", "phone", mode="before")
    @classmethod
    def normalize_contact(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("phone")
    @classmethod
    def optional_phone(cls, value: str | None) -> str | None:
        return value or None


class RevokeStaffSessionsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class StaffListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    page: int = Field(default=1, ge=1, le=2_147_483_647)
    page_size: int = Field(default=50, ge=1, le=200)


class StaffOut(ORMModel):
    id: uuid.UUID
    email: str
    full_name: str
    phone: str | None
    role: StaffRole
    is_active: bool
    created_at: datetime
