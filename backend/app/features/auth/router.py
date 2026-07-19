"""Auth API routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.features.auth import service
from app.features.auth.schemas import (
    ForgotPasswordRequest, LoginRequest, LoginResponse, RegisterCustomerRequest,
    ResetPasswordRequest, UserOut,
)
from app.infrastructure.db.models.tenant import Tenant
from app.shared.deps import client_ip, get_current_user
from app.shared.schemas import MessageResponse
from sqlalchemy import select

settings = get_settings()
router = APIRouter(prefix="/auth", tags=["auth"])

COOKIE_KW = {"httponly": True, "secure": False, "samesite": "lax", "path": "/"}


def _serialize_user(u) -> UserOut:
    return UserOut(
        id=str(u.id), tenant_id=str(u.tenant_id), email=u.email,
        full_name=u.full_name, phone=u.phone, role=u.role, is_active=u.is_active,
    )


@router.post("/login", response_model=LoginResponse)
async def login(
    payload: LoginRequest, request: Request, response: Response, db: AsyncSession = Depends(get_db)
):
    ip = client_ip(request)
    device = request.headers.get("user-agent", "")
    user, access, refresh, _ = await service.authenticate(db, payload, ip, device)
    response.set_cookie(
        "access_token", access, max_age=settings.access_token_minutes * 60, **COOKIE_KW
    )
    response.set_cookie(
        "refresh_token", refresh, max_age=settings.refresh_token_days * 86400, **COOKIE_KW
    )
    return LoginResponse(user=_serialize_user(user), access_token=access)


@router.post("/register-customer", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register_customer(
    payload: RegisterCustomerRequest, request: Request, db: AsyncSession = Depends(get_db)
):
    # Auto-attach to the (single) tenant of this instance
    tenant = (await db.execute(select(Tenant).limit(1))).scalar_one_or_none()
    if not tenant:
        from app.core.exceptions import DomainError
        raise DomainError("Setup not complete. Contact the administrator.")
    user = await service.register_customer(db, payload, tenant.id, client_ip(request))
    return _serialize_user(user)


@router.post("/refresh")
async def refresh(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    from app.core.exceptions import Unauthorized

    tok = request.cookies.get("refresh_token")
    if not tok:
        raise Unauthorized("No refresh token")
    access, _ = await service.refresh_access(db, tok)
    response.set_cookie(
        "access_token", access, max_age=settings.access_token_minutes * 60, **COOKIE_KW
    )
    return {"access_token": access, "token_type": "bearer"}


@router.post("/logout", response_model=MessageResponse)
async def logout(
    request: Request, response: Response, db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    refresh_jti = None
    tok = request.cookies.get("refresh_token")
    if tok:
        try:
            from app.core.security import decode_token
            refresh_jti = decode_token(tok).get("jti")
        except Exception:
            pass
    await service.logout(db, user, refresh_jti)
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/")
    return MessageResponse(message="Logged out")


@router.get("/me", response_model=UserOut)
async def me(user=Depends(get_current_user)):
    return _serialize_user(user)


@router.post("/forgot-password", response_model=MessageResponse)
async def forgot_password(payload: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)):
    token = await service.create_password_reset(db, payload.email)
    if token:
        # In production this would email. Log to server console for now.
        print(f"[password-reset] token for {payload.email}: {token}")
    return MessageResponse(message="If the email exists, a reset link has been sent.")


@router.post("/reset-password", response_model=MessageResponse)
async def reset_password(payload: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
    await service.reset_password(db, payload.token, payload.new_password)
    return MessageResponse(message="Password reset successful")
