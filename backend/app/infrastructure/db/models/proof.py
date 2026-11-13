"""Private delivery-bound proof receipts; storage is never publicly mounted."""
from __future__ import annotations

import uuid
from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.infrastructure.db.base import Base, TimestampMixin, UUIDPKMixin


class DeliveryProof(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "delivery_proofs"
    __table_args__ = (
        Index("ix_proofs_tenant_delivery", "tenant_id", "delivery_id"),
        CheckConstraint("kind IN ('signature', 'photo')", name="valid_kind"),
        CheckConstraint("size_bytes > 0", name="positive_size"),
        CheckConstraint(
            "(storage_backend = 'local' AND storage_origin IS NULL AND storage_bucket IS NULL "
            "AND provider_object_id IS NULL AND provider_version IS NULL) OR "
            "(storage_backend = 'supabase' AND storage_origin IS NOT NULL "
            "AND storage_bucket IS NOT NULL AND provider_object_id IS NOT NULL "
            "AND provider_version IS NOT NULL AND upload_operation_id IS NOT NULL)",
            name="storage_identity",
        ),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    delivery_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("deliveries.id", ondelete="RESTRICT"), nullable=False)
    uploaded_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    object_key: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    mime_type: Mapped[str] = mapped_column(String(40), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_backend: Mapped[str] = mapped_column(
        String(20), nullable=False, default="local", server_default=text("'local'")
    )
    storage_origin: Mapped[str | None] = mapped_column(String(120))
    storage_bucket: Mapped[str | None] = mapped_column(String(63))
    provider_object_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    provider_version: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    upload_operation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("proof_upload_operations.id", ondelete="RESTRICT"), unique=True
    )


class ProofUploadOperation(Base, UUIDPKMixin, TimestampMixin):
    """Durable pre-write ownership; ambiguous writes are retained, never deleted."""

    __tablename__ = "proof_upload_operations"
    __table_args__ = (
        Index("ix_proof_uploads_tenant_delivery", "tenant_id", "delivery_id"),
        Index("ix_proof_uploads_state_created", "state", "created_at"),
        CheckConstraint("state IN ('reserved', 'committed')", name="valid_state"),
        CheckConstraint("kind IN ('signature', 'photo')", name="valid_kind"),
        CheckConstraint("size_bytes > 0 AND size_bytes <= 5242880", name="bounded_size"),
        CheckConstraint(
            "(storage_backend = 'local' AND storage_origin IS NULL AND storage_bucket IS NULL) OR "
            "(storage_backend = 'supabase' AND storage_origin IS NOT NULL AND storage_bucket IS NOT NULL)",
            name="storage_location",
        ),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    delivery_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("deliveries.id", ondelete="RESTRICT"), nullable=False
    )
    uploaded_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    object_key: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    mime_type: Mapped[str] = mapped_column(String(40), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_backend: Mapped[str] = mapped_column(String(20), nullable=False)
    storage_origin: Mapped[str | None] = mapped_column(String(120))
    storage_bucket: Mapped[str | None] = mapped_column(String(63))
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="reserved")
