"""Real HTTP/PostgreSQL contention checks, guarded by isolated API fixtures."""
from __future__ import annotations

import threading
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import requests
import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session


def result(response, status=200):
    if response.status_code != status:
        raise AssertionError(f"Isolated inventory fixture failed (HTTP {response.status_code})")
    return response.json()


def product_and_warehouse(admin_session, api_prefix):
    warehouse = result(admin_session.get(f"{api_prefix}/warehouses", timeout=10))[0]["id"]
    product = result(admin_session.post(f"{api_prefix}/products", json={
        "sku": f"LOCK-{uuid.uuid4().hex[:10]}", "name": "Concurrency product",
        "base_price": "10.00", "gst_rate": "0", "unit": "pcs",
    }, timeout=10), 201)["id"]
    return product, warehouse


def customer(admin_session, api_prefix):
    return result(admin_session.post(f"{api_prefix}/customers", json={
        "name": "Concurrency customer", "customer_type": "cash",
    }, timeout=10), 201)["id"]


def make_order(admin_session, api_prefix, buyer, warehouse, items):
    return result(admin_session.post(f"{api_prefix}/orders", json={
        "customer_id": buyer, "warehouse_id": warehouse,
        "items": [{"product_id": product, "quantity": str(quantity)} for product, quantity in items],
    }, timeout=10), 201)["id"]


def post_together(admin_session, endpoints, payloads):
    barrier = threading.Barrier(len(endpoints))
    headers = dict(admin_session.headers)

    def send(pair):
        endpoint, payload = pair
        barrier.wait(timeout=10)
        return requests.post(endpoint, headers=headers, json=payload, timeout=30)

    with ThreadPoolExecutor(max_workers=len(endpoints)) as pool:
        return list(pool.map(send, zip(endpoints, payloads)))


def inventory(admin_session, api_prefix, product):
    return result(admin_session.get(f"{api_prefix}/inventory", params={"product_id": product}, timeout=10))


def test_concurrent_first_adjustments_create_one_nullable_location(admin_session, api_prefix):
    product, warehouse = product_and_warehouse(admin_session, api_prefix)
    payload = {"product_id": product, "warehouse_id": warehouse, "delta_qty": "1"}
    responses = post_together(
        admin_session, [f"{api_prefix}/inventory/adjust"] * 8, [payload] * 8,
    )
    assert all(response.status_code == 200 for response in responses)
    rows = inventory(admin_session, api_prefix, product)
    assert len(rows) == 1
    assert Decimal(rows[0]["quantity"]) == Decimal("8")
    assert Decimal(rows[0]["reserved_qty"]) == 0


def test_two_orders_cannot_reserve_the_same_physical_stock(admin_session, api_prefix):
    product, warehouse = product_and_warehouse(admin_session, api_prefix)
    buyer = customer(admin_session, api_prefix)
    result(admin_session.post(f"{api_prefix}/inventory/adjust", json={
        "product_id": product, "warehouse_id": warehouse, "delta_qty": "10",
    }, timeout=10))
    orders = [make_order(admin_session, api_prefix, buyer, warehouse, [(product, 10)]) for _ in range(2)]
    responses = post_together(admin_session, [f"{api_prefix}/orders/{order}/reserve" for order in orders], [{}, {}])
    assert sorted(response.status_code for response in responses) == [200, 409]
    rows = inventory(admin_session, api_prefix, product)
    assert Decimal(rows[0]["quantity"]) == 10
    assert Decimal(rows[0]["reserved_qty"]) == 10
    assert Decimal(rows[0]["available_qty"]) == 0


