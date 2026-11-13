"""Real PostgreSQL ownership/commit races; storage protocol is deliberately offline."""
from __future__ import annotations

import asyncio
import base64
import json
import secrets
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from alembic import command
from alembic.migration import MigrationContext
from fastapi import FastAPI
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import create_access_token
from app.features.proofs.router import router
from app.infrastructure.db.models.customer import Customer
from app.infrastructure.db.models.order import Delivery, Order
from app.infrastructure.db.models.proof import DeliveryProof, ProofUploadOperation
from app.infrastructure.db.models.tenant import Tenant
from app.infrastructure.db.models.user import RefreshToken, User
from app.infrastructure.db.models.warehouse import Warehouse
from app.infrastructure.storage.contracts import StorageWriteUncertain
from app.infrastructure.storage.local import read_private_file
from app.infrastructure.storage.proof_store import ProofStore, get_proof_store
from app.infrastructure.storage.supabase import OWNERSHIP_FIELD, SupabaseProofStore, SupabaseStorageConfig
from test_migrations import database  # noqa: F401 owned disposable PostgreSQL
from test_supabase_storage import Provider, png

pytestmark = pytest.mark.integration


@dataclass(repr=False)
class Case:
    engine: object
    app: FastAPI
    store: ProofStore
    delivery_id: uuid.UUID
    user_id: uuid.UUID
    token: str = field(repr=False)

    async def upload(self, prefix="/api/v1"):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app, raise_app_exceptions=False),
            base_url="http://127.0.0.1",
        ) as client:
            return await client.post(
                f"{prefix}/deliveries/{self.delivery_id}/proofs",
                headers={"Authorization": "Bearer " + self.token}, data={"kind": "photo"},
                files={"file": ("proof.png", png(), "image/png")},
            )

    async def read(self, url):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app, raise_app_exceptions=False),
            base_url="http://127.0.0.1",
        ) as client:
            return await client.get(url, headers={"Authorization": "Bearer " + self.token})


@pytest.fixture
def case(database, monkeypatch, tmp_path):
    engine, config = database
    command.upgrade(config, "head")
    monkeypatch.setenv("PROOF_STORAGE_BACKEND", "local")
    monkeypatch.setenv("PROOF_STORAGE_DIR", str(tmp_path / "proofs"))
    monkeypatch.setenv("SUPABASE_STORAGE_KEY", "")
    monkeypatch.setenv("SUPABASE_STORAGE_ORIGIN", "")
    monkeypatch.setenv("SUPABASE_STORAGE_BUCKET", "")
    get_settings.cache_clear()
    with Session(engine) as db:
        tenant = Tenant(name="Upload journal fixture", currency="INR", settings={}, is_setup_complete=True)
        db.add(tenant)
        db.flush()
        buyer = Customer(tenant_id=tenant.id, code="POD", name="Upload fixture", customer_type="cash")
        warehouse = Warehouse(tenant_id=tenant.id, code="POD", name="Upload fixture")
        user = User(
            tenant_id=tenant.id, email="upload-fixture@example.com", password_hash="unused-fixture",
            full_name="Upload fixture", role="delivery_partner", is_active=True,
        )
        db.add_all([buyer, warehouse, user])
        db.flush()
        order = Order(
            tenant_id=tenant.id, customer_id=buyer.id, warehouse_id=warehouse.id,
            order_number="UPLOAD-JOURNAL", status="out_for_delivery", payment_mode="cash",
        )
        db.add(order)
        db.flush()
        delivery = Delivery(tenant_id=tenant.id, order_id=order.id, partner_id=user.id)
        session_id = uuid.uuid4()
        db.add_all([delivery, RefreshToken(
            user_id=user.id, jti=str(uuid.uuid4()), session_id=session_id,
            expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        )])
        db.commit()
        token, _ = create_access_token(
            str(user.id), str(tenant.id), user.role, session_id=session_id, session_version=user.session_version,
        )
        user_id, delivery_id = user.id, delivery.id
    settings = get_settings()
    store = ProofStore(settings)
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.include_router(router, prefix="/api")
    async_url = engine.url.set(drivername="postgresql+asyncpg")
    async_engine = create_async_engine(async_url, poolclass=NullPool)
    factory = async_sessionmaker(async_engine, expire_on_commit=False, autoflush=False)

    async def session():
        async with factory() as db:
            yield db

    app.dependency_overrides[get_db] = session
    app.dependency_overrides[get_proof_store] = lambda: store
    app.state.test_factory = factory
    try:
        yield Case(engine, app, store, delivery_id, user_id, token)
    finally:
        asyncio.run(async_engine.dispose())


