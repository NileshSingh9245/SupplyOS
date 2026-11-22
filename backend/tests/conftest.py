"""Shared pytest fixtures for SupplyOS backend tests."""
from __future__ import annotations

import os
from urllib.parse import urlsplit
import requests
import pytest

BASE_URL = os.environ.get("TEST_API_URL", "").rstrip("/")

API = f"{BASE_URL}/api/v1"

ADMIN_EMAIL = os.environ.get("TEST_ADMIN_EMAIL", "")
ADMIN_PASSWORD = os.environ.get("TEST_ADMIN_PASSWORD", "")


@pytest.fixture(scope="session")
def base_url():
    if not BASE_URL or os.environ.get("SUPPLYOS_ALLOW_API_WRITE_TESTS") != "1":
        pytest.skip("API write tests require an explicitly prepared isolated test server")
    parsed = urlsplit(BASE_URL)
    if (
        parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.username is not None or parsed.password is not None
        or parsed.path not in {"", "/"} or parsed.query or parsed.fragment
    ):
        pytest.fail("API write tests may only target an isolated loopback server", pytrace=False)
    run_id = os.environ.get("TEST_RUN_ID", "")
    if not run_id:
        pytest.fail("TEST_RUN_ID is required to identify the isolated test server", pytrace=False)
    response = requests.get(f"{BASE_URL}/api/health", timeout=10)
    if response.status_code != 200:
        pytest.fail("The isolated test server is not ready", pytrace=False)
    health = response.json()
    if health.get("env") != "test" or health.get("app") != f"SupplyOS Verification {run_id}":
        pytest.fail("Refusing to write to a server without the expected test identity", pytrace=False)
    return BASE_URL


@pytest.fixture(scope="session")
def api_prefix(base_url):
    return API


@pytest.fixture(scope="session")
def admin_session(api_prefix):
    """Logged-in super_admin session with cookies + Bearer header."""
    email = os.environ.get("TEST_ADMIN_EMAIL", "")
    password = os.environ.get("TEST_ADMIN_PASSWORD", "")
    if not email or not password:
        pytest.fail("Explicit TEST_ADMIN_EMAIL and TEST_ADMIN_PASSWORD are required", pytrace=False)
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(
        f"{API}/auth/login",
        json={"email": email, "password": password},
        timeout=30,
    )
    if r.status_code != 200:
        pytest.fail(f"Test admin login failed (HTTP {r.status_code})", pytrace=False)
    body = r.json()
    token = body["access_token"]
    s.headers.update({"Authorization": f"Bearer {token}"})
    s.admin_user = body["user"]  # type: ignore[attr-defined]
    yield s
    s.close()


@pytest.fixture(scope="session")
def shared_state():
    """Mutable dict shared across ordered tests."""
    return {}
