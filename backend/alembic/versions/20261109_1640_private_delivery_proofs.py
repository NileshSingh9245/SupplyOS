"""Persist private delivery-bound proof receipts."""
from alembic import op
import sqlalchemy as sa

revision = "20261109_0005"
down_revision = "20261109_0004"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "delivery_proofs",
        sa.Column("id", sa.UUID(), nullable=False), sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("delivery_id", sa.UUID(), nullable=False), sa.Column("uploaded_by", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False), sa.Column("object_key", sa.String(80), nullable=False),
        sa.Column("mime_type", sa.String(40), nullable=False), sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_delivery_proofs")),
        sa.ForeignKeyConstraint(["delivery_id"], ["deliveries.id"], ondelete="RESTRICT", name=op.f("fk_delivery_proofs_delivery_id_deliveries")),
        sa.UniqueConstraint("object_key", name=op.f("uq_delivery_proofs_object_key")),
        sa.CheckConstraint("kind IN ('signature', 'photo')", name=op.f("ck_delivery_proofs_valid_kind")),
        sa.CheckConstraint("size_bytes > 0", name=op.f("ck_delivery_proofs_positive_size")),
    )
    op.create_index("ix_proofs_tenant_delivery", "delivery_proofs", ["tenant_id", "delivery_id"])


def downgrade():
    if not op.get_context().as_sql:
        stored = op.get_bind().execute(sa.text("SELECT 1 FROM delivery_proofs LIMIT 1")).first()
        referenced = op.get_bind().execute(sa.text(
            "SELECT 1 FROM deliveries WHERE signature_url LIKE '/api/v1/delivery-proofs/%' "
            "OR proof_photo_url LIKE '/api/v1/delivery-proofs/%' LIMIT 1"
        )).first()
        if stored is not None or referenced is not None:
            raise RuntimeError("Private proof receipts/history must be preserved; downgrade is refused")
    op.drop_index("ix_proofs_tenant_delivery", table_name="delivery_proofs")
    op.drop_table("delivery_proofs")