def rows(case):
    with Session(case.engine) as db:
        return (
            db.scalars(select(ProofUploadOperation)).all(),
            db.scalars(select(DeliveryProof)).all(),
        )


@pytest.mark.parametrize("prefix", ["/api/v1", "/api"])
def test_reservation_is_durable_and_delivery_lock_is_released_before_io(case, prefix):
    create = case.store.create

    async def observed(operation, data):
        with Session(case.engine) as db:
            reserved = db.get(ProofUploadOperation, operation.id)
            assert reserved is not None and reserved.state == "reserved"
            db.execute(select(Delivery).where(Delivery.id == case.delivery_id).with_for_update(nowait=True))
            db.execute(select(User.id).where(User.id == case.user_id).with_for_update(nowait=True))
            db.execute(select(RefreshToken.id).where(
                RefreshToken.user_id == case.user_id,
            ).with_for_update(nowait=True))
        return await create(operation, data)

    case.store.create = observed
    response = asyncio.run(case.upload(prefix))
    assert response.status_code == 201
    operations, proofs = rows(case)
    assert len(operations) == len(proofs) == 1
    assert operations[0].state == "committed"
    assert proofs[0].upload_operation_id == operations[0].id
    assert proofs[0].storage_backend == "local"
    assert response.json()["url"] == f"/api/v1/delivery-proofs/{proofs[0].id}"
    assert "object_key" not in response.json() and "upload_operation_id" not in response.json()


def test_lost_upload_reply_retains_durable_ownership_and_bytes_without_receipt(case):
    create = case.store.create

    async def lost_reply(operation, data):
        await create(operation, data)
        raise StorageWriteUncertain()

    case.store.create = lost_reply
    assert asyncio.run(case.upload()).status_code == 503
    operations, proofs = rows(case)
    assert len(operations) == 1 and operations[0].state == "reserved" and not proofs
    assert read_private_file(
        case.store.settings.proof_storage_dir, operations[0].object_key, limit=len(png()),
    ) == png()


@pytest.mark.parametrize("change,expected", [
    ("inactive", 401), ("reassigned", 403), ("completed", 409),
])
def test_auth_assignment_and_completion_are_rechecked_after_io(case, change, expected):
    create = case.store.create

    async def changed(operation, data):
        stored = await create(operation, data)
        with Session(case.engine) as db:
            if change == "inactive":
                db.execute(update(User).where(User.id == case.user_id).values(is_active=False))
            elif change == "reassigned":
                db.execute(update(Delivery).where(Delivery.id == case.delivery_id).values(partner_id=None))
            else:
                db.execute(update(Delivery).where(Delivery.id == case.delivery_id).values(
                    completed_at=datetime.now(timezone.utc),
                ))
            db.commit()
        return stored

    case.store.create = changed
    assert asyncio.run(case.upload()).status_code == expected
    operations, proofs = rows(case)
    assert len(operations) == 1 and operations[0].state == "reserved" and not proofs
    assert read_private_file(
        case.store.settings.proof_storage_dir, operations[0].object_key, limit=len(png()),
    ) == png()


