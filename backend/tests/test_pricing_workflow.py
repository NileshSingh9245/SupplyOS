"""Owned PostgreSQL pricing controls, self-catalog authority and immutable order snapshots."""
from __future__ import annotations

import asyncio
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
import requests
from fastapi import FastAPI
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.infrastructure.db.models.customer import Customer, CustomerPrice, PriceTier
from app.infrastructure.db.models.product import Product
from app.infrastructure.db.models.order import OrderItem
from app.infrastructure.db.models.tenant import Tenant
from app.infrastructure.db.models.user import AuditLog, RefreshToken, User
from app.infrastructure.db.models.warehouse import Warehouse
from test_customer_onboarding import checked, database, roles
from test_password_change import Database, _wait_for_lock

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def owned_pricing_only():
    if os.environ.get("SUPPLYOS_OWNED_TEST_ENV") != "1":
        pytest.skip("Pricing regressions require the owned disposable verifier")


@pytest.fixture
def pricing_case(roles, database, api_prefix):
    own = checked(roles["customer"].get(f"{api_prefix}/customers", timeout=10))["items"][0]
    owner = checked(roles["super_admin"].get(f"{api_prefix}/auth/me", timeout=10))
    prefix = f"catalog-{uuid.uuid4().hex}"
    products = [checked(roles["super_admin"].post(f"{api_prefix}/products", json={
        "sku": f"{prefix}-{index}", "name": f"{prefix}-{index}", "unit": "pcs",
        "base_price": value, "gst_rate": "0.00",
    }, timeout=15), 201) for index, value in enumerate(("44.00", "20.00"))]
    tier = checked(roles["super_admin"].post(f"{api_prefix}/pricing/tiers", json={
        "name": "tier-" + uuid.uuid4().hex[:12], "discount_pct": "5.00",
    }, timeout=15), 201)
    with Session(database, expire_on_commit=False) as db:
        warehouse = Warehouse(tenant_id=uuid.UUID(owner["tenant_id"]),
                              code=uuid.uuid4().hex[:20], name="Owned pricing warehouse", is_active=True)
        db.add(warehouse)
        db.commit()
        warehouse_id = warehouse.id
    return SimpleNamespace(roles=roles, engine=database, api=api_prefix, customer=own,
                           tenant_id=uuid.UUID(owner["tenant_id"]), prefix=prefix, products=products,
                           tier=tier, warehouse_id=warehouse_id)


def catalog(case, **query):
    return case.roles["customer"].get(f"{case.api}/catalog", params={"q": case.prefix, **query}, timeout=15)


def assign(case, value, role="super_admin"):
    return case.roles[role].patch(f"{case.api}/customers/{case.customer['id']}/pricing-tier",
                                  json={"tier_id": value}, timeout=15)


def override(case, product, price, role="super_admin"):
    return case.roles[role].post(f"{case.api}/customers/{case.customer['id']}/prices",
                                 json={"product_id": product["id"], "price": price}, timeout=15)


def test_catalog_returns_only_own_server_prices_and_keeps_products_base_contract(pricing_case):
    case = pricing_case
    checked(assign(case, case.tier["id"]))
    reply = catalog(case)
    assert reply.headers["cache-control"] == "no-store"
    data = checked(reply)
    assert data["total"] == 2 and data["page_size"] == 50
    assert [item["price"] for item in data["items"]] == ["41.80", "19.00"]
    assert all(set(item) == {"id", "sku", "name", "unit", "price", "gst_rate", "currency_code"} for item in data["items"])
    assert {item["currency_code"] for item in data["items"]} == {"INR"}
    base = checked(case.roles["customer"].get(f"{case.api}/products", params={"q": case.prefix}, timeout=15))
    assert [item["base_price"] for item in base["items"]] == ["44.00", "20.00"]
    assert all("price" not in item for item in base["items"])
    for item in data["items"]:
        quoted = checked(case.roles["customer"].get(f"{case.api}/pricing/resolve", params={
            "customer_id": case.customer["id"], "product_id": item["id"],
        }, timeout=15))
        assert quoted["price"] == item["price"]


