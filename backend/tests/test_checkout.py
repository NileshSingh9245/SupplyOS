"""Additive quote/checkout contracts on owned test resources, never live business data."""
from __future__ import annotations

import asyncio
import os
import secrets
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
import requests
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.exceptions import Conflict, DomainError, Forbidden
from app.features.checkout import service
from app.features.checkout.proof import decode_quote, encode_quote
from app.features.checkout.schemas import CheckoutCreate, QuoteClaim, QuoteCreate
from app.infrastructure.db.models.customer import Customer, LedgerEntry
from app.infrastructure.db.models.inventory import InventoryItem
from app.infrastructure.db.models.order import Order, OrderItem, OrderReservation, OrderStatusHistory
from app.infrastructure.db.models.user import User
from app.infrastructure.db.models.tenant import Tenant
from test_customer_onboarding import checked, database, roles


def capsule():
    actor = User(id=uuid.uuid4(), tenant_id=uuid.uuid4(), customer_id=uuid.uuid4(),
                 role="customer", is_active=True, session_version=2)
    request = QuoteCreate(warehouse_id=uuid.uuid4(), items=[{
        "product_id": uuid.uuid4(), "quantity": "1.000",
    }])
    claim = QuoteClaim(id=uuid.uuid4(), actor_id=actor.id, tenant_id=actor.tenant_id,
                       customer_id=actor.customer_id, authorization_epoch=actor.session_version,
                       expires_at=datetime.now(timezone.utc) + timedelta(minutes=10), request=request,
                       prices_hash="a" * 64)
    return actor, claim


def test_quote_proof_is_purpose_key_bound_and_preserves_typed_terms():
    actor, claim = capsule()
    proof = encode_quote(claim, secret="Owned fixture signing input; not a live service key")
    decoded = decode_quote(proof, secret="Owned fixture signing input; not a live service key")
    assert decoded == claim
    service.authorize_claim(decoded, actor)
    with pytest.raises(DomainError):
        decode_quote(proof, secret="Different owned fixture signing input")
    with pytest.raises(DomainError):
        decode_quote(proof[:-1] + ("A" if proof[-1] != "A" else "B"), secret="Owned fixture signing input; not a live service key")


@pytest.mark.parametrize("value", ["", "x", "a.b.c", "../x", "a=.b", "a.b?key=secret", "a" * 32769],
                         ids=["empty", "short", "parts", "path", "padding", "query", "oversize"])
def test_quote_proof_rejects_malformed_values_without_echo(value):
    with pytest.raises(DomainError) as failure:
        decode_quote(value, secret="Owned fixture input")
    assert failure.value.detail == "The accepted quote could not be validated"


@pytest.mark.parametrize("field,value", [
    ("id", uuid.uuid4()), ("tenant_id", uuid.uuid4()), ("customer_id", uuid.uuid4()),
    ("session_version", 3), ("role", "warehouse_manager"), ("is_active", False),
])
def test_quote_claim_is_bound_to_current_actor_profile_and_epoch(field, value):
    actor, claim = capsule()
    setattr(actor, field, value)
    with pytest.raises(Forbidden):
        service.authorize_claim(claim, actor)


def test_expired_quote_cannot_start_checkout_before_any_database_effect():
    actor, claim = capsule()
    claim.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    with pytest.raises(Conflict, match="expired"):
        asyncio.run(service.checkout(None, user=actor, claim=claim))


@pytest.mark.parametrize("extra", ["tenant_id", "customer_id", "unit_price", "subtotal", "status", "pricing_snapshot"])
def test_quote_input_cannot_supply_scope_price_or_order_authority(extra):
    _, claim = capsule()
    payload = claim.request.model_dump()
    payload[extra] = "forbidden fixture authority"
    with pytest.raises(ValueError):
        QuoteCreate.model_validate(payload)


@pytest.mark.parametrize("quantity", ["0", "-1", "NaN", "Infinity", "1.0001", "10000000000000"])
def test_quote_quantities_are_positive_finite_and_exact(quantity):
    with pytest.raises(ValueError):
        QuoteCreate(warehouse_id=uuid.uuid4(), items=[{"product_id": uuid.uuid4(), "quantity": quantity}])


