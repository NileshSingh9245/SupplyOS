"""Real PostgreSQL financial invariants, contention, replay, and guarded delivery flows."""
from __future__ import annotations

import asyncio
import base64
import os
import secrets
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

import pytest
import requests
from alembic import command
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

from app.infrastructure.db.models.customer import Customer, LedgerEntry
from app.infrastructure.db.models.idempotency import IdempotencyRecord
from app.infrastructure.db.models.inventory import InventoryItem, StockMovement
from app.infrastructure.db.models.order import Delivery, Order, OrderItem, OrderReservation, Payment
from app.infrastructure.db.models.tenant import Tenant
from app.infrastructure.db.models.user import AuditLog, User
from app.infrastructure.db.models.warehouse import Warehouse
from test_migrations import database  # noqa: F401 shared isolated migration fixture

pytestmark = pytest.mark.integration
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAE0lEQVR4nGP8//8/AwMDEwMYAAAkBgMBXaJOiAAAAABJRU5ErkJggg=="
)


def success(response: requests.Response, expected: int = 200) -> dict | list:
    if response.status_code != expected:
        pytest.fail(f"Isolated financial request failed (HTTP {response.status_code})", pytrace=False)
    return response.json()


def scalar(engine: Engine, statement):
    with engine.connect() as connection:
        return connection.scalar(statement)


@pytest.fixture(scope="module")
def financial_db(admin_session, base_url):
    url = make_url(os.environ["DATABASE_URL_SYNC"])
    async_url = make_url(os.environ["DATABASE_URL"])
    if (
        url.drivername != "postgresql+psycopg2"
        or url.host not in {"127.0.0.1", "localhost", "::1"}
        or not (url.database or "").startswith("supplyos_test_")
        or async_url.drivername != "postgresql+asyncpg"
        or (async_url.host, async_url.port, async_url.database) != (url.host, url.port, url.database)
    ):
        pytest.fail("Financial tests require the owned loopback PostgreSQL database", pytrace=False)
    engine = create_engine(url, hide_parameters=True)
    try:
        assert scalar(engine, text("SELECT current_database()")) == url.database
        yield engine
    finally:
        engine.dispose()


@dataclass(repr=False)
class FinancialCase:
    api: str
    client: requests.Session
    engine: Engine
    customer_id: str
    product_id: str
    warehouse_id: str

    def order_payload(self, quantity="1", **extra) -> dict:
        return {
            "customer_id": self.customer_id, "warehouse_id": self.warehouse_id,
            "items": [{"product_id": self.product_id, "quantity": quantity}], **extra,
        }

    def post(self, path: str, payload=None, *, key=None) -> requests.Response:
        headers = {"X-Idempotency-Key": str(key)} if key is not None else {}
        return self.client.post(f"{self.api}/{path}", json=payload, headers=headers, timeout=30)

    def make_order(self, quantity="1", *, key=None, **extra) -> dict:
        return success(self.post("orders", self.order_payload(quantity, **extra), key=key), 201)

    def payment(self, amount, *, order_id=None, key=None, mode="cash", **extra):
        return self.post("payments", {
            "customer_id": self.customer_id, "order_id": order_id,
            "amount": str(amount), "mode": mode, **extra,
        }, key=key)

    def customer(self) -> dict:
        return success(self.client.get(f"{self.api}/customers/{self.customer_id}", timeout=10))

    def get_order(self, order_id: str) -> dict:
        return success(self.client.get(f"{self.api}/orders/{order_id}", timeout=10))

    def dispatch(self, order_id: str) -> dict:
        for action in ("confirm", "reserve", "pick", "pack", "dispatch"):
            success(self.post(f"orders/{order_id}/{action}"))
        deliveries = success(self.client.get(f"{self.api}/deliveries", timeout=10))
        return next(item for item in deliveries if item["order_id"] == order_id)

    def verify_and_prove(self, delivery_id: str) -> dict:
        code = scalar(self.engine, select(Delivery.otp_code).where(
            Delivery.id == uuid.UUID(delivery_id),
            Delivery.tenant_id == uuid.UUID(self.client.admin_user["tenant_id"]),
        ))
        success(self.post(f"deliveries/{delivery_id}/verify-otp", {"otp_code": code}))
        references = {}
        for kind, field in (("signature", "signature_url"), ("photo", "proof_photo_url")):
            response = self.client.post(
                f"{self.api}/deliveries/{delivery_id}/proofs", data={"kind": kind},
                files={"file": ("financial-proof.png", PNG, "image/png")},
                headers={"Content-Type": None}, timeout=30,
            )
            references[field] = success(response, 201)["url"]
        return references

    def ledger(self) -> list:
        with Session(self.engine) as session:
            return session.scalars(select(LedgerEntry).where(
                LedgerEntry.customer_id == uuid.UUID(self.customer_id),
            ).order_by(LedgerEntry.created_at, LedgerEntry.id)).all()

    def assert_ledger(self, expected: Decimal) -> None:
        balance = Decimal("0")
        for entry in self.ledger():
            balance += entry.debit - entry.credit
            assert entry.balance_after == balance
        assert balance == expected
        assert Decimal(self.customer()["outstanding"]) == expected

    def payment_count(self) -> int:
        return scalar(self.engine, select(func.count()).select_from(Payment).where(
            Payment.customer_id == uuid.UUID(self.customer_id),
        ))


@pytest.fixture
def make_case(admin_session, api_prefix, financial_db):
    def create(*, customer_type="credit", credit_limit="100.00", price="10.00", stock="100"):
        customer = success(admin_session.post(f"{api_prefix}/customers", json={
            "name": "Financial invariant customer", "customer_type": customer_type,
            "credit_limit": credit_limit,
        }, timeout=10), 201)
        product = success(admin_session.post(f"{api_prefix}/products", json={
            "sku": f"FIN-{uuid.uuid4().hex[:14]}", "name": "Financial invariant product",
            "base_price": price, "gst_rate": "0", "unit": "pcs",
        }, timeout=10), 201)
        warehouse = success(admin_session.get(f"{api_prefix}/warehouses", timeout=10))[0]["id"]
        if stock != "0":
            success(admin_session.post(f"{api_prefix}/inventory/adjust", json={
                "product_id": product["id"], "warehouse_id": warehouse, "delta_qty": stock,
            }, timeout=10))
        return FinancialCase(
            api_prefix, admin_session, financial_db, customer["id"], product["id"], warehouse,
        )
    return create


def locked_requests(case: FinancialCase, lock_statement, calls: list[tuple]) -> list:
    """Observe a real PostgreSQL lock chain before releasing concurrent HTTP operations."""
    headers = dict(case.client.headers)
    barrier = threading.Barrier(len(calls))
    chain = text(
        "WITH RECURSIVE waiters(pid) AS (SELECT pid FROM pg_stat_activity "
        "WHERE wait_event_type='Lock' AND :holder=ANY(pg_blocking_pids(pid)) UNION "
        "SELECT a.pid FROM pg_stat_activity a JOIN waiters w "
        "ON w.pid=ANY(pg_blocking_pids(a.pid)) WHERE a.wait_event_type='Lock') "
        "SELECT COUNT(*) FROM waiters"
    )

    def send(call):
        path, body, key = call
        request_headers = dict(headers)
        if key is not None:
            request_headers["X-Idempotency-Key"] = str(key)
        barrier.wait(timeout=10)
        return requests.post(f"{case.api}/{path}", json=body, headers=request_headers, timeout=30)

    with case.engine.connect() as holder, ThreadPoolExecutor(max_workers=len(calls)) as workers:
        holder.execute(lock_statement.with_for_update())
        holder_pid = holder.scalar(text("SELECT pg_backend_pid()"))
        futures = [workers.submit(send, call) for call in calls]
        observed = False
        try:
            with case.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as observer:
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    if observer.scalar(chain, {"holder": holder_pid}) >= len(calls):
                        observed = True
                        break
                    time.sleep(0.01)
        finally:
            holder.rollback()
        if not observed:
            pytest.fail("Financial operations did not reach the real PostgreSQL lock chain", pytrace=False)
        return [future.result(timeout=30) for future in futures]


def customer_lock(case):
    return select(Customer.id).where(Customer.id == uuid.UUID(case.customer_id))


def order_lock(order_id):
    return select(Order.id).where(Order.id == uuid.UUID(order_id))


def audit_count(case, action, identifier):
    return scalar(case.engine, select(func.count()).select_from(AuditLog).where(
        AuditLog.tenant_id == uuid.UUID(case.client.admin_user["tenant_id"]),
        AuditLog.action == action, AuditLog.resource_id == identifier,
    ))


