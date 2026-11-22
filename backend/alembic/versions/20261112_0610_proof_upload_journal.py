"""Reserve private proof writes and persist hosted receipt provenance."""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20261112_0006"
down_revision = "20261109_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "proof_upload_operations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("delivery_id", sa.UUID(), nullable=False),
        sa.Column("uploaded_by", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("object_key", sa.String(80), nullable=False),
        sa.Column("mime_type", sa.String(40), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("storage_backend", sa.String(20), nullable=False),
        sa.Column("storage_origin", sa.String(120)),
        sa.Column("storage_bucket", sa.String(63)),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_proof_upload_operations")),
        sa.ForeignKeyConstraint(
            ["delivery_id"], ["deliveries.id"], ondelete="RESTRICT",
            name=op.f("fk_proof_upload_operations_delivery_id_deliveries"),
        ),
        sa.UniqueConstraint("object_key", name=op.f("uq_proof_upload_operations_object_key")),
        sa.CheckConstraint("state IN ('reserved', 'committed')", name=op.f("ck_proof_upload_operations_valid_state")),
        sa.CheckConstraint("kind IN ('signature', 'photo')", name=op.f("ck_proof_upload_operations_valid_kind")),
        sa.CheckConstraint("size_bytes > 0 AND size_bytes <= 5242880", name=op.f("ck_proof_upload_operations_bounded_size")),
        sa.CheckConstraint(
            "(storage_backend = 'local' AND storage_origin IS NULL AND storage_bucket IS NULL) OR "
            "(storage_backend = 'supabase' AND storage_origin IS NOT NULL AND storage_bucket IS NOT NULL)",
            name=op.f("ck_proof_upload_operations_storage_location"),
        ),
    )
    op.create_index("ix_proof_uploads_tenant_delivery", "proof_upload_operations", ["tenant_id", "delivery_id"])
    op.create_index("ix_proof_uploads_state_created", "proof_upload_operations", ["state", "created_at"])
    op.execute("ALTER TABLE proof_upload_operations ENABLE ROW LEVEL SECURITY")
    op.execute("REVOKE ALL ON proof_upload_operations FROM PUBLIC")
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
            REVOKE ALL ON proof_upload_operations FROM anon;
        END IF;
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
            REVOKE ALL ON proof_upload_operations FROM authenticated;
        END IF;
    END $$""")
    for column in (
        sa.Column("storage_backend", sa.String(20), nullable=False, server_default=sa.text("'local'")),
        sa.Column("storage_origin", sa.String(120)), sa.Column("storage_bucket", sa.String(63)),
        sa.Column("provider_object_id", sa.UUID()), sa.Column("provider_version", sa.UUID()),
        sa.Column("upload_operation_id", sa.UUID()),
    ):
        op.add_column("delivery_proofs", column)
    op.create_foreign_key(
        op.f("fk_delivery_proofs_upload_operation_id_proof_upload_operations"),
        "delivery_proofs", "proof_upload_operations", ["upload_operation_id"], ["id"], ondelete="RESTRICT",
    )
    op.create_unique_constraint(op.f("uq_delivery_proofs_upload_operation_id"), "delivery_proofs", ["upload_operation_id"])
    op.create_check_constraint(
        op.f("ck_delivery_proofs_storage_identity"), "delivery_proofs",
        "(storage_backend = 'local' AND storage_origin IS NULL AND storage_bucket IS NULL "
        "AND provider_object_id IS NULL AND provider_version IS NULL) OR "
        "(storage_backend = 'supabase' AND storage_origin IS NOT NULL "
        "AND storage_bucket IS NOT NULL AND provider_object_id IS NOT NULL "
        "AND provider_version IS NOT NULL AND upload_operation_id IS NOT NULL)",
    )


def downgrade() -> None:
    if op.get_context().as_sql:
        raise RuntimeError("Proof journal downgrade needs online evidence checks")
    connection = op.get_bind()
    connection.execute(sa.text("LOCK TABLE delivery_proofs, proof_upload_operations IN ACCESS EXCLUSIVE MODE"))
    operations = connection.execute(sa.text("SELECT 1 FROM proof_upload_operations LIMIT 1")).first()
    hosted = connection.execute(sa.text(
        "SELECT 1 FROM delivery_proofs WHERE storage_backend <> 'local' "
        "OR upload_operation_id IS NOT NULL LIMIT 1"
    )).first()
    if operations is not None or hosted is not None:
        raise RuntimeError("Private proof receipts/history must be preserved; journal downgrade is refused")
    op.drop_constraint(op.f("ck_delivery_proofs_storage_identity"), "delivery_proofs", type_="check")
    op.drop_constraint(op.f("uq_delivery_proofs_upload_operation_id"), "delivery_proofs", type_="unique")
    op.drop_constraint(op.f("fk_delivery_proofs_upload_operation_id_proof_upload_operations"), "delivery_proofs", type_="foreignkey")
    for name in (
        "upload_operation_id", "provider_version", "provider_object_id", "storage_bucket",
        "storage_origin", "storage_backend",
    ):
        op.drop_column("delivery_proofs", name)
    op.drop_index("ix_proof_uploads_state_created", table_name="proof_upload_operations")
    op.drop_index("ix_proof_uploads_tenant_delivery", table_name="proof_upload_operations")
    op.drop_table("proof_upload_operations")
