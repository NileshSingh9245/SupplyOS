"""Evidence metadata is never discarded by a downgrade with live proof receipts."""
from __future__ import annotations

import uuid
from decimal import Decimal
import pytest
from alembic import command
from alembic.migration import MigrationContext
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.db.models.customer import Customer
from app.infrastructure.db.models.order import Order, Delivery
from app.infrastructure.db.models.proof import DeliveryProof
from app.infrastructure.db.models.tenant import Tenant
from app.infrastructure.db.models.warehouse import Warehouse
from test_migrations import database  # noqa: F401 owned disposable database

pytestmark = pytest.mark.integration


def test_empty_proof_schema_can_downgrade_and_upgrade(database):
    engine, config = database
    command.upgrade(config, "head")
    command.downgrade(config, "20261109_0004")
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert "20261112_0006" in MigrationContext.configure(connection).get_current_heads()


def test_proof_receipts_are_preserved_when_downgrade_is_refused(database):
    engine, config = database
    command.upgrade(config, "head")
    with Session(engine) as session:
        tenant = Tenant(name="Proof history fixture", currency="INR", settings={}, is_setup_complete=True)
        session.add(tenant)
        session.flush()
        warehouse = Warehouse(tenant_id=tenant.id, code="POD", name="Proof history")
        customer = Customer(tenant_id=tenant.id, code="POD", name="Proof customer", customer_type="cash")
        session.add_all([warehouse, customer])
        session.flush()
        order = Order(tenant_id=tenant.id, customer_id=customer.id, warehouse_id=warehouse.id,
                      order_number="PROOF-HISTORY", status="pending", payment_mode="cash", grand_total=Decimal("0"))
        session.add(order)
        session.flush()
        delivery = Delivery(tenant_id=tenant.id, order_id=order.id)
        session.add(delivery)
        session.flush()
        identifier = uuid.uuid4()
        proof = DeliveryProof(id=identifier, tenant_id=tenant.id, delivery_id=delivery.id,
                              uploaded_by=uuid.uuid4(), kind="photo", object_key=f"{identifier.hex}.png",
                              mime_type="image/png", size_bytes=1, sha256="0" * 64)
        session.add(proof)
        session.commit()
    with pytest.raises(RuntimeError, match="proof receipts/history must be preserved"):
        command.downgrade(config, "20261109_0004")
    with engine.connect() as connection:
        assert connection.scalar(select(DeliveryProof.id).where(DeliveryProof.id == identifier)) == identifier
        assert "20261112_0006" in MigrationContext.configure(connection).get_current_heads()
