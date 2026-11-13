"""Bounded private Supabase Storage transport; never publishes an object URL."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
import threading
import uuid
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.infrastructure.storage.contracts import (
    ExpectedProof, StorageConflict, StorageDeleteUncertain, StorageIntegrityError,
    StorageUnavailable, StorageWriteUncertain, StoredObject,
)

MAX_PROOF_BYTES = 5 * 1024 * 1024
MAX_METADATA_BYTES = 64 * 1024
OWNERSHIP_FIELD = "supplyos_upload_operation"
KEY_PATTERN = re.compile(r"[0-9a-f]{32}\.(png|jpg)")


class SupabaseStorageConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)
    origin: str
    bucket: str
    service_role_key: str = Field(min_length=32, max_length=4096, repr=False, exclude=True)
    approved_free: bool = Field(default=False, strict=True)
    versioning_verified: bool = Field(default=False, strict=True)
    timeout_seconds: float = Field(default=10, ge=0.1, le=30, allow_inf_nan=False, strict=True)
    capacity: int = Field(default=4, ge=1, le=16, strict=True)

    @model_validator(mode="after")
    def validate_private_configuration(self) -> "SupabaseStorageConfig":
        if not re.fullmatch(r"https://[a-z0-9-]{3,63}\.supabase\.co", self.origin):
            raise ValueError("Storage needs a canonical HTTPS Supabase project origin")
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,62}", self.bucket):
            raise ValueError("Storage bucket name is invalid")
        if not 32 <= len(self.service_role_key) <= 4096 or any(
            char.isspace() or ord(char) < 32 for char in self.service_role_key
        ):
            raise ValueError("Storage needs a private service credential")
        if not 0.1 <= self.timeout_seconds <= 30 or not 1 <= self.capacity <= 16:
            raise ValueError("Storage deadline or capacity is invalid")
        return self


class SupabaseProofStore:
    """Create/read immutable private versions; callers own durable reservations."""

    def __init__(
        self, config: SupabaseStorageConfig, *, transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._config = config
        self._transport = transport
        self._slots = threading.BoundedSemaphore(config.capacity)

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._config.origin + "/storage/v1/", follow_redirects=False,
            timeout=self._config.timeout_seconds, transport=self._transport,
            trust_env=False, verify=True,
            headers={
                "Authorization": "Bearer " + self._config.service_role_key,
                "apikey": self._config.service_role_key,
                "Accept-Encoding": "identity", "Cache-Control": "no-store",
            },
        )

    def _admit(self) -> None:
        if not self._config.approved_free or not self._config.versioning_verified or not self._slots.acquire(False):
            raise StorageUnavailable()

    @staticmethod
    def _validate_expected(key: str, expected: ExpectedProof) -> None:
        match = KEY_PATTERN.fullmatch(key)
        if match is None or type(expected.size_bytes) is not int or not 1 <= expected.size_bytes <= MAX_PROOF_BYTES:
            raise StorageIntegrityError()
        mime = "image/png" if match[1] == "png" else "image/jpeg"
        if expected.mime_type != mime or not re.fullmatch(r"[0-9a-f]{64}", expected.sha256):
            raise StorageIntegrityError()

    async def _body(self, response: httpx.Response, limit: int) -> bytes:
        if response.headers.get("content-encoding", "identity").lower() != "identity":
            raise StorageIntegrityError()
        length = response.headers.get("content-length")
        if length is not None and (
            len(length) > 20 or not length.isascii() or not length.isdigit() or int(length) > limit
        ):
            raise StorageIntegrityError()
        data = bytearray()
        async for chunk in response.aiter_bytes():
            if len(data) + len(chunk) > limit:
                raise StorageIntegrityError()
            data.extend(chunk)
        if length is not None and len(data) != int(length):
            raise StorageIntegrityError()
        return bytes(data)

    async def _json(
        self, client: httpx.AsyncClient, method: str, path: str, **options: Any,
    ) -> tuple[int, Any]:
        async with client.stream(method, path, **options) as response:
            body = await self._body(response, MAX_METADATA_BYTES)
            try:
                return response.status_code, json.loads(body)
            except (ValueError, UnicodeError):
                raise StorageIntegrityError() from None

    async def _private_bucket(self, client: httpx.AsyncClient) -> None:
        status, metadata = await self._json(client, "GET", "bucket/" + self._config.bucket)
        if status != 200:
            raise StorageUnavailable()
        if not isinstance(metadata, dict) or metadata.get("public") is not False or (
            metadata.get("id") != self._config.bucket or metadata.get("name") != self._config.bucket
            or metadata.get("versioning_status") != "ENABLED"
        ):
            raise StorageIntegrityError()

    async def _info(
        self, client: httpx.AsyncClient, key: str, operation_id: uuid.UUID,
        expected: ExpectedProof, *, version: uuid.UUID | None = None,
    ) -> StoredObject:
        status, info = await self._json(
            client, "GET", f"object/info/authenticated/{self._config.bucket}/{key}",
            params={"versionId": str(version)} if version is not None else None,
        )
        if status != 200 or not isinstance(info, dict):
            raise StorageUnavailable()
        metadata = info.get("metadata")
        if (
            info.get("name") != key or info.get("bucket_id") != self._config.bucket
            or type(info.get("size")) is not int or info["size"] != expected.size_bytes
            or info.get("content_type") != expected.mime_type
            or info.get("content_encoding") not in {None, "identity"}
            or not isinstance(metadata, dict) or metadata.get(OWNERSHIP_FIELD) != str(operation_id)
            or info.get("is_delete_marker") is not False or info.get("is_versioned") is not True
            or (version is None and info.get("archived_at") is not None)
        ):
            raise StorageIntegrityError()
        try:
            result = StoredObject(key, uuid.UUID(info["id"]), uuid.UUID(info["version"]), operation_id)
        except (KeyError, ValueError, TypeError, AttributeError):
            raise StorageIntegrityError() from None
        if version is not None and result.version != version:
            raise StorageIntegrityError()
        return result

    async def _read(
        self, client: httpx.AsyncClient, stored: StoredObject, expected: ExpectedProof,
    ) -> bytes:
        before = await self._info(
            client, stored.key, stored.operation_id, expected, version=stored.version,
        )
        if before != stored:
            raise StorageIntegrityError()
        async with client.stream(
            "GET", f"object/authenticated/{self._config.bucket}/{stored.key}",
            params={"versionId": str(stored.version)},
        ) as response:
            if response.status_code != 200 or response.headers.get("content-type") != expected.mime_type:
                raise StorageIntegrityError()
            data = await self._body(response, expected.size_bytes)
        if len(data) != expected.size_bytes or hashlib.sha256(data).hexdigest() != expected.sha256:
            raise StorageIntegrityError()
        after = await self._info(
            client, stored.key, stored.operation_id, expected, version=stored.version,
        )
        if after != stored:
            raise StorageIntegrityError()
        return data

    async def create_only(
        self, *, key: str, data: bytes, mime_type: str, operation_id: uuid.UUID,
    ) -> StoredObject:
        if type(data) is not bytes or not 1 <= len(data) <= MAX_PROOF_BYTES or not isinstance(operation_id, uuid.UUID):
            raise StorageIntegrityError()
        expected = ExpectedProof(len(data), mime_type, hashlib.sha256(data).hexdigest())
        self._validate_expected(key, expected)
        self._admit()
        write_started = False
        try:
            async with asyncio.timeout(self._config.timeout_seconds), self._client() as client:
                await self._private_bucket(client)
                metadata = base64.b64encode(json.dumps({OWNERSHIP_FIELD: str(operation_id)}).encode()).decode()
                write_started = True
                status, acknowledgement = await self._json(
                    client, "POST", f"object/{self._config.bucket}/{key}", content=data,
                    headers={"Content-Type": mime_type, "x-upsert": "false", "x-metadata": metadata},
                )
                if status in {400, 409} and isinstance(acknowledgement, dict) and (
                    str(acknowledgement.get("statusCode")) == "409"
                    or acknowledgement.get("code") in {"Duplicate", "KeyAlreadyExists"}
                ):
                    raise StorageConflict()
                if status not in {200, 201} or not isinstance(acknowledgement, dict):
                    raise StorageWriteUncertain()
                try:
                    stored = StoredObject(
                        key, uuid.UUID(acknowledgement["Id"]),
                        uuid.UUID(acknowledgement["version"]), operation_id,
                    )
                except (KeyError, ValueError, TypeError, AttributeError):
                    raise StorageWriteUncertain() from None
                if acknowledgement.get("Key") != f"{self._config.bucket}/{key}" or stored.object_id == stored.version:
                    raise StorageWriteUncertain()
                await self._read(client, stored, expected)
                return stored
        except StorageConflict:
            raise
        except asyncio.CancelledError:
            raise
        except (httpx.HTTPError, TimeoutError, StorageIntegrityError, StorageUnavailable):
            if write_started:
                raise StorageWriteUncertain() from None
            raise StorageUnavailable() from None
        finally:
            self._slots.release()

    async def read_verified(self, stored: StoredObject, expected: ExpectedProof) -> bytes:
        self._validate_expected(stored.key, expected)
        self._admit()
        try:
            async with asyncio.timeout(self._config.timeout_seconds), self._client() as client:
                await self._private_bucket(client)
                return await self._read(client, stored, expected)
        except (httpx.HTTPError, TimeoutError):
            raise StorageUnavailable() from None
        finally:
            self._slots.release()

    async def delete_owned_version(self, stored: StoredObject, expected: ExpectedProof) -> None:
        """Caller must first prove the durable operation has no committed receipt."""
        self._validate_expected(stored.key, expected)
        self._admit()
        delete_started = False
        try:
            async with asyncio.timeout(self._config.timeout_seconds), self._client() as client:
                await self._private_bucket(client)
                selected = await self._info(
                    client, stored.key, stored.operation_id, expected, version=stored.version,
                )
                if selected != stored:
                    raise StorageIntegrityError()
                delete_started = True
                status, removed = await self._json(
                    client, "DELETE", f"object/{self._config.bucket}",
                    json={"prefixes": [{"path": stored.key, "versionId": str(stored.version)}]},
                )
                if status != 200 or not isinstance(removed, list) or len(removed) != 1 or not isinstance(removed[0], dict) or (
                    removed[0].get("id") != str(stored.object_id)
                    or removed[0].get("name") != stored.key
                    or removed[0].get("version") != str(stored.version)
                ):
                    raise StorageDeleteUncertain()
        except asyncio.CancelledError:
            raise
        except (httpx.HTTPError, TimeoutError, StorageIntegrityError, StorageUnavailable):
            if delete_started:
                raise StorageDeleteUncertain() from None
            raise StorageUnavailable() from None
        finally:
            self._slots.release()