@pytest.fixture
def basket(roles, api_prefix):
    if os.environ.get("SUPPLYOS_OWNED_TEST_ENV") != "1":
        pytest.skip("Checkout integration requires the owned isolated verifier")
    owner, customer = roles["super_admin"], roles["customer"]
    warehouse = checked(owner.get(f"{api_prefix}/warehouses", timeout=10))[0]
    product = checked(owner.post(f"{api_prefix}/products", json={
        "sku": "checkout-" + uuid.uuid4().hex[:16], "name": "Owned checkout product", "unit": "pcs",
        "base_price": "10.00", "gst_rate": "5.00",
    }, timeout=15), 201)
    checked(owner.post(f"{api_prefix}/inventory/adjust", json={
        "product_id": product["id"], "warehouse_id": warehouse["id"], "delta_qty": "100.000",
    }, timeout=15))
    profile = checked(customer.get(f"{api_prefix}/customers", timeout=10))["items"][0]
    return {"owner": owner, "customer": customer, "warehouse": warehouse, "product": product,
            "profile": profile, "body": {"warehouse_id": warehouse["id"], "payment_mode": "cash",
                                         "items": [{"product_id": product["id"], "quantity": "1.000"}]}}


def quoted(basket, api_prefix, *, body=None, key=None):
    identity = key or str(uuid.uuid4())
    value = checked(basket["customer"].post(f"{api_prefix}/order-quotes", json=body or basket["body"],
                    headers={"X-Idempotency-Key": identity}, timeout=20), 201)
    assert value["id"] == identity
    return value


def place(basket, api_prefix, quote, *, key=None):
    return basket["customer"].post(f"{api_prefix}/orders/checkout", json={
        "quote_id": quote["id"], "quote_proof": quote["quote_proof"],
    }, headers={"X-Idempotency-Key": key or quote["id"]}, timeout=30)


@pytest.mark.integration
def test_quote_has_no_stock_order_or_credit_effect_and_replay_preserves_original_terms(basket, database, api_prefix):
    quote = quoted(basket, api_prefix)
    assert quote["grand_total"] == "10.50" and quote["currency_code"] == "INR" and quote["blockers"] == []
    checked(basket["owner"].patch(f"{api_prefix}/products/{basket['product']['id']}",
                                 json={"base_price": "20.00"}, timeout=15))
    assert quoted(basket, api_prefix, key=quote["id"]) == quote
    with Session(database) as db:
        stock = db.scalar(select(InventoryItem).where(InventoryItem.product_id == uuid.UUID(basket["product"]["id"])))
        assert stock.reserved_qty == 0 and stock.quantity == 100
        assert db.get(Customer, uuid.UUID(basket["profile"]["id"])).credit_held == 0
        assert db.scalar(select(OrderItem.id).where(
            OrderItem.product_id == uuid.UUID(basket["product"]["id"]))) is None
        assert db.scalar(select(OrderReservation.id).join(
            InventoryItem, InventoryItem.id == OrderReservation.inventory_item_id,
        ).where(InventoryItem.product_id == uuid.UUID(basket["product"]["id"]))) is None


@pytest.mark.integration
def test_checkout_atomically_reserves_and_recovers_same_order_after_price_change(basket, database, api_prefix):
    quote = quoted(basket, api_prefix)
    result = checked(place(basket, api_prefix, quote), 201)
    assert result["status"] == "reserved" and result["grand_total"] == "10.50"
    assert result["quote_id"] == quote["id"] and result["currency_code"] == "INR"
    checked(basket["owner"].patch(f"{api_prefix}/products/{basket['product']['id']}",
                                 json={"base_price": "25.00"}, timeout=15))
    assert checked(place(basket, api_prefix, quote), 201) == result
    assert place(basket, api_prefix, quote, key=str(uuid.uuid4())).status_code == 400
    with Session(database) as db:
        row = db.get(Order, uuid.UUID(result["id"]))
        assert row.meta["checkout_currency"] == "INR" and row.meta["checkout_quote_id"] == quote["id"]
        stock = db.scalar(select(InventoryItem).where(InventoryItem.product_id == uuid.UUID(basket["product"]["id"])))
        assert stock.quantity == 100 and stock.reserved_qty == 1
        events = list(db.scalars(select(OrderStatusHistory).where(OrderStatusHistory.order_id == row.id)
                                 .order_by(OrderStatusHistory.created_at)))
        assert [event.to_status for event in events] == ["pending", "reserved"]
        assert events[0].created_at < events[1].created_at
        tenant_id = row.tenant_id
        previous_currency = db.get(Tenant, tenant_id).currency
        db.get(Tenant, tenant_id).currency = "USD"
        db.commit()
    try:
        current = checked(basket["customer"].get(f"{api_prefix}/orders/{result['id']}", timeout=15))
        assert current["currency_code"] == "INR" and current["grand_total"] == result["grand_total"]
    finally:
        with Session(database) as db, db.begin():
            db.get(Tenant, tenant_id).currency = previous_currency


