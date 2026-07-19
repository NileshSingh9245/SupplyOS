"""Auth schemas."""
from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field

from app.shared.schemas import ORMModel


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6, max_length=200)


class RegisterCustomerRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    full_name: str = Field(min_length=2, max_length=200)
    phone: str | None = None
    business_name: str | None = None


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(min_length=8, max_length=200)


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
    access_token: str
    token_type: str = "bearer"
