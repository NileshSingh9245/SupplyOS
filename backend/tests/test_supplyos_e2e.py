"""SupplyOS end-to-end backend test.

Runs a full happy-path plus RBAC + row-locking checks against the deployed backend
using the external REACT_APP_BACKEND_URL. Tests are ordered — state is passed via
the `shared_state` fixture. Any test that depends on a prior step will skip if the
prerequisite state is missing.
"""
from __future__ import annotations

import os
import time
import uuid
from decimal import Decimal

import pytest
import requests

from conftest import API, ADMIN_EMAIL, ADMIN_PASSWORD


def _skip_if_missing(state, key):
    if key not in state:
        pytest.skip(f"prerequisite missing: {key}")


# ---------------------------------------------------------------------------
# Health / setup / auth
# ---------------------------------------------------------------------------
class TestHealthAndSetup:
    def test_health_deep(self, base_url):
        r = requests.get(f"{base_url}/api/health/deep", timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("database") == "ok"
        assert data.get("redis") == "ok"

    def test_setup_status_complete(self, api_prefix):
        r = requests.get(f"{api_prefix}/setup/status", timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("is_setup_complete") is True
        assert "tenant_id" in data and data["tenant_id"]


class TestAuth:
    def test_login_sets_cookies_and_returns_token(self):
        s = requests.Session()
        r = s.post(
            f"{API}/auth/login",
            json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert "access_token" in body and body["access_token"]
        assert body["token_type"] == "bearer"
        assert body["user"]["email"] == ADMIN_EMAIL
        assert body["user"]["role"] == "super_admin"
        # httpOnly cookies must be present
        cookie_names = {c.name for c in s.cookies}
        assert "access_token" in cookie_names, cookie_names
        assert "refresh_token" in cookie_names, cookie_names

    def test_me_returns_admin_profile(self, admin_session):
        r = admin_session.get(f"{API}/auth/me", timeout=15)
        assert r.status_code == 200, r.text
        me = r.json()
        assert me["email"] == ADMIN_EMAIL
        assert me["role"] == "super_admin"


# ---------------------------------------------------------------------------
# Settings — INR/GST rules + RBAC
# ---------------------------------------------------------------------------
class TestSettings:
    def test_get_settings_returns_inr_defaults(self, admin_session, shared_state):
        r = admin_session.get(f"{API}/settings", timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["currency_code"] == "INR"
        assert data["currency_symbol"] == "₹"
        values = data.get("values", {})
        assert len(values) >= 30, f"expected 30+ rules, got {len(values)}"
        # required keys spot-check
        for key in [
            "default_gst_rate", "gst_type", "gstin_required_for_credit",
            "allow_below_base_price", "default_credit_limit",
            "block_orders_over_credit", "auto_reserve_on_confirm",
            "otp_length", "low_stock_threshold_default", "dead_stock_days",
            "ai_analyze_interval_minutes",
        ]:
            assert key in values, f"missing key {key}"
        shared_state["original_block_credit"] = values.get("block_orders_over_credit")
        shared_state["original_gst_rate"] = values.get("default_gst_rate")

    def test_patch_settings_super_admin(self, admin_session, shared_state):
        payload = {"patch": {"default_gst_rate": "12.00", "block_orders_over_credit": False}}
        r = admin_session.patch(f"{API}/settings", json=payload, timeout=15)
        assert r.status_code == 200, r.text
        values = r.json()["values"]
        assert values["default_gst_rate"] == "12.00"
        assert values["block_orders_over_credit"] is False

        # GET again to verify persistence
        r2 = admin_session.get(f"{API}/settings", timeout=15)
        assert r2.status_code == 200
        v2 = r2.json()["values"]
        assert v2["default_gst_rate"] == "12.00"
        assert v2["block_orders_over_credit"] is False

        # Revert so we don't pollute other tests
        revert = {
            "patch": {
                "default_gst_rate": shared_state.get("original_gst_rate", "5.00"),
                "block_orders_over_credit": shared_state.get("original_block_credit", True),
            }
        }
        r3 = admin_session.patch(f"{API}/settings", json=revert, timeout=15)
        assert r3.status_code == 200


# ---------------------------------------------------------------------------
# Products / Warehouses / Inventory
# ---------------------------------------------------------------------------
class TestProductsWarehousesInventory:
    def test_create_product_basmati_rice(self, admin_session, shared_state):
        sku = f"TEST-RICE-{uuid.uuid4().hex[:6].upper()}"
        payload = {
            "sku": sku,
            "name": "Basmati Rice",
            "unit": "kg",
            "pack_size": "1",
            "base_price": "100.00",
            "gst_rate": "5.00",
            "low_stock_threshold": 20,
        }
        r = admin_session.post(f"{API}/products", json=payload, timeout=15)
        assert r.status_code == 201, r.text
        p = r.json()
        assert p["sku"] == sku
        assert p["name"] == "Basmati Rice"
        assert Decimal(p["gst_rate"]) == Decimal("5.00")
        assert Decimal(p["base_price"]) == Decimal("100.00")
        shared_state["product_id"] = p["id"]
        shared_state["product_sku"] = sku

        # GET verify persistence
        g = admin_session.get(f"{API}/products/{p['id']}", timeout=15)
        assert g.status_code == 200
        assert g.json()["sku"] == sku

    def test_create_warehouse(self, admin_session, shared_state):
        code = f"TEST-WH-{uuid.uuid4().hex[:4].upper()}"
        payload = {
            "code": code,
            "name": "Test Warehouse Delhi",
            "address": "Sector 63, Noida",
            "city": "Noida",
            "state": "UP",
            "pincode": "201301",
        }
        r = admin_session.post(f"{API}/warehouses", json=payload, timeout=15)
        assert r.status_code == 201, r.text
        w = r.json()
        assert w["code"] == code
        assert w["is_active"] is True
        shared_state["warehouse_id"] = w["id"]

    def test_adjust_stock_plus_500(self, admin_session, shared_state):
        _skip_if_missing(shared_state, "product_id")
        _skip_if_missing(shared_state, "warehouse_id")
        payload = {
            "product_id": shared_state["product_id"],
            "warehouse_id": shared_state["warehouse_id"],
            "delta_qty": "500",
            "note": "Initial stock",
        }
        r = admin_session.post(f"{API}/inventory/adjust", json=payload, timeout=15)
        assert r.status_code == 200, r.text
        row = r.json()
        assert Decimal(row["quantity"]) == Decimal("500")
        assert Decimal(row["reserved_qty"]) == Decimal("0")
        assert Decimal(row["available_qty"]) == Decimal("500")

    def test_list_inventory_shows_new_row(self, admin_session, shared_state):
        _skip_if_missing(shared_state, "product_id")
        r = admin_session.get(
            f"{API}/inventory",
            params={"product_id": shared_state["product_id"]},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        rows = r.json()
        assert len(rows) >= 1
        row = rows[0]
        assert Decimal(row["quantity"]) == Decimal("500")
        assert Decimal(row["reserved_qty"]) == Decimal("0")
        assert Decimal(row["available_qty"]) == Decimal("500")

    def test_inventory_stats(self, admin_session):
        r = admin_session.get(f"{API}/inventory/stats", timeout=15)
        assert r.status_code == 200, r.text
        s = r.json()
        # Should reflect the +500 addition
        assert Decimal(s["total_inventory_value"]) >= Decimal("500") * Decimal("100")
        assert isinstance(s["total_products"], int)


# ---------------------------------------------------------------------------
# Customers / customer-price override / pricing.resolve
# ---------------------------------------------------------------------------
class TestCustomerAndPricing:
    def test_create_credit_customer(self, admin_session, shared_state):
        payload = {
            "name": "TEST Rajesh Kirana",
            "business_name": "TEST Rajesh Kirana Stores",
            "phone": "9999000111",
            "customer_type": "credit",
            "credit_limit": "10000.00",
        }
        r = admin_session.post(f"{API}/customers", json=payload, timeout=15)
        assert r.status_code == 201, r.text
        c = r.json()
        assert c["customer_type"] == "credit"
        assert Decimal(c["credit_limit"]) == Decimal("10000.00")
        shared_state["customer_id"] = c["id"]

    def test_customer_price_override(self, admin_session, shared_state):
        _skip_if_missing(shared_state, "customer_id")
        _skip_if_missing(shared_state, "product_id")
        r = admin_session.post(
            f"{API}/customers/{shared_state['customer_id']}/prices",
            json={"product_id": shared_state["product_id"], "price": "80.00"},
            timeout=15,
        )
        assert r.status_code in (200, 201), r.text
        body = r.json()
        assert Decimal(body["price"]) == Decimal("80.00")

    def test_pricing_resolve_returns_override(self, admin_session, shared_state):
        _skip_if_missing(shared_state, "customer_id")
        _skip_if_missing(shared_state, "product_id")
        r = admin_session.get(
            f"{API}/pricing/resolve",
            params={
                "customer_id": shared_state["customer_id"],
                "product_id": shared_state["product_id"],
            },
            timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert Decimal(body["price"]) == Decimal("80.00"), body


# ---------------------------------------------------------------------------
# Order lifecycle: create → confirm → reserve → pick → pack → dispatch → deliver
# ---------------------------------------------------------------------------
class TestOrderFlow:
    def test_create_order_uses_override_price_and_gst(self, admin_session, shared_state):
        for key in ("customer_id", "product_id", "warehouse_id"):
            _skip_if_missing(shared_state, key)
        payload = {
            "customer_id": shared_state["customer_id"],
            "warehouse_id": shared_state["warehouse_id"],
            "is_credit": True,
            "items": [{"product_id": shared_state["product_id"], "quantity": "50"}],
        }
        r = admin_session.post(f"{API}/orders", json=payload, timeout=20)
        assert r.status_code == 201, r.text
        o = r.json()
        assert o["status"] == "pending"
        assert len(o["items"]) == 1
        it = o["items"][0]
        # 80 * 50 = 4000 subtotal, GST 5% = 200, total = 4200
        assert Decimal(it["unit_price"]) == Decimal("80.00"), it
        assert Decimal(o["subtotal"]) == Decimal("4000.00")
        assert Decimal(o["tax_total"]) == Decimal("200.00")
        assert Decimal(o["grand_total"]) == Decimal("4200.00")
        shared_state["order_id"] = o["id"]

    def test_confirm_order(self, admin_session, shared_state):
        _skip_if_missing(shared_state, "order_id")
        r = admin_session.post(
            f"{API}/orders/{shared_state['order_id']}/confirm", timeout=20
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "confirmed"

    def test_reserve_order_locks_inventory(self, admin_session, shared_state):
        _skip_if_missing(shared_state, "order_id")
        r = admin_session.post(
            f"{API}/orders/{shared_state['order_id']}/reserve", timeout=20
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "reserved"

        inv = admin_session.get(
            f"{API}/inventory",
            params={"product_id": shared_state["product_id"]},
            timeout=15,
        )
        assert inv.status_code == 200
        row = inv.json()[0]
        assert Decimal(row["reserved_qty"]) == Decimal("50"), row
        assert Decimal(row["available_qty"]) == Decimal("450"), row

    def test_second_order_insufficient_stock_returns_409(self, admin_session, shared_state):
        """Row locking: only 450 available after prior reservation."""
        for key in ("customer_id", "product_id", "warehouse_id"):
            _skip_if_missing(shared_state, key)
        payload = {
            "customer_id": shared_state["customer_id"],
            "warehouse_id": shared_state["warehouse_id"],
            "is_credit": False,
            "items": [{"product_id": shared_state["product_id"], "quantity": "500"}],
        }
        # First create the order (create is allowed — insufficient-stock check
        # happens on reserve, not create).
        r = admin_session.post(f"{API}/orders", json=payload, timeout=20)
        assert r.status_code == 201, r.text
        second_id = r.json()["id"]

        # confirm should still succeed (transition only)
        rc = admin_session.post(f"{API}/orders/{second_id}/confirm", timeout=20)
        assert rc.status_code == 200, rc.text

        # reserve MUST fail with 409 InsufficientStock
        rr = admin_session.post(f"{API}/orders/{second_id}/reserve", timeout=20)
        assert rr.status_code == 409, f"expected 409, got {rr.status_code}: {rr.text}"
        detail = (rr.json().get("detail") or "").lower()
        assert (
            "stock" in detail or "insufficient" in detail or "available" in detail
        ), detail
        shared_state["second_order_id"] = second_id

    def test_advance_pick_pack_dispatch_creates_delivery(self, admin_session, shared_state):
        _skip_if_missing(shared_state, "order_id")
        oid = shared_state["order_id"]
        for step in ("pick", "pack", "dispatch"):
            r = admin_session.post(f"{API}/orders/{oid}/{step}", timeout=20)
            assert r.status_code == 200, f"{step} failed: {r.status_code} {r.text}"
        # After dispatch status should be out_for_delivery
        g = admin_session.get(f"{API}/orders/{oid}", timeout=15)
        assert g.json()["status"] == "out_for_delivery"

        # Delivery skeleton auto-created
        dr = admin_session.get(f"{API}/deliveries", timeout=15)
        assert dr.status_code == 200, dr.text
        deliveries = dr.json()
        matching = [d for d in deliveries if d["order_id"] == oid]
        assert len(matching) >= 1, f"no delivery for order {oid} in {deliveries}"

    def test_cancel_second_order_releases_reservation_none(
        self, admin_session, shared_state
    ):
        """Cancel the second (confirmed, unreserved) order — nothing to release,
        should still succeed.  Also verify available_qty remains 450."""
        _skip_if_missing(shared_state, "second_order_id")
        r = admin_session.post(
            f"{API}/orders/{shared_state['second_order_id']}/cancel",
            json={"note": "test cancel"}, timeout=15,
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "cancelled"

        inv = admin_session.get(
            f"{API}/inventory",
            params={"product_id": shared_state["product_id"]},
            timeout=15,
        )
        row = inv.json()[0]
        assert Decimal(row["reserved_qty"]) == Decimal("50"), row


# ---------------------------------------------------------------------------
# Deliver + ledger + order stats
# ---------------------------------------------------------------------------
class TestDeliveryAndLedger:
    def test_deliver_order(self, admin_session, shared_state):
        _skip_if_missing(shared_state, "order_id")
        r = admin_session.post(
            f"{API}/orders/{shared_state['order_id']}/deliver", timeout=20
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "delivered"

    def test_ledger_has_debit_entry(self, admin_session, shared_state):
        _skip_if_missing(shared_state, "customer_id")
        r = admin_session.get(
            f"{API}/customers/{shared_state['customer_id']}/ledger", timeout=15
        )
        assert r.status_code == 200, r.text
        entries = r.json()
        assert len(entries) >= 1, entries
        e = entries[0]
        assert Decimal(e["debit"]) == Decimal("4200.00"), e
        assert Decimal(e["balance_after"]) == Decimal("4200.00"), e

    def test_order_stats(self, admin_session):
        r = admin_session.get(f"{API}/orders/stats", timeout=15)
        assert r.status_code == 200, r.text
        s = r.json()
        assert s["total_orders"] >= 1
        assert Decimal(s["revenue_today"]) >= Decimal("4200.00")


# ---------------------------------------------------------------------------
# Cancellation releases reservation (separate flow, small order)
# ---------------------------------------------------------------------------
class TestCancellationReleasesReservation:
    def test_cancel_pending_order_releases(self, admin_session, shared_state):
        for key in ("customer_id", "product_id", "warehouse_id"):
            _skip_if_missing(shared_state, key)
        # Baseline
        inv0 = admin_session.get(
            f"{API}/inventory",
            params={"product_id": shared_state["product_id"]}, timeout=15,
        )
        base_reserved = Decimal(inv0.json()[0]["reserved_qty"])
        base_avail = Decimal(inv0.json()[0]["available_qty"])

        # Create + confirm + reserve small order
        payload = {
            "customer_id": shared_state["customer_id"],
            "warehouse_id": shared_state["warehouse_id"],
            "is_credit": False,
            "items": [{"product_id": shared_state["product_id"], "quantity": "10"}],
        }
        r = admin_session.post(f"{API}/orders", json=payload, timeout=20)
        assert r.status_code == 201, r.text
        oid = r.json()["id"]
        assert admin_session.post(f"{API}/orders/{oid}/confirm", timeout=15).status_code == 200
        assert admin_session.post(f"{API}/orders/{oid}/reserve", timeout=15).status_code == 200

        inv1 = admin_session.get(
            f"{API}/inventory",
            params={"product_id": shared_state["product_id"]}, timeout=15,
        )
        assert Decimal(inv1.json()[0]["reserved_qty"]) == base_reserved + Decimal("10")

        # Cancel
        rc = admin_session.post(
            f"{API}/orders/{oid}/cancel", json={"note": "test release"}, timeout=15
        )
        assert rc.status_code == 200, rc.text

        inv2 = admin_session.get(
            f"{API}/inventory",
            params={"product_id": shared_state["product_id"]}, timeout=15,
        )
        row = inv2.json()[0]
        assert Decimal(row["reserved_qty"]) == base_reserved, row
        assert Decimal(row["available_qty"]) == base_avail, row


# ---------------------------------------------------------------------------
# AI supervisor
# ---------------------------------------------------------------------------
class TestAISupervisor:
    def test_analyze_returns_counts(self, admin_session, shared_state):
        r = admin_session.post(f"{API}/ai/analyze", timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "counts" in body
        counts = body["counts"]
        # Categories expected — spot check
        for k in ("low_stock", "dead_stock", "credit_risk"):
            assert k in counts, counts

    def test_analyze_with_summary_and_claude(self, admin_session):
        r = admin_session.post(
            f"{API}/ai/analyze", params={"include_summary": "true"}, timeout=30
        )
        assert r.status_code == 200, r.text
        # Wait for background Claude call
        time.sleep(18)
        r2 = admin_session.get(
            f"{API}/ai/alerts",
            params={"category": "operations", "include_dismissed": "true"},
            timeout=15,
        )
        assert r2.status_code == 200, r2.text
        alerts = r2.json()
        # If there's an operations alert, its message must NOT contain AttributeError
        for a in alerts:
            msg = (a.get("message") or "") + " " + (a.get("title") or "")
            assert "AttributeError" not in msg, f"Claude summary failed: {a}"

    def test_list_and_dismiss_alert(self, admin_session, shared_state):
        r = admin_session.get(
            f"{API}/ai/alerts", params={"include_dismissed": "false"}, timeout=15
        )
        assert r.status_code == 200, r.text
        alerts = r.json()
        if not alerts:
            pytest.skip("no non-dismissed alerts to dismiss")
        alert_id = alerts[0]["id"]
        # severity chip present
        assert alerts[0]["severity"] in {"info", "low", "medium", "high", "critical"}, alerts[0]

        d = admin_session.post(f"{API}/ai/alerts/{alert_id}/dismiss", timeout=15)
        assert d.status_code == 200, d.text
        assert d.json()["is_dismissed"] is True


# ---------------------------------------------------------------------------
# RBAC: customer role cannot mutate inventory / settings
# ---------------------------------------------------------------------------
class TestRBACCustomerRole:
    @pytest.fixture(scope="class")
    def customer_session(self, shared_state):
        email = f"test_cust_{uuid.uuid4().hex[:8]}@example.com"
        password = "CustomerPass123!"
        # Register
        r = requests.post(
            f"{API}/auth/register-customer",
            json={
                "email": email,
                "password": password,
                "full_name": "TEST RBAC Customer",
                "phone": "9998887770",
            },
            timeout=15,
        )
        assert r.status_code in (200, 201), r.text
        # Login
        s = requests.Session()
        s.headers.update({"Content-Type": "application/json"})
        rl = s.post(
            f"{API}/auth/login", json={"email": email, "password": password}, timeout=15
        )
        assert rl.status_code == 200, rl.text
        tok = rl.json()["access_token"]
        s.headers.update({"Authorization": f"Bearer {tok}"})
        return s

    def test_customer_can_list_inventory(self, customer_session):
        r = customer_session.get(f"{API}/inventory", timeout=15)
        assert r.status_code == 200, r.text

    def test_customer_cannot_adjust_inventory(self, customer_session, shared_state):
        for key in ("product_id", "warehouse_id"):
            _skip_if_missing(shared_state, key)
        payload = {
            "product_id": shared_state["product_id"],
            "warehouse_id": shared_state["warehouse_id"],
            "delta_qty": "10",
        }
        r = customer_session.post(f"{API}/inventory/adjust", json=payload, timeout=15)
        assert r.status_code == 403, f"expected 403, got {r.status_code}: {r.text}"

    def test_customer_cannot_patch_settings(self, customer_session):
        r = customer_session.patch(
            f"{API}/settings", json={"patch": {"default_gst_rate": "18.00"}}, timeout=15
        )
        assert r.status_code == 403, f"expected 403, got {r.status_code}: {r.text}"
