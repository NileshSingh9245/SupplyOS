"""Auth API routes."""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.core.enums import Role
from app.core.exceptions import DomainError, Unauthorized
from app.features.auth import service
from app.features.auth.schemas import (
    ChangePasswordRequest, ForgotPasswordRequest, LoginRequest, LoginResponse, RegisterCustomerRequest,
    ResetPasswordRequest, UserOut,
)
from app.infrastructure.db.models.user import User
from app.shared.deps import access_token_from_request, client_ip, get_current_user, lock_current_user, require_roles
from app.shared.schemas import MessageResponse
from app.shared.private_route import PrivateInputRoute

settings = get_settings()


router = APIRouter(prefix="/auth", tags=["auth"], route_class=PrivateInputRoute)
require_customer_provisioner = require_roles(Role.SUPER_ADMIN, Role.ACCOUNTANT)

COOKIE_KW = {
    "httponly": True, "secure": settings.secure_cookies,
    "samesite": settings.cookie_samesite, "path": "/",
}


def _serialize_user(u: User) -> UserOut:
    return UserOut(
        id=str(u.id), tenant_id=str(u.tenant_id), email=u.email,
        full_name=u.full_name, phone=u.phone, role=u.role, is_active=u.is_active,
    )


@router.post("/login", response_model=LoginResponse)
async def login(
    payload: LoginRequest, request: Request, response: Response, db: AsyncSession = Depends(get_db)
) -> LoginResponse:
    ip = client_ip(request)
    device = request.headers.get("user-agent", "")
    user, access, refresh, _ = await service.authenticate(db, payload, ip, device)
    _set_tokens(response, access, refresh)
    return LoginResponse(user=_serialize_user(user), access_token=access)


@router.post("/register-customer", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register_customer(
    payload: RegisterCustomerRequest, request: Request, db: AsyncSession = Depends(get_db),
    user=Depends(require_customer_provisioner),
) -> UserOut:
    actor = await lock_current_user(request, db)
    created = await service.register_customer(db, payload, client_ip(request), actor=actor)
    await get_current_user(request, db)
    await db.commit()
    return _serialize_user(created)


@router.post("/refresh", response_model=None)
async def refresh(
    request: Request, response: Response, db: AsyncSession = Depends(get_db),
) -> dict[str, str] | Response:
    tok = request.cookies.get("refresh_token")
    try:
        if not tok:
            raise Unauthorized("No refresh token")
        access, new_refresh, _ = await service.refresh_access(db, tok)
    except Unauthorized as error:
        rejected = JSONResponse(status_code=error.status_code, content={"detail": error.detail})
        _clear_tokens(rejected)
        return rejected
    _set_tokens(response, access, new_refresh)
    return {"access_token": access, "token_type": "bearer"}


@router.post("/logout", response_model=MessageResponse)
async def logout(
    request: Request, response: Response, db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    await service.logout(
        db, refresh_token_str=request.cookies.get("refresh_token"),
        access_token_str=access_token_from_request(request), ip=client_ip(request),
    )
    _clear_tokens(response)
    return MessageResponse(message="Logged out")


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)) -> UserOut:
    return _serialize_user(user)


@router.post("/forgot-password", response_model=MessageResponse)
async def forgot_password(
    payload: ForgotPasswordRequest, request: Request, background_tasks: BackgroundTasks,
) -> MessageResponse:
    if not settings.smtp_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Password reset email is not configured. Contact the business administrator.",
        )
    recovery = getattr(request.app.state, "password_recovery", None)
    admission = await recovery.enqueue(
        email=str(payload.email), tenant_id=payload.tenant_id,
        client_host=request.client.host if request.client else None,
        background_tasks=background_tasks, scope=request.scope,
    ) if recovery is not None else None
    if admission is None or admission.state == "unavailable":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Password reset is temporarily unavailable. Try again later.",
        )
    if admission.state == "limited":
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many password reset requests. Try again later.",
            headers={"Retry-After": str(admission.retry_after)},
        )
    return MessageResponse(
        message="If an eligible account exists, check its email for a password reset link.",
    )


@router.post("/reset-password", response_model=MessageResponse)
async def reset_password(
    payload: ResetPasswordRequest, response: Response, db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    await service.reset_password(db, payload.token, payload.new_password)
    _clear_tokens(response)
    return MessageResponse(message="Password reset successful")


@router.post(
    "/change-password", response_model=MessageResponse, summary="Change your own password",
    description="Requires the current password and active signed session. Revokes every session "
                "and outstanding reset link without signing in automatically.",
)
async def change_password(
    payload: ChangePasswordRequest, request: Request, response: Response,
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
) -> MessageResponse:
    try:
        if request.query_params:
            raise DomainError("Password change query parameters are not supported", code=422)
        actor = await lock_current_user(request, db)

        async def recheck() -> User:
            return await get_current_user(request, db)

        rejected = await service.change_password(
            db, actor=actor, payload=payload, recheck=recheck, ip=client_ip(request),
        )
        # Only explicit rejected reauthentication may commit counters. All unexpected
        # failures roll back password, audit, epoch, sessions, resets and counters together.
        await db.commit()
    except BaseException:
        await db.rollback()
        raise
    if rejected is not None:
        raise rejected
    _clear_tokens(response)
    return MessageResponse(message="Password changed. Sign in again.")


def _set_tokens(response: Response, access: str, refresh: str) -> None:
    response.set_cookie(
        "access_token", access, max_age=settings.access_token_minutes * 60, **COOKIE_KW,
    )
    response.set_cookie(
        "refresh_token", refresh, max_age=settings.refresh_token_days * 86400, **COOKIE_KW,
    )


def _clear_tokens(response: Response) -> None:
    response.delete_cookie("access_token", **COOKIE_KW)
    response.delete_cookie("refresh_token", **COOKIE_KW)
