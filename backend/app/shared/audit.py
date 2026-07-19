"""Audit logger helper — call inside services on write operations."""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models.user import AuditLog


async def audit(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID | None,
    actor_id: uuid.UUID | None,
    actor_email: str | None,
    action: str,
    resource_type: str | None = None,
    resource_id: str | None = None,
    ip_address: str | None = None,
    meta: dict[str, Any] | None = None,
) -> None:
    entry = AuditLog(
        tenant_id=tenant_id,
        actor_id=actor_id,
        actor_email=actor_email,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        ip_address=ip_address,
        metadata_json=meta or {},
    )
    db.add(entry)
