"""Offline ASGI browser security contracts; never load runtime settings or private files."""
from __future__ import annotations

import ast
import uuid
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware
from starlette.types import Message, Scope

from app.core.browser_security import BrowserSecurityMiddleware, normalize_trusted_origins

TRUSTED = ("http://localhost:3000", "https://frontend.example.test", "http://[::1]:3000")
UNTRUSTED = [(b"origin", b"https://attacker.example.test")]
SECURITY_HEADERS = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "no-referrer",
    "content-security-policy": "frame-ancestors 'none'; base-uri 'self'; object-src 'none'",
}


async def exercise(
    *, headers=(), method="POST", path="/api/v1/payments", scheme="http", hsts=False,
    status=200, response_headers=(), chunks=(b"first", b"second"),
) -> tuple[httpx.Response, list[Scope], int]:
    sent: list[Message] = []
    entered: list[Scope] = []
    received = 0

    async def receive():
        nonlocal received
        received += 1
        return {"type": "http.request", "body": b"unparsed request body", "more_body": False}

    async def send(message):
        sent.append(message)

    async def downstream(scope, receive, send):
        entered.append(scope)
        await receive()
        await send({"type": "http.response.start", "status": status, "headers": list(response_headers)})
        for index, chunk in enumerate(chunks):
            await send({"type": "http.response.body", "body": chunk, "more_body": index < len(chunks) - 1})

    scope = {
        "type": "http", "method": method, "path": path, "scheme": scheme,
        "headers": list(headers), "state": {},
    }
    await BrowserSecurityMiddleware(downstream, trusted_origins=TRUSTED, hsts=hsts)(
        scope, receive, send,
    )
    start = sent[0]
    response = httpx.Response(
        start["status"], headers=start["headers"],
        content=b"".join(message.get("body", b"") for message in sent[1:]),
    )
    return response, entered, received


@pytest.mark.asyncio
@pytest.mark.parametrize("prefix", ["/api/v1", "/api", "/custom/v1"])
@pytest.mark.parametrize("suffix,content_type", [
    ("/auth/login", b"application/json"), ("/auth/register-customer", b"application/json"),
    ("/auth/refresh", b"application/json"), ("/auth/logout", b"application/json"),
    ("/auth/forgot-password", b"application/json"), ("/auth/reset-password", b"application/json"),
    ("/setup/initialize", b"application/json"), ("/payments", b"application/json"),
    ("/orders", b"application/json"),
    ("/deliveries/not-a-uuid/proofs", b"multipart/form-data; boundary=isolated"),
    ("/deliveries/not-a-uuid/proofs/", b"multipart/form-data; boundary=isolated"),
])
async def test_all_mutation_paths_reject_before_body_parsing(prefix, suffix, content_type):
    response, entered, received = await exercise(
        path=prefix + suffix, headers=UNTRUSTED + [(b"content-type", content_type)],
    )
    assert response.status_code == 403
    assert response.json() == {"detail": "Untrusted browser request origin"}
    assert response.headers["cache-control"] == "no-store"
    assert entered == [] and received == 0
    assert "attacker" not in response.text
    for key, value in SECURITY_HEADERS.items():
        assert response.headers[key] == value


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "TRACE", "CONNECT", "CUSTOM"])
async def test_only_safe_methods_are_exempt(method):
    response, entered, received = await exercise(method=method, headers=UNTRUSTED)
    assert response.status_code == 403 and not entered and received == 0
    response, entered, received = await exercise(
        method=method, headers=[(b"origin", TRUSTED[1].encode())],
    )
    assert response.status_code == 200 and len(entered) == 1 and received == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS"])
async def test_safe_requests_keep_read_and_preflight_compatibility(method):
    response, entered, _ = await exercise(method=method, headers=[(b"origin", b"null")])
    assert response.status_code == 200 and len(entered) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("headers", [
    [], [(b"authorization", b"Bearer isolated-native-token")],
    [(b"cookie", b"refresh_token=isolated-native-cookie")],
    [(b"cookie", b"access_token=isolated-native-cookie"), (b"user-agent", b"Native API client")],
])
@pytest.mark.parametrize("prefix", ["/api/v1", "/api", "/custom/v1"])
async def test_no_browser_headers_preserves_native_api_and_cookie_refresh(headers, prefix):
    response, entered, received = await exercise(headers=headers, path=prefix + "/auth/refresh")
    assert response.status_code == 200 and len(entered) == 1 and received == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("origin", TRUSTED)
