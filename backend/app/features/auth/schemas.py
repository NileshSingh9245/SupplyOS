"""Auth schemas."""
from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.security import validate_new_password
from app.shared.schemas import ORMModel


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    email: EmailStr = Field(max_length=200)
    password: str = Field(min_length=6, max_length=200, repr=False)
    tenant_id: uuid.UUID | None = None


class RegisterCustomerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    email: EmailStr = Field(max_length=200)
    password: str = Field(min_length=12, max_length=72, repr=False, exclude=True)
    full_name: str = Field(min_length=2, max_length=200)
    phone: str | None = Field(default=None, max_length=30)
    business_name: str | None = Field(default=None, max_length=200)
    tenant_id: uuid.UUID | None = None

    @field_validator("full_name", "email", mode="before")
    @classmethod
    def trim_identity(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("phone", "business_name", mode="before")
    @classmethod
    def blank_optional(cls, value):
        return (value.strip() or None) if isinstance(value, str) else value

    @field_validator("password")
    @classmethod
    def valid_password(cls, value: str) -> str:
        return validate_new_password(value)


class ForgotPasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    email: EmailStr = Field(max_length=200)
    tenant_id: uuid.UUID | None = None


class ResetPasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    token: str = Field(min_length=1, max_length=128, repr=False)
    new_password: str = Field(min_length=12, max_length=72, repr=False)

    @field_validator("new_password")
    @classmethod
    def valid_password(cls, value: str) -> str:
        return validate_new_password(value)


class ChangePasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    current_password: str = Field(min_length=6, max_length=200, repr=False, exclude=True)
    new_password: str = Field(min_length=12, max_length=72, repr=False, exclude=True)

    @field_validator("new_password")
    @classmethod
    def valid_password(cls, value: str) -> str:
        return validate_new_password(value)


class UserOut(ORMModel):
    id: str
    tenant_id: str
    email: str
    full_name: str
    phone: str | None
    role: str
    is_active: bool


class LoginResponse(BaseModel):
    user: UserOut
    access_token: str = Field(repr=False)
    token_type: str = "bearer"