def test_lost_commit_reply_cannot_delete_a_committed_proof(case):
    factory = case.app.state.test_factory

    class LostCommitSession(AsyncSession):
        commits = 0

        async def commit(self):
            await super().commit()
            self.commits += 1
            if self.commits == 2:
                raise RuntimeError("Offline lost acknowledgement fixture")

    async def session():
        async with LostCommitSession(bind=factory.kw["bind"], expire_on_commit=False) as db:
            yield db

    case.app.dependency_overrides[get_db] = session
    assert asyncio.run(case.upload()).status_code == 500
    operations, proofs = rows(case)
    assert len(operations) == len(proofs) == 1 and operations[0].state == "committed"
    assert read_private_file(
        case.store.settings.proof_storage_dir, proofs[0].object_key, limit=proofs[0].size_bytes,
    ) == png()


def test_hosted_upload_and_read_commit_exact_provenance_without_local_fallback(case, monkeypatch):
    config = SupabaseStorageConfig(
        origin="https://private-project.supabase.co", bucket="delivery-proofs",
        service_role_key=secrets.token_urlsafe(48), approved_free=True, versioning_verified=True,
    )
    monkeypatch.setenv("PROOF_STORAGE_BACKEND", "supabase")
    monkeypatch.setenv("SUPABASE_STORAGE_ORIGIN", config.origin)
    monkeypatch.setenv("SUPABASE_STORAGE_BUCKET", config.bucket)
    monkeypatch.setenv("SUPABASE_STORAGE_KEY", config.service_role_key)
    monkeypatch.setenv("APPROVED_FREE_STORAGE", "true")
    monkeypatch.setenv("SUPABASE_VERSIONING_VERIFIED", "true")
    get_settings.cache_clear()
    provider = Provider(config)

    def bound_protocol(request):
        if request.method == "POST":
            provider.key = request.url.path.rsplit("/", 1)[1]
            metadata = json.loads(base64.b64decode(request.headers["x-metadata"]))
            provider.operation = uuid.UUID(metadata[OWNERSHIP_FIELD])
            with Session(case.engine) as db:
                operation = db.get(ProofUploadOperation, provider.operation)
                assert operation is not None and operation.state == "reserved"
                db.execute(select(Delivery).where(
                    Delivery.id == case.delivery_id,
                ).with_for_update(nowait=True))
        return provider.handle(request)

    hosted = SupabaseProofStore(config, transport=httpx.MockTransport(bound_protocol))
    case.store = ProofStore(get_settings(), hosted=hosted)
    case.app.dependency_overrides[get_proof_store] = lambda: case.store
    response = asyncio.run(case.upload())
    assert response.status_code == 201
    operations, proofs = rows(case)
    assert len(operations) == len(proofs) == 1 and operations[0].state == "committed"
    proof = proofs[0]
    assert proof.storage_backend == "supabase"
    assert (proof.provider_object_id, proof.provider_version) == (provider.identifier, provider.version)
    assert (proof.storage_origin, proof.storage_bucket) == (config.origin, config.bucket)
    assert not case.store.settings.proof_storage_dir.exists()

    async def read():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=case.app), base_url="http://127.0.0.1",
        ) as client:
            return await client.get(response.json()["url"], headers={
                "Authorization": "Bearer " + case.token,
            })

    retrieved = asyncio.run(read())
    assert retrieved.status_code == 200 and retrieved.content == png()
    assert retrieved.headers["cache-control"] == "private, no-store"
    assert not any(request.method == "DELETE" for request in provider.requests)
    if config.service_role_key in response.text or config.service_role_key in retrieved.text:
        pytest.fail("Private storage credentials escaped the API", pytrace=False)