def test_catalog_page_search_and_query_authority_are_bounded(pricing_case):
    case = pricing_case
    first, second = checked(catalog(case, page_size=1)), checked(catalog(case, page=2, page_size=1))
    assert first["total"] == second["total"] == 2
    assert first["items"][0]["id"] != second["items"][0]["id"]
    empty = checked(catalog(case, page=99, page_size=1))
    assert empty["items"] == [] and empty["total"] == 2
    for query in ({"page_size": 201}, {"page": 0}, {"q": "x" * 101},
                  {"customer_id": str(uuid.uuid4())}, {"tenant_id": str(uuid.uuid4())}, {"price": "0"}):
        assert catalog(case, **query).status_code == 422
    assert case.roles["customer"].get(f"{case.api}/catalog?page=1&page=2", timeout=10).status_code == 422
    for role in ("super_admin", "warehouse_manager", "accountant", "delivery_partner"):
        assert case.roles[role].get(f"{case.api}/catalog", timeout=10).status_code == 403
    assert requests.get(f"{case.api}/catalog", timeout=10).status_code == 401


def test_zero_override_has_priority_and_removal_returns_to_tier_then_base(pricing_case):
    case = pricing_case
    checked(assign(case, case.tier["id"], role="accountant"))
    checked(override(case, case.products[0], "0.00", role="accountant"))
    assert checked(catalog(case))["items"][0]["price"] == "0.00"
    path = f"{case.api}/customers/{case.customer['id']}/prices/{case.products[0]['id']}"
    assert case.roles["accountant"].delete(path, timeout=15).status_code == 204
    assert case.roles["accountant"].delete(path, timeout=15).status_code == 204
    assert checked(catalog(case))["items"][0]["price"] == "41.80"
    checked(assign(case, None))
    assert checked(catalog(case))["items"][0]["price"] == "44.00"
    with Session(case.engine) as db:
        actions = set(db.scalars(select(AuditLog.action).where(
            AuditLog.resource_id.in_((case.customer["id"], case.tier["id"])),
        )))
    assert {"pricing.tier_create", "pricing.customer_tier", "pricing.customer_price_remove"} <= actions


def test_pricing_write_roles_are_independent_and_do_not_accept_extra_authority(pricing_case):
    case = pricing_case
    for role in ("accountant", "delivery_partner", "customer"):
        response = case.roles[role].patch(f"{case.api}/pricing/tiers/{case.tier['id']}",
                                          json={"discount_pct": "10.00"}, timeout=15)
        assert response.status_code == 403
    checked(case.roles["warehouse_manager"].patch(f"{case.api}/pricing/tiers/{case.tier['id']}",
                                                  json={"discount_pct": "10.00"}, timeout=15))
    for role in ("warehouse_manager", "delivery_partner", "customer"):
        assert assign(case, case.tier["id"], role).status_code == 403
        assert override(case, case.products[0], "10.00", role).status_code == 403
        assert case.roles[role].delete(
            f"{case.api}/customers/{case.customer['id']}/prices/{case.products[0]['id']}", timeout=10,
        ).status_code == 403
    for body in ({}, {"tier_id": case.tier["id"], "tenant_id": str(uuid.uuid4())}, {"price_tier": "untrusted"}):
        assert case.roles["super_admin"].patch(f"{case.api}/customers/{case.customer['id']}/pricing-tier",
                                               json=body, timeout=10).status_code == 422
    assert case.roles["super_admin"].patch(f"{case.api}/pricing/tiers/{case.tier['id']}",
                                           json={"name": "renamed", "discount_pct": "5.00"}, timeout=10).status_code == 422


def test_discount_boundaries_duplicates_and_legacy_name_assignment_are_explicit(pricing_case):
    case = pricing_case
    path = f"{case.api}/pricing/tiers/{case.tier['id']}"
    for value in ("-0.01", "100.01", "1.001", "NaN", "Infinity", None):
        assert case.roles["super_admin"].patch(path, json={"discount_pct": value}, timeout=10).status_code == 422
    duplicate = case.roles["super_admin"].post(f"{case.api}/pricing/tiers", json={
        "name": case.tier["name"], "discount_pct": "0.00",
    }, timeout=15)
    assert duplicate.status_code == 409
    legacy = checked(case.roles["super_admin"].post(f"{case.api}/pricing/tiers", json={
        "name": "long-" + uuid.uuid4().hex, "discount_pct": "5.00",
    }, timeout=15), 201)
    assert assign(case, legacy["id"]).status_code == 400
    assert checked(case.roles["super_admin"].get(f"{case.api}/customers/{case.customer['id']}", timeout=10))["price_tier"] is None
    checked(assign(case, case.tier["id"]))
    checked(case.roles["super_admin"].patch(path, json={"discount_pct": "100.00"}, timeout=15))
    assert {item["price"] for item in checked(catalog(case))["items"]} == {"0.00"}