def actor_session(case, *, role="accountant", tenant_id=None):
    from app.core.security import hash_password

    password = secrets.token_urlsafe(24)
    email = f"financial-actor-{uuid.uuid4().hex}@example.com"
    tenant_id = tenant_id or case.client.admin_user["tenant_id"]
    with Session(case.engine) as session:
        actor = User(
            tenant_id=uuid.UUID(str(tenant_id)), email=email, full_name="Financial test actor",
            role=role, password_hash=hash_password(password), is_active=True,
        )
        session.add(actor)
        session.flush()
        identifier = actor.id
        session.commit()
    client = requests.Session()
    body = success(client.post(f"{case.api}/auth/login", json={
        "email": email, "password": password, "tenant_id": str(tenant_id),
    }, timeout=15))
    client.headers["Authorization"] = f"Bearer {body['access_token']}"
    client.admin_user = body["user"]
    return client, identifier


def test_s2_and_false_credit_flag_cannot_bypass_creation(make_case):
    case = make_case(credit_limit="50000.00", price="18000.00")
    with Session(case.engine) as session:
        customer = session.scalar(customer_lock(case).with_only_columns(Customer).with_for_update())
        customer.outstanding = Decimal("37000.00")
        session.add(LedgerEntry(
            tenant_id=customer.tenant_id, customer_id=customer.id, debit=Decimal("37000.00"),
            credit=Decimal("0"), balance_after=customer.outstanding, reference_type="opening",
        ))
        session.commit()
    for flag in (True, False):
        response = case.post("orders", case.order_payload(is_credit=flag), key=uuid.uuid4())
        assert response.status_code == 409
    assert scalar(case.engine, select(func.count()).select_from(Order).where(
        Order.customer_id == uuid.UUID(case.customer_id),
    )) == 0
    assert Decimal(case.customer()["credit_held"]) == 0
    case.assert_ledger(Decimal("37000"))


def test_simultaneous_credit_creation_holds_include_other_pending_orders(make_case):
    case = make_case(price="80.00")
    responses = locked_requests(case, customer_lock(case), [
        ("orders", case.order_payload(is_credit=False), uuid.uuid4()) for _ in range(2)
    ])
    assert sorted(response.status_code for response in responses) == [201, 409]
    accepted = next(response.json() for response in responses if response.status_code == 201)
    assert accepted["payment_mode"] == "credit"
    assert Decimal(accepted["credit_hold_amount"]) == 80
    assert Decimal(case.customer()["credit_held"]) == 80
    assert Decimal(case.customer()["credit_exposure"]) == 80
    assert scalar(case.engine, select(InventoryItem.reserved_qty).where(
        InventoryItem.product_id == uuid.UUID(case.product_id),
    )) == 0


def test_reservation_rechecks_limit_and_cancellation_releases_gross_hold(make_case):
    case = make_case(credit_limit="200", price="80")
    first, second = case.make_order(), case.make_order()
    response = case.client.patch(f"{case.api}/customers/{case.customer_id}", json={
        "credit_limit": "100.00",
    }, timeout=10)
    assert response.status_code == 409
    # A legacy/out-of-band policy change must still be caught at reservation time.
    with Session(case.engine) as session:
        existing = session.scalar(customer_lock(case).with_only_columns(Customer).with_for_update())
        existing.credit_limit = Decimal("100.00")
        session.commit()
    assert case.post(f"orders/{first['id']}/reserve").status_code == 409
    assert Decimal(case.customer()["credit_held"]) == 160
    assert scalar(case.engine, select(InventoryItem.reserved_qty).where(
        InventoryItem.product_id == uuid.UUID(case.product_id),
    )) == 0
    cancelled = success(case.post(f"orders/{second['id']}/cancel", {"note": "Release exposure"}))
    assert Decimal(cancelled["credit_hold_amount"]) == 0
    assert Decimal(case.customer()["credit_held"]) == 80
    success(case.post(f"orders/{first['id']}/reserve"))
    assert case.post(f"orders/{second['id']}/cancel", {}).status_code == 409
    assert Decimal(case.customer()["credit_held"]) == 80


def test_failed_reservation_keeps_only_the_original_live_credit_hold(make_case):
    case = make_case(price="40", stock="0")
    order = case.make_order()
    assert case.post(f"orders/{order['id']}/reserve").status_code == 409
    assert case.get_order(order["id"])["status"] == "pending"
    assert Decimal(case.customer()["credit_held"]) == 40
    success(case.post(f"orders/{order['id']}/cancel", {}))
    assert Decimal(case.customer()["credit_held"]) == 0


def test_credit_cancellation_preserves_prepayment_and_releases_stock_once(make_case):
    case = make_case(price="100", stock="2")
    order = case.make_order()
    success(case.payment("50", order_id=order["id"]), 201)
    success(case.post(f"orders/{order['id']}/reserve"))
    success(case.post(f"orders/{order['id']}/cancel", {}))
    assert Decimal(case.customer()["credit_held"]) == 0
    assert Decimal(case.customer()["advance_balance"]) == 50
    assert case.post(f"orders/{order['id']}/cancel", {}).status_code == 409
    assert case.payment("1", order_id=order["id"]).status_code == 409
    assert scalar(case.engine, select(InventoryItem.reserved_qty).where(
        InventoryItem.product_id == uuid.UUID(case.product_id),
    )) == 0
    assert scalar(case.engine, select(InventoryItem.quantity).where(
        InventoryItem.product_id == uuid.UUID(case.product_id),
    )) == 2
    assert scalar(case.engine, select(func.count()).select_from(StockMovement).where(
        StockMovement.reference_id == uuid.UUID(order["id"]), StockMovement.movement_type == "release",
    )) == 1
    case.assert_ledger(Decimal("-50"))


def test_gross_hold_and_signed_prepayment_are_not_counted_twice(make_case):
    case = make_case(price="100")
    order = case.make_order()
    success(case.payment("40", order_id=order["id"], mode="bank_transfer"), 201)
    customer = case.customer()
    assert Decimal(customer["outstanding"]) == -40
    assert Decimal(customer["credit_held"]) == 100
    assert Decimal(customer["credit_exposure"]) == 60
    assert case.post("orders", case.order_payload(quantity="0.7")).status_code == 409
    second = case.make_order(quantity="0.4")
    assert Decimal(second["credit_hold_amount"]) == 40
    assert Decimal(case.customer()["credit_held"]) == 140
    assert Decimal(case.customer()["credit_exposure"]) == 100
    assert case.get_order(order["id"])["status"] == "pending"
    assert case.get_order(order["id"])["payment_status"] == "partial"
    case.assert_ledger(Decimal("-40"))


def test_orderless_advance_is_not_fake_order_funding(make_case):
    case = make_case(credit_limit="0", price="100")
    receipt = success(case.payment("100"), 201)
    assert receipt["order_id"] is None
    assert receipt["allocation_kind"] == "unallocated_advance"
    order = case.make_order()
    assert Decimal(order["amount_paid"]) == 0
    assert order["payment_status"] == "unpaid"
    assert Decimal(case.customer()["outstanding"]) == -100
    assert Decimal(case.customer()["credit_held"]) == 100
    assert Decimal(case.customer()["credit_exposure"]) == 0
    case.assert_ledger(Decimal("-100"))


def test_cash_prepayment_cannot_falsely_free_credit_capacity(make_case):
    case = make_case(credit_limit="50", price="100")
    cash = case.make_order(payment_mode="cash", is_credit=False)
    success(case.payment("100", order_id=cash["id"]), 201)
    customer = case.customer()
    assert Decimal(customer["outstanding"]) == -100
    assert Decimal(customer["cash_funded_pending"]) == 100
    assert Decimal(customer["credit_exposure"]) == 0
    assert case.post("orders", case.order_payload(quantity="0.6")).status_code == 409
    case.make_order(quantity="0.5")
    assert Decimal(case.customer()["credit_exposure"]) == 50
    success(case.post(f"orders/{cash['id']}/cancel", {}))
    assert Decimal(case.customer()["cash_funded_pending"]) == 0
    assert Decimal(case.customer()["outstanding"]) == -100


def test_linked_payment_rejects_wrong_customer_or_tenant_before_effects(make_case):
    case, other = make_case(), make_case()
    order = other.make_order()
    key = uuid.uuid4()
    assert case.payment("1", order_id=order["id"], key=key).status_code == 404
    with Session(case.engine) as session:
        tenant = Tenant(name="Foreign financial fixture", currency="INR", is_setup_complete=True)
        session.add(tenant)
        session.flush()
        customer = Customer(tenant_id=tenant.id, code="FOREIGN", name="Foreign customer")
        warehouse = Warehouse(tenant_id=tenant.id, code="FOREIGN", name="Foreign warehouse")
        session.add_all([customer, warehouse])
        session.flush()
        foreign = Order(
            tenant_id=tenant.id, customer_id=customer.id, warehouse_id=warehouse.id,
            order_number=f"FOREIGN-{uuid.uuid4().hex[:8]}", grand_total=Decimal("10"),
        )
        session.add(foreign)
        session.flush()
        foreign_id = str(foreign.id)
        session.commit()
    assert case.payment("1", order_id=foreign_id, key=key).status_code == 404
    assert case.payment_count() == 0
    assert scalar(case.engine, select(func.count()).select_from(IdempotencyRecord).where(
        IdempotencyRecord.key == key,
    )) == 0
    case.assert_ledger(Decimal("0"))