def test_reverse_product_order_does_not_deadlock_reservations(admin_session, api_prefix):
    first, warehouse = product_and_warehouse(admin_session, api_prefix)
    second, _ = product_and_warehouse(admin_session, api_prefix)
    buyer = customer(admin_session, api_prefix)
    for product in (first, second):
        result(admin_session.post(f"{api_prefix}/inventory/adjust", json={
            "product_id": product, "warehouse_id": warehouse, "delta_qty": "1",
        }, timeout=10))
    orders = [
        make_order(admin_session, api_prefix, buyer, warehouse, [(first, 1), (second, 1)]),
        make_order(admin_session, api_prefix, buyer, warehouse, [(second, 1), (first, 1)]),
    ]
    responses = post_together(admin_session, [f"{api_prefix}/orders/{order}/reserve" for order in orders], [{}, {}])
    assert sorted(response.status_code for response in responses) == [200, 409]
    for product in (first, second):
        rows = inventory(admin_session, api_prefix, product)
        assert Decimal(rows[0]["reserved_qty"]) == 1


def test_failed_multi_product_reservation_rolls_back_and_cancel_releases_once(admin_session, api_prefix):
    first, warehouse = product_and_warehouse(admin_session, api_prefix)
    missing, _ = product_and_warehouse(admin_session, api_prefix)
    buyer = customer(admin_session, api_prefix)
    result(admin_session.post(f"{api_prefix}/inventory/adjust", json={
        "product_id": first, "warehouse_id": warehouse, "delta_qty": "5",
    }, timeout=10))
    failed = make_order(admin_session, api_prefix, buyer, warehouse, [(first, 5), (missing, 1)])
    assert admin_session.post(f"{api_prefix}/orders/{failed}/reserve", timeout=10).status_code == 409
    assert Decimal(inventory(admin_session, api_prefix, first)[0]["reserved_qty"]) == 0
    valid = make_order(admin_session, api_prefix, buyer, warehouse, [(first, 5)])
    result(admin_session.post(f"{api_prefix}/orders/{valid}/reserve", timeout=10))
    result(admin_session.post(f"{api_prefix}/orders/{valid}/cancel", json={"note": "Verification cancellation"}, timeout=10))
    assert Decimal(inventory(admin_session, api_prefix, first)[0]["reserved_qty"]) == 0
    assert admin_session.post(f"{api_prefix}/orders/{valid}/cancel", json={"note": "Repeat"}, timeout=10).status_code == 409
    assert Decimal(inventory(admin_session, api_prefix, first)[0]["quantity"]) == 5