@pytest.mark.integration
def test_changed_quote_or_insufficient_stock_rolls_back_checkout_completely(basket, database, api_prefix):
    quote = quoted(basket, api_prefix)
    checked(basket["owner"].patch(f"{api_prefix}/products/{basket['product']['id']}",
                                 json={"base_price": "15.00"}, timeout=15))
    assert place(basket, api_prefix, quote).status_code == 409
    body = {**basket["body"], "items": [{"product_id": basket["product"]["id"], "quantity": "101.000"}]}
    shortage = quoted(basket, api_prefix, body=body)
    assert shortage["blockers"] == ["insufficient_stock"]
    assert place(basket, api_prefix, shortage).status_code == 409
    with Session(database) as db:
        stock = db.scalar(select(InventoryItem).where(InventoryItem.product_id == uuid.UUID(basket["product"]["id"])))
        assert stock.quantity == 100 and stock.reserved_qty == 0
        assert db.scalar(select(OrderItem.id).where(
            OrderItem.product_id == uuid.UUID(basket["product"]["id"]))) is None
        assert db.scalar(select(OrderReservation.id).join(
            InventoryItem, InventoryItem.id == OrderReservation.inventory_item_id,
        ).where(InventoryItem.product_id == uuid.UUID(basket["product"]["id"]))) is None


@pytest.mark.integration
def test_credit_limit_quote_blocker_and_checkout_reject_before_reservation(basket, database, api_prefix):
    checked(basket["owner"].patch(f"{api_prefix}/customers/{basket['profile']['id']}",
                                 json={"customer_type": "credit", "credit_limit": "10.00"}, timeout=15))
    quote = quoted(basket, api_prefix, body={**basket["body"], "payment_mode": "credit"})
    assert quote["blockers"] == ["credit_limit_exceeded"]
    assert place(basket, api_prefix, quote).status_code == 409
    with Session(database) as db:
        stock = db.scalar(select(InventoryItem).where(InventoryItem.product_id == uuid.UUID(basket["product"]["id"])))
        assert stock.reserved_qty == 0
        profile = db.get(Customer, uuid.UUID(basket["profile"]["id"]))
        assert profile.credit_held == 0 and profile.outstanding == 0


@pytest.mark.integration
def test_quote_and_checkout_require_customer_role_and_original_request_identity(basket, roles, api_prefix):
    assert basket["customer"].post(f"{api_prefix}/order-quotes", json=basket["body"], timeout=15).status_code == 422
    for role in ("super_admin", "warehouse_manager", "accountant", "delivery_partner"):
        assert roles[role].post(f"{api_prefix}/order-quotes", json=basket["body"],
                                headers={"X-Idempotency-Key": str(uuid.uuid4())}, timeout=15).status_code == 403
    quote = quoted(basket, api_prefix)
    assert basket["customer"].post(f"{api_prefix}/orders/checkout", json={
        "quote_id": quote["id"], "quote_proof": quote["quote_proof"], "unit_price": "0.00",
    }, headers={"X-Idempotency-Key": quote["id"]}, timeout=15).status_code == 422
    assert basket["customer"].post(f"{api_prefix}/order-quotes?tenant_id=shadow", json=basket["body"],
                                  headers={"X-Idempotency-Key": str(uuid.uuid4())}, timeout=15).status_code == 400


def wait_for_inventory_waiters(database, *, count: int) -> None:
    deadline = time.monotonic() + 15
    with database.connect() as connection:
        while time.monotonic() < deadline:
            observed = connection.execute(text("""
                SELECT count(*) FROM pg_stat_activity
                WHERE datname = current_database() AND pid <> pg_backend_pid()
                  AND wait_event_type = 'Lock' AND query ILIKE '%inventory_items%'
            """)).scalar_one()
            connection.commit()  # PostgreSQL activity snapshots are transaction-scoped.
            if observed >= count:
                return
            time.sleep(0.02)
    pytest.fail(f"Checkout did not reach {count} observed canonical inventory waiters", pytrace=False)