def test_overpayment_rollback_retry_and_changed_payload_conflict(make_case):
    case = make_case(price="100")
    order = case.make_order()
    key = uuid.uuid4()
    assert case.payment("100.01", order_id=order["id"], key=key).status_code == 409
    assert case.payment_count() == 0
    assert Decimal(case.get_order(order["id"])["amount_paid"]) == 0
    original = success(case.payment("100.00", order_id=order["id"], key=key), 201)
    replay = success(case.payment("100.0", order_id=order["id"], key=key), 201)
    assert replay == original
    assert case.payment("1", order_id=order["id"], key=key).status_code == 409
    assert case.payment("100", order_id=order["id"], key=key, reference="changed").status_code == 409
    funded = case.get_order(order["id"])
    assert funded["status"] == "pending"
    assert funded["payment_status"] == "paid"
    assert Decimal(funded["amount_paid"]) == 100
    assert Decimal(funded["amount_due"]) == 0
    assert case.payment_count() == 1
    assert audit_count(case, "payments.record", original["id"]) == 1
    case.assert_ledger(Decimal("-100"))


def test_concurrent_idempotent_payments_credit_customer_only_once(make_case):
    case = make_case()
    key = uuid.uuid4()
    body = {"customer_id": case.customer_id, "amount": "80.00", "mode": "cash"}
    responses = locked_requests(case, customer_lock(case), [("payments", body, key)] * 2)
    assert [response.status_code for response in responses] == [201, 201]
    assert responses[0].json() == responses[1].json()
    assert case.payment_count() == 1
    receipt = responses[0].json()
    assert audit_count(case, "payments.record", receipt["id"]) == 1
    case.assert_ledger(Decimal("-80"))


def test_coarse_clock_keeps_staged_and_persisted_ledger_entries_in_balance_order(make_case, monkeypatch):
    from app.features.payments import service

    case = make_case()
    moment = datetime.now(timezone.utc)

    class CoarseClock:
        @staticmethod
        def now(tz):
            return moment

    monkeypatch.setattr(service, "datetime", CoarseClock)

    async def record_with_frozen_clock():
        engine = create_async_engine(os.environ["DATABASE_URL"], hide_parameters=True)
        sessions = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        tenant = uuid.UUID(case.client.admin_user["tenant_id"])
        actor = uuid.UUID(case.client.admin_user["id"])
        try:
            for amounts in ((Decimal("1"), Decimal("2")), (Decimal("3"),)):
                async with sessions() as session, session.begin():
                    context = await service.lock_context(
                        session, tenant_id=tenant, customer_id=uuid.UUID(case.customer_id),
                    )
                    for amount in amounts:
                        await service.record_payment(
                            session, tenant_id=tenant, customer_id=context.customer.id,
                            amount=amount, mode="cash", actor_id=actor, actor_email=None, context=context,
                        )
        finally:
            await engine.dispose()

    asyncio.run(record_with_frozen_clock())
    entries = case.ledger()
    assert len(entries) == 3
    assert entries[0].created_at < entries[1].created_at < entries[2].created_at
    assert [entry.credit for entry in entries] == [Decimal("1"), Decimal("2"), Decimal("3")]
    case.assert_ledger(Decimal("-6"))


def test_concurrent_linked_payments_cannot_overallocate_an_order(make_case):
    case = make_case(price="100")
    order = case.make_order()
    body = {"customer_id": case.customer_id, "order_id": order["id"], "amount": "70", "mode": "upi"}
    responses = locked_requests(case, order_lock(order["id"]), [
        ("payments", body, uuid.uuid4()) for _ in range(2)
    ])
    assert sorted(response.status_code for response in responses) == [201, 409]
    assert Decimal(case.get_order(order["id"])["amount_paid"]) == 70
    assert case.payment_count() == 1
    case.assert_ledger(Decimal("-70"))


def test_order_idempotency_replays_creation_not_current_resource_state(make_case):
    case = make_case(price="40")
    key = uuid.uuid4()
    original = case.make_order(key=key)
    success(case.post(f"orders/{original['id']}/confirm"))
    replay = case.make_order(key=key)
    assert replay == original
    assert replay["status"] == "pending"
    assert case.get_order(original["id"])["status"] == "confirmed"
    assert Decimal(case.customer()["credit_held"]) == 40
    assert case.post("orders", case.order_payload(quantity="2"), key=key).status_code == 409
    assert audit_count(case, "orders.create", original["id"]) == 1


def test_concurrent_idempotent_order_creation_holds_credit_once(make_case):
    case = make_case(price="80")
    key = uuid.uuid4()
    responses = locked_requests(case, customer_lock(case), [("orders", case.order_payload(), key)] * 2)
    assert [response.status_code for response in responses] == [201, 201]
    assert responses[0].json() == responses[1].json()
    assert Decimal(case.customer()["credit_held"]) == 80
    assert audit_count(case, "orders.create", responses[0].json()["id"]) == 1


def test_no_key_requests_and_operation_scopes_do_not_dedupe_legitimate_effects(make_case):
    case = make_case(credit_limit="1000")
    first, second = case.make_order(), case.make_order()
    assert first["id"] != second["id"]
    payments = [success(case.payment("1"), 201) for _ in range(2)]
    assert payments[0]["id"] != payments[1]["id"]
    key = uuid.uuid4()
    case.make_order(key=key)
    success(case.payment("1", key=key), 201)
    assert case.payment_count() == 3
    case.assert_ledger(Decimal("-3"))


def test_actor_scope_and_current_authorization_are_enforced_before_replay(make_case):
    case = make_case()
    key = uuid.uuid4()
    original = success(case.payment("1", key=key), 201)
    client, actor_id = actor_session(case)
    body = {"customer_id": case.customer_id, "amount": "1", "mode": "cash"}
    try:
        second = success(client.post(f"{case.api}/payments", json=body,
                                     headers={"X-Idempotency-Key": str(key)}, timeout=15), 201)
        assert second["id"] != original["id"]
        with Session(case.engine) as session:
            actor = session.get(User, actor_id, with_for_update=True)
            actor.role = "delivery_partner"
            session.commit()
        # Even the cached resource cannot be returned through a revoked role identity.
        assert client.post(f"{case.api}/payments", json=body,
                           headers={"X-Idempotency-Key": str(key)}, timeout=15).status_code == 401
        assert case.payment_count() == 2
        case.assert_ledger(Decimal("-2"))
    finally:
        client.close()


def test_v1_and_legacy_prefix_replay_share_one_operation_scope(make_case):
    case = make_case()
    key = uuid.uuid4()
    original = case.make_order(key=key)
    legacy = case.api.removesuffix("/api/v1") + "/api/orders"
    replay = success(case.client.post(legacy, json=case.order_payload(),
                                      headers={"X-Idempotency-Key": str(key)}, timeout=15), 201)
    assert replay == original
    assert Decimal(case.customer()["credit_held"]) == 10


def test_credit_notes_are_explicit_and_cannot_fake_collected_cash(make_case):
    case = make_case(price="10")
    order = case.make_order(payment_mode="cash")
    assert case.payment("10", order_id=order["id"], mode="credit").status_code == 409
    note = success(case.payment("10", mode="credit"), 201)
    assert note["allocation_kind"] == "credit_note"
    assert Decimal(case.get_order(order["id"])["amount_paid"]) == 0
    case.assert_ledger(Decimal("-10"))


@pytest.mark.parametrize("quantity", ["0", "-1", "0.0001", "NaN", "Infinity", "10000000000000"])
def test_quantity_validation_precedes_order_and_idempotency_writes(make_case, quantity):
    case = make_case()
    key = uuid.uuid4()
    assert case.post("orders", case.order_payload(quantity=quantity), key=key).status_code == 422
    assert scalar(case.engine, select(func.count()).select_from(IdempotencyRecord).where(
        IdempotencyRecord.key == key,
    )) == 0


@pytest.mark.parametrize("amount", ["0", "-1", "0.001", "NaN", "-Infinity", "1000000000000"])
def test_money_validation_precedes_payment_and_ledger_writes(make_case, amount):
    case = make_case()
    assert case.payment(amount, key=uuid.uuid4()).status_code == 422
    assert case.payment_count() == 0
    case.assert_ledger(Decimal("0"))


def test_computed_line_overflow_is_domain_error_not_database_overflow(make_case):
    case = make_case(credit_limit="0", price="999999999999.99")
    assert case.post("orders", case.order_payload(quantity="2", payment_mode="cash")).status_code == 400
    assert scalar(case.engine, select(func.count()).select_from(Order).where(
        Order.customer_id == uuid.UUID(case.customer_id),
    )) == 0


