"""Command authorization at real PostgreSQL waits, flushed effects and replay boundaries."""
from __future__ import annotations

import asyncio
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
import pytest
from fastapi import FastAPI
from pydantic import ValidationError
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.infrastructure.db.models.customer import Customer, LedgerEntry
from app.infrastructure.db.models.idempotency import IdempotencyRecord
from app.infrastructure.db.models.inventory import InventoryItem, StockMovement
from app.infrastructure.db.models.order import (
    Delivery, Order, OrderItem, OrderReservation, OrderStatusHistory, Payment,
)
from app.infrastructure.db.models.product import Product
from app.infrastructure.db.models.proof import DeliveryProof, ProofUploadOperation
from app.infrastructure.db.models.tenant import Tenant
from app.infrastructure.db.models.user import AuditLog, RefreshToken, User
from app.infrastructure.db.models.warehouse import Warehouse
from test_delivery_proofs import png
from test_financial_invariants import financial_db  # noqa: F401 identified owned PostgreSQL fixture

pytestmark = pytest.mark.integration
COMMANDS = (
    "create", "confirm", "reserve", "pick", "pack", "dispatch", "cancel", "payment",
    "start", "verify-otp", "deliver", "complete",
)
EFFECT_MODELS = (
    Customer, Order, OrderItem, OrderReservation, OrderStatusHistory, Delivery,
    Payment, LedgerEntry, InventoryItem, StockMovement, AuditLog, IdempotencyRecord,
    DeliveryProof, ProofUploadOperation,
)
INVALID_DATA = {"detail": [{
    "loc": ["body"], "msg": "Invalid request data", "type": "value_error",
}]}


class PrivateText(str):
    def __repr__(self) -> str:
        return "<redacted>"


@dataclass(frozen=True, repr=False)
class Actor:
    id: uuid.UUID
    session_id: uuid.UUID
    token: str


@dataclass(repr=False)
class CommandCase:
    engine: object
    async_engine: object
    app: FastAPI
    store: object
    tenant_id: uuid.UUID
    customer_id: uuid.UUID
    warehouse_id: uuid.UUID
    product_id: uuid.UUID
    owner: Actor
    partner: Actor
    customer: Actor
    other_partner_id: uuid.UUID
    actor: Actor
    session_class: type[AsyncSession] = AsyncSession
    order_id: uuid.UUID | None = None
    delivery_id: uuid.UUID | None = None
    otp: str | None = field(default=None, repr=False)
    references: dict = field(default_factory=dict)
    path: str = ""
    payload: dict | None = None
    operation: str = ""
    key: uuid.UUID = field(default_factory=uuid.uuid4)

    async def request(self, *, path=None, payload=None, actor=None, method="POST", prefix="/api/v1"):
        actor = actor or self.actor
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app, raise_app_exceptions=False),
            base_url="http://127.0.0.1",
        ) as client:
            return await client.request(
                method, prefix + (path or self.path),
                json=self.payload if payload is None else payload,
                headers={"Authorization": f"Bearer {actor.token}", "X-Idempotency-Key": str(self.key)},
            )

    async def upload(self, kind="photo", *, actor=None):
        actor = actor or self.actor
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app, raise_app_exceptions=False),
            base_url="http://127.0.0.1",
        ) as client:
            return await client.post(
                f"/api/v1/deliveries/{self.delivery_id}/proofs",
                headers={"Authorization": f"Bearer {actor.token}"}, data={"kind": kind},
                files={"file": ("private-proof.png", png(), "image/png")},
            )

    def call(self):
        return asyncio.run(self.upload() if self.operation == "upload" else self.request())

    def prepare(self, operation):
        self.operation = operation
        order_body = {
            "customer_id": str(self.customer_id), "warehouse_id": str(self.warehouse_id),
            "items": [{"product_id": str(self.product_id), "quantity": "1.000"}],
        }
        if operation == "create":
            self.path, self.payload = "/orders", order_body
            return
        created = _success(asyncio.run(self.request(path="/orders", payload=order_body, actor=self.owner)), 201)
        self.order_id = uuid.UUID(created["id"])
        stages = {
            "confirm": (), "reserve": (), "payment": (), "pick": ("reserve",),
            "pack": ("reserve", "pick"), "dispatch": ("reserve", "pick", "pack"),
            "cancel": ("reserve",),
        }.get(operation, ("reserve", "pick", "pack", "dispatch"))
        for action in stages:
            _success(asyncio.run(self.request(
                path=f"/orders/{self.order_id}/{action}", payload={}, actor=self.owner,
            )))
        if operation in {"start", "verify-otp", "complete", "deliver", "assign", "upload", "read"}:
            with Session(self.engine) as db:
                delivery = db.scalar(select(Delivery).where(
                    Delivery.order_id == self.order_id, Delivery.tenant_id == self.tenant_id,
                ))
                self.delivery_id, self.otp = delivery.id, PrivateText(delivery.otp_code)
            _success(asyncio.run(self.request(
                path=f"/deliveries/{self.delivery_id}/assign",
                payload={"partner_id": str(self.partner.id)}, actor=self.owner,
            )))
            if operation in {"start", "verify-otp", "complete", "upload", "read"}:
                self.actor = self.partner
        if operation in {"complete", "deliver"}:
            _success(asyncio.run(self.request(
                path=f"/deliveries/{self.delivery_id}/verify-otp", payload={"otp_code": self.otp},
            )))
            for kind, name in (("signature", "signature_url"), ("photo", "proof_photo_url")):
                self.references[name] = _success(asyncio.run(self.upload(kind)), 201)["url"]
        if operation == "payment":
            self.path, self.payload = "/payments", {
                "customer_id": str(self.customer_id), "order_id": str(self.order_id),
                "amount": "3.00", "mode": "cash",
            }
        elif operation in {"start", "verify-otp", "complete", "assign"}:
            self.path = f"/deliveries/{self.delivery_id}/{operation}"
            self.payload = {
                "verify-otp": {"otp_code": self.otp},
                "complete": {**self.references, "cash_amount": "3.00", "upi_amount": "2.00"},
                "assign": {"partner_id": str(self.other_partner_id), "priority": 2},
            }.get(operation, {})
        else:
            self.path = f"/orders/{self.order_id}/{operation}"
            self.payload = {**self.references, "cash_amount": "3.00", "upi_amount": "2.00"} if operation == "deliver" else {}


