"""Make nullable inventory location keys unique on PostgreSQL 15+."""
from alembic import op
import sqlalchemy as sa

revision = "20261109_0003"
down_revision = "20261109_0002"
branch_labels = None
depends_on = None

LOCATION_COLUMNS = ["tenant_id", "product_id", "warehouse_id", "rack_id", "shelf_id", "batch_id"]


def upgrade() -> None:
    if not op.get_context().as_sql:
        duplicate = op.get_bind().execute(sa.text(
            "SELECT 1 FROM inventory_items GROUP BY tenant_id, product_id, warehouse_id, "
            "rack_id, shelf_id, batch_id HAVING COUNT(*) > 1 LIMIT 1"
        )).first()
        if duplicate is not None:
            raise RuntimeError(
                "Duplicate legacy inventory locations need reviewed reconciliation before migration; "
                "no stock rows or reservation references were merged or deleted."
            )
    op.drop_index("ix_inv_unique_location", table_name="inventory_items")
    op.create_index(
        "ix_inv_unique_location", "inventory_items", LOCATION_COLUMNS,
        unique=True, postgresql_nulls_not_distinct=True,
    )


def downgrade() -> None:
    op.drop_index("ix_inv_unique_location", table_name="inventory_items")
    op.create_index("ix_inv_unique_location", "inventory_items", LOCATION_COLUMNS, unique=True)
