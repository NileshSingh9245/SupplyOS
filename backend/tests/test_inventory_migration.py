"""Canonical location migration never silently merges legacy stock or references."""
from __future__ import annotations

from decimal import Decimal

import pytest
from alembic import command
from alembic.migration import MigrationContext
from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from app.infrastructure.db.models.inventory import InventoryItem
from app.infrastructure.db.models.product import Product
from app.infrastructure.db.models.tenant import Tenant
from app.infrastructure.db.models.warehouse import Warehouse
from test_migrations import database  # noqa: F401 reusable owned-database fixture

pytestmark = pytest.mark.integration


def test_nullable_location_index_is_strict_after_upgrade(database):
    engine, config = database
    command.upgrade(config, "head")
    with engine.connect() as connection:
        index = next(
            item for item in inspect(connection).get_indexes("inventory_items")
            if item["name"] == "ix_inv_unique_location"
        )
        assert index["unique"] is True
        assert index["dialect_options"]["postgresql_nulls_not_distinct"] is True


def test_legacy_duplicate_locations_stop_without_changing_stock(database):
    engine, config = database
    command.upgrade(config, "20261109_0002")
    with Session(engine) as session:
        tenant = Tenant(name="Duplicate verification tenant", currency="INR", is_setup_complete=True, settings={})
        session.add(tenant)
        session.flush()
        warehouse = Warehouse(tenant_id=tenant.id, code="DUP", name="Duplicate warehouse")
        product = Product(tenant_id=tenant.id, sku="DUP", name="Duplicate product", base_price=Decimal("1"))
        session.add_all([warehouse, product])
        session.flush()
        rows = [InventoryItem(
            tenant_id=tenant.id, product_id=product.id, warehouse_id=warehouse.id,
            quantity=Decimal(quantity), reserved_qty=Decimal("0"),
        ) for quantity in ("1", "2")]
        session.add_all(rows)
        session.flush()
        row_ids = [row.id for row in rows]
        session.commit()
    with pytest.raises(RuntimeError, match="no stock rows or reservation references were merged or deleted"):
        command.upgrade(config, "head")
    with engine.connect() as connection:
        quantities = connection.execute(select(InventoryItem.quantity).where(
            InventoryItem.id.in_(row_ids),
        )).scalars().all()
        assert sorted(quantities) == [Decimal("1"), Decimal("2")]
        assert "20261109_0003" not in MigrationContext.configure(connection).get_current_heads()