@pytest.mark.parametrize("change", ["inactive", "revoked", "version", "role", "expired"])
def test_auth_changes_committed_during_final_lock_wait_refuse_the_receipt(case, change):
    create = case.store.create
    uploaded = threading.Event()

    async def observed(operation, data):
        stored = await create(operation, data)
        uploaded.set()
        return stored

    case.store.create = observed
    with case.engine.connect() as holder, ThreadPoolExecutor(max_workers=1) as workers:
        holder.execute(select(User.id).where(User.id == case.user_id).with_for_update())
        pid = holder.scalar(text("SELECT pg_backend_pid()"))
        result = workers.submit(lambda: asyncio.run(case.upload()))
        try:
            assert uploaded.wait(timeout=10)
            deadline = time.monotonic() + 5
            waiting = False
            while time.monotonic() < deadline:
                with case.engine.connect() as observer:
                    waiting = bool(observer.scalar(text(
                        "SELECT EXISTS (SELECT 1 FROM pg_stat_activity "
                        "WHERE :holder = ANY(pg_blocking_pids(pid)))"
                    ), {"holder": pid}))
                if waiting:
                    break
                time.sleep(0.02)
            assert waiting, "The final receipt must wait for the authenticated user lock"
            if change in {"revoked", "expired"}:
                values = {"revoked_at": datetime.now(timezone.utc)} if change == "revoked" else {
                    "expires_at": datetime.now(timezone.utc) - timedelta(seconds=1),
                }
                holder.execute(update(RefreshToken).where(
                    RefreshToken.user_id == case.user_id,
                ).values(**values))
            else:
                values = {
                    "inactive": {"is_active": False}, "version": {"session_version": 1},
                    "role": {"role": "customer"},
                }[change]
                holder.execute(update(User).where(User.id == case.user_id).values(**values))
            holder.commit()
            assert result.result(timeout=15).status_code == 401
        finally:
            holder.rollback()
    operations, proofs = rows(case)
    assert len(operations) == 1 and operations[0].state == "reserved" and not proofs
    assert read_private_file(
        case.store.settings.proof_storage_dir, operations[0].object_key, limit=len(png()),
    ) == png()


def test_invalid_journal_is_rejected_before_any_storage_read(case):
    response = asyncio.run(case.upload())
    assert response.status_code == 201
    operations, _ = rows(case)
    with Session(case.engine) as db:
        db.execute(update(ProofUploadOperation).where(
            ProofUploadOperation.id == operations[0].id,
        ).values(state="reserved"))
        db.commit()

    async def forbidden_read(*args, **kwargs):
        pytest.fail("Invalid journal ownership reached the storage boundary", pytrace=False)

    case.store.read = forbidden_read
    assert asyncio.run(case.read(response.json()["url"])).status_code == 409


def test_public_data_api_roles_cannot_access_the_private_journal(case):
    assert asyncio.run(case.upload()).status_code == 201
    created = []
    roles = ("anon", "authenticated")
    try:
        with case.engine.begin() as connection:
            for role in roles:
                if not connection.scalar(text("SELECT 1 FROM pg_roles WHERE rolname=:role"), {"role": role}):
                    connection.execute(text(f"CREATE ROLE {role} NOLOGIN"))
                    created.append(role)
        for role in roles:
            with case.engine.connect() as connection:
                with pytest.raises(DBAPIError) as failure:
                    connection.execute(text(f"SET LOCAL ROLE {role}"))
                    connection.execute(text("SELECT count(*) FROM proof_upload_operations"))
                assert failure.value.orig.pgcode == "42501"
                connection.rollback()
            with case.engine.begin() as connection:
                connection.execute(text(f"GRANT SELECT ON proof_upload_operations TO {role}"))
            with case.engine.connect() as connection:
                connection.execute(text(f"SET LOCAL ROLE {role}"))
                assert connection.scalar(text("SELECT count(*) FROM proof_upload_operations")) == 0
                connection.rollback()
    finally:
        with case.engine.begin() as connection:
            for role in roles:
                if connection.scalar(text("SELECT 1 FROM pg_roles WHERE rolname=:role"), {"role": role}):
                    connection.execute(text(f"REVOKE ALL ON proof_upload_operations FROM {role}"))
            for role in created:
                connection.execute(text(f"DROP ROLE {role}"))