def test_order_subtotal_overflow_rolls_back_the_claim_and_all_lines(make_case):
    case = make_case(credit_limit="0", price="499999999999.99")
    key = uuid.uuid4()
    body = case.order_payload(payment_mode="cash")
    body["items"] *= 3
    assert case.post("orders", body, key=key).status_code == 400
    assert scalar(case.engine, select(func.count()).select_from(Order).where(
        Order.customer_id == uuid.UUID(case.customer_id),
    )) == 0
    assert scalar(case.engine, select(func.count()).select_from(IdempotencyRecord).where(
        IdempotencyRecord.key == key,
    )) == 0


def test_bad_idempotency_header_is_validation_error(make_case):
    case = make_case()
    assert case.post("orders", case.order_payload(), key="not-a-uuid").status_code == 422
    assert case.payment("1", key="not-a-uuid").status_code == 422
    assert case.payment_count() == 0


@pytest.mark.parametrize("amount", ["-1", "0.001", "NaN", "Infinity", "1000000000000"])
def test_collection_money_validation_happens_before_any_completion(make_case, amount):
    case = make_case()
    order = case.make_order()
    delivery = case.dispatch(order["id"])
    assert case.post(f"deliveries/{delivery['id']}/complete", {"cash_amount": amount}).status_code == 422
    assert case.post(f"orders/{order['id']}/deliver", {"upi_amount": amount}).status_code == 422
    assert case.get_order(order["id"])["status"] == "out_for_delivery"
    assert case.payment_count() == 0


def test_both_delivery_paths_require_otp_and_untrusted_urls_cannot_bypass_proof(make_case):
    case = make_case(price="100")
    order = case.make_order()
    delivery = case.dispatch(order["id"])
    payload = {"proof_photo_url": "https://example.com/not-a-proof.png"}
    assert case.post(f"orders/{order['id']}/deliver", payload).status_code == 409
    assert case.post(f"deliveries/{delivery['id']}/complete", payload).status_code == 409
    with Session(case.engine) as session:
        row = session.scalar(select(Delivery).where(Delivery.id == uuid.UUID(delivery["id"])).with_for_update())
        row.otp_verified = True
        session.commit()
    assert case.post(f"orders/{order['id']}/deliver").status_code == 409
    assert case.post(f"deliveries/{delivery['id']}/complete", payload).status_code == 409
    assert case.get_order(order["id"])["status"] == "out_for_delivery"
    assert case.payment_count() == 0
    assert scalar(case.engine, select(func.count()).select_from(StockMovement).where(
        StockMovement.reference_id == uuid.UUID(order["id"]), StockMovement.movement_type == "outbound",
    )) == 0


def test_explicit_cash_on_credit_customer_requires_full_real_funding(make_case):
    case = make_case(credit_limit="0", price="100")
    order = case.make_order(payment_mode="cash", is_credit=False)
    assert order["payment_mode"] == "cash"
    assert Decimal(order["credit_hold_amount"]) == 0
    delivery = case.dispatch(order["id"])
    proof = case.verify_and_prove(delivery["id"])
    success(case.payment("100"), 201)
    key = uuid.uuid4()
    assert case.post(f"deliveries/{delivery['id']}/complete", proof, key=key).status_code == 409
    assert case.post(f"orders/{order['id']}/deliver", proof).status_code == 409
    assert Decimal(case.get_order(order["id"])["amount_paid"]) == 0
    assert case.payment_count() == 1
    completion = success(case.post(
        f"deliveries/{delivery['id']}/complete", {**proof, "cash_amount": "100"}, key=key,
    ))
    assert completion["completed_at"] is not None
    assert case.get_order(order["id"])["status"] == "paid"
    assert Decimal(case.customer()["cash_funded_pending"]) == 0
    assert Decimal(case.customer()["credit_held"]) == 0
    case.assert_ledger(Decimal("-100"))


def test_server_cash_mode_does_not_flip_when_customer_becomes_credit(make_case):
    case = make_case(customer_type="cash", credit_limit="0", price="100")
    order = case.make_order()
    assert order["payment_mode"] == "cash"
    success(case.client.patch(f"{case.api}/customers/{case.customer_id}", json={
        "customer_type": "credit", "credit_limit": "200",
    }, timeout=10))
    delivery = case.dispatch(order["id"])
    proof = case.verify_and_prove(delivery["id"])
    assert case.post(f"deliveries/{delivery['id']}/complete", proof).status_code == 409
    success(case.post(f"deliveries/{delivery['id']}/complete", {
        **proof, "cash_amount": "30", "upi_amount": "70",
    }))
    assert case.get_order(order["id"])["payment_mode"] == "cash"
    assert case.get_order(order["id"])["status"] == "paid"
    assert Decimal(case.customer()["credit_held"]) == 0
    assert Decimal(case.customer()["cash_funded_pending"]) == 0
    case.assert_ledger(Decimal("0"))


def test_inconsistent_pricing_fails_closed_without_repairing_or_collecting(make_case):
    case = make_case(price="100")
    order = case.make_order()

    def change_line(amount):
        with Session(case.engine) as session:
            item = session.scalar(select(OrderItem).where(
                OrderItem.order_id == uuid.UUID(order["id"]),
            ).with_for_update())
            item.line_total = Decimal(amount)
            session.commit()

    change_line("101")
    assert case.post(f"orders/{order['id']}/reserve").status_code == 409
    change_line("100")
    delivery = case.dispatch(order["id"])
    proof = case.verify_and_prove(delivery["id"])
    change_line("101")
    key = uuid.uuid4()
    payload = {**proof, "cash_amount": "40"}
    assert case.post(f"deliveries/{delivery['id']}/complete", payload, key=key).status_code == 409
    assert case.payment_count() == 0
    assert len(case.ledger()) == 0
    assert Decimal(case.customer()["credit_held"]) == 100
    assert scalar(case.engine, select(OrderItem.line_total).where(
        OrderItem.order_id == uuid.UUID(order["id"]),
    )) == 101
    change_line("100")
    success(case.post(f"deliveries/{delivery['id']}/complete", payload, key=key))
    assert case.payment_count() == 1
    case.assert_ledger(Decimal("60"))


@pytest.mark.parametrize("wrong_reference", ["product", "warehouse"])
def test_corrupt_reservation_cannot_consume_or_release_another_location(make_case, wrong_reference):
    case = make_case(price="100", stock="2")
    order = case.make_order()
    delivery = case.dispatch(order["id"])
    proof = case.verify_and_prove(delivery["id"])
    product, warehouse = case.product_id, case.warehouse_id
    if wrong_reference == "product":
        product = success(case.client.post(f"{case.api}/products", json={
            "sku": f"REF-{uuid.uuid4().hex[:10]}", "name": "Different financial stock",
            "base_price": "100", "gst_rate": "0", "unit": "pcs",
        }, timeout=10), 201)["id"]
    else:
        warehouse = success(case.client.post(f"{case.api}/warehouses", json={
            "code": f"REF-{uuid.uuid4().hex[:8]}", "name": "Different financial warehouse",
        }, timeout=10), 201)["id"]
    success(case.client.post(f"{case.api}/inventory/adjust", json={
        "product_id": product, "warehouse_id": warehouse, "delta_qty": "2",
    }, timeout=10))
    target = scalar(case.engine, select(InventoryItem.id).where(
        InventoryItem.product_id == uuid.UUID(product), InventoryItem.warehouse_id == uuid.UUID(warehouse),
    ))
    original = scalar(case.engine, select(InventoryItem.id).where(
        InventoryItem.product_id == uuid.UUID(case.product_id),
        InventoryItem.warehouse_id == uuid.UUID(case.warehouse_id),
    ))
    with Session(case.engine) as session:
        reservation = session.scalar(select(OrderReservation).where(
            OrderReservation.order_id == uuid.UUID(order["id"]),
        ).with_for_update())
        reservation.inventory_item_id = target
        session.get(InventoryItem, target, with_for_update=True).reserved_qty = Decimal("1")
        session.commit()
    key = uuid.uuid4()
    payload = {**proof, "cash_amount": "40"}
    assert case.post(f"orders/{order['id']}/cancel", {}).status_code == 409
    assert case.post(f"deliveries/{delivery['id']}/complete", payload, key=key).status_code == 409
    assert case.payment_count() == 0
    assert len(case.ledger()) == 0
    assert Decimal(case.customer()["credit_held"]) == 100
    assert scalar(case.engine, select(InventoryItem.quantity).where(InventoryItem.id == target)) == 2
    assert scalar(case.engine, select(InventoryItem.reserved_qty).where(InventoryItem.id == target)) == 1
    assert scalar(case.engine, select(InventoryItem.quantity).where(InventoryItem.id == original)) == 2
    with Session(case.engine) as session:
        reservation = session.scalar(select(OrderReservation).where(
            OrderReservation.order_id == uuid.UUID(order["id"]),
        ).with_for_update())
        reservation.inventory_item_id = original
        session.get(InventoryItem, target, with_for_update=True).reserved_qty = Decimal("0")
        session.commit()
    success(case.post(f"deliveries/{delivery['id']}/complete", payload, key=key))
    assert scalar(case.engine, select(InventoryItem.quantity).where(InventoryItem.id == original)) == 1
    assert scalar(case.engine, select(InventoryItem.quantity).where(InventoryItem.id == target)) == 2
    case.assert_ledger(Decimal("60"))


