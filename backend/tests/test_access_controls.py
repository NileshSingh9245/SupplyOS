"""Tenant relationships and role/privacy boundaries on the owned real API/database."""
from __future__ import annotations

import os
import secrets
import uuid
from decimal import Decimal
from urllib.parse import urlsplit

import pytest
import requests
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session


def success(response, expected=200):
    if response.status_code != expected:
        path = urlsplit(response.request.url).path
        pytest.fail(f"Isolated {response.request.method} {path} failed (HTTP {response.status_code})", pytrace=False)
    return response.json()


@pytest.fixture(scope="module")
def access_data(admin_session, api_prefix, base_url):
    from app.core.security import hash_password
    from app.infrastructure.db.models.customer import Customer
    from app.infrastructure.db.models.order import Order
    from app.infrastructure.db.models.product import Batch, Category, Product
    from app.infrastructure.db.models.tenant import Tenant
    from app.infrastructure.db.models.user import User
    from app.infrastructure.db.models.warehouse import Rack, Shelf, Warehouse

    tenant_id = success(admin_session.get(f"{api_prefix}/setup/status", timeout=10))["tenant_id"]
    assert tenant_id == admin_session.admin_user["tenant_id"]
    assert admin_session.admin_user["role"] == "super_admin"
    actors = []
    customers = []
    for _ in range(2):
        email = f"customer-{uuid.uuid4().hex}@example.com"
        password = secrets.token_urlsafe(24)
        session = requests.Session()
        registration = admin_session.post(f"{api_prefix}/auth/register-customer", json={
            "email": email, "password": password, "full_name": "Private verification customer",
        }, timeout=15)
        created = success(registration, 201)
        assert created["tenant_id"] == tenant_id
        assert created["role"] == "customer"
        assert registration.headers["Cache-Control"] == "no-store"
        assert "Set-Cookie" not in registration.headers
        success(session.post(f"{api_prefix}/auth/login", json={
            "email": email, "password": password, "tenant_id": tenant_id,
        }, timeout=15))
        actors.append(session)
        own = success(session.get(f"{api_prefix}/customers", timeout=10))["items"]
        if len(own) != 1:
            pytest.fail("Customer directory did not restrict the newly registered profile", pytrace=False)
        customers.append(own[0]["id"])
    warehouse_id = success(admin_session.get(f"{api_prefix}/warehouses", timeout=10))[0]["id"]
    product = success(admin_session.post(f"{api_prefix}/products", json={
        "sku": f"ACCESS-{uuid.uuid4().hex[:10]}", "name": "Access control product",
        "base_price": "10.00", "gst_rate": "0", "unit": "pcs",
    }, timeout=10), 201)
    success(admin_session.post(f"{api_prefix}/inventory/adjust", json={
        "product_id": product["id"], "warehouse_id": warehouse_id, "delta_qty": "20",
    }, timeout=10))
    orders = []
    for customer in customers:
        order = success(admin_session.post(f"{api_prefix}/orders", json={
            "customer_id": customer, "warehouse_id": warehouse_id,
            "items": [{"product_id": product["id"], "quantity": "1"}],
        }, timeout=10), 201)
        for action in ("confirm", "reserve", "pick", "pack", "dispatch"):
            success(admin_session.post(f"{api_prefix}/orders/{order['id']}/{action}", timeout=10))
        orders.append(order["id"])

    url = make_url(os.environ["DATABASE_URL_SYNC"])
    if (
        url.drivername != "postgresql+psycopg2"
        or url.host not in {"127.0.0.1", "localhost", "::1"}
        or not (url.database or "").startswith("supplyos_test_")
        or os.environ.get("APP_ENV") != "test"
    ):
        pytest.fail("Direct fixture seeding requires the owned loopback test database", pytrace=False)
    engine = create_engine(url, hide_parameters=True)
    credentials = []
    try:
        with Session(engine) as database:
            owner = database.scalar(select(User.id).where(
                User.id == uuid.UUID(admin_session.admin_user["id"]),
                User.tenant_id == uuid.UUID(tenant_id), User.email == os.environ["TEST_ADMIN_EMAIL"],
                User.role == "super_admin", User.is_active.is_(True),
            ))
            if owner is None:
                pytest.fail("Database does not match the identified test API", pytrace=False)
            for role in ("delivery_partner", "delivery_partner", "accountant", "warehouse_manager"):
                email = f"staff-{uuid.uuid4().hex}@example.com"
                password = secrets.token_urlsafe(24)
                actor = User(
                    tenant_id=uuid.UUID(tenant_id), email=email, full_name="Verification staff",
                    password_hash=hash_password(password), role=role, is_active=True,
                )
                database.add(actor)
                database.flush()
                credentials.append((str(actor.id), email, password))
            foreign = Tenant(name="Foreign verification business", currency="INR", settings={}, is_setup_complete=True)
            database.add(foreign)
            database.flush()
            foreign_warehouse = Warehouse(tenant_id=foreign.id, code="OTHER", name="Foreign warehouse")
            category = Category(tenant_id=foreign.id, name="Foreign category")
            foreign_product = Product(tenant_id=foreign.id, sku="OTHER", name="Foreign product", base_price=Decimal("10"))
            foreign_customer = Customer(tenant_id=foreign.id, code="OTHER", name="Foreign customer", customer_type="cash")
            partner = User(
                tenant_id=foreign.id, email=f"foreign-{uuid.uuid4().hex}@example.com",
                full_name="Foreign partner", role="delivery_partner", password_hash=hash_password(secrets.token_urlsafe(24)),
            )
            database.add_all([foreign_warehouse, category, foreign_product, foreign_customer, partner])
            database.flush()
            rack = Rack(tenant_id=foreign.id, warehouse_id=foreign_warehouse.id, code="OTHER", label="Foreign rack")
            database.add(rack)
            database.flush()
            shelf = Shelf(tenant_id=foreign.id, warehouse_id=foreign_warehouse.id, rack_id=rack.id, code="OTHER", label="Foreign shelf")
            batch = Batch(tenant_id=foreign.id, product_id=foreign_product.id, batch_code="OTHER")
            foreign_order = Order(
                tenant_id=foreign.id, order_number=f"OTHER-{uuid.uuid4().hex[:10]}",
                customer_id=foreign_customer.id, warehouse_id=foreign_warehouse.id, status="pending",
            )
            database.add_all([shelf, batch, foreign_order])
            database.flush()
            foreign_ids = {
                "warehouse": str(foreign_warehouse.id), "category": str(category.id),
                "product": str(foreign_product.id), "customer": str(foreign_customer.id),
                "partner": str(partner.id), "rack": str(rack.id), "shelf": str(shelf.id),
                "batch": str(batch.id), "order": str(foreign_order.id),
            }
            database.commit()
    finally:
        engine.dispose()
    staff = []
    for actor_id, email, password in credentials:
        session = requests.Session()
        success(session.post(f"{api_prefix}/auth/login", json={
            "email": email, "password": password, "tenant_id": tenant_id,
        }, timeout=15))
        staff.append(session)
    deliveries = success(admin_session.get(f"{api_prefix}/deliveries", timeout=10))
    ids = [next(row["id"] for row in deliveries if row["order_id"] == order) for order in orders]
    for index, delivery in enumerate(ids):
        success(admin_session.post(f"{api_prefix}/deliveries/{delivery}/assign", json={
            "partner_id": credentials[index][0],
        }, timeout=10))
    try:
        yield {
            "customers": customers, "customer_sessions": actors, "orders": orders,
            "deliveries": ids, "staff": staff, "staff_ids": [item[0] for item in credentials],
            "warehouse": warehouse_id, "product": product["id"], "foreign": foreign_ids,
        }
    finally:
        for session in actors + staff:
            session.close()


