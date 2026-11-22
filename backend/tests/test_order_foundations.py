"""Exact shared amounts and ordered history; no live/client data or inferred legacy order."""
from __future__ import annotations

import asyncio
import os
import uuid
from contextlib import contextmanager
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, localcontext
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.core.exceptions import DomainError
from app.features.orders.amounts import calculate_line
from app.features.payments import service as payments
from app.infrastructure.db.models.order import Order, OrderStatusHistory
from app.shared import order_events
from test_customer_onboarding import checked, database, roles


@pytest.mark.parametrize("price,tax,quantity,subtotal,gst,total", [
    ("41.80", "5.00", "1.500", "62.70", "3.14", "65.84"),
    ("0.05", "10.00", "1.000", "0.05", "0.00", "0.05"),
    ("0.15", "10.00", "1.000", "0.15", "0.02", "0.17"),
    ("1.05", "18.00", "1.005", "1.06", "0.19", "1.25"),
    ("0.00", "18.00", "100.000", "0.00", "0.00", "0.00"),
])
def test_shared_amounts_preserve_server_cent_rounding(price, tax, quantity, subtotal, gst, total):
    result = calculate_line(Decimal(price), Decimal(tax), quantity=Decimal(quantity))
    assert (result.subtotal, result.tax, result.total) == tuple(map(Decimal, (subtotal, gst, total)))
    with pytest.raises(FrozenInstanceError):
        result.total = Decimal("0")


def test_shared_amounts_do_not_change_existing_caller_rounding_or_precision():
    with localcontext() as context:
        context.prec, context.rounding = 2, ROUND_HALF_UP
        result = calculate_line(Decimal("0.05"), Decimal("10"), quantity=Decimal("1"))
        assert result.tax == Decimal("0.01") and result.total == Decimal("0.06")
        assert context.prec == 2 and context.rounding == ROUND_HALF_UP


@pytest.mark.parametrize("price,tax,quantity", [
    ("-1", "0", "1"), ("1.001", "0", "1"), ("NaN", "0", "1"),
    ("Infinity", "0", "1"), ("1", "-1", "1"), ("1", "0.001", "1"),
    ("1", "Infinity", "1"), ("1", "0", "0"), ("1", "0", "-1"),
    ("1", "0", "0.0001"), ("1", "0", "NaN"),
    ("999999999999.99", "100", "1"), ("999999999999.99", "0", "2"),
])
def test_shared_amounts_reject_nonfinite_precision_loss_or_line_overflow(price, tax, quantity):
    with pytest.raises(DomainError):
        calculate_line(Decimal(price), Decimal(tax), quantity=Decimal(quantity))


class HistorySession:
    def __init__(self, latest=None):
        self.latest, self.new, self.reads = latest, [], 0
        self.autoflush_suppressed = False

    @property
    @contextmanager
    def no_autoflush(self):
        self.autoflush_suppressed = True
        try:
            yield
        finally:
            self.autoflush_suppressed = False

    async def execute(self, statement):
        assert self.autoflush_suppressed
        assert "order_status_history.tenant_id" in str(statement)
        assert "order_status_history.order_id" in str(statement)
        self.reads += 1
        return SimpleNamespace(scalar_one=lambda: self.latest)

    def add(self, value):
        self.new.append(value)


def order():
    return Order(id=uuid.uuid4(), tenant_id=uuid.uuid4(), status="pending",
                 grand_total=Decimal("10.00"), amount_paid=Decimal("0.00"))


@pytest.mark.parametrize("metadata", [None, {}, {"currency": "INR"}, {"checkout_currency": "USD"},
                                      {"order_currency_snapshot": {"version": 0, "code": "INR"}},
                                      {"order_currency_snapshot": {"version": 1, "code": "inr"}}])
def test_legacy_order_currency_is_not_inferred_from_unrecorded_or_unvalidated_metadata(metadata):
    current = order()
    current.meta = metadata
    assert current.currency_code is None


def test_versioned_order_currency_projection_retains_recorded_code():
    current = order()
    current.meta = {"order_currency_snapshot": {"version": 1, "code": "USD"}}
    assert current.currency_code == "USD"


