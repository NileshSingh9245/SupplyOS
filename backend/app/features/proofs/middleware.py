"""Bound proof request bytes before Starlette creates multipart spool files."""
from __future__ import annotations

import re
from starlette.responses import JSONResponse

from app.features.proofs.service import MAX_PROOF_BYTES

MAX_PROOF_REQUEST_BYTES = MAX_PROOF_BYTES + 64 * 1024


class ProofBodyLimit:
    def __init__(self, app, prefixes=("/api", "/api/v1")):
        self.app = app
        self.path = re.compile(r"^(?:" + "|".join(re.escape(prefix) for prefix in prefixes) + r")/deliveries/[^/]+/proofs/?$")

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") != "POST" or not self.path.fullmatch(scope.get("path", "")):
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers", []))
        declared = headers.get(b"content-length")
        if declared is not None:
            try:
                length = int(declared)
            except ValueError:
                await JSONResponse({"detail": "Invalid request length"}, status_code=400)(scope, receive, send)
                return
            if length < 0 or length > MAX_PROOF_REQUEST_BYTES:
                await JSONResponse({"detail": "Proof upload request is too large"}, status_code=413)(scope, receive, send)
                return
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            if message["type"] != "http.request":
                continue
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > MAX_PROOF_REQUEST_BYTES:
                await JSONResponse({"detail": "Proof upload request is too large"}, status_code=413)(scope, receive, send)
                return
            body.extend(chunk)
            if not message.get("more_body", False):
                break
        consumed = False

        async def bounded_receive():
            nonlocal consumed
            if not consumed:
                consumed = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, bounded_receive, send)