def test_customer_directory_prices_and_ledger_are_private(access_data, api_prefix):
    own, other = access_data["customers"]
    customer = access_data["customer_sessions"][0]
    assert [item["id"] for item in success(customer.get(f"{api_prefix}/customers", timeout=10))["items"]] == [own]
    for path in (f"customers/{other}", f"customers/{other}/prices", f"customers/{other}/ledger"):
        assert customer.get(f"{api_prefix}/{path}", timeout=10).status_code == 404
    assert customer.get(f"{api_prefix}/customers/{own}/ledger", timeout=10).status_code == 200
    assert customer.get(f"{api_prefix}/pricing/resolve", params={
        "customer_id": other, "product_id": access_data["product"],
    }, timeout=10).status_code == 404


def test_customer_orders_stats_history_and_delivery_tracking_are_private(access_data, api_prefix):
    customer = access_data["customer_sessions"][0]
    own, other = access_data["orders"]
    assert [item["id"] for item in success(customer.get(f"{api_prefix}/orders", timeout=10))["items"]] == [own]
    assert success(customer.get(f"{api_prefix}/orders/stats", timeout=10))["total_orders"] == 1
    assert customer.get(f"{api_prefix}/orders/{other}/history", timeout=10).status_code == 404
    assert customer.get(f"{api_prefix}/orders/{own}/history", timeout=10).status_code == 200
    assert [item["order_id"] for item in success(customer.get(f"{api_prefix}/deliveries", timeout=10))] == [own]