async def test_explicit_cross_origin_frontend_is_allowed(origin):
    response, entered, _ = await exercise(headers=[
        (b"origin", origin.encode()), (b"sec-fetch-site", b"cross-site"),
        (b"sec-fetch-mode", b"cors"), (b"cookie", b"access_token=isolated-cookie"),
    ])
    assert response.status_code == 200 and len(entered) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("origin", [
    b"", b"null", b"*", b"https://attacker.example.test",
    b"https://frontend.example.test.attacker.test", b"https://frontend.example.test:444",
    b"http://frontend.example.test", b"https://frontend.example.test/",
    b"https://frontend.example.test/path", b"https://frontend.example.test?",
    b"https://frontend.example.test?query=1", b"https://frontend.example.test#",
    b"https://frontend.example.test#fragment", b"https://user@frontend.example.test",
    b"https://frontend.example.test@attacker.test", b"https://frontend.example.test:",
    b"https://frontend.example.test:0", b"https://frontend.example.test:65536",
    b"https://frontend.example.test:bad", b" https://frontend.example.test",
    b"https://frontend.example.test ", b"https://frontend.example.test\r\nX-Injected: yes",
    b"https://frontend.example.test\x00", b"https://front\tend.example.test",
    b"https://frontend.example.test\\attacker", b"https://frontend%2eexample.test",
    b"https://frontend.example.test,https://attacker.test",
    b"https://frontend.example.test https://attacker.test", b"https://[::1]junk:3000",
    b"https://[broken]", b"http://[::1%25zone]:3000", b"http://127.0.0.999",
    b"//frontend.example.test", b"javascript:frontend.example.test",
    b"https://fr\xffntend.example.test", b"a" * 1025,
])
async def test_malformed_opaque_and_unapproved_origins_never_use_referer_as_a_bypass(origin):
    response, entered, received = await exercise(headers=[
        (b"origin", origin), (b"referer", b"https://frontend.example.test/login"),
        (b"sec-fetch-site", b"same-origin"), (b"authorization", b"Bearer isolated-token"),
    ])
    assert response.status_code == 403 and not entered and received == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("headers", [
    [(b"origin", TRUSTED[1].encode()), (b"origin", TRUSTED[1].encode())],
    [(b"Origin", TRUSTED[1].encode()), (b"origin", b"https://attacker.test")],
    [(b"referer", b"https://frontend.example.test/"), (b"referer", b"https://frontend.example.test/")],
    [(b"origin", TRUSTED[1].encode()), (b"referer", b"https://frontend.example.test/"),
     (b"Referer", b"https://attacker.test/")],
    [(b"origin", TRUSTED[1].encode()), (b"sec-fetch-site", b"same-origin"),
     (b"sec-fetch-site", b"cross-site")],
    [(b"origin", TRUSTED[1].encode()), (b"sec-fetch-site", b"unknown")],
])
async def test_ambiguous_browser_headers_fail_closed(headers):
    response, entered, received = await exercise(headers=headers)
    assert response.status_code == 403 and not entered and received == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("referer", [
    b"https://frontend.example.test/", b"https://frontend.example.test/reset-password?view=1",
    b"http://localhost:3000/setup", b"http://[::1]:3000/path%20name",
])
async def test_trusted_referer_is_a_fallback_for_missing_origin(referer):
    response, entered, _ = await exercise(headers=[
        (b"referer", referer), (b"sec-fetch-site", b"cross-site"),
    ])
    assert response.status_code == 200 and len(entered) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("referer", [
    b"", b"null", b"https://attacker.test/", b"http://frontend.example.test/",
    b"https://frontend.example.test.attacker.test/path", b"https://frontend.example.test:444/",
    b"https://user@frontend.example.test/", b"https://frontend.example.test/#fragment",
    b"https://frontend.example.test/#", b"https://frontend.example.test\\attacker/path",
    b"https://frontend.example.test/path,https://attacker.test/",
    b"https://frontend.example.test/path%ZZ", b"https://frontend.example.test/path\n",
    b"https://frontend.example.test:bad/", b"https://[::1]suffix:3000/path", b"a" * 8193,
])
async def test_malformed_or_untrusted_referers_cannot_enable_native_compatibility(referer):
    response, entered, received = await exercise(headers=[(b"referer", referer)])
    assert response.status_code == 403 and not entered and received == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("header", [
    (b"sec-fetch-site", b"cross-site"), (b"sec-fetch-site", b"same-site"),
    (b"sec-fetch-site", b"same-origin"), (b"sec-fetch-site", b"none"),
    (b"sec-fetch-mode", b"no-cors"), (b"sec-fetch-dest", b"document"),
])
async def test_fetch_metadata_without_origin_or_referer_is_not_native(header):
    response, entered, received = await exercise(headers=[header])
    assert response.status_code == 403 and not entered and received == 0