def test_new_history_has_strict_order_when_transaction_clock_is_tied(monkeypatch):
    current, db = order(), HistorySession()
    clock = datetime(2026, 1, 1, tzinfo=timezone.utc)
    monkeypatch.setattr(order_events, "datetime", SimpleNamespace(now=lambda _: clock))

    async def write():
        first = await order_events.record_status(db, order=current, to_status="pending", actor_id=None)
        second = await order_events.record_status(db, order=current, to_status="reserved", actor_id=None)
        third = await order_events.record_status(db, order=current, to_status="picked", actor_id=None)
        return first, second, third

    events = asyncio.run(write())
    assert [event.created_at for event in events] == [clock + timedelta(microseconds=index) for index in range(3)]
    assert db.reads == 3 and [event.to_status for event in events] == ["pending", "reserved", "picked"]
    assert current.status == "pending"  # The passive writer does not transition business state.


def test_history_clamps_backward_clock_without_rewriting_legacy_or_foreign_events(monkeypatch):
    current = order()
    previous = datetime(2026, 1, 2, tzinfo=timezone.utc)
    db = HistorySession(previous)
    foreign = OrderStatusHistory(order_id=current.id, tenant_id=uuid.uuid4(), created_at=previous + timedelta(days=1))
    db.new.append(foreign)
    monkeypatch.setattr(order_events, "datetime", SimpleNamespace(now=lambda _: previous - timedelta(days=1)))
    event = asyncio.run(order_events.record_status(db, order=current, to_status="reserved", actor_id=None))
    assert event.created_at == previous + timedelta(microseconds=1)
    assert db.latest == previous and foreign.created_at == previous + timedelta(days=1)


def test_paid_event_requires_physical_delivery_and_follows_its_history(monkeypatch):
    current, db = order(), HistorySession()
    current.amount_paid = current.grand_total
    clock = datetime(2026, 1, 1, tzinfo=timezone.utc)
    monkeypatch.setattr(order_events, "datetime", SimpleNamespace(now=lambda _: clock))

    async def write():
        await payments.mark_paid(db, order=current, actor_id=None)
        assert db.new == [] and current.status == "pending"
        delivered = await order_events.record_status(db, order=current, to_status="delivered", actor_id=None)
        current.status = "delivered"
        await payments.mark_paid(db, order=current, actor_id=None)
        return delivered, db.new[-1]

    delivered, paid = asyncio.run(write())
    assert current.status == "paid" and paid.from_status == "delivered"
    assert paid.created_at == delivered.created_at + timedelta(microseconds=1)


@pytest.mark.integration
def test_actual_order_create_and_reserve_have_distinct_history_in_one_transaction(roles, database, api_prefix, monkeypatch):
    if os.environ.get("SUPPLYOS_OWNED_TEST_ENV") != "1":
        pytest.skip("Real order history requires the owned isolated verifier")
    owner = checked(roles["super_admin"].get(f"{api_prefix}/auth/me", timeout=10))
    customer = checked(roles["customer"].get(f"{api_prefix}/customers", timeout=10))["items"][0]
    warehouse = checked(roles["super_admin"].get(f"{api_prefix}/warehouses", timeout=10))[0]
    product = checked(roles["super_admin"].post(f"{api_prefix}/products", json={
        "sku": "ordered-history-" + uuid.uuid4().hex[:16], "name": "Owned history product",
        "unit": "pcs", "base_price": "10.00", "gst_rate": "5.00",
    }, timeout=15), 201)
    checked(roles["super_admin"].post(f"{api_prefix}/inventory/adjust", json={
        "product_id": product["id"], "warehouse_id": warehouse["id"], "delta_qty": "5.000",
    }, timeout=15))
    clock = datetime(2026, 1, 1, tzinfo=timezone.utc)
    monkeypatch.setattr(order_events, "datetime", SimpleNamespace(now=lambda _: clock))

    async def create_reserved():
        from app.features.orders import service
        engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool, hide_parameters=True)
        try:
            factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
            async with factory() as db, db.begin():
                row = await service.create_order(db, tenant_id=uuid.UUID(owner["tenant_id"]),
                    customer_id=uuid.UUID(customer["id"]), warehouse_id=uuid.UUID(warehouse["id"]),
                    items=[{"product_id": uuid.UUID(product["id"]), "quantity": Decimal("1.000")}])
                await service.reserve_order(db, tenant_id=row.tenant_id, order_id=row.id, actor_id=None)
                return row.id
        finally:
            await engine.dispose()

    identity = asyncio.run(create_reserved())
    with Session(database) as db:
        events = list(db.scalars(select(OrderStatusHistory).where(
            OrderStatusHistory.order_id == identity,
        ).order_by(OrderStatusHistory.created_at)))
        assert [event.to_status for event in events] == ["pending", "reserved"]
        assert [event.created_at for event in events] == [clock, clock + timedelta(microseconds=1)]
        assert db.get(Order, identity).status == "reserved"
