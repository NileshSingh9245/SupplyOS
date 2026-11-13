"""Private hosted storage protocol tests use no provider account or real credential."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import secrets
import uuid

import httpx
import pytest
from PIL import Image
from pydantic import ValidationError

from app.infrastructure.storage.contracts import (
    ExpectedProof, StorageConflict, StorageDeleteUncertain, StorageIntegrityError,
    StorageUnavailable, StorageWriteUncertain,
)
from app.infrastructure.storage.supabase import (
    OWNERSHIP_FIELD, SupabaseProofStore, SupabaseStorageConfig,
)


def png() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (8, 8), "white").save(output, format="PNG")
    return output.getvalue()


@pytest.fixture
def config():
    return SupabaseStorageConfig(
        origin="https://private-project.supabase.co", bucket="delivery-proofs",
        service_role_key=secrets.token_urlsafe(48), approved_free=True, versioning_verified=True,
    )


class Provider:
    """A protocol fixture, never installed as application functionality."""

    def __init__(self, config):
        self.config = config
        self.key = uuid.uuid4().hex + ".png"
        self.operation = uuid.uuid4()
        self.identifier = uuid.uuid4()
        self.version = uuid.uuid4()
        self.data = png()
        self.public = False
        self.created = False
        self.collision = False
        self.bad_ack = False
        self.bad_owner = False
        self.bad_hash = False
        self.change_version = False
        self.bad_delete = False
        self.failure = ""
        self.requests = []
        self.metadata = {}
        self.info_reads = 0

    def __repr__(self):
        return "<offline private storage fixture>"

    @property
    def expected(self):
        return ExpectedProof(len(self.data), "image/png", hashlib.sha256(self.data).hexdigest())

    def handle(self, request):
        self.requests.append(request)
        assert request.headers["apikey"] == self.config.service_role_key
        assert request.headers["authorization"] == "Bearer " + self.config.service_role_key
        assert request.headers["accept-encoding"] == "identity"
        path = request.url.path
        if self.failure == "bucket_redirect" and "/bucket/" in path:
            return httpx.Response(307, headers={"location": "https://not-approved.example.com/"})
        if "/bucket/" in path:
            return httpx.Response(200, json={
                "id": self.config.bucket, "name": self.config.bucket, "public": self.public,
                "versioning_status": "ENABLED",
            })
        if request.method == "POST":
            assert path == f"/storage/v1/object/{self.config.bucket}/{self.key}"
            assert request.headers["x-upsert"] == "false"
            assert request.content == self.data
            self.metadata = json.loads(base64.b64decode(request.headers["x-metadata"]))
            if self.collision:
                return httpx.Response(409, json={"statusCode": "409", "error": "Duplicate"})
            self.created = True
            if self.failure == "write_timeout":
                raise httpx.ReadTimeout("Private provider reply is not a public error", request=request)
            return httpx.Response(200, json={
                "Key": "wrong-key" if self.bad_ack else f"{self.config.bucket}/{self.key}",
                "Id": str(self.identifier), "version": str(self.version),
            })
        if "/info/authenticated/" in path:
            assert request.url.params["versionId"] == str(self.version)
            self.info_reads += 1
            if self.change_version and self.info_reads >= 2:
                self.version = uuid.uuid4()
            return httpx.Response(200, json={
                "id": str(self.identifier), "version": str(self.version), "name": self.key,
                "bucket_id": self.config.bucket, "size": len(self.data), "content_type": "image/png",
                "content_encoding": None,
                "metadata": {OWNERSHIP_FIELD: "wrong-owner" if self.bad_owner else str(self.operation)},
                "archived_at": None, "is_delete_marker": False, "is_versioned": True,
            })
        if request.method == "DELETE":
            assert json.loads(request.content) == {
                "prefixes": [{"path": self.key, "versionId": str(self.version)}],
            }
            if self.failure == "delete_timeout":
                raise httpx.ReadTimeout("Do not expose provider details", request=request)
            return httpx.Response(200, json=[] if self.bad_delete else [{
                "id": str(self.identifier), "name": self.key, "version": str(self.version),
            }])
        if "/object/authenticated/" in path:
            assert request.url.params["versionId"] == str(self.version)
            content = b"X" * len(self.data) if self.bad_hash else self.data
            return httpx.Response(200, content=content, headers={"content-type": "image/png"})
        raise AssertionError("Unexpected offline storage route")


async def upload(store, provider):
    return await store.create_only(
        key=provider.key, data=provider.data, mime_type="image/png", operation_id=provider.operation,
    )


@pytest.mark.parametrize("origin", [
    "http://private-project.supabase.co", "https://user:secret@private-project.supabase.co",
    "https://private-project.supabase.co/path", "https://private-project.supabase.co?token=value",
    "https://127.0.0.1", "https://private-project.supabase.co/",
])
def test_configuration_rejects_noncanonical_origins_without_echoing_secrets(config, origin):
    with pytest.raises(ValidationError) as error:
        SupabaseStorageConfig(**{**config.model_dump(), "service_role_key": config.service_role_key, "origin": origin})
    assert config.service_role_key not in str(error.value)


def test_storage_key_is_hidden_from_representations_and_exports(config):
    for value in (repr(config), str(config), config.model_dump(), config.model_dump_json()):
        if config.service_role_key in str(value):
            pytest.fail("Storage credential escaped its private configuration", pytrace=False)


@pytest.mark.asyncio
async def test_unapproved_storage_is_blocked_before_network(config):
    provider = Provider(config)
    store = SupabaseProofStore(config.model_copy(update={"approved_free": False}), transport=httpx.MockTransport(provider.handle))
    with pytest.raises(StorageUnavailable):
        await upload(store, provider)
    assert not provider.requests


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["public", "redirect"])
async def test_bucket_privacy_and_redirects_block_creation(config, mode):
    provider = Provider(config)
    provider.public = mode == "public"
    provider.failure = "bucket_redirect" if mode == "redirect" else ""
    store = SupabaseProofStore(config, transport=httpx.MockTransport(provider.handle))
    with pytest.raises(StorageUnavailable):
        await upload(store, provider)
    assert not provider.created
    assert all(request.url.host == "private-project.supabase.co" for request in provider.requests)


@pytest.mark.asyncio
async def test_create_only_requires_identity_and_exact_readback_then_reads_same_bytes(config):
    provider = Provider(config)
    store = SupabaseProofStore(config, transport=httpx.MockTransport(provider.handle))
    stored = await upload(store, provider)
    assert stored.operation_id == provider.operation and stored.object_id == provider.identifier
    assert provider.metadata == {OWNERSHIP_FIELD: str(provider.operation)}
    assert await store.read_verified(stored, provider.expected) == provider.data
    assert not any(request.method == "DELETE" for request in provider.requests)


@pytest.mark.asyncio
async def test_collision_is_never_adopted_or_deleted(config):
    provider = Provider(config)
    provider.collision = True
    store = SupabaseProofStore(config, transport=httpx.MockTransport(provider.handle))
    with pytest.raises(StorageConflict):
        await upload(store, provider)
    assert not provider.created and not any(request.method == "DELETE" for request in provider.requests)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["bad_ack", "bad_owner", "bad_hash", "change_version", "write_timeout"])
async def test_uncertain_created_objects_are_preserved_for_reconciliation(config, mode):
    provider = Provider(config)
    if mode == "write_timeout":
        provider.failure = mode
    else:
        setattr(provider, mode, True)
    store = SupabaseProofStore(config, transport=httpx.MockTransport(provider.handle))
    with pytest.raises(StorageWriteUncertain) as error:
        await upload(store, provider)
    assert provider.created and not any(request.method == "DELETE" for request in provider.requests)
    assert config.service_role_key not in str(error.value)


@pytest.mark.asyncio
async def test_cleanup_requires_exact_identity_and_removes_only_specific_version(config):
    provider = Provider(config)
    store = SupabaseProofStore(config, transport=httpx.MockTransport(provider.handle))
    stored = await upload(store, provider)
    await store.delete_owned_version(stored, provider.expected)
    assert sum(request.method == "DELETE" for request in provider.requests) == 1
    provider.bad_owner = True
    with pytest.raises(StorageUnavailable):
        await store.delete_owned_version(stored, provider.expected)
    assert sum(request.method == "DELETE" for request in provider.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["empty_ack", "delete_timeout"])
async def test_cleanup_uncertainty_is_explicit_without_unsafe_fallback(config, failure):
    provider = Provider(config)
    store = SupabaseProofStore(config, transport=httpx.MockTransport(provider.handle))
    stored = await upload(store, provider)
    provider.bad_delete = failure == "empty_ack"
    provider.failure = failure if failure == "delete_timeout" else ""
    with pytest.raises(StorageDeleteUncertain):
        await store.delete_owned_version(stored, provider.expected)
    assert sum(request.method == "DELETE" for request in provider.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["../outside.png", "folder/file.png", "A" * 32 + ".png", "a" * 32 + ".svg"])
async def test_invalid_object_keys_never_make_a_request(config, key):
    provider = Provider(config)
    provider.key = key
    store = SupabaseProofStore(config, transport=httpx.MockTransport(provider.handle))
    with pytest.raises(StorageIntegrityError):
        await upload(store, provider)
    assert not provider.requests


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["size", "mime", "oversized", "encoded", "truncated"])
async def test_read_rejects_metadata_transformations_and_byte_changes(config, mode):
    provider = Provider(config)
    store = SupabaseProofStore(config, transport=httpx.MockTransport(provider.handle))
    stored = await upload(store, provider)

    def changed(request):
        response = provider.handle(request)
        if "/info/authenticated/" in request.url.path and mode in {"size", "mime"}:
            metadata = response.json()
            if mode == "size":
                metadata["size"] += 1
            else:
                metadata["content_type"] = "image/jpeg"
            return httpx.Response(200, json=metadata)
        if "/object/authenticated/" in request.url.path:
            if mode == "oversized":
                return httpx.Response(200, content=provider.data + b"extra", headers={"content-type": "image/png"})
            if mode == "encoded":
                return httpx.Response(200, content=provider.data, headers={"content-type": "image/png", "content-encoding": "unknown"})
            if mode == "truncated":
                return httpx.Response(200, content=provider.data[:-1], headers={"content-type": "image/png", "content-length": str(len(provider.data))})
        return response

    store._transport = httpx.MockTransport(changed)
    with pytest.raises(StorageIntegrityError):
        await store.read_verified(stored, provider.expected)


@pytest.mark.asyncio
async def test_capacity_is_no_wait_and_released_after_a_coroutine_deadline(config):
    config = config.model_copy(update={"capacity": 1, "timeout_seconds": 0.1})
    provider = Provider(config)
    entered = asyncio.Event()
    release = asyncio.Event()

    async def wait(request):
        entered.set()
        await release.wait()
        return provider.handle(request)

    store = SupabaseProofStore(config, transport=httpx.MockTransport(wait))
    first = asyncio.create_task(upload(store, provider))
    await entered.wait()
    with pytest.raises(StorageUnavailable):
        await upload(store, provider)
    with pytest.raises(StorageUnavailable):
        await first
    store._transport = httpx.MockTransport(provider.handle)
    assert (await upload(store, provider)).operation_id == provider.operation


@pytest.mark.asyncio
async def test_cancellation_preserves_possible_created_content_and_releases_admission(config):
    config = config.model_copy(update={"capacity": 1})
    provider = Provider(config)
    entered = asyncio.Event()
    release = asyncio.Event()

    async def wait_after_write(request):
        response = provider.handle(request)
        if request.method == "POST":
            entered.set()
            await release.wait()
        return response

    store = SupabaseProofStore(config, transport=httpx.MockTransport(wait_after_write))
    first = asyncio.create_task(upload(store, provider))
    await entered.wait()
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    assert provider.created and not any(request.method == "DELETE" for request in provider.requests)
    provider.identifier, provider.version = uuid.uuid4(), uuid.uuid4()
    store._transport = httpx.MockTransport(provider.handle)
    assert (await upload(store, provider)).operation_id == provider.operation


@pytest.mark.parametrize("changes", [
    {"capacity": True}, {"capacity": 1.5}, {"capacity": 0}, {"timeout_seconds": True},
    {"timeout_seconds": float("nan")}, {"approved_free": "true"},
    {"bucket": "../another"}, {"service_role_key": "short"}, {"versioning_verified": "true"},
])
def test_configuration_limits_and_approvals_are_explicit(config, changes):
    with pytest.raises(ValidationError):
        SupabaseStorageConfig(**{**config.model_dump(), "service_role_key": config.service_role_key, **changes})


@pytest.mark.asyncio
async def test_unattested_versioning_never_contacts_storage(config):
    provider = Provider(config)
    store = SupabaseProofStore(
        config.model_copy(update={"versioning_verified": False}),
        transport=httpx.MockTransport(provider.handle),
    )
    with pytest.raises(StorageUnavailable):
        await upload(store, provider)
    assert not provider.requests


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [None, "DISABLED", "SUSPENDED", True])
async def test_bucket_must_retain_versions_before_any_upload(config, status):
    provider = Provider(config)

    def changed(request):
        response = provider.handle(request)
        if "/bucket/" in request.url.path:
            metadata = response.json()
            metadata["versioning_status"] = status
            return httpx.Response(200, json=metadata)
        return response

    store = SupabaseProofStore(config, transport=httpx.MockTransport(changed))
    with pytest.raises(StorageUnavailable):
        await upload(store, provider)
    assert not provider.created and not any(request.method == "DELETE" for request in provider.requests)


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [
    ("is_versioned", None), ("is_versioned", False),
    ("is_delete_marker", None), ("is_delete_marker", True),
])
async def test_ambiguous_version_identity_remains_uncertain_not_adopted(config, field, value):
    provider = Provider(config)

    def changed(request):
        response = provider.handle(request)
        if "/info/authenticated/" in request.url.path:
            metadata = response.json()
            metadata[field] = value
            return httpx.Response(200, json=metadata)
        return response

    store = SupabaseProofStore(config, transport=httpx.MockTransport(changed))
    with pytest.raises(StorageWriteUncertain):
        await upload(store, provider)
    assert provider.created and not any(request.method == "DELETE" for request in provider.requests)


@pytest.mark.asyncio
async def test_archived_recorded_version_is_read_without_latest_fallback(config):
    provider = Provider(config)
    store = SupabaseProofStore(config, transport=httpx.MockTransport(provider.handle))
    stored = await upload(store, provider)
    current_version = uuid.uuid4()

    def versioned(request):
        if "/info/authenticated/" in request.url.path or "/object/authenticated/" in request.url.path:
            assert request.url.params["versionId"] == str(stored.version)
        response = provider.handle(request)
        if "/info/authenticated/" in request.url.path:
            metadata = response.json()
            metadata["archived_at"] = "2026-11-12T00:00:00Z"
            assert metadata["version"] != str(current_version)
            return httpx.Response(200, json=metadata)
        return response

    store._transport = httpx.MockTransport(versioned)
    assert await store.read_verified(stored, provider.expected) == provider.data
    assert not any(request.method == "DELETE" for request in provider.requests)