@pytest.mark.parametrize("path", [
    "inventory", "inventory/stats", "inventory/movements", "pricing/tiers",
    "ai/alerts", "ai/insights/peak-hours",
])
def test_customer_cannot_read_internal_operations(access_data, api_prefix, path):
    assert access_data["customer_sessions"][0].get(f"{api_prefix}/{path}", timeout=10).status_code == 403


@pytest.mark.parametrize("action,payload", [
    ("start", {}), ("verify-otp", {"otp_code": "123456"}), ("complete", {}),
])
def test_customer_and_accountant_cannot_operate_delivery(access_data, api_prefix, action, payload):
    for actor in (access_data["customer_sessions"][0], access_data["staff"][2]):
        assert actor.post(
            f"{api_prefix}/deliveries/{access_data['deliveries'][0]}/{action}", json=payload, timeout=10,
        ).status_code == 403


def test_partner_only_reads_and_operates_assigned_delivery(access_data, api_prefix):
    partner = access_data["staff"][0]
    assert [item["id"] for item in success(partner.get(f"{api_prefix}/deliveries", timeout=10))] == [access_data["deliveries"][0]]
    assert [item["id"] for item in success(partner.get(f"{api_prefix}/orders", timeout=10))["items"]] == [access_data["orders"][0]]
    assert partner.post(f"{api_prefix}/deliveries/{access_data['deliveries'][1]}/start", timeout=10).status_code == 403
    assert partner.get(f"{api_prefix}/customers", timeout=10).status_code == 403
    assert partner.get(f"{api_prefix}/payments", timeout=10).status_code == 403


def test_foreign_relationships_are_rejected_before_writes(access_data, admin_session, api_prefix):
    foreign = access_data["foreign"]
    assert admin_session.post(f"{api_prefix}/orders", json={
        "customer_id": access_data["customers"][0], "warehouse_id": foreign["warehouse"],
        "items": [{"product_id": access_data["product"], "quantity": "1"}],
    }, timeout=10).status_code == 404
    assert admin_session.post(f"{api_prefix}/customers/{access_data['customers'][0]}/prices", json={
        "product_id": foreign["product"], "price": "1.00",
    }, timeout=10).status_code == 404
    assert admin_session.post(f"{api_prefix}/products", json={
        "sku": f"REJECT-{uuid.uuid4().hex[:8]}", "name": "Must reject", "base_price": "1.00",
        "category_id": foreign["category"],
    }, timeout=10).status_code == 404
    for location in ("rack", "shelf", "batch"):
        payload = {
            "product_id": access_data["product"], "warehouse_id": access_data["warehouse"],
            "delta_qty": "1", f"{location}_id": foreign[location],
        }
        expected = 400 if location == "shelf" else 404
        assert admin_session.post(f"{api_prefix}/inventory/adjust", json=payload, timeout=10).status_code == expected
    assert admin_session.post(f"{api_prefix}/deliveries/{access_data['deliveries'][0]}/assign", json={
        "partner_id": foreign["partner"],
    }, timeout=10).status_code == 404
    assert admin_session.post(f"{api_prefix}/payments", json={
        "customer_id": access_data["customers"][0], "order_id": foreign["order"],
        "amount": "1", "mode": "cash",
    }, timeout=10).status_code == 404


def test_financial_and_stock_write_roles_are_separated(access_data, api_prefix):
    accountant = access_data["staff"][2]
    manager = access_data["staff"][3]
    assert accountant.post(f"{api_prefix}/orders/{access_data['orders'][0]}/confirm", timeout=10).status_code == 403
    assert manager.post(f"{api_prefix}/payments", json={
        "customer_id": access_data["customers"][0], "amount": "1", "mode": "cash",
    }, timeout=10).status_code == 403


def test_invalid_metadata_updates_fail_validation_before_database_writes(access_data, admin_session, api_prefix):
    assert admin_session.patch(f"{api_prefix}/products/{access_data['product']}", json={
        "base_price": None,
    }, timeout=10).status_code == 422
    assert admin_session.patch(f"{api_prefix}/customers/{access_data['customers'][0]}", json={
        "credit_limit": None,
    }, timeout=10).status_code == 422
    assert admin_session.post(f"{api_prefix}/products", json={
        "sku": f"BAD-{uuid.uuid4().hex[:8]}", "name": "Invalid price", "base_price": "-1.00",
    }, timeout=10).status_code == 422


def test_non_ascii_and_non_numeric_otp_is_validation_error(access_data, api_prefix):
    partner = access_data["staff"][0]
    for code in ("\u00e9" * 6, "abcdef"):
        assert partner.post(
            f"{api_prefix}/deliveries/{access_data['deliveries'][0]}/verify-otp",
            json={"otp_code": code}, timeout=10,
        ).status_code == 422
