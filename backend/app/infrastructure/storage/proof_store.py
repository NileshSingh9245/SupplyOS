"""Private proof storage selected explicitly; receipt provenance prevents fallback."""
from __future__ import annotations

import hashlib
import re
import uuid
from asyncio import to_thread
from functools import lru_cache

from app.core.config import Settings, get_settings
from app.infrastructure.db.models.proof import DeliveryProof, ProofUploadOperation
from app.infrastructure.storage.contracts import (
    ExpectedProof, StorageIntegrityError, StorageUnavailable, StoredObject,
)
from app.infrastructure.storage.local import create_private_file, read_private_file
from app.infrastructure.storage.supabase import SupabaseProofStore, SupabaseStorageConfig

MAX_PROOF_BYTES = 5 * 1024 * 1024


class ProofStore:
    def __init__(self, settings: Settings, *, hosted: SupabaseProofStore | None = None) -> None:
        self.settings = settings
        self.hosted = hosted
        if hosted is None and all((
            settings.supabase_storage_origin, settings.supabase_storage_bucket, settings.supabase_storage_key,
        )):
            self.hosted = SupabaseProofStore(SupabaseStorageConfig(
                origin=settings.supabase_storage_origin, bucket=settings.supabase_storage_bucket,
                service_role_key=settings.supabase_storage_key,
                approved_free=not settings.free_only_mode or settings.approved_free_storage,
                versioning_verified=settings.supabase_versioning_verified,
                timeout_seconds=settings.proof_storage_timeout_seconds,
                capacity=settings.proof_storage_capacity,
            ))

    def check_location(self, record: DeliveryProof | ProofUploadOperation) -> ExpectedProof:
        match = re.fullmatch(r"[0-9a-f]{32}\.(png|jpg)", record.object_key)
        if match is None or type(record.size_bytes) is not int or not 1 <= record.size_bytes <= MAX_PROOF_BYTES:
            raise StorageIntegrityError()
        mime = "image/png" if match[1] == "png" else "image/jpeg"
        if record.mime_type != mime or not re.fullmatch(r"[0-9a-f]{64}", record.sha256):
            raise StorageIntegrityError()
        if record.storage_backend == "local":
            if record.storage_origin is not None or record.storage_bucket is not None:
                raise StorageIntegrityError()
        elif record.storage_backend == "supabase":
            if (
                self.hosted is None or record.storage_origin != self.settings.supabase_storage_origin
                or record.storage_bucket != self.settings.supabase_storage_bucket
                or (self.settings.free_only_mode and not self.settings.approved_free_storage)
                or not self.settings.supabase_versioning_verified
            ):
                raise StorageUnavailable()
        else:
            raise StorageIntegrityError()
        return ExpectedProof(record.size_bytes, record.mime_type, record.sha256)

    async def create(self, operation: ProofUploadOperation, data: bytes) -> StoredObject | None:
        expected = self.check_location(operation)
        if type(data) is not bytes or len(data) != expected.size_bytes or (
            hashlib.sha256(data).hexdigest() != expected.sha256
        ):
            raise StorageIntegrityError()
        if operation.storage_backend == "supabase":
            return await self.hosted.create_only(
                key=operation.object_key, data=data, mime_type=expected.mime_type,
                operation_id=operation.id,
            )
        try:
            await to_thread(create_private_file, self.settings.proof_storage_dir, operation.object_key, data)
            stored = await to_thread(
                read_private_file, self.settings.proof_storage_dir, operation.object_key,
                limit=expected.size_bytes,
            )
        except (RuntimeError, OSError):
            raise StorageUnavailable() from None
        if len(stored) != expected.size_bytes or hashlib.sha256(stored).hexdigest() != expected.sha256:
            raise StorageIntegrityError()
        return None

    async def read(self, proof: DeliveryProof) -> bytes:
        expected = self.check_location(proof)
        if proof.storage_backend == "supabase":
            if not all(isinstance(value, uuid.UUID) for value in (
                proof.provider_object_id, proof.provider_version, proof.upload_operation_id,
            )):
                raise StorageIntegrityError()
            return await self.hosted.read_verified(StoredObject(
                proof.object_key, proof.provider_object_id, proof.provider_version,
                proof.upload_operation_id,
            ), expected)
        if proof.provider_object_id is not None or proof.provider_version is not None:
            raise StorageIntegrityError()
        try:
            data = await to_thread(
                read_private_file, self.settings.proof_storage_dir, proof.object_key,
                limit=expected.size_bytes,
            )
        except (RuntimeError, OSError):
            raise StorageUnavailable() from None
        if len(data) != expected.size_bytes or hashlib.sha256(data).hexdigest() != expected.sha256:
            raise StorageIntegrityError()
        return data


@lru_cache(maxsize=4)
def _configured_store(settings: Settings) -> ProofStore:
    return ProofStore(settings)


def get_proof_store() -> ProofStore:
    return _configured_store(get_settings())