@pytest.fixture(autouse=True)
def require_owned_environment():
    if os.environ.get("SUPPLYOS_OWNED_TEST_ENV") != "1":
        pytest.skip("Command authorization tests require the owned disposable verifier")


@pytest.fixture
def case(financial_db, monkeypatch, tmp_path):
    from app.core.config import get_settings
    from app.core.database import get_db
    from app.core.security import create_access_token
    from app.features.deliveries.router import router as deliveries_router
    from app.features.orders.router import router as orders_router
    from app.features.payments.router import router as payments_router
    from app.features.proofs import service as proof_service
    from app.features.proofs.router import router as proofs_router
    from app.infrastructure.storage.proof_store import ProofStore, get_proof_store

    with Session(financial_db, expire_on_commit=False) as db:
        tenant = Tenant(name="Owned command authorization", currency="INR", settings={}, is_setup_complete=True)
        db.add(tenant)
        db.flush()
        buyer = Customer(
            tenant_id=tenant.id, code="AUTH", name="Synthetic command customer",
            customer_type="credit", credit_limit=Decimal("1000.00"),
        )
        warehouse = Warehouse(tenant_id=tenant.id, code="AUTH", name="Synthetic command warehouse")
        product = Product(
            tenant_id=tenant.id, sku="AUTH", name="Synthetic command product",
            base_price=Decimal("10.00"), gst_rate=Decimal("0"),
        )
        db.add_all([buyer, warehouse, product])
        db.flush()
        users = []
        for index, role in enumerate(("super_admin", "delivery_partner", "customer", "delivery_partner")):
            user = User(
                tenant_id=tenant.id, email=f"command-{index}-{uuid.uuid4().hex}@example.com",
                full_name="Synthetic command identity", password_hash="unused-fixture-hash",
                role=role, is_active=True, customer_id=buyer.id if role == "customer" else None,
            )
            db.add(user)
            users.append(user)
        db.flush()
        actors = []
        for user in users:
            session_id = uuid.uuid4()
            db.add(RefreshToken(
                user_id=user.id, session_id=session_id, jti=str(uuid.uuid4()),
                expires_at=datetime.now(timezone.utc) + timedelta(days=1),
            ))
            token, _ = create_access_token(
                str(user.id), str(tenant.id), user.role,
                session_id=session_id, session_version=user.session_version,
            )
            actors.append(Actor(user.id, session_id, PrivateText(token)))
        db.add(InventoryItem(
            tenant_id=tenant.id, product_id=product.id, warehouse_id=warehouse.id,
            quantity=Decimal("5.000"),
        ))
        db.add(StockMovement(
            tenant_id=tenant.id, product_id=product.id, warehouse_id=warehouse.id,
            movement_type="inbound", quantity=Decimal("5.000"), note="Owned fixture stock",
        ))
        db.commit()

    asynchronous = create_async_engine(
        financial_db.url.set(drivername="postgresql+asyncpg"), poolclass=NullPool,
        hide_parameters=True, connect_args={"server_settings": {"statement_timeout": "18000"}},
    )
    app = FastAPI()
    for router in (orders_router, payments_router, deliveries_router, proofs_router):
        app.include_router(router, prefix="/api/v1")
        app.include_router(router, prefix="/api")
    store = ProofStore(get_settings().model_copy(update={"proof_storage_dir": tmp_path / "proofs"}))
    fixture = CommandCase(
        financial_db, asynchronous, app, store, tenant.id, buyer.id, warehouse.id, product.id,
        actors[0], actors[1], actors[2], users[3].id, actors[0],
    )

    async def session():
        async with fixture.session_class(bind=asynchronous, expire_on_commit=False, autoflush=False) as db:
            try:
                yield db
            except BaseException:
                await db.rollback()
                raise

    app.dependency_overrides[get_db] = session
    app.dependency_overrides[get_proof_store] = lambda: fixture.store
    monkeypatch.setattr(proof_service, "get_proof_store", lambda: fixture.store)
    try:
        yield fixture
    finally:
        asyncio.run(asynchronous.dispose())