def test_foreign_tier_customer_and_override_identifiers_are_not_visible(pricing_case):
    case = pricing_case
    for path, body in ((f"/pricing/tiers/{uuid.uuid4()}", {"discount_pct": "10.00"}),
                       (f"/customers/{uuid.uuid4()}/pricing-tier", {"tier_id": case.tier["id"]})):
        assert case.roles["super_admin"].patch(case.api + path, json=body, timeout=10).status_code == 404
    assert assign(case, str(uuid.uuid4())).status_code == 404
    with Session(case.engine, expire_on_commit=False) as db:
        foreign = Tenant(name="Owned foreign pricing tenant", currency="USD")
        db.add(foreign)
        db.flush()
        foreign_tier = PriceTier(tenant_id=foreign.id, name=case.tier["name"], discount_pct=Decimal("99"))
        foreign_product = Product(tenant_id=foreign.id, sku=case.prefix, name=case.prefix, unit="pcs", base_price=Decimal("1"), gst_rate=Decimal("0"))
        db.add_all([foreign_tier, foreign_product])
        db.commit()
    assert assign(case, str(foreign_tier.id)).status_code == 404
    assert checked(catalog(case))["total"] == 2
    assert case.roles["super_admin"].delete(
        f"{case.api}/customers/{uuid.uuid4()}/prices/{case.products[0]['id']}", timeout=10,
    ).status_code == 404
    with Session(case.engine) as db:
        user = db.get(User, uuid.UUID(checked(case.roles["customer"].get(f"{case.api}/auth/me", timeout=10))["id"]))
        user.customer_id = None
        db.commit()
    assert catalog(case).status_code == 403


def test_inactive_customer_or_product_and_corrupt_selected_price_fail_closed(pricing_case):
    case = pricing_case
    checked(override(case, case.products[0], "10.00"))
    with case.engine.begin() as connection:
        connection.execute(update(CustomerPrice).where(CustomerPrice.customer_id == uuid.UUID(case.customer["id"])).values(price=Decimal("-1")))
    assert catalog(case).status_code == 400
    with case.engine.begin() as connection:
        connection.execute(update(CustomerPrice).where(CustomerPrice.customer_id == uuid.UUID(case.customer["id"])).values(price=Decimal("10")))
        connection.execute(update(Product).where(Product.id == uuid.UUID(case.products[0]["id"])).values(is_active=False))
    assert [item["id"] for item in checked(catalog(case))["items"]] == [case.products[1]["id"]]
    with case.engine.begin() as connection:
        connection.execute(update(Customer).where(Customer.id == uuid.UUID(case.customer["id"])).values(is_active=False))
    assert catalog(case).status_code == 404


def test_order_uses_one_immutable_price_metadata_and_tax_batch_before_future_changes(pricing_case, monkeypatch):
    from app.features.orders import service as orders
    from app.features.pricing import repositories

    case = pricing_case
    checked(assign(case, case.tier["id"]))
    original = repositories.priced_rows
    calls = []

    async def changed_after_read(db, **kwargs):
        rows = await original(db, **kwargs)
        calls.append(rows)
        with case.engine.begin() as writer:
            writer.execute(update(PriceTier).where(PriceTier.id == uuid.UUID(case.tier["id"])).values(discount_pct=Decimal("50")))
            writer.execute(update(Product).where(Product.id.in_([uuid.UUID(p["id"]) for p in case.products])).values(
                base_price=Decimal("100"), gst_rate=Decimal("10"), name="Future product metadata",
            ))
        return rows
    monkeypatch.setattr(repositories, "priced_rows", changed_after_read)

    async def create():
        engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool, hide_parameters=True)
        try:
            factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
            async with factory() as db, db.begin():
                order = await orders.create_order(db, tenant_id=case.tenant_id,
                    customer_id=uuid.UUID(case.customer["id"]), warehouse_id=case.warehouse_id,
                    items=[{"product_id": uuid.UUID(product["id"]), "quantity": Decimal("1")} for product in case.products])
                await db.flush()
                return order.id, order.subtotal, order.tax_total
        finally:
            await engine.dispose()
    order_id, subtotal, tax = asyncio.run(create())
    assert len(calls) == 1 and subtotal == Decimal("60.80") and tax == Decimal("0.00")
    assert [row.name for row in calls[0]] == [product["name"] for product in case.products]
    with Session(case.engine) as db:
        items = list(db.scalars(select(OrderItem).where(OrderItem.order_id == order_id).order_by(OrderItem.product_name)))
        assert [item.product_name for item in items] == [product["name"] for product in case.products]
        assert [item.unit_price for item in items] == [Decimal("41.80"), Decimal("19.00")]
        assert all(item.gst_rate == 0 for item in items)
    monkeypatch.setattr(repositories, "priced_rows", original)
    assert {item["price"] for item in checked(catalog(case))["items"]} == {"50.00"}


