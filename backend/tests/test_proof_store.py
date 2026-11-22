"""Storage provenance and held-handle reads, with offline hosted transports only."""
from __future__ import annotations

import hashlib
import secrets
import uuid
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.infrastructure.db.models.proof import DeliveryProof, ProofUploadOperation
from app.infrastructure.storage.contracts import StorageIntegrityError, StorageUnavailable
from app.infrastructure.storage.local import create_private_file, read_private_file
from app.infrastructure.storage.proof_store import ProofStore
from app.infrastructure.storage.supabase import SupabaseProofStore, SupabaseStorageConfig
from test_supabase_storage import Provider, png


@pytest.fixture
def settings(tmp_path):
    return Settings(
        _env_file=None, app_env="test", free_only_mode=True, approved_free_smtp=False,
        database_url="postgresql+asyncpg://test_user@127.0.0.1/supplyos_test_storage",
        database_url_sync="postgresql+psycopg2://test_user@127.0.0.1/supplyos_test_storage",
        redis_url="redis://127.0.0.1:6379/0", jwt_secret=secrets.token_urlsafe(48),
        smtp_enabled=False, smtp_host="", smtp_username="", smtp_password="", smtp_from="",
        password_reset_url="", anthropic_api_key="", proof_storage_dir=tmp_path / "proofs",
        proof_storage_backend="local", approved_free_storage=False,
        supabase_versioning_verified=False,
        supabase_storage_origin="", supabase_storage_bucket="", supabase_storage_key="",
        proof_storage_timeout_seconds=10, proof_storage_capacity=4,
    )


def records(*, backend="local", origin=None, bucket=None):
    identifier, operation_id = uuid.uuid4(), uuid.uuid4()
    values = {
        "tenant_id": uuid.uuid4(), "delivery_id": uuid.uuid4(), "uploaded_by": uuid.uuid4(),
        "kind": "photo", "object_key": identifier.hex + ".png", "mime_type": "image/png",
        "size_bytes": len(png()), "sha256": hashlib.sha256(png()).hexdigest(),
        "storage_backend": backend, "storage_origin": origin, "storage_bucket": bucket,
    }
    return (
        ProofUploadOperation(id=operation_id, state="reserved", **values),
        DeliveryProof(id=identifier, upload_operation_id=operation_id, **values),
    )


@pytest.mark.asyncio
async def test_local_write_and_verified_bytes_preserve_legacy_receipt_read(settings):
    operation, proof = records()
    store = ProofStore(settings)
    assert await store.create(operation, png()) is None
    assert await store.read(proof) == png()
    proof.upload_operation_id = None
    assert await store.read(proof) == png()


@pytest.mark.asyncio
async def test_corruption_is_not_served(settings):
    _, proof = records()
    create_private_file(settings.proof_storage_dir, proof.object_key, b"X" * proof.size_bytes)
    with pytest.raises(StorageIntegrityError):
        await ProofStore(settings).read(proof)


@pytest.mark.asyncio
async def test_changed_digest_or_payload_cannot_create_a_file(settings):
    operation, _ = records()
    with pytest.raises(StorageIntegrityError):
        await ProofStore(settings).create(operation, b"X" * operation.size_bytes)
    assert not settings.proof_storage_dir.exists()


@pytest.mark.parametrize("limit", [0, True, 5 * 1024 * 1024 + 1, "10"])
def test_local_read_limit_is_bounded(settings, limit):
    operation, _ = records()
    create_private_file(settings.proof_storage_dir, operation.object_key, png())
    with pytest.raises(RuntimeError):
        read_private_file(settings.proof_storage_dir, operation.object_key, limit=limit)


def test_read_does_not_reopen_checked_path(settings, monkeypatch):
    operation, _ = records()
    create_private_file(settings.proof_storage_dir, operation.object_key, png())

    def forbidden_open(*args, **kwargs):
        pytest.fail("Checked proof bytes were reopened using an unheld path", pytrace=False)

    monkeypatch.setattr(Path, "open", forbidden_open)
    assert read_private_file(settings.proof_storage_dir, operation.object_key, limit=len(png())) == png()
    with pytest.raises(RuntimeError):
        read_private_file(settings.proof_storage_dir, operation.object_key, limit=len(png()) - 1)