def test_receipt_commit_serializes_before_a_waiting_session_revocation(case):
    factory = case.app.state.test_factory
    committing, release = threading.Event(), threading.Event()

    class PausedCommitSession(AsyncSession):
        commits = 0

        async def commit(self):
            self.commits += 1
            if self.commits == 2:
                committing.set()
                assert await asyncio.to_thread(release.wait, 10)
            await super().commit()

    async def session():
        async with PausedCommitSession(bind=factory.kw["bind"], expire_on_commit=False) as db:
            yield db

    case.app.dependency_overrides[get_db] = session
    with ThreadPoolExecutor(max_workers=1) as workers:
        result = workers.submit(lambda: asyncio.run(case.upload()))
        try:
            assert committing.wait(timeout=10)
            with case.engine.connect() as revoker:
                revoker.execute(text("SET LOCAL lock_timeout='150ms'"))
                with pytest.raises(DBAPIError) as failure:
                    revoker.execute(update(User).where(User.id == case.user_id).values(session_version=1))
                assert failure.value.orig.pgcode == "55P03"
                revoker.rollback()
        finally:
            release.set()
        response = result.result(timeout=15)
    assert response.status_code == 201
    operations, proofs = rows(case)
    assert len(operations) == len(proofs) == 1 and operations[0].state == "committed"
    with case.engine.begin() as revoker:
        revoker.execute(update(User).where(User.id == case.user_id).values(session_version=1))
    assert asyncio.run(case.read(response.json()["url"])).status_code == 401


def test_partner_fk_reassignment_does_not_deadlock_post_upload_auth_guard(case):
    create = case.store.create
    uploaded, release = threading.Event(), threading.Event()

    async def observed(operation, data):
        stored = await create(operation, data)
        uploaded.set()
        assert await asyncio.to_thread(release.wait, 10)
        return stored

    case.store.create = observed
    with case.engine.connect() as assignment, ThreadPoolExecutor(max_workers=1) as workers:
        result = workers.submit(lambda: asyncio.run(case.upload()))
        try:
            assert uploaded.wait(timeout=10)
            assignment.execute(select(Delivery.id).where(
                Delivery.id == case.delivery_id,
            ).with_for_update())
            pid = assignment.scalar(text("SELECT pg_backend_pid()"))
            release.set()
            deadline = time.monotonic() + 5
            waiting = False
            while time.monotonic() < deadline:
                with case.engine.connect() as observer:
                    waiting = bool(observer.scalar(text(
                        "SELECT EXISTS (SELECT 1 FROM pg_stat_activity "
                        "WHERE :holder = ANY(pg_blocking_pids(pid)))"
                    ), {"holder": pid}))
                if waiting:
                    break
                time.sleep(0.02)
            assert waiting, "The upload finalizer must be waiting on the assignment's delivery lock"
            assignment.execute(text("SET LOCAL lock_timeout='250ms'"))
            assignment.execute(update(Delivery).where(Delivery.id == case.delivery_id).values(partner_id=None))
            # This acquires a users.id FK KEY SHARE lock while the upload holds its auth lock.
            assignment.execute(update(Delivery).where(Delivery.id == case.delivery_id).values(
                partner_id=case.user_id,
            ))
            assignment.commit()
            assert result.result(timeout=15).status_code == 201
        finally:
            release.set()
            assignment.rollback()
    operations, proofs = rows(case)
    assert len(operations) == len(proofs) == 1 and operations[0].state == "committed"


def test_uncommitted_journal_prevents_an_evidence_erasing_downgrade(case, database):
    _, config = database
    create = case.store.create

    async def uncertain(operation, data):
        await create(operation, data)
        raise StorageWriteUncertain()

    case.store.create = uncertain
    assert asyncio.run(case.upload()).status_code == 503
    with pytest.raises(RuntimeError, match="proof receipts/history must be preserved"):
        command.downgrade(config, "20261109_0005")
    with case.engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(ProofUploadOperation)) == 1
        assert set(MigrationContext.configure(connection).get_current_heads()) == {"20261112_0006"}
        assert connection.scalar(text(
            "SELECT relrowsecurity FROM pg_class WHERE oid='proof_upload_operations'::regclass"
        )) is True