def _success(response, code=200):
    if response.status_code != code:
        pytest.fail(f"Owned command fixture failed (HTTP {response.status_code})", pytrace=False)
    return response.json()


def snapshot(case):
    with case.engine.connect() as connection:
        return {
            model.__tablename__: tuple(connection.execute(select(*model.__table__.columns).where(
                model.tenant_id == case.tenant_id,
            ).order_by(model.id)).all())
            for model in EFFECT_MODELS
        }


def unchanged(case, before, *, ignore=()):
    after = snapshot(case)
    if any(after[name] != value for name, value in before.items() if name not in ignore):
        pytest.fail("Denied authorization changed durable business effects", pytrace=False)


def _wait_for_lock(case, holder_pid):
    deadline = time.monotonic() + 8
    with case.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as observer:
        while time.monotonic() < deadline:
            if observer.scalar(text(
                "SELECT EXISTS (SELECT 1 FROM pg_stat_activity WHERE wait_event_type='Lock' "
                "AND :holder=ANY(pg_blocking_pids(pid)))"
            ), {"holder": holder_pid}):
                return
            time.sleep(0.01)
    pytest.fail("Command did not reach the actual PostgreSQL row wait", pytrace=False)


@contextmanager
def held_command(case, statement):
    with case.engine.connect() as holder, ThreadPoolExecutor(max_workers=1) as workers:
        holder.execute(statement.with_for_update())
        pid = holder.scalar(select(func.pg_backend_pid()))
        pending = workers.submit(case.call)
        try:
            _wait_for_lock(case, pid)
            yield holder, pending
        finally:
            holder.rollback()


def _business_unlocked(case):
    with case.engine.connect() as observer:
        for model in (Customer, Order, Delivery, InventoryItem):
            observer.execute(select(model.id).where(
                model.tenant_id == case.tenant_id,
            ).with_for_update(nowait=True))


def auth_change(actor, change):
    if change in {"revoked", "session_expired"}:
        values = {"revoked_at": datetime.now(timezone.utc)} if change == "revoked" else {
            "expires_at": datetime.now(timezone.utc) - timedelta(seconds=1),
        }
        return update(RefreshToken).where(RefreshToken.session_id == actor.session_id).values(**values)
    values = {"role": {"role": "accountant"}, "inactive": {"is_active": False},
              "epoch": {"session_version": 1}}[change]
    return update(User).where(User.id == actor.id).values(**values)


def clock_expiry(monkeypatch, change):
    import jwt.api_jwt
    from app.shared import deps

    future = None

    class Clock:
        @staticmethod
        def now(tz=None):
            return future or datetime.now(tz)

    monkeypatch.setattr(jwt.api_jwt if change == "access_expired" else deps, "datetime", Clock)

    def advance():
        nonlocal future
        future = datetime.now(timezone.utc) + timedelta(days=2)

    return advance


