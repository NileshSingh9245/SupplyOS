"""Claim optional UUID keys in the same database transaction as their effects."""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import Conflict
from app.infrastructure.db.models.idempotency import IdempotencyRecord


def _canonical(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _canonical(value.model_dump(mode="python"))
    if isinstance(value, dict):
        return {str(key): _canonical(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if isinstance(value, Decimal):
        return format(value.normalize(), "f") if value else "0"
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    return value


async def claim(
    db: AsyncSession, *, tenant_id: uuid.UUID, actor_id: uuid.UUID, operation: str,
    key: uuid.UUID | None, payload: Any,
) -> IdempotencyRecord | None:
    """A conflicting insert waits for the original effect's commit or rollback."""
    if key is None:
        return None
    encoded = json.dumps(_canonical(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    fingerprint = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    identifier = uuid.uuid4()
    inserted = (await db.execute(insert(IdempotencyRecord).values(
        id=identifier, tenant_id=tenant_id, actor_id=actor_id, operation=operation,
        key=key, fingerprint=fingerprint,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
    ).on_conflict_do_nothing(index_elements=[
        IdempotencyRecord.tenant_id, IdempotencyRecord.actor_id,
        IdempotencyRecord.operation, IdempotencyRecord.key,
    ]).returning(IdempotencyRecord.id))).scalar_one_or_none()
    record = (await db.execute(select(IdempotencyRecord).where(
        IdempotencyRecord.tenant_id == tenant_id, IdempotencyRecord.actor_id == actor_id,
        IdempotencyRecord.operation == operation, IdempotencyRecord.key == key,
    ).with_for_update().execution_options(populate_existing=True))).scalar_one()
    if record.fingerprint != fingerprint:
        raise Conflict("Idempotency key was already used with a different payload")
    if inserted is None and record.response_body is None:
        raise Conflict("Incomplete idempotency claim needs reviewed reconciliation")
    # Retained records never permit a second financial effect, even beyond the 24h minimum.
    return record


def remember(
    record: IdempotencyRecord | None, *, response: BaseModel, status_code: int,
    resource_type: str, resource_id: uuid.UUID,
) -> None:
    if record is not None:
        record.response_body = response.model_dump(mode="json")
        record.response_status = status_code
        record.resource_type = resource_type
        record.resource_id = resource_id