def test_audit_failure_rolls_back_tier_price_instead_of_claiming_success(pricing_case, monkeypatch):
    from app.core.database import get_db
    from app.features.pricing import service
    from app.features.pricing.router import router

    case = pricing_case
    async def fail(*args, **kwargs):
        raise RuntimeError("Synthetic pricing audit failure")
    monkeypatch.setattr(service, "audit", fail)

    async def request():
        engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool, hide_parameters=True)
        factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        app = FastAPI()
        app.include_router(router, prefix="/api/v1")
        async def session():
            async with factory() as db:
                yield db
        app.dependency_overrides[get_db] = session
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://owned-asgi",
                                         cookies=dict(case.roles["super_admin"].cookies)) as client:
                return await client.patch(f"/api/v1/pricing/tiers/{case.tier['id']}", json={"discount_pct": "50.00"})
        finally:
            await engine.dispose()
    assert asyncio.run(request()).status_code == 500
    with Session(case.engine) as db:
        assert db.get(PriceTier, uuid.UUID(case.tier["id"])).discount_pct == Decimal("5.00")


def test_expiring_session_after_tier_lock_wait_cannot_commit_price_or_audit(pricing_case):
    case = pricing_case
    actor = checked(case.roles["warehouse_manager"].get(f"{case.api}/auth/me", timeout=10))
    expiry = datetime.now(timezone.utc) + timedelta(seconds=3)
    with case.engine.begin() as connection:
        connection.execute(update(RefreshToken).where(RefreshToken.user_id == uuid.UUID(actor["id"])).values(expires_at=expiry))
    with case.engine.connect() as holder, ThreadPoolExecutor(max_workers=1) as workers:
        holder.execute(select(PriceTier.id).where(PriceTier.id == uuid.UUID(case.tier["id"])).with_for_update())
        pid = holder.scalar(select(func.pg_backend_pid()))
        pending = workers.submit(lambda: case.roles["warehouse_manager"].patch(
            f"{case.api}/pricing/tiers/{case.tier['id']}", json={"discount_pct": "50.00"}, timeout=15,
        ))
        try:
            _wait_for_lock(Database(case.engine, case.tenant_id), pid)
            while datetime.now(timezone.utc) <= expiry:
                time.sleep(0.02)
        finally:
            holder.rollback()
        assert pending.result(timeout=15).status_code == 401
    with Session(case.engine) as db:
        assert db.get(PriceTier, uuid.UUID(case.tier["id"])).discount_pct == Decimal("5.00")
        assert db.scalar(select(func.count()).select_from(AuditLog).where(
            AuditLog.action == "pricing.tier_update", AuditLog.resource_id == case.tier["id"],
        )) == 0


def test_catalog_declares_tenant_currency_without_guessing_an_inr_price(pricing_case):
    case = pricing_case
    with Session(case.engine) as db:
        original = db.get(Tenant, case.tenant_id).currency
    try:
        with case.engine.begin() as writer:
            writer.execute(update(Tenant).where(Tenant.id == case.tenant_id).values(currency="USD"))
        assert {item["currency_code"] for item in checked(catalog(case))["items"]} == {"USD"}
    finally:
        with case.engine.begin() as writer:
            writer.execute(update(Tenant).where(Tenant.id == case.tenant_id).values(currency=original))


def test_customer_deactivation_while_catalog_waits_cannot_publish_prices_or_fake_empty(pricing_case):
    case = pricing_case
    with case.engine.connect() as holder, ThreadPoolExecutor(max_workers=1) as workers:
        holder.execute(update(Customer).where(Customer.id == uuid.UUID(case.customer["id"])).values(is_active=False))
        pid = holder.scalar(select(func.pg_backend_pid()))
        pending = workers.submit(lambda: catalog(case))
        try:
            _wait_for_lock(Database(case.engine, case.tenant_id), pid)
        finally:
            holder.commit()
        reply = pending.result(timeout=15)
    assert reply.status_code == 404
    assert "items" not in reply.json()