@pytest.mark.parametrize("operation", ["cancel", "deliver"])
def test_mixed_reserve_and_finalize_share_canonical_stock_lock_order(admin_session, api_prefix, operation):
    from app.infrastructure.db.models.inventory import InventoryItem

    products = sorted([product_and_warehouse(admin_session, api_prefix)[0] for _ in range(2)])
    warehouse = result(admin_session.get(f"{api_prefix}/warehouses", timeout=10))[0]["id"]
    buyer = customer(admin_session, api_prefix)
    url = make_url(os.environ["DATABASE_URL_SYNC"])
    if url.host not in {"127.0.0.1", "localhost", "::1"} or not (url.database or "").startswith("supplyos_test_"):
        pytest.fail("Mixed stock tests require the owned loopback database", pytrace=False)
    engine = create_engine(url, hide_parameters=True)
    ids = [uuid.UUID("f" + uuid.uuid4().hex[1:]), uuid.UUID("0" + uuid.uuid4().hex[1:])]
    try:
        with Session(engine) as session:
            for product, identifier in zip(products, ids):
                session.add(InventoryItem(
                    id=identifier, tenant_id=uuid.UUID(admin_session.admin_user["tenant_id"]),
                    product_id=uuid.UUID(product), warehouse_id=uuid.UUID(warehouse), quantity=Decimal("2"),
                ))
            session.commit()
        old = make_order(admin_session, api_prefix, buyer, warehouse, [(product, 1) for product in products])
        result(admin_session.post(f"{api_prefix}/orders/{old}/reserve", timeout=10))
        if operation == "deliver":
            for step in ("pick", "pack", "dispatch"):
                result(admin_session.post(f"{api_prefix}/orders/{old}/{step}", timeout=10))
            import io
            from PIL import Image
            from app.infrastructure.db.models.order import Delivery

            delivered_order = result(admin_session.get(f"{api_prefix}/orders/{old}", timeout=10))
            result(admin_session.post(f"{api_prefix}/payments", json={
                "customer_id": buyer, "order_id": old, "amount": delivered_order["amount_due"], "mode": "cash",
            }, timeout=10), 201)
            delivery = next(row for row in result(admin_session.get(f"{api_prefix}/deliveries", timeout=10)) if row["order_id"] == old)
            with engine.connect() as connection:
                otp = connection.scalar(select(Delivery.otp_code).where(Delivery.id == uuid.UUID(delivery["id"])))
            result(admin_session.post(f"{api_prefix}/deliveries/{delivery['id']}/verify-otp", json={"otp_code": otp}, timeout=10))
            buffer = io.BytesIO()
            Image.new("RGB", (4, 4), color="white").save(buffer, format="PNG")
            complete_body = {}
            for kind, field in (("signature", "signature_url"), ("photo", "proof_photo_url")):
                receipt = result(admin_session.post(f"{api_prefix}/deliveries/{delivery['id']}/proofs", data={"kind": kind},
                                                    files={"file": ("proof.png", buffer.getvalue(), "image/png")},
                                                    headers={"Content-Type": None}, timeout=15), 201)
                complete_body[field] = receipt["url"]
        else:
            complete_body = {}
        new = make_order(admin_session, api_prefix, buyer, warehouse, [(product, 1) for product in reversed(products)])
        headers = dict(admin_session.headers)
        with engine.connect() as holder, ThreadPoolExecutor(max_workers=2) as workers:
            holder.execute(select(InventoryItem.id).where(InventoryItem.id == ids[0]).with_for_update())
            holder_pid = holder.scalar(text("SELECT pg_backend_pid()"))
            wait_chain = text(
                "WITH RECURSIVE waiters(pid) AS ("
                "SELECT pid FROM pg_stat_activity WHERE wait_event_type = 'Lock' "
                "AND :holder = ANY(pg_blocking_pids(pid)) UNION "
                "SELECT activity.pid FROM pg_stat_activity activity JOIN waiters "
                "ON waiters.pid = ANY(pg_blocking_pids(activity.pid)) "
                "WHERE activity.wait_event_type = 'Lock') SELECT count(*) FROM waiters"
            )

            def post(order, action):
                return requests.post(f"{api_prefix}/orders/{order}/{action}", headers=headers,
                                     json=complete_body if action == "deliver" else {}, timeout=30)

            reserve = workers.submit(post, new, "reserve")
            observed = False
            finalize = None
            try:
                with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as observer:
                    deadline = time.monotonic() + 8
                    while time.monotonic() < deadline:
                        waiting = observer.scalar(wait_chain, {"holder": holder_pid})
                        if waiting:
                            break
                        time.sleep(0.01)
                    else:
                        pytest.fail("Reservation did not reach the observed stock row lock", pytrace=False)
                    finalize = workers.submit(post, old, operation)
                    deadline = time.monotonic() + 8
                    while time.monotonic() < deadline:
                        waiting = observer.scalar(wait_chain, {"holder": holder_pid})
                        if waiting >= 2:
                            observed = True
                            break
                        time.sleep(0.01)
            finally:
                holder.rollback()
            if not observed:
                pytest.fail("Mixed stock operations did not share the observed canonical lock", pytrace=False)
            assert reserve.result(timeout=30).status_code == 200
            assert finalize is not None and finalize.result(timeout=30).status_code == 200
        for product in products:
            row = inventory(admin_session, api_prefix, product)[0]
            assert Decimal(row["reserved_qty"]) == 1
            assert Decimal(row["quantity"]) == (2 if operation == "cancel" else 1)
    finally:
        engine.dispose()
