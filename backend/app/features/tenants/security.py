"""Operator authorization precedes first-owner request parsing and database work."""
from __future__ import annotations

import hmac

from fastapi import HTTPException, Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.config import Settings, get_settings


def authorize_setup(scope: Scope, settings: Settings) -> None:
    if not settings.setup_authorization_token:
        raise HTTPException(503, "Initial setup authorization is not configured")
    headers = [value for name, value in scope.get("headers", []) if name.lower() == b"x-setup-authorization"]
    if (
        len(headers) != 1 or not 32 <= len(headers[0]) <= 256
        or not hmac.compare_digest(headers[0], settings.setup_authorization_token.encode("ascii"))
    ):
        raise HTTPException(403, "Initial setup authorization is required")


def require_setup_authorization(request: Request) -> None:
    authorize_setup(request.scope, get_settings())


class SetupAuthorizationMiddleware:
    def __init__(self, app: ASGIApp, *, settings: Settings, prefixes: tuple[str, ...]) -> None:
        self.app = app
        self.settings = settings
        self.paths = {prefix.rstrip("/") + "/setup/initialize" for prefix in prefixes}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] == "http" and scope.get("method") == "POST"
            and scope.get("path", "").rstrip("/") in self.paths
        ):
            try:
                authorize_setup(scope, self.settings)
            except HTTPException as error:
                await JSONResponse(
                    status_code=error.status_code, content={"detail": error.detail},
                    headers={"Cache-Control": "no-store"},
                )(scope, receive, send)
                return
        await self.app(scope, receive, send)
