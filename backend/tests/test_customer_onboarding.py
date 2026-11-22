"""Owned live API customer authority, exact money and credit edit serialization."""
from __future__ import annotations

import os
import secrets
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest
import requests
from sqlalchemy import create_engine, select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.infrastructure.db.models.customer import Customer
from app.infrastructure.db.models.user import User

pytestmark = pytest.mark.integration


def checked(response, expected=200):
    if response.status_code != expected:
        pytest.fail(f"Owned onboarding request failed (HTTP {response.status_code})", pytrace=False)
    return response.json()


@pytest.fixture
def database(admin_session, api_prefix):
    identity = checked(admin_session.get(f"{api_prefix}/auth/me", timeout=10))
    url = make_url(os.environ.get("DATABASE_URL_SYNC", ""))
    if not (
        os.environ.get("APP_ENV") == "test" and os.environ.get("SUPPLYOS_OWNED_TEST_ENV") == "1"
        and url.host in {"127.0.0.1", "localhost", "::1"}
        and (url.database or "").startswith("supplyos_test_")
    ):
        pytest.fail("Onboarding requires the owned no-dotenv verifier", pytrace=False)
    engine = create_engine(url, hide_parameters=True)
    try:
        with Session(engine) as db:
            current = db.get(User, uuid.UUID(identity["id"]))
            if current is None or str(current.tenant_id) != identity["tenant_id"]:
                pytest.fail("Onboarding database does not match API identity", pytrace=False)
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def roles(admin_session, api_prefix):
    result = {"super_admin": admin_session}
    created = []
    try:
        for role in ("warehouse_manager", "accountant", "delivery_partner", "customer"):
            email, password = f"onboarding-{uuid.uuid4().hex}@example.com", secrets.token_urlsafe(24)
            body = {"email": email, "password": password, "full_name": "Owned onboarding user"}
            endpoint = "/auth/register-customer" if role == "customer" else "/staff"
            if role != "customer":
                body["role"] = role
            checked(admin_session.post(f"{api_prefix}{endpoint}", json=body, timeout=20), 201)
            session = requests.Session()
            created.append(session)
            checked(session.post(f"{api_prefix}/auth/login", json={"email": email, "password": password}, timeout=20))
            result[role] = session
        yield result
    finally:
        for session in created:
            session.close()


def account():
    return {
        "email": f"account-{uuid.uuid4().hex}@example.com", "password": secrets.token_urlsafe(24),
        "full_name": "New holder", "phone": "", "business_name": "",
    }


def customer(admin_session, api_prefix, **fields):
    return checked(admin_session.post(f"{api_prefix}/customers", json={
        "name": "Owned customer fixture", **fields,
    }, timeout=20), 201)


def test_anonymous_tenant_uuid_is_not_customer_signup_authority(admin_session, api_prefix):
    body = account()
    body["tenant_id"] = checked(admin_session.get(f"{api_prefix}/auth/me", timeout=10))["tenant_id"]
    response = requests.post(f"{api_prefix}/auth/register-customer", json=body, timeout=20)
    assert response.status_code == 401
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("role", ["warehouse_manager", "delivery_partner", "customer"])
def test_non_finance_roles_cannot_create_accounts_or_customer_records(roles, api_prefix, role):
    assert roles[role].post(f"{api_prefix}/auth/register-customer", json=account(), timeout=20).status_code == 403
    assert roles[role].post(f"{api_prefix}/customers", json={"name": "Forbidden"}, timeout=20).status_code == 403


@pytest.mark.parametrize("role", ["super_admin", "accountant"])
def test_holder_selected_account_is_own_tenant_cash_unverified_without_login(roles, api_prefix, database, role):
    creator = checked(roles[role].get(f"{api_prefix}/auth/me", timeout=10))
    response = roles[role].post(f"{api_prefix}/auth/register-customer", json=account(), timeout=20)
    data = checked(response, 201)
    assert data["role"] == "customer" and data["tenant_id"] == creator["tenant_id"]
    assert not response.cookies
    with Session(database) as db:
        user = db.get(User, uuid.UUID(data["id"]))
        record = db.get(Customer, user.customer_id)
        assert user.is_email_verified is False and record.customer_type == "cash"
        assert record.credit_limit == 0 and record.outstanding == 0


def test_supplied_foreign_tenant_assertion_cannot_change_authority(admin_session, api_prefix):
    body = account()
    body["tenant_id"] = str(uuid.uuid4())
    assert admin_session.post(f"{api_prefix}/auth/register-customer", json=body, timeout=20).status_code == 403


def test_optional_contact_record_is_not_silently_a_login_account(admin_session, api_prefix, database):
    data = customer(admin_session, api_prefix, email="", phone="", address="", name="  Contact only  ")
    assert data["email"] is None and data["phone"] is None and data["address"] is None
    assert data["name"] == "Contact only"
    with Session(database) as db:
        assert db.scalar(select(User.id).where(User.customer_id == uuid.UUID(data["id"]))) is None


def test_credit_changes_preserve_existing_commitments_and_balances(admin_session, api_prefix, database):
    data = customer(admin_session, api_prefix, customer_type="credit", credit_limit="200.00")
    identifier = uuid.UUID(data["id"])
    with database.begin() as connection:
        connection.execute(update(Customer).where(Customer.id == identifier).values(
            outstanding=Decimal("75.00"), credit_held=Decimal("100.00"), cash_funded_pending=Decimal("10.00"),
        ))
    assert admin_session.patch(f"{api_prefix}/customers/{identifier}", json={"credit_limit": "184.99"}, timeout=20).status_code == 409
    assert admin_session.patch(f"{api_prefix}/customers/{identifier}", json={"customer_type": "cash"}, timeout=20).status_code == 409
    updated = checked(admin_session.patch(f"{api_prefix}/customers/{identifier}", json={"credit_limit": "185.00"}, timeout=20))
    assert Decimal(updated["credit_limit"]) == Decimal("185.00")
    assert tuple(Decimal(updated[name]) for name in ("outstanding", "credit_held", "cash_funded_pending")) == (
        Decimal("75.00"), Decimal("100.00"), Decimal("10.00"),
    )


def test_credit_limit_rechecks_after_waiting_for_financial_writer(admin_session, api_prefix, database):
    data = customer(admin_session, api_prefix, customer_type="credit", credit_limit="200.00")
    identifier = uuid.UUID(data["id"])
    with database.connect() as holder, ThreadPoolExecutor(max_workers=1) as workers:
        holder.execute(select(Customer.id).where(Customer.id == identifier).with_for_update())
        pid = holder.scalar(text("SELECT pg_backend_pid()"))
        request = workers.submit(lambda: admin_session.patch(
            f"{api_prefix}/customers/{identifier}", json={"credit_limit": "50.00"}, timeout=20,
        ))
        try:
            deadline, waiting = time.monotonic() + 10, False
            while time.monotonic() < deadline:
                with database.connect() as observe:
                    waiting = bool(observe.scalar(text(
                        "SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE :holder=ANY(pg_blocking_pids(pid)))"
                    ), {"holder": pid}))
                if waiting:
                    break
                time.sleep(0.02)
            assert waiting
            holder.execute(update(Customer).where(Customer.id == identifier).values(outstanding=Decimal("75.00")))
            holder.commit()
            assert request.result(timeout=20).status_code == 409
        finally:
            holder.rollback()
    with Session(database) as db:
        record = db.get(Customer, identifier)
        assert record.credit_limit == 200 and record.outstanding == 75