@pytest.mark.asyncio
async def test_host_and_forwarded_headers_never_expand_trusted_origins():
    response, entered, _ = await exercise(headers=UNTRUSTED + [
        (b"host", b"attacker.example.test"), (b"x-forwarded-host", b"frontend.example.test"),
        (b"forwarded", b"host=frontend.example.test;proto=https"),
        (b"sec-fetch-site", b"same-origin"),
    ])
    assert response.status_code == 403 and not entered


@pytest.mark.parametrize("origins", [
    [], ["*"], ["null"], ["https://*.example.test"], ["https://app.example.test/path"],
    ["https://app.example.test?"], ["https://app.example.test#"],
    ["https://app.example.test:"], ["https://app.example.test:65536"],
    ["https://user@app.example.test"], ["https://app.example.test\n"],
    ["https://[::1]suffix"], ["https://app.example.test", "*"], "https://app.example.test",
])
def test_invalid_configured_trust_is_rejected_not_disabled(origins):
    with pytest.raises(ValueError, match="explicit HTTP"):
        normalize_trusted_origins(origins)
    with pytest.raises(ValueError, match="explicit HTTP"):
        BrowserSecurityMiddleware(FastAPI(), trusted_origins=origins)


def test_configuration_normalizes_only_origin_identity():
    assert normalize_trusted_origins([
        "https://APP.example.test:443/", "https://app.example.test",
        "http://LOCALHOST:80", "http://[0:0:0:0:0:0:0:1]:3000",
    ]) == ("https://app.example.test", "http://localhost", "http://[::1]:3000")


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [
    b"12345678-ABCD-4ABC-8ABC-123456789ABC", b"12345678abcd4abc8abc123456789abc",
])
async def test_caller_uuid_is_normalized_in_state_request_and_response(value):
    response, entered, _ = await exercise(headers=[(b"x-request-id", value)])
    expected = str(uuid.UUID(value.decode()))
    assert response.headers["x-request-id"] == expected
    assert entered[0]["state"]["request_id"] == expected
    assert [value for name, value in entered[0]["headers"] if name == b"x-request-id"] == [expected.encode()]


@pytest.mark.asyncio
@pytest.mark.parametrize("values", [
    [], [b""], [b"not-a-uuid"], [b"a" * 100_000], [b"invalid\r\nX-Injected: value"],
    [b"\xff" * 36], [b"12345678-abcd-4abc-8abc-123456789abc"] * 2,
])
async def test_invalid_or_duplicate_ids_are_replaced_before_downstream_use(values):
    response, entered, _ = await exercise(headers=[(b"X-Request-Id", value) for value in values])
    rid = response.headers["x-request-id"]
    assert str(uuid.UUID(rid)) == rid and uuid.UUID(rid).version == 4
    assert entered[0]["state"]["request_id"] == rid
    assert [value for name, value in entered[0]["headers"] if name.lower() == b"x-request-id"] == [rid.encode()]
    assert "x-injected" not in response.headers


@pytest.mark.asyncio
@pytest.mark.parametrize("scheme,hsts,expected", [
    ("http", False, None), ("https", False, None), ("http", True, None),
    ("https", True, "max-age=31536000"),
])
async def test_hsts_requires_secure_asgi_scheme_and_deployed_environment(scheme, hsts, expected):
    response, _, _ = await exercise(
        scheme=scheme, hsts=hsts, headers=[(b"x-forwarded-proto", b"https")],
    )
    assert response.headers.get("strict-transport-security") == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200, 206, 401, 404, 422, 503])
async def test_proof_responses_keep_stream_bytes_and_download_headers(status):
    chunks = (b"\x89PNG\r\n", b"isolated private image bytes")
    response, _, _ = await exercise(
        method="GET", path="/api/v1/delivery-proofs/isolated", status=status,
        response_headers=[
            (b"content-type", b"image/png"), (b"cache-control", b"no-store"),
            (b"content-disposition", b'attachment; filename="proof.png"'),
            (b"content-range", b"bytes 0-31/32"), (b"x-content-type-options", b"unsafe"),
        ], chunks=chunks,
    )
    assert response.status_code == status and response.content == b"".join(chunks)
    assert response.headers["content-type"] == "image/png"
    assert response.headers["content-disposition"] == 'attachment; filename="proof.png"'
    assert response.headers["content-range"] == "bytes 0-31/32"
    assert response.headers["cache-control"] == "no-store"
    for key, value in SECURITY_HEADERS.items():
        assert response.headers[key] == value
    assert "img-src" not in response.headers["content-security-policy"]
    assert "cross-origin-resource-policy" not in response.headers