@pytest.mark.integration
def test_two_customer_checkouts_observe_stock_contention_without_oversell(basket, database, api_prefix):
    class PrivateText(str):
        def __repr__(self):
            return "<owned private test input>"

    email = "checkout-b-" + uuid.uuid4().hex[:12] + "@example.com"
    password = PrivateText(secrets.token_urlsafe(18))
    created = checked(basket["owner"].post(f"{api_prefix}/auth/register-customer", json={
        "email": email, "password": str(password), "full_name": "Owned checkout actor B",
    }, timeout=20), 201)
    client_b = requests.Session()
    try:
        checked(client_b.post(f"{api_prefix}/auth/login", json={"email": email, "password": str(password)}, timeout=15))
        identity_b = checked(client_b.get(f"{api_prefix}/auth/me", timeout=15))
        identity_a = checked(basket["customer"].get(f"{api_prefix}/auth/me", timeout=15))
        assert identity_b["id"] != identity_a["id"] and created["id"] == identity_b["id"]
        body_a = {**basket["body"], "items": [{"product_id": basket["product"]["id"], "quantity": "100.000"}]}
        body_b = {**basket["body"], "items": [{"product_id": basket["product"]["id"], "quantity": "60.000"}]}
        quote_a = quoted(basket, api_prefix, body=body_a)
        basket_b = {**basket, "customer": client_b}
        quote_b = quoted(basket_b, api_prefix, body=body_b)
        with ThreadPoolExecutor(max_workers=2) as executor, Session(database) as blocker:
            blocker.scalar(select(InventoryItem).where(
                InventoryItem.product_id == uuid.UUID(basket["product"]["id"]),
            ).with_for_update())
            first = executor.submit(place, basket, api_prefix, quote_a)
            wait_for_inventory_waiters(database, count=1)
            second = executor.submit(place, basket_b, api_prefix, quote_b)
            wait_for_inventory_waiters(database, count=2)
            blocker.commit()
            success = checked(first.result(timeout=30), 201)
            assert second.result(timeout=30).status_code == 409
        with Session(database) as db:
            stock = db.scalar(select(InventoryItem).where(InventoryItem.product_id == uuid.UUID(basket["product"]["id"])))
            assert stock.quantity == 100 and stock.reserved_qty == 100
            rows = list(db.scalars(select(OrderItem).where(OrderItem.product_id == stock.product_id)))
            assert len(rows) == 1 and rows[0].quantity == 100 and str(rows[0].order_id) == success["id"]
            assert db.get(Order, rows[0].order_id).status == "reserved"
    finally:
        client_b.cookies.clear()
        client_b.close()


@pytest.mark.integration
def test_s2_exact_credit_exposure_rejects_eighteen_thousand_before_stock_effect(basket, database, api_prefix):
    checked(basket["owner"].patch(f"{api_prefix}/customers/{basket['profile']['id']}",
                                 json={"customer_type": "credit", "credit_limit": "50000.00"}, timeout=15))
    checked(basket["owner"].patch(f"{api_prefix}/products/{basket['product']['id']}",
                                 json={"base_price": "18000.00", "gst_rate": "0.00"}, timeout=15))
    with Session(database) as db, db.begin():
        profile = db.get(Customer, uuid.UUID(basket["profile"]["id"]))
        profile.outstanding = Decimal("37000.00")
        db.add(LedgerEntry(tenant_id=profile.tenant_id, customer_id=profile.id,
                           debit=Decimal("37000.00"), credit=Decimal("0.00"),
                           balance_after=Decimal("37000.00"), reference_type="owned_opening_balance",
                           note="Owned S2 scenario opening balance, not a payment receipt"))
    quote = quoted(basket, api_prefix, body={**basket["body"], "payment_mode": "credit"})
    assert quote["grand_total"] == "18000.00" and quote["blockers"] == ["credit_limit_exceeded"]
    assert place(basket, api_prefix, quote).status_code == 409
    with Session(database) as db:
        stock = db.scalar(select(InventoryItem).where(InventoryItem.product_id == uuid.UUID(basket["product"]["id"])))
        profile = db.get(Customer, uuid.UUID(basket["profile"]["id"]))
        assert stock.quantity == 100 and stock.reserved_qty == 0
        assert profile.credit_held == 0 and profile.outstanding == Decimal("37000.00")
        assert db.scalar(select(OrderItem.id).where(OrderItem.product_id == stock.product_id)) is None
