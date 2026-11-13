"""Enforce browser request origins and transport headers without buffering ASGI bodies."""
from __future__ import annotations

import re
import uuid
from collections.abc import Sequence
from ipaddress import ip_address
from urllib.parse import urlsplit

from starlette.datastructures import MutableHeaders
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_AUTHORITY = re.compile(r"(?:[a-zA-Z0-9.-]+|\[[a-fA-F0-9:.]+\])(?::[0-9]{1,5})?")
_HOST = re.compile(
    r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
    r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*\.?"
)
_FETCH_SITES = {b"same-origin", b"same-site", b"cross-site", b"none"}
_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    # No default/script/style/img restrictions: API docs, downloads and proof images still work.
    "Content-Security-Policy": "frame-ancestors 'none'; base-uri 'self'; object-src 'none'",
}


def _http_origin(value: str, *, referer: bool = False) -> str | None:
    if not value or len(value) > (8192 if referer else 1024):
        return None
    if any(not "!" <= char <= "~" or char in "\\,#" for char in value):
        return None
    if referer and re.search(r"%(?![a-fA-F0-9]{2})", value):
        return None
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not _AUTHORITY.fullmatch(parsed.netloc)
            or parsed.username is not None or parsed.password is not None
            or (not referer and (parsed.path or "?" in value))
        ):
            return None
        host = parsed.hostname or ""
        port = parsed.port
        if port is not None and not 1 <= port <= 65535:
            return None
        try:
            address = ip_address(host)
        except ValueError:
            if len(host) > 253 or not _HOST.fullmatch(host) or all(c in "0123456789." for c in host):
                return None
        else:
            host = f"[{address.compressed}]" if address.version == 6 else str(address)
    except ValueError:
        return None
    suffix = f":{port}" if port is not None and port != {"http": 80, "https": 443}[parsed.scheme] else ""
    return f"{parsed.scheme}://{host}{suffix}"


def normalize_trusted_origins(origins: Sequence[str]) -> tuple[str, ...]:
    """Validate explicit configuration, never infer trust from Host or forwarded headers."""
    if isinstance(origins, str) or not origins:
        raise ValueError("Browser security requires explicit HTTP(S) frontend origins")
    normalized = []
    for value in origins:
        origin = _http_origin(value[:-1] if value.endswith("/") else value)
        if origin is None:
            raise ValueError("Browser security requires explicit HTTP(S) frontend origins")
        normalized.append(origin)
    return tuple(dict.fromkeys(normalized))


def _request_id(headers: list[tuple[bytes, bytes]]) -> str:
    values = [value for name, value in headers if name.lower() == b"x-request-id"]
    if len(values) == 1 and len(values[0]) in {32, 36}:
        try:
            return str(uuid.UUID(values[0].decode("ascii")))
        except (ValueError, UnicodeDecodeError):
            pass
    return str(uuid.uuid4())


class BrowserSecurityMiddleware:
    def __init__(
        self, app: ASGIApp, *, trusted_origins: Sequence[str], hsts: bool = False,
    ) -> None:
        self.app = app
        self.trusted_origins = frozenset(normalize_trusted_origins(trusted_origins))
        self.hsts = hsts

    def _trusted_browser_request(self, headers: list[tuple[bytes, bytes]]) -> tuple[bool, str | None]:
        values: dict[bytes, list[bytes]] = {name: [] for name in (
            b"origin", b"referer", b"sec-fetch-site",
        )}
        has_fetch_metadata = False
        for name, value in headers:
            name = name.lower()
            if name in values:
                values[name].append(value)
            has_fetch_metadata |= name.startswith(b"sec-fetch-")
        if any(len(items) > 1 for items in values.values()):
            return False, None
        if values[b"sec-fetch-site"] and values[b"sec-fetch-site"][0] not in _FETCH_SITES:
            return False, None
        try:
            if values[b"origin"]:
                origin = _http_origin(values[b"origin"][0].decode("ascii"))
                return origin in self.trusted_origins, origin
            if values[b"referer"]:
                origin = _http_origin(values[b"referer"][0].decode("ascii"), referer=True)
                return origin in self.trusted_origins, None
        except UnicodeDecodeError:
            return False, None
        # Cookie-only refresh is also used by native clients. No-header compatibility is explicit.
        return not has_fetch_metadata, None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = scope.get("headers", [])
        request_id = _request_id(headers)
        scope.setdefault("state", {})["request_id"] = request_id
        trusted, origin = True, None
        if scope.get("method", "").upper() not in {"GET", "HEAD", "OPTIONS"}:
            trusted, origin = self._trusted_browser_request(headers)
        scope = dict(scope)
        scope["headers"] = [
            (name, value) for name, value in headers
            if name.lower() != b"x-request-id" and not (origin and name.lower() == b"origin")
        ] + [(b"x-request-id", request_id.encode("ascii"))]
        if origin:
            scope["headers"].append((b"origin", origin.encode("ascii")))
        response_started = False

        async def secure_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
                output = MutableHeaders(scope=message)
                output.update(_SECURITY_HEADERS)
                output["X-Request-Id"] = request_id
                # Only a trusted ASGI scheme, not a raw X-Forwarded-Proto, activates backend HSTS.
                if self.hsts and scope.get("scheme") == "https":
                    output["Strict-Transport-Security"] = "max-age=31536000"
                else:
                    del output["Strict-Transport-Security"]
            await send(message)

        if not trusted:
            await JSONResponse(
                {"detail": "Untrusted browser request origin"}, status_code=403,
                headers={"Cache-Control": "no-store"},
            )(scope, receive, secure_send)
            return
        try:
            await self.app(scope, receive, secure_send)
        except Exception:
            # Decorate the unhandled error before Starlette's outer error layer; still propagate it.
            if not response_started:
                await PlainTextResponse("Internal Server Error", status_code=500)(
                    scope, receive, secure_send,
                )
            raise