def server_boundary(prefix="/custom/v1", environment="test") -> tuple[FastAPI, list[str]]:
    """Execute only the real middleware declarations, avoiding all runtime/credential imports."""
    from app.features.tenants.security import SetupAuthorizationMiddleware
    tree = ast.parse((Path(__file__).resolve().parents[1] / "server.py").read_text(encoding="utf-8"))
    statements = [node for node in tree.body if (
        isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "allow_origins" for target in node.targets
        )
    ) or (
        isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Attribute) and node.value.func.attr == "add_middleware"
    )]
    app = FastAPI()
    inner_calls: list[str] = []

    class InnerBoundary:
        def __init__(self, app, **kwargs):
            self.app = app

        async def __call__(self, scope, receive, send):
            inner_calls.append(scope.get("path", ""))
            await self.app(scope, receive, send)

    namespace = {
        "app": app, "settings": SimpleNamespace(
            cors_origins=list(TRUSTED), api_v1_prefix=prefix, app_env=environment,
            setup_authorization_token="",
        ),
        "normalize_trusted_origins": normalize_trusted_origins,
        "BrowserSecurityMiddleware": BrowserSecurityMiddleware, "CORSMiddleware": CORSMiddleware,
        "ProofBodyLimit": InnerBoundary, "RecoveryCapacityRelease": InnerBoundary,
        "SetupAuthorizationMiddleware": SetupAuthorizationMiddleware,
    }
    exec(compile(ast.Module(body=statements, type_ignores=[]), "server-middleware", "exec"), namespace)
    assert app.user_middleware[0].cls is BrowserSecurityMiddleware
    return app, inner_calls


@pytest.mark.asyncio
@pytest.mark.parametrize("prefix", ["/api/v1", "/api", "/custom/v1"])
async def test_server_wiring_rejects_json_and_multipart_before_inner_boundaries(prefix):
    app, inner_calls = server_boundary(prefix)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://isolated.test", trust_env=False,
    ) as client:
        for suffix, content_type in [
            ("/payments", "application/json"), ("/setup/initialize", "application/json"),
            ("/auth/login", "application/json"), ("/auth/reset-password", "application/json"),
            ("/deliveries/isolated/proofs", "multipart/form-data; boundary=isolated"),
        ]:
            response = await client.post(prefix + suffix, content=b"unparsed", headers={
                "Origin": "https://attacker.example.test", "Content-Type": content_type,
            })
            assert response.status_code == 403
    assert inner_calls == []


@pytest.mark.asyncio
async def test_server_cors_preserves_explicit_frontend_and_secures_preflight_and_errors():
    app, inner_calls = server_boundary(environment="production")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://isolated.test", trust_env=False,
    ) as client:
        headers = {"Origin": TRUSTED[1], "Access-Control-Request-Method": "POST"}
        response = await client.options("/api/v1/payments", headers=headers)
        assert response.status_code == 200 and inner_calls == []
        assert response.headers["access-control-allow-origin"] == TRUSTED[1]
        assert response.headers["access-control-allow-credentials"] == "true"
        assert response.headers["strict-transport-security"] == "max-age=31536000"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert uuid.UUID(response.headers["x-request-id"])
        response = await client.post("/api/v1/missing", headers={
            "Origin": "https://FRONTEND.example.test:443", "Sec-Fetch-Site": "cross-site",
        })
        assert response.status_code == 404 and len(inner_calls) == 2
        assert response.headers["access-control-allow-origin"] == TRUSTED[1]
        assert response.headers["access-control-expose-headers"] == "X-Request-Id"


@pytest.mark.asyncio
async def test_unhandled_error_is_secured_without_swallowing_original_exception():
    sent = []

    async def failure(scope, receive, send):
        raise RuntimeError("private failure detail must not appear in response")

    async def send(message):
        sent.append(message)

    async def receive():
        pytest.fail("Unhandled error response must not consume a request body")

    with pytest.raises(RuntimeError, match="private failure"):
        await BrowserSecurityMiddleware(failure, trusted_origins=TRUSTED, hsts=True)(
            {"type": "http", "method": "POST", "headers": [], "scheme": "https"}, receive, send,
        )
    assert sent[0]["status"] == 500
    assert sent[1]["body"] == b"Internal Server Error"
    headers = httpx.Headers(sent[0]["headers"])
    assert headers["strict-transport-security"] == "max-age=31536000"
    for key, value in SECURITY_HEADERS.items():
        assert headers[key] == value


@pytest.mark.asyncio
@pytest.mark.parametrize("scope_type", ["lifespan", "websocket"])
async def test_non_http_scopes_pass_through_unchanged(scope_type):
    scope = {"type": scope_type, "headers": UNTRUSTED}
    called = []

    async def downstream(scope, receive, send):
        called.append(scope)

    async def unused():
        pytest.fail("Non-HTTP passthrough must not receive or send")

    await BrowserSecurityMiddleware(downstream, trusted_origins=TRUSTED)(scope, unused, unused)
    assert called == [scope] and called[0] is scope and "state" not in scope