def test_credit_delivery_moves_gross_hold_to_debt_and_later_payment_marks_paid(make_case):
    case = make_case(price="100")
    order = case.make_order()
    success(case.payment("30", order_id=order["id"], mode="bank_transfer"), 201)
    delivery = case.dispatch(order["id"])
    proof = case.verify_and_prove(delivery["id"])
    success(case.post(f"deliveries/{delivery['id']}/complete", proof))
    delivered = case.get_order(order["id"])
    assert delivered["status"] == "delivered"
    assert delivered["delivered_at"] is not None
    assert Decimal(delivered["credit_hold_amount"]) == 0
    assert Decimal(case.customer()["outstanding"]) == 70
    assert Decimal(case.customer()["credit_held"]) == 0
    success(case.payment("70", order_id=order["id"]), 201)
    assert case.get_order(order["id"])["status"] == "paid"
    case.assert_ledger(Decimal("0"))


def test_unallocated_advance_offsets_debt_without_claiming_the_order_is_paid(make_case):
    case = make_case(credit_limit="0", price="100")
    success(case.payment("100"), 201)
    order = case.make_order()
    delivery = case.dispatch(order["id"])
    proof = case.verify_and_prove(delivery["id"])
    success(case.post(f"orders/{order['id']}/deliver", proof))
    assert case.get_order(order["id"])["status"] == "delivered"
    assert Decimal(case.get_order(order["id"])["amount_paid"]) == 0
    assert Decimal(case.customer()["credit_held"]) == 0
    case.assert_ledger(Decimal("0"))


def test_cash_delivery_absorbs_prepayment_without_inflating_credit_exposure(make_case):
    case = make_case(credit_limit="50", price="100")
    order = case.make_order(payment_mode="cash")
    success(case.payment("100", order_id=order["id"]), 201)
    other = case.make_order(quantity="0.5")
    delivery = case.dispatch(order["id"])
    proof = case.verify_and_prove(delivery["id"])
    result = success(case.post(f"orders/{order['id']}/deliver", proof, key=uuid.uuid4()))
    assert result["status"] == "paid"
    assert result["payment_mode"] == "cash"
    assert Decimal(case.customer()["cash_funded_pending"]) == 0
    assert Decimal(case.customer()["credit_held"]) == Decimal(other["grand_total"])
    assert Decimal(case.customer()["credit_exposure"]) == 50
    case.assert_ledger(Decimal("0"))


def test_concurrent_idempotent_delivery_consumes_stock_and_money_once(make_case):
    case = make_case(price="100", stock="2")
    order = case.make_order()
    delivery = case.dispatch(order["id"])
    proof = case.verify_and_prove(delivery["id"])
    key = uuid.uuid4()
    payload = {**proof, "cash_amount": "30", "upi_amount": "20"}
    responses = locked_requests(case, order_lock(order["id"]), [
        (f"deliveries/{delivery['id']}/complete", payload, key),
        (f"deliveries/{delivery['id']}/complete", payload, key),
    ])
    assert [response.status_code for response in responses] == [200, 200]
    assert responses[0].json() == responses[1].json()
    assert case.payment_count() == 2
    assert len(case.ledger()) == 3
    assert Decimal(case.get_order(order["id"])["amount_paid"]) == 50
    assert audit_count(case, "orders.deliver", order["id"]) == 1
    assert audit_count(case, "deliveries.complete", delivery["id"]) == 1
    assert scalar(case.engine, select(InventoryItem.quantity).where(
        InventoryItem.product_id == uuid.UUID(case.product_id),
    )) == 1
    assert scalar(case.engine, select(InventoryItem.reserved_qty).where(
        InventoryItem.product_id == uuid.UUID(case.product_id),
    )) == 0
    assert case.post(f"deliveries/{delivery['id']}/complete", {**payload, "cash_amount": "31"}, key=key).status_code == 409
    assert case.post(f"deliveries/{delivery['id']}/complete", payload).status_code == 409
    case.assert_ledger(Decimal("50"))


def test_concurrent_completion_and_linked_payment_use_the_same_order_lock(make_case):
    case = make_case(price="100")
    order = case.make_order()
    delivery = case.dispatch(order["id"])
    proof = case.verify_and_prove(delivery["id"])
    responses = locked_requests(case, order_lock(order["id"]), [
        (f"deliveries/{delivery['id']}/complete", {**proof, "cash_amount": "80"}, uuid.uuid4()),
        ("payments", {"customer_id": case.customer_id, "order_id": order["id"],
                      "amount": "20", "mode": "bank_transfer"}, uuid.uuid4()),
    ])
    assert sorted(response.status_code for response in responses) == [200, 201]
    assert Decimal(case.get_order(order["id"])["amount_paid"]) == 100
    assert case.get_order(order["id"])["status"] == "paid"
    assert case.payment_count() == 2
    case.assert_ledger(Decimal("0"))


def test_legacy_and_delivery_completion_race_cannot_finalize_twice(make_case):
    case = make_case(price="100", stock="2")
    order = case.make_order()
    delivery = case.dispatch(order["id"])
    proof = case.verify_and_prove(delivery["id"])
    responses = locked_requests(case, order_lock(order["id"]), [
        (f"orders/{order['id']}/deliver", proof, uuid.uuid4()),
        (f"deliveries/{delivery['id']}/complete", proof, uuid.uuid4()),
    ])
    assert sorted(response.status_code for response in responses) == [200, 409]
    assert audit_count(case, "orders.deliver", order["id"]) == 1
    assert audit_count(case, "deliveries.complete", delivery["id"]) == 1
    assert scalar(case.engine, select(func.count()).select_from(StockMovement).where(
        StockMovement.reference_id == uuid.UUID(order["id"]), StockMovement.movement_type == "outbound",
    )) == 1
    assert scalar(case.engine, select(InventoryItem.quantity).where(
        InventoryItem.product_id == uuid.UUID(case.product_id),
    )) == 1
    assert Decimal(case.customer()["credit_held"]) == 0
    case.assert_ledger(Decimal("100"))


def test_delivery_replay_still_enforces_current_partner_assignment(make_case):
    case = make_case(price="100")
    order = case.make_order()
    delivery = case.dispatch(order["id"])
    proof = case.verify_and_prove(delivery["id"])
    partner, actor_id = actor_session(case, role="delivery_partner")
    other, other_id = actor_session(case, role="delivery_partner")
    try:
        success(case.post(f"deliveries/{delivery['id']}/assign", {"partner_id": str(actor_id)}))
        key = uuid.uuid4()
        path = f"{case.api}/deliveries/{delivery['id']}/complete"
        original = success(partner.post(path, json=proof,
                                        headers={"X-Idempotency-Key": str(key)}, timeout=15))
        assert original["completed_at"] is not None
        with Session(case.engine) as session:
            row = session.get(Delivery, uuid.UUID(delivery["id"]), with_for_update=True)
            row.partner_id = other_id
            session.commit()
        assert partner.post(path, json=proof, headers={"X-Idempotency-Key": str(key)}, timeout=15).status_code == 403
        assert audit_count(case, "deliveries.complete", delivery["id"]) == 1
        case.assert_ledger(Decimal("100"))
    finally:
        partner.close()
        other.close()