@pytest.mark.parametrize("operation", COMMANDS)
@pytest.mark.parametrize("change", ("inactive", "role", "epoch", "revoked", "session_expired"))
def test_user_wait_revalidates_before_any_business_lock_and_rolls_back(case, operation, change):
    case.prepare(operation)
    before = snapshot(case)
    with held_command(case, select(User.id).where(User.id == case.actor.id)) as (holder, pending):
        _business_unlocked(case)
        holder.execute(auth_change(case.actor, change))
        holder.commit()
        response = pending.result(timeout=20)
    assert response.status_code == 401
    unchanged(case, before)


@pytest.mark.parametrize("operation", ("create", "payment", "start", "verify-otp", "deliver", "complete"))
@pytest.mark.parametrize("change", ("revoked", "session_expired"))
def test_active_session_wait_revalidates_before_any_business_lock(case, operation, change):
    case.prepare(operation)
    before = snapshot(case)
    with held_command(case, select(RefreshToken.id).where(
        RefreshToken.session_id == case.actor.session_id,
    )) as (holder, pending):
        _business_unlocked(case)
        holder.execute(auth_change(case.actor, change))
        holder.commit()
        response = pending.result(timeout=20)
    assert response.status_code == 401
    unchanged(case, before)


@pytest.mark.parametrize("operation", COMMANDS)
@pytest.mark.parametrize("change", ("access_expired", "session_clock_expired"))
def test_expiry_at_later_business_wait_rolls_back_money_stock_history_and_claims(
    case, monkeypatch, operation, change,
):
    case.prepare(operation)
    advance = clock_expiry(monkeypatch, change)
    before = snapshot(case)
    statement = select(Customer.id).where(Customer.id == case.customer_id) if operation == "create" else (
        select(Order.id).where(Order.id == case.order_id)
    )
    with held_command(case, statement) as (holder, pending):
        # Both eligibility and active session remain held while business rows wait.
        with case.engine.connect() as revoker:
            for lock in (select(User.id).where(User.id == case.actor.id), select(RefreshToken.id).where(
                RefreshToken.session_id == case.actor.session_id,
            )):
                with pytest.raises(DBAPIError) as failure:
                    revoker.execute(lock.with_for_update(nowait=True))
                assert failure.value.orig.pgcode == "55P03"
                revoker.rollback()
        advance()
        holder.rollback()
        response = pending.result(timeout=20)
    assert response.status_code == 401
    unchanged(case, before)


@pytest.mark.parametrize("operation", (*COMMANDS, "assign", "upload"))
@pytest.mark.parametrize("change", ("role", "access_expired", "revoked", "session_expired"))
def test_final_effect_flush_requires_current_auth_before_commit(case, monkeypatch, operation, change):
    case.prepare(operation)
    before = snapshot(case)
    advance = clock_expiry(monkeypatch, change) if change == "access_expired" else None
    action = {
        "payment": "payments.record", "complete": "deliveries.complete", "assign": "deliveries.assign",
        "upload": "deliveries.proof_upload", "verify-otp": "deliveries.verify_otp", "start": "deliveries.start",
    }.get(operation, f"orders.{operation}")
    injected = False

    class ChangedFlush(AsyncSession):
        async def flush(self, *args, **kwargs):
            nonlocal injected
            targeted = any(isinstance(row, AuditLog) and row.action == action for row in self.new)
            await super().flush(*args, **kwargs)
            if targeted and not injected:
                injected = True
                if advance is not None:
                    advance()
                else:
                    await self.execute(auth_change(case.actor, change))

    case.session_class = ChangedFlush
    response = case.call()
    assert injected, "The regression must cross the actual financial/audit/proof flush"
    assert response.status_code == 401
    unchanged(case, before, ignore={"proof_upload_operations"} if operation == "upload" else ())
    if operation == "upload":
        from app.infrastructure.storage.local import read_private_file

        with Session(case.engine) as db:
            operation_row = db.scalar(select(ProofUploadOperation).where(
                ProofUploadOperation.tenant_id == case.tenant_id,
            ))
            assert operation_row is not None and operation_row.state == "reserved"
            assert read_private_file(case.store.settings.proof_storage_dir, operation_row.object_key,
                                     limit=operation_row.size_bytes) == png()


