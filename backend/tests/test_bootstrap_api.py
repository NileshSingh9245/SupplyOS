"""Authenticated bootstrap smoke tests, protected by the isolated-server fixtures."""
from __future__ import annotations

import os

import requests


def test_setup_is_complete(api_prefix):
    response = requests.get(f"{api_prefix}/setup/status", timeout=10)
    assert response.status_code == 200
    assert response.json()["is_setup_complete"] is True


def test_login_and_current_user_are_backwards_compatible(admin_session, api_prefix):
    response = admin_session.get(f"{api_prefix}/auth/me", timeout=10)
    assert response.status_code == 200
    assert response.json()["role"] == "super_admin"
    assert response.json()["email"] == os.environ["TEST_ADMIN_EMAIL"]


def test_legacy_api_alias_still_works(admin_session, base_url):
    response = admin_session.get(f"{base_url}/api/auth/me", timeout=10)
    assert response.status_code == 200
    assert response.json()["role"] == "super_admin"


def test_private_api_rejects_anonymous_requests(api_prefix):
    response = requests.get(f"{api_prefix}/auth/me", timeout=10)
    assert response.status_code == 401


def test_initial_warehouse_and_inventory_are_queryable(admin_session, api_prefix):
    warehouses = admin_session.get(f"{api_prefix}/warehouses", timeout=10)
    assert warehouses.status_code == 200
    assert len(warehouses.json()) == 1
    inventory = admin_session.get(f"{api_prefix}/inventory/stats", timeout=10)
    assert inventory.status_code == 200


def test_settings_are_available_to_staff(admin_session, api_prefix):
    response = admin_session.get(f"{api_prefix}/settings", timeout=10)
    assert response.status_code == 200
    assert response.json()["currency_code"] == "INR"


def test_unconfigured_email_does_not_claim_password_delivery(api_prefix):
    response = requests.post(f"{api_prefix}/auth/forgot-password", json={
        "email": os.environ["TEST_ADMIN_EMAIL"],
    }, timeout=10)
    assert response.status_code == 503