def test_flushed_finalization_rolls_back_claim_stock_ledger_payment_and_audits(make_case):
    case = make_case(price="100", stock="2")
    order = case.make_order()
    delivery = case.dispatch(order["id"])
    proof = case.verify_and_prove(delivery["id"])
    key = uuid.uuid4()
    payload = {**proof, "cash_amount": "100"}

    async def fail_after_flush():
        from app.features.deliveries.router import DeliveryOut
        from app.features.orders.service import finalize_delivery
        from app.features.payments.schemas import CollectRequest
        from app.shared import idempotency

        engine = create_async_engine(os.environ["DATABASE_URL"], hide_parameters=True)
        sessions = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        tenant = uuid.UUID(case.client.admin_user["tenant_id"])
        actor = uuid.UUID(case.client.admin_user["id"])
        try:
            with pytest.raises(RuntimeError, match="Injected caller rollback"):
                async with sessions() as session, session.begin():
                    claim = await idempotency.claim(
                        session, tenant_id=tenant, actor_id=actor, operation="deliveries.complete",
                        key=key, payload={"delivery_id": uuid.UUID(delivery["id"]),
                                          "request": CollectRequest(**payload)},
                    )
                    _, completed = await finalize_delivery(
                        session, tenant_id=tenant, actor_id=actor, actor_role="super_admin",
                        delivery_id=uuid.UUID(delivery["id"]), **CollectRequest(**payload).model_dump(),
                    )
                    await session.flush()
                    idempotency.remember(
                        claim, response=DeliveryOut.model_validate(completed), status_code=200,
                        resource_type="delivery", resource_id=completed.id,
                    )
                    await session.flush()
                    raise RuntimeError("Injected caller rollback")
        finally:
            await engine.dispose()

    asyncio.run(fail_after_flush())
    assert case.get_order(order["id"])["status"] == "out_for_delivery"
    assert Decimal(case.get_order(order["id"])["amount_paid"]) == 0
    assert Decimal(case.customer()["credit_held"]) == 100
    assert case.payment_count() == 0
    assert len(case.ledger()) == 0
    assert audit_count(case, "orders.deliver", order["id"]) == 0
    assert audit_count(case, "deliveries.complete", delivery["id"]) == 0
    assert scalar(case.engine, select(func.count()).select_from(IdempotencyRecord).where(
        IdempotencyRecord.key == key,
    )) == 0
    assert scalar(case.engine, select(InventoryItem.quantity).where(
        InventoryItem.product_id == uuid.UUID(case.product_id),
    )) == 2
    assert scalar(case.engine, select(InventoryItem.reserved_qty).where(
        InventoryItem.product_id == uuid.UUID(case.product_id),
    )) == 1
    assert scalar(case.engine, select(Delivery.completed_at).where(
        Delivery.id == uuid.UUID(delivery["id"]),
    )) is None
    assert scalar(case.engine, select(OrderReservation.fulfilled_at).where(
        OrderReservation.order_id == uuid.UUID(order["id"]),
    )) is None
    success(case.post(f"deliveries/{delivery['id']}/complete", payload, key=key))
    assert case.payment_count() == 1
    assert audit_count(case, "deliveries.complete", delivery["id"]) == 1
    case.assert_ledger(Decimal("0"))


def legacy_rows(engine, *, customer_type="credit", total="80", status="pending", outstanding="0"):
    """Insert frozen 0003 rows without current ORM defaults or financial columns."""
    with Session(engine) as session:
        tenant = Tenant(name="Frozen financial fixture", currency="INR", is_setup_complete=True)
        session.add(tenant)
        session.flush()
        warehouse = Warehouse(tenant_id=tenant.id, code="LEGACY", name="Legacy warehouse")
        session.add(warehouse)
        session.flush()
        tenant_id, warehouse_id = tenant.id, warehouse.id
        session.commit()
    customer_id, order_id = uuid.uuid4(), uuid.uuid4()
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO customers (id,tenant_id,code,name,customer_type,credit_limit,outstanding,"
            "is_active) VALUES (:id,:tenant,'LEGACY','Legacy customer',:kind,100,:balance,true)"
        ), {"id": customer_id, "tenant": tenant_id, "kind": customer_type, "balance": Decimal(outstanding)})
        connection.execute(text(
            "INSERT INTO orders (id,tenant_id,order_number,customer_id,warehouse_id,status,channel,"
            "subtotal,tax_total,discount_total,grand_total,amount_paid) "
            "VALUES (:id,:tenant,'LEGACY-ORDER',:customer,:warehouse,:status,'manual',:total,0,0,:total,0)"
        ), {"id": order_id, "tenant": tenant_id, "customer": customer_id,
            "warehouse": warehouse_id, "status": status, "total": Decimal(total)})
    return tenant_id, customer_id, order_id


def legacy_receipt(
    engine, *, tenant, customer, amount="100", order=None, mode="cash", created_at=None,
):
    identifier = uuid.uuid4()
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO payments (id,tenant_id,customer_id,order_id,amount,mode,created_at) "
            "VALUES (:id,:tenant,:customer,:order,:amount,:mode,COALESCE(:created,now()))"
        ), {"id": identifier, "tenant": tenant, "customer": customer, "order": order,
            "amount": Decimal(amount), "mode": mode, "created": created_at})
    return identifier


def legacy_ledger(
    engine, *, tenant, customer, reference_type, reference_id, balance, debit="0", credit="0",
    created_at=None,
):
    identifier = uuid.uuid4()
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO ledger_entries (id,tenant_id,customer_id,debit,credit,balance_after,"
            "reference_type,reference_id,created_at) VALUES (:id,:tenant,:customer,:debit,:credit,"
            ":balance,:kind,:reference,COALESCE(:created,now()))"
        ), {"id": identifier, "tenant": tenant, "customer": customer, "debit": Decimal(debit),
            "credit": Decimal(credit), "balance": Decimal(balance), "kind": reference_type,
            "reference": reference_id, "created": created_at})
    return identifier


def legacy_history_snapshot(engine):
    fields = (
        ("customers", "id,tenant_id,customer_type,credit_limit,outstanding,created_at,updated_at"),
        ("orders", "id,tenant_id,customer_id,status,subtotal,tax_total,discount_total,"
         "grand_total,amount_paid,created_at,updated_at"),
        ("payments", "id,tenant_id,customer_id,order_id,amount,mode,reference,created_at,updated_at"),
        ("ledger_entries", "id,tenant_id,customer_id,debit,credit,balance_after,"
         "reference_type,reference_id,created_at,updated_at"),
        ("deliveries", "id,tenant_id,order_id,otp_verified,cash_collected,upi_collected,"
         "started_at,completed_at,created_at,updated_at"),
    )
    with engine.connect() as connection:
        return {table: connection.execute(text(
            f"SELECT {columns} FROM {table} ORDER BY id"
        )).all() for table, columns in fields}


def assert_legacy_rejected(engine, config, reason):
    before = legacy_history_snapshot(engine)
    with pytest.raises(RuntimeError, match=reason) as failure:
        command.upgrade(config, "20261109_0004")
    assert "requires reviewed reconciliation" in str(failure.value)
    assert "no historical orders, payments, or ledger entries were rewritten" in str(failure.value)
    assert legacy_history_snapshot(engine) == before
    with engine.connect() as connection:
        assert MigrationContext.configure(connection).get_current_heads() == ("20261109_0003",)
        assert "idempotency_records" not in inspect(connection).get_table_names()
        assert "credit_held" not in {column["name"] for column in inspect(connection).get_columns("customers")}


def legacy_collection_group(engine, *, standalone="0", cash="50", upi="20"):
    from datetime import timedelta

    collected = Decimal(cash) + Decimal(upi)
    paid = Decimal(standalone) + collected
    tenant, customer, order = legacy_rows(
        engine, status="delivered", outstanding=str(Decimal("80") - paid),
    )
    moment = datetime(2026, 1, 1, tzinfo=timezone.utc)
    legacy_ledger(
        engine, tenant=tenant, customer=customer, reference_type="order", reference_id=order,
        debit="80", balance="80", created_at=moment,
    )
    if Decimal(standalone):
        receipt = legacy_receipt(
            engine, tenant=tenant, customer=customer, order=order, amount=standalone,
            created_at=moment + timedelta(seconds=1),
        )
        legacy_ledger(
            engine, tenant=tenant, customer=customer, reference_type="payment", reference_id=receipt,
            credit=standalone, balance=str(Decimal("80") - Decimal(standalone)),
            created_at=moment + timedelta(seconds=1),
        )
    group_time = moment + timedelta(seconds=2)
    receipts = []
    for mode, amount in (("cash", cash), ("upi", upi)):
        if Decimal(amount):
            receipts.append(legacy_receipt(
                engine, tenant=tenant, customer=customer, order=order, amount=amount, mode=mode,
                created_at=group_time,
            ))
    delivery = uuid.uuid4()
    with engine.begin() as connection:
        connection.execute(text(
            "UPDATE orders SET amount_paid=:paid WHERE id=:id"
        ), {"paid": paid, "id": order})
        connection.execute(text(
            "INSERT INTO deliveries (id,tenant_id,order_id,priority,otp_verified,cash_collected,"
            "upi_collected,completed_at,created_at) VALUES (:id,:tenant,:order,5,true,:cash,:upi,"
            ":completed,:created)"
        ), {"id": delivery, "tenant": tenant, "order": order, "cash": Decimal(cash),
            "upi": Decimal(upi), "completed": group_time + timedelta(seconds=1), "created": group_time})
    group_ledger = legacy_ledger(
        engine, tenant=tenant, customer=customer, reference_type="delivery_payment",
        reference_id=delivery, credit=str(collected), balance=str(Decimal("80") - paid),
        created_at=group_time,
    )
    return tenant, customer, order, delivery, receipts, group_ledger