@pytest.mark.parametrize("operation", ("create", "payment", "deliver", "complete"))
def test_same_key_replay_requires_a_current_role_that_can_execute_the_command(case, operation):
    from app.core.security import create_access_token

    case.prepare(operation)
    original = case.call()
    _success(original, 201 if operation in {"create", "payment"} else 200)
    before = snapshot(case)
    role = "warehouse_manager" if operation == "payment" else "accountant"
    with case.engine.begin() as connection:
        connection.execute(update(User).where(User.id == case.actor.id).values(role=role))
    token, _ = create_access_token(
        str(case.actor.id), str(case.tenant_id), role,
        session_id=case.actor.session_id, session_version=0,
    )
    case.actor = Actor(case.actor.id, case.actor.session_id, PrivateText(token))
    assert case.call().status_code == 403
    unchanged(case, before)


@pytest.mark.parametrize("operation", ("start", "verify-otp", "upload", "complete", "deliver"))
def test_cancelled_parent_rejects_operations_without_resetting_existing_evidence(case, operation):
    case.prepare("complete")
    proof_ids = [uuid.UUID(reference.rsplit("/", 1)[1]) for reference in case.references.values()]
    _success(asyncio.run(case.request(
        path=f"/orders/{case.order_id}/cancel", payload={"note": "Owned cancellation"}, actor=case.owner,
    )))
    case.operation = operation
    case.actor = case.owner if operation == "deliver" else case.partner
    case.path = f"/orders/{case.order_id}/deliver" if operation == "deliver" else (
        f"/deliveries/{case.delivery_id}/{operation}"
    )
    case.payload = {"otp_code": case.otp} if operation == "verify-otp" else {
        **case.references, "cash_amount": "3.00", "upi_amount": "2.00",
    } if operation in {"complete", "deliver"} else {}
    before = snapshot(case)
    assert case.call().status_code == 409
    unchanged(case, before)
    with Session(case.engine) as db:
        delivery = db.get(Delivery, case.delivery_id)
        assert delivery.otp_verified is True and delivery.completed_at is None
        assert delivery.otp_code == case.otp
        assert db.scalar(select(InventoryItem.reserved_qty).where(InventoryItem.tenant_id == case.tenant_id)) == 0
    for identifier in proof_ids:
        response = asyncio.run(case.request(path=f"/delivery-proofs/{identifier}", method="GET", payload={}))
        assert response.status_code == 200 and response.content == png()


@pytest.mark.parametrize("operation", ("start", "verify-otp", "upload"))
def test_actual_cancellation_wins_the_parent_lock_before_delivery_mutation(case, monkeypatch, operation):
    from app.features.orders import service

    case.prepare(operation)
    ready, release = threading.Event(), threading.Event()
    holder_pid = None
    cancel = service.cancel_order

    async def paused(*args, **kwargs):
        nonlocal holder_pid
        result = await cancel(*args, **kwargs)
        holder_pid = await args[0].scalar(select(func.pg_backend_pid()))
        ready.set()
        assert await asyncio.to_thread(release.wait, 10)
        return result

    monkeypatch.setattr(service, "cancel_order", paused)
    with ThreadPoolExecutor(max_workers=2) as workers:
        cancelling = workers.submit(lambda: asyncio.run(case.request(
            path=f"/orders/{case.order_id}/cancel", payload={}, actor=case.owner,
        )))
        try:
            assert ready.wait(timeout=10)
            pending = workers.submit(case.call)
            _wait_for_lock(case, holder_pid)
        finally:
            release.set()
        assert cancelling.result(timeout=20).status_code == 200
        assert pending.result(timeout=20).status_code == 409
    with Session(case.engine) as db:
        delivery = db.get(Delivery, case.delivery_id)
        assert delivery.started_at is None and delivery.otp_verified is False
        assert delivery.completed_at is None and delivery.otp_code == case.otp
        assert db.get(Order, case.order_id).status == "cancelled"
        assert db.scalar(select(func.count()).select_from(ProofUploadOperation).where(
            ProofUploadOperation.tenant_id == case.tenant_id,
        )) == 0
        assert db.scalar(select(func.count()).select_from(OrderStatusHistory).where(
            OrderStatusHistory.order_id == case.order_id, OrderStatusHistory.to_status == "cancelled",
        )) == 1


