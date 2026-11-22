"""Private immutable object identities and sanitized storage failures."""
from __future__ import annotations

import uuid
from dataclasses import dataclass


class StorageUnavailable(RuntimeError):
    def __init__(self) -> None:
        super().__init__("Private proof storage is unavailable")


class StorageConflict(RuntimeError):
    def __init__(self) -> None:
        super().__init__("Private object already exists")


class StorageIntegrityError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("Private proof identity or integrity is invalid")


class StorageWriteUncertain(RuntimeError):
    def __init__(self) -> None:
        super().__init__("Private upload outcome requires reconciliation")


class StorageDeleteUncertain(RuntimeError):
    def __init__(self) -> None:
        super().__init__("Private cleanup outcome requires reconciliation")


@dataclass(frozen=True, slots=True)
class StoredObject:
    key: str
    object_id: uuid.UUID
    version: uuid.UUID
    operation_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class ExpectedProof:
    size_bytes: int
    mime_type: str
    sha256: str
