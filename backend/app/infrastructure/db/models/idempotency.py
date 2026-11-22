"""Durable request claims and success responses, committed with financial effects."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.base import Base, TimestampMixin, UUIDPKMixin


class IdempotencyRecord(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        Index("ix_idempotency_scope", "tenant_id", "actor_id", "operation", "key", unique=True),
        Index("ix_idempotency_records_tenant_id", "tenant_id"),
        Index("ix_idempotency_records_actor_id", "actor_id"),
        Index("ix_idempotency_records_expires_at", "expires_at"),
        CheckConstraint(
            "(response_body IS NULL AND response_status IS NULL AND resource_id IS NULL "
            "AND resource_type IS NULL) OR (response_body IS NOT NULL "
            "AND response_status BETWEEN 200 AND 299 AND resource_id IS NOT NULL "
            "AND resource_type IS NOT NULL)", name="response_state",
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False,
    )
    actor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False,
    )
    operation: Mapped[str] = mapped_column(String(80), nullable=False)
    key: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    response_body: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    response_status: Mapped[int | None] = mapped_column(Integer)
    resource_type: Mapped[str | None] = mapped_column(String(30))
    resource_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
