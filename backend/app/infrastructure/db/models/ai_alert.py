"""AI supervisor generated alerts."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import String, Boolean, DateTime, Index, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, TimestampMixin, UUIDPKMixin
from app.core.enums import AlertSeverity, AlertCategory


class AIAlert(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "ai_alerts"
    __table_args__ = (
        Index("ix_alerts_tenant_created", "tenant_id", "created_at"),
        Index("ix_alerts_tenant_dismissed", "tenant_id", "is_dismissed"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    category: Mapped[str] = mapped_column(String(30), nullable=False, default=AlertCategory.OPERATIONS.value)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default=AlertSeverity.INFO.value)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    message: Mapped[str] = mapped_column(String(1000), nullable=False)
    action_hint: Mapped[str | None] = mapped_column(String(300))
    resource_type: Mapped[str | None] = mapped_column(String(30))
    resource_id: Mapped[str | None] = mapped_column(String(64))
    meta: Mapped[dict | None] = mapped_column(JSON, default=dict)
    is_dismissed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dismissed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
