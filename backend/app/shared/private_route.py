"""Credential/administration responses never echo validation input or cache state."""
from __future__ import annotations

from typing import Any, Callable, Coroutine
import logging

from fastapi import HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute


class PrivateInputRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def handle(request: Request) -> Response:
            try:
                response = await handler(request)
            except RequestValidationError:
                # Error locations/messages can themselves contain submitted keys or values.
                response = JSONResponse(status_code=422, content={"detail": [{
                    "loc": ["body"], "msg": "Invalid request data", "type": "value_error",
                }]})
            except HTTPException as error:
                response = JSONResponse(
                    status_code=error.status_code, content={"detail": error.detail},
                    headers=error.headers,
                )
            except Exception as error:
                logging.getLogger(__name__).error("Private API request failed (%s)", type(error).__name__)
                response = JSONResponse(status_code=500, content={"detail": "Request could not be completed"})
            response.headers["Cache-Control"] = "no-store"
            return response

        return handle
