"""Shared pytest fixtures for SupplyOS backend tests."""
from __future__ import annotations

import os
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    # Fall back to frontend/.env when tests run inside container
    try:
        with open("/app/frontend/.env") as f:
            for line in f:
                if line.startswith("REACT_APP_BACKEND_URL="):
                    BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
                    break
    except FileNotFoundError:
        pass

API = f"{BASE_URL}/api/v1"

ADMIN_EMAIL = "admin@acme.com"
ADMIN_PASSWORD = "AdminPass123!"


@pytest.fixture(scope="session")
def base_url():
    return BASE_URL


@pytest.fixture(scope="session")
def api_prefix():
    return API


@pytest.fixture(scope="session")
def admin_session():
    """Logged-in super_admin session with cookies + Bearer header."""
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(
        f"{API}/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=30,
    )
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    body = r.json()
    token = body["access_token"]
    s.headers.update({"Authorization": f"Bearer {token}"})
    s.admin_user = body["user"]  # type: ignore[attr-defined]
    return s


@pytest.fixture(scope="session")
def shared_state():
    """Mutable dict shared across ordered tests."""
    return {}
