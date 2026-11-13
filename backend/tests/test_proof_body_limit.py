"""ASGI proof size limits run before any multipart parser or spool is created."""
from __future__ import annotations

import pytest
from app.features.proofs.middleware import MAX_PROOF_REQUEST_BYTES, ProofBodyLimit


async def exercise(chunks, *, headers=(), path="/api/v1/deliveries/not-a-uuid/proofs"):
    messages = [{"type": "http.request", "body": chunk, "more_body": index < len(chunks) - 1}
                for index, chunk in enumerate(chunks)]
    sent = []
    parsed = []

    async def receive():
        return messages.pop(0) if messages else {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    async def parser(scope, received, output):
        request = await received()
        parsed.append(request["body"])
        await output({"type": "http.response.start", "status": 200, "headers": []})
        await output({"type": "http.response.body", "body": b"ok"})

    await ProofBodyLimit(parser)({"type": "http", "method": "POST", "path": path, "headers": list(headers)}, receive, send)
    return next(message["status"] for message in sent if message["type"] == "http.response.start"), parsed


@pytest.mark.asyncio
async def test_declared_oversize_never_invokes_parser():
    status, parsed = await exercise([b""], headers=[(b"content-length", str(MAX_PROOF_REQUEST_BYTES + 1).encode())])
    assert status == 413
    assert parsed == []


@pytest.mark.asyncio
async def test_chunked_oversize_never_invokes_parser():
    status, parsed = await exercise([b"x" * MAX_PROOF_REQUEST_BYTES, b"x"])
    assert status == 413
    assert parsed == []


@pytest.mark.asyncio
async def test_false_small_length_cannot_bypass_actual_byte_limit():
    status, parsed = await exercise([b"x" * (MAX_PROOF_REQUEST_BYTES + 1)], headers=[(b"content-length", b"1")])
    assert status == 413
    assert parsed == []


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/api/v1/deliveries/not-a-uuid/proofs", "/api/deliveries/not-a-uuid/proofs/"])
async def test_invalid_identifiers_and_legacy_paths_are_still_bounded(path):
    status, parsed = await exercise([b"x" * (MAX_PROOF_REQUEST_BYTES + 1)], path=path)
    assert status == 413
    assert parsed == []


@pytest.mark.asyncio
async def test_bounded_body_is_replayed_intact():
    status, parsed = await exercise([b"first", b"second"])
    assert status == 200
    assert parsed == [b"firstsecond"]