def test_frozen_migration_backfills_actual_legacy_credit_behavior(database):
    engine, config = database
    command.upgrade(config, "20261109_0003")
    tenant, customer, order = legacy_rows(engine)
    command.upgrade(config, "20261109_0004")
    with engine.connect() as connection:
        row = connection.execute(text(
            "SELECT payment_mode,credit_hold_amount,amount_paid FROM orders WHERE id=:id"
        ), {"id": order}).one()
        assert row.payment_mode == "credit"
        assert row.credit_hold_amount == 80
        assert row.amount_paid == 0
        assert connection.scalar(text("SELECT credit_held FROM customers WHERE id=:id"), {"id": customer}) == 80
        assert connection.scalar(text("SELECT outstanding FROM customers WHERE id=:id"), {"id": customer}) == 0
        assert "idempotency_records" in inspect(connection).get_table_names()


def test_historical_credit_ledger_evidence_is_preserved_when_customer_type_changed(database):
    engine, config = database
    command.upgrade(config, "20261109_0003")
    tenant, customer, order = legacy_rows(engine, customer_type="cash", status="delivered", outstanding="80")
    ledger_id = uuid.uuid4()
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO ledger_entries (id,tenant_id,customer_id,debit,credit,balance_after,"
            "reference_type,reference_id) VALUES (:id,:tenant,:customer,80,0,80,'order',:order)"
        ), {"id": ledger_id, "tenant": tenant, "customer": customer, "order": order})
    command.upgrade(config, "20261109_0004")
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT payment_mode FROM orders WHERE id=:id"), {"id": order}) == "credit"
        assert connection.scalar(text("SELECT credit_hold_amount FROM orders WHERE id=:id"), {"id": order}) == 0
        assert connection.scalar(text("SELECT balance_after FROM ledger_entries WHERE id=:id"), {"id": ledger_id}) == 80
        assert connection.scalar(text("SELECT outstanding FROM customers WHERE id=:id"), {"id": customer}) == 80


def test_legacy_linked_payment_mismatch_fails_without_rewriting_history(database):
    engine, config = database
    command.upgrade(config, "20261109_0003")
    tenant, customer, order = legacy_rows(engine)
    payment_id = uuid.uuid4()
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO payments (id,tenant_id,customer_id,order_id,amount,mode) "
            "VALUES (:id,:tenant,:customer,:order,50,'cash')"
        ), {"id": payment_id, "tenant": tenant, "customer": customer, "order": order})
    with pytest.raises(RuntimeError, match="linked payments disagree with amount_paid"):
        command.upgrade(config, "20261109_0004")
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT amount FROM payments WHERE id=:id"), {"id": payment_id}) == 50
        assert connection.scalar(text("SELECT amount_paid FROM orders WHERE id=:id"), {"id": order}) == 0
        assert MigrationContext.configure(connection).get_current_heads() == ("20261109_0003",)
        assert "credit_held" not in {column["name"] for column in inspect(connection).get_columns("customers")}


def test_ambiguous_legacy_clamped_advance_fails_closed(database):
    engine, config = database
    command.upgrade(config, "20261109_0003")
    tenant, customer, order = legacy_rows(engine)
    ledger_id = uuid.uuid4()
    receipt = legacy_receipt(engine, tenant=tenant, customer=customer, amount="50")
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO ledger_entries (id,tenant_id,customer_id,debit,credit,balance_after,"
            "reference_type,reference_id) VALUES (:id,:tenant,:customer,0,50,0,'payment',:receipt)"
        ), {"id": ledger_id, "tenant": tenant, "customer": customer, "receipt": receipt})
    with pytest.raises(RuntimeError, match="ambiguous running ledger balance"):
        command.upgrade(config, "20261109_0004")
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT credit FROM ledger_entries WHERE id=:id"), {"id": ledger_id}) == 50
        assert connection.scalar(text("SELECT balance_after FROM ledger_entries WHERE id=:id"), {"id": ledger_id}) == 0
        assert MigrationContext.configure(connection).get_current_heads() == ("20261109_0003",)


def test_empty_financial_revision_can_downgrade_and_reupgrade(database):
    engine, config = database
    command.upgrade(config, "20261109_0004")
    command.downgrade(config, "20261109_0003")
    with engine.connect() as connection:
        assert "idempotency_records" not in inspect(connection).get_table_names()
        assert "payment_mode" not in {column["name"] for column in inspect(connection).get_columns("orders")}
    command.upgrade(config, "20261109_0004")
    with engine.connect() as connection:
        assert MigrationContext.configure(connection).get_current_heads() == ("20261109_0004",)


def test_financial_downgrade_refuses_to_forget_persisted_order_mode(database):
    engine, config = database
    command.upgrade(config, "20261109_0003")
    tenant, customer, order = legacy_rows(engine)
    command.upgrade(config, "20261109_0004")
    with pytest.raises(RuntimeError, match="Financial modes, balances, and replay records must be preserved"):
        command.downgrade(config, "20261109_0003")
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT payment_mode FROM orders WHERE id=:id"), {"id": order}) == "credit"
        assert connection.scalar(text("SELECT credit_held FROM customers WHERE id=:id"), {"id": customer}) == 80
        assert MigrationContext.configure(connection).get_current_heads() == ("20261109_0004",)


@pytest.mark.parametrize("opening,remaining", [("0", "-100"), ("125", "25"), ("50", "-50")])
@pytest.mark.parametrize("mode", ["cash", "upi", "bank_transfer", "credit"])
def test_migration_valid_payment_reference_preserves_implied_opening_balance(database, opening, remaining, mode):
    engine, config = database
    command.upgrade(config, "20261109_0003")
    tenant, customer, order = legacy_rows(engine, outstanding=remaining)
    receipt = legacy_receipt(engine, tenant=tenant, customer=customer, mode=mode)
    legacy_ledger(
        engine, tenant=tenant, customer=customer, reference_type="payment", reference_id=receipt,
        credit="100", balance=remaining,
    )
    before = legacy_history_snapshot(engine)
    command.upgrade(config, "20261109_0004")
    assert legacy_history_snapshot(engine) == before
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT outstanding FROM customers WHERE id=:id"), {"id": customer}) == Decimal(remaining)
        assert connection.scalar(text("SELECT balance_after+credit-debit FROM ledger_entries WHERE reference_id=:id"), {"id": receipt}) == Decimal(opening)
        assert MigrationContext.configure(connection).get_current_heads() == ("20261109_0004",)


def test_migration_duplicate_payment_credit_cannot_create_a_phantom_advance(database):
    from datetime import timedelta

    engine, config = database
    command.upgrade(config, "20261109_0003")
    tenant, customer, order = legacy_rows(engine, outstanding="-200")
    receipt = legacy_receipt(engine, tenant=tenant, customer=customer)
    moment = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for offset, balance in ((0, "-100"), (1, "-200")):
        legacy_ledger(
            engine, tenant=tenant, customer=customer, reference_type="payment", reference_id=receipt,
            credit="100", balance=balance, created_at=moment + timedelta(seconds=offset),
        )
    assert_legacy_rejected(engine, config, "duplicate historical payment credits")


def test_migration_distinct_identical_receipts_are_each_credited_once(database):
    from datetime import timedelta

    engine, config = database
    command.upgrade(config, "20261109_0003")
    tenant, customer, order = legacy_rows(engine, outstanding="-200")
    moment = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for offset, balance in ((0, "-100"), (1, "-200")):
        receipt = legacy_receipt(engine, tenant=tenant, customer=customer)
        legacy_ledger(
            engine, tenant=tenant, customer=customer, reference_type="payment", reference_id=receipt,
            credit="100", balance=balance, created_at=moment + timedelta(seconds=offset),
        )
    before = legacy_history_snapshot(engine)
    command.upgrade(config, "20261109_0004")
    assert legacy_history_snapshot(engine) == before


@pytest.mark.parametrize("kind", ["order", "payment"])
@pytest.mark.parametrize("missing_reference", ["null", "orphan"])
def test_migration_null_and_orphan_financial_references_fail_closed(database, kind, missing_reference):
    engine, config = database
    command.upgrade(config, "20261109_0003")
    balance = "80" if kind == "order" else "-100"
    tenant, customer, order = legacy_rows(engine, outstanding=balance)
    reference = None if missing_reference == "null" else uuid.uuid4()
    legacy_ledger(
        engine, tenant=tenant, customer=customer, reference_type=kind, reference_id=reference,
        debit="80" if kind == "order" else "0", credit="100" if kind == "payment" else "0",
        balance=balance,
    )
    assert_legacy_rejected(engine, config, f"historical {kind} .* reference")