@pytest.mark.parametrize("prefix", ("/api/v1", "/api"))
@pytest.mark.parametrize("payload", (
    {}, {"otp_code": "not-a-code"}, {"otp_code": "12345678901"}, {"otp_code": ["private-marker"]},
    {"otp_code": "123456", "private-marker-as-field": "private-marker-as-value"},
))
def test_otp_validation_is_private_static_and_cannot_echo_inputs(case, payload, prefix, caplog):
    case.prepare("verify-otp")
    before = snapshot(case)
    response = asyncio.run(case.request(payload=payload, prefix=prefix))
    assert response.status_code == 422 and response.json() == INVALID_DATA
    assert response.headers["Cache-Control"] == "no-store"
    for marker in ("not-a-code", "private-marker", "12345678901", case.actor.token):
        if marker in response.text or marker in caplog.text:
            pytest.fail("Private OTP validation echoed a credential-bearing input", pytrace=False)
    unchanged(case, before)


def test_otp_dto_redacts_repr_exports_and_credential_validation(case):
    from app.features.deliveries.router import VerifyOTPRequest

    credential = PrivateText("123456")
    dto = VerifyOTPRequest(otp_code=credential)
    assert dto.model_dump() == {} and dto.model_dump_json() == "{}"
    if credential in repr(dto):
        pytest.fail("OTP DTO repr disclosed a credential", pytrace=False)
    with pytest.raises(ValidationError) as failure:
        VerifyOTPRequest(otp_code="private-marker-invalid")
    if "private-marker-invalid" in str(failure.value):
        pytest.fail("OTP DTO validation disclosed a credential", pytrace=False)


@pytest.mark.parametrize("operation", ("confirm", "reserve", "pick", "pack", "dispatch", "cancel"))
def test_order_response_building_is_inside_the_final_auth_boundary(case, monkeypatch, operation):
    import app.features.orders.router as orders

    case.prepare(operation)
    before = snapshot(case)
    advance = clock_expiry(monkeypatch, "access_expired")
    load = orders._load_full
    built = False

    async def expired_after_receipt(*args, **kwargs):
        nonlocal built
        response = await load(*args, **kwargs)
        built = True
        advance()
        return response

    monkeypatch.setattr(orders, "_load_full", expired_after_receipt)
    assert case.call().status_code == 401
    assert built
    unchanged(case, before)


def test_proof_upload_rechecks_actual_parent_cancellation_after_io_and_retains_owned_bytes(case):
    from app.infrastructure.storage.local import read_private_file

    case.prepare("upload")
    create = case.store.create
    stored_key = None

    async def cancelled_after_store_write(operation, data):
        nonlocal stored_key
        result = await create(operation, data)
        stored_key = operation.object_key
        response = await case.request(
            path=f"/orders/{case.order_id}/cancel", payload={}, actor=case.owner,
        )
        assert response.status_code == 200
        return result

    case.store.create = cancelled_after_store_write
    assert case.call().status_code == 409
    assert stored_key is not None
    with Session(case.engine) as db:
        assert db.get(Order, case.order_id).status == "cancelled"
        assert db.scalar(select(func.count()).select_from(DeliveryProof).where(
            DeliveryProof.tenant_id == case.tenant_id,
        )) == 0
        operation = db.scalar(select(ProofUploadOperation).where(
            ProofUploadOperation.tenant_id == case.tenant_id,
        ))
        assert operation is not None and operation.state == "reserved" and operation.object_key == stored_key
        assert read_private_file(case.store.settings.proof_storage_dir, stored_key,
                                 limit=operation.size_bytes) == png()


@pytest.mark.parametrize("operation", ("payment", "start", "verify-otp", "complete", "assign"))
def test_payment_and_delivery_receipt_builders_precede_final_auth_check(case, monkeypatch, operation):
    from app.features.deliveries.router import DeliveryOut
    from app.features.payments.router import PaymentOut

    case.prepare(operation)
    before = snapshot(case)
    advance = clock_expiry(monkeypatch, "access_expired")
    model = PaymentOut if operation == "payment" else DeliveryOut
    build = model.model_validate
    built = False

    def expired_after_receipt(*args, **kwargs):
        nonlocal built
        response = build(*args, **kwargs)
        built = True
        advance()
        return response

    monkeypatch.setattr(model, "model_validate", expired_after_receipt)
    assert case.call().status_code == 401
    assert built
    unchanged(case, before)