@pytest.mark.asyncio
async def test_hosted_receipt_uses_exact_provider_identity_and_no_local_fallback(settings):
    config = SupabaseStorageConfig(
        origin="https://private-project.supabase.co", bucket="delivery-proofs",
        service_role_key=secrets.token_urlsafe(48), approved_free=True, versioning_verified=True,
    )
    settings = Settings(**{
        **settings.model_dump(), "_env_file": None,
        "database_url": settings.database_url, "database_url_sync": settings.database_url_sync,
        "redis_url": settings.redis_url, "jwt_secret": settings.jwt_secret,
        "proof_storage_backend": "supabase", "approved_free_storage": True,
        "supabase_versioning_verified": True,
        "supabase_storage_origin": config.origin, "supabase_storage_bucket": config.bucket,
        "supabase_storage_key": config.service_role_key,
        "anthropic_api_key": "", "smtp_username": "", "smtp_password": "",
    })
    operation, proof = records(backend="supabase", origin=config.origin, bucket=config.bucket)
    provider = Provider(config)
    provider.key, provider.operation = operation.object_key, operation.id
    hosted = SupabaseProofStore(config, transport=httpx.MockTransport(provider.handle))
    store = ProofStore(settings, hosted=hosted)
    stored = await store.create(operation, png())
    proof.provider_object_id, proof.provider_version = stored.object_id, stored.version
    assert await store.read(proof) == png()
    assert not settings.proof_storage_dir.exists()
    proof.storage_origin = "https://another-project.supabase.co"
    with pytest.raises(StorageUnavailable):
        await store.read(proof)
    assert not settings.proof_storage_dir.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [
    ("storage_backend", "unknown"), ("object_key", "../outside.png"),
    ("mime_type", "image/svg+xml"), ("sha256", "not-a-digest"),
    ("size_bytes", 0), ("storage_origin", "https://unselected.example.com"),
    ("provider_version", uuid.UUID(int=1)),
])
async def test_invalid_local_receipt_provenance_is_rejected(settings, field, value):
    _, proof = records()
    setattr(proof, field, value)
    with pytest.raises(StorageIntegrityError):
        await ProofStore(settings).read(proof)


@pytest.mark.parametrize("field,value", [
    ("supabase_storage_origin", "http://private-project.supabase.co"),
    ("supabase_storage_origin", "https://user:secret@private-project.supabase.co"),
    ("supabase_storage_origin", "https://private-project.supabase.co/path"),
    ("supabase_storage_bucket", "../public"), ("supabase_storage_key", "short"),
    ("proof_storage_capacity", 0), ("proof_storage_timeout_seconds", float("inf")),
])
def test_hosted_configuration_rejects_unsafe_values(settings, field, value):
    values = settings.model_dump()
    values.update(
        _env_file=None, database_url=settings.database_url, database_url_sync=settings.database_url_sync,
        redis_url=settings.redis_url, jwt_secret=settings.jwt_secret,
        anthropic_api_key="", smtp_username="", smtp_password="", supabase_storage_key="",
    )
    values[field] = value
    with pytest.raises(ValidationError):
        Settings(**values)


def test_hosted_credentials_are_not_exported(settings):
    private_key = secrets.token_urlsafe(48)
    settings = settings.model_copy(update={"supabase_storage_key": private_key})
    assert "supabase_storage_key" not in settings.model_dump()
    if private_key in repr(settings) or private_key in settings.model_dump_json():
        pytest.fail("A private storage credential escaped configuration", pytrace=False)


@pytest.mark.asyncio
async def test_unapproved_hosted_access_cannot_contact_provider(settings):
    operation, _ = records(
        backend="supabase", origin="https://private-project.supabase.co", bucket="delivery-proofs",
    )
    with pytest.raises(StorageUnavailable):
        await ProofStore(settings).create(operation, png())
    assert not settings.proof_storage_dir.exists()