@pytest.mark.parametrize("kind", ["order", "payment"])
@pytest.mark.parametrize("cross_scope", ["customer", "tenant"])
def test_migration_cross_customer_or_tenant_attribution_fails_closed(database, kind, cross_scope):
    engine, config = database
    command.upgrade(config, "20261109_0003")
    tenant, customer, order = legacy_rows(engine, status="delivered", outstanding="0")
    if cross_scope == "tenant":
        other_tenant, other_customer, _ = legacy_rows(
            engine, outstanding="80" if kind == "order" else "-100",
        )
    else:
        other_tenant, other_customer = tenant, uuid.uuid4()
        with engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO customers (id,tenant_id,code,name,customer_type,credit_limit,"
                "outstanding,is_active) VALUES (:id,:tenant,'OTHER','Other legacy customer',"
                "'credit',100,:balance,true)"
            ), {"id": other_customer, "tenant": tenant,
                "balance": Decimal("80" if kind == "order" else "-100")})
    reference = order if kind == "order" else legacy_receipt(engine, tenant=tenant, customer=customer)
    legacy_ledger(
        engine, tenant=other_tenant, customer=other_customer, reference_type=kind,
        reference_id=reference, debit="80" if kind == "order" else "0",
        credit="100" if kind == "payment" else "0", balance="80" if kind == "order" else "-100",
    )
    assert_legacy_rejected(engine, config, f"historical {kind} .* reference")


@pytest.mark.parametrize("kind,amount", [("payment", "99"), ("payment", "101"), ("order", "79"), ("order", "81")])
def test_migration_financial_reference_amount_must_match_receipt_or_order(database, kind, amount):
    engine, config = database
    command.upgrade(config, "20261109_0003")
    tenant, customer, order = legacy_rows(
        engine, status="delivered" if kind == "order" else "pending",
        outstanding=amount if kind == "order" else str(-Decimal(amount)),
    )
    reference = order if kind == "order" else legacy_receipt(engine, tenant=tenant, customer=customer)
    legacy_ledger(
        engine, tenant=tenant, customer=customer, reference_type=kind, reference_id=reference,
        debit=amount if kind == "order" else "0", credit=amount if kind == "payment" else "0",
        balance=amount if kind == "order" else str(-Decimal(amount)),
    )
    assert_legacy_rejected(engine, config, f"historical {kind} .* reference")


def test_migration_every_receipt_requires_one_verifiable_credit(database):
    engine, config = database
    command.upgrade(config, "20261109_0003")
    tenant, customer, order = legacy_rows(engine)
    legacy_receipt(engine, tenant=tenant, customer=customer)
    assert_legacy_rejected(engine, config, "historical receipt must be credited exactly once")


@pytest.mark.parametrize("kind", [None, "opening_credit", "unknown"])
def test_migration_unverifiable_credit_kinds_are_not_silently_adopted(database, kind):
    engine, config = database
    command.upgrade(config, "20261109_0003")
    tenant, customer, order = legacy_rows(engine, outstanding="-100")
    legacy_receipt(engine, tenant=tenant, customer=customer)
    legacy_ledger(
        engine, tenant=tenant, customer=customer, reference_type=kind, reference_id=None,
        credit="100", balance="-100",
    )
    assert_legacy_rejected(engine, config, "unverifiable historical credit reference")


def test_migration_debit_only_opening_row_is_preserved(database):
    from datetime import timedelta

    engine, config = database
    command.upgrade(config, "20261109_0003")
    tenant, customer, order = legacy_rows(engine, outstanding="25")
    moment = datetime(2026, 1, 1, tzinfo=timezone.utc)
    legacy_ledger(
        engine, tenant=tenant, customer=customer, reference_type="opening", reference_id=None,
        debit="125", balance="125", created_at=moment,
    )
    receipt = legacy_receipt(engine, tenant=tenant, customer=customer)
    legacy_ledger(
        engine, tenant=tenant, customer=customer, reference_type="payment", reference_id=receipt,
        credit="100", balance="25", created_at=moment + timedelta(seconds=1),
    )
    before = legacy_history_snapshot(engine)
    command.upgrade(config, "20261109_0004")
    assert legacy_history_snapshot(engine) == before


@pytest.mark.parametrize("standalone,cash,upi", [("0", "50", "20"), ("25", "50", "0"), ("0", "0", "70")])
def test_migration_valid_delivery_group_excludes_individually_credited_receipts(database, standalone, cash, upi):
    engine, config = database
    command.upgrade(config, "20261109_0003")
    legacy_collection_group(engine, standalone=standalone, cash=cash, upi=upi)
    before = legacy_history_snapshot(engine)
    command.upgrade(config, "20261109_0004")
    assert legacy_history_snapshot(engine) == before


@pytest.mark.parametrize("damage", [
    "individual_overlap", "split_cash", "timestamp", "amount", "partial", "null", "orphan",
    "duplicate", "receipt_shortfall", "bank_receipt", "unverified_otp", "nonterminal",
    "cross_customer", "cross_tenant",
])
def test_migration_ambiguous_delivery_payment_group_fails_without_rewriting(database, damage):
    from datetime import timedelta

    engine, config = database
    command.upgrade(config, "20261109_0003")
    tenant, customer, order, delivery, receipts, group = legacy_collection_group(engine)
    with engine.begin() as connection:
        if damage == "individual_overlap":
            legacy_ledger(
                engine, tenant=tenant, customer=customer, reference_type="payment",
                reference_id=receipts[0], credit="50", balance="-40",
            )
            connection.execute(text("UPDATE customers SET outstanding=-40 WHERE id=:id"), {"id": customer})
        elif damage == "split_cash":
            created = connection.scalar(text("SELECT created_at FROM payments WHERE id=:id"), {"id": receipts[0]})
            connection.execute(text("UPDATE payments SET amount=25 WHERE id=:id"), {"id": receipts[0]})
            legacy_receipt(engine, tenant=tenant, customer=customer, order=order, amount="25", created_at=created)
        elif damage == "timestamp":
            connection.execute(text("UPDATE payments SET created_at=created_at+INTERVAL '1 second' WHERE id=:id"), {"id": receipts[0]})
        elif damage == "amount":
            connection.execute(text("UPDATE ledger_entries SET credit=69 WHERE id=:id"), {"id": group})
        elif damage == "partial":
            connection.execute(text("UPDATE deliveries SET completed_at=NULL WHERE id=:id"), {"id": delivery})
        elif damage == "receipt_shortfall":
            connection.execute(text("UPDATE payments SET amount=19 WHERE id=:id"), {"id": receipts[1]})
            connection.execute(text("UPDATE orders SET amount_paid=69 WHERE id=:id"), {"id": order})
        elif damage == "bank_receipt":
            connection.execute(text("UPDATE payments SET mode='bank_transfer' WHERE id=:id"), {"id": receipts[1]})
        elif damage == "unverified_otp":
            connection.execute(text("UPDATE deliveries SET otp_verified=false WHERE id=:id"), {"id": delivery})
        elif damage == "nonterminal":
            connection.execute(text("UPDATE orders SET status='out_for_delivery' WHERE id=:id"), {"id": order})
        elif damage == "cross_customer":
            other_customer = uuid.uuid4()
            connection.execute(text(
                "INSERT INTO customers (id,tenant_id,code,name,customer_type,credit_limit,"
                "outstanding,is_active) VALUES (:id,:tenant,'OTHER','Other legacy customer',"
                "'credit',100,10,true)"
            ), {"id": other_customer, "tenant": tenant})
            connection.execute(text("UPDATE ledger_entries SET customer_id=:customer WHERE id=:id"),
                               {"customer": other_customer, "id": group})
        elif damage == "cross_tenant":
            other_tenant, other_customer, _ = legacy_rows(engine, outstanding="10")
            connection.execute(text(
                "UPDATE ledger_entries SET tenant_id=:tenant,customer_id=:customer WHERE id=:id"
            ), {"tenant": other_tenant, "customer": other_customer, "id": group})
        elif damage in {"null", "orphan"}:
            connection.execute(text("UPDATE ledger_entries SET reference_id=:reference WHERE id=:id"),
                               {"reference": None if damage == "null" else uuid.uuid4(), "id": group})
        else:
            created = connection.scalar(text("SELECT created_at FROM ledger_entries WHERE id=:id"), {"id": group})
            legacy_ledger(
                engine, tenant=tenant, customer=customer, reference_type="delivery_payment",
                reference_id=delivery, credit="70", balance="-60", created_at=created + timedelta(seconds=1),
            )
            connection.execute(text("UPDATE customers SET outstanding=-60 WHERE id=:id"), {"id": customer})
    reason = ("duplicate legacy delivery_payment credits" if damage == "duplicate" else
              "historical order debit reference" if damage == "nonterminal" else
              "legacy delivery_payment reference" if damage in {
                  "amount", "partial", "null", "orphan", "unverified_otp", "cross_customer", "cross_tenant",
              } else
              "ambiguous legacy delivery_payment receipt attribution")
    assert_legacy_rejected(engine, config, reason)
