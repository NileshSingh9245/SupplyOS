"""Private byte publication rechecks authorization and exact receipts after storage I/O."""
from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.infrastructure.db.models.order import Delivery, Order
from app.infrastructure.db.models.proof import DeliveryProof, ProofUploadOperation
from app.infrastructure.db.models.user import RefreshToken, User
from test_command_authorization import (
    Actor, PrivateText, _success, _wait_for_lock, auth_change, case, clock_expiry,
    financial_db, require_owned_environment, snapshot, unchanged,
)  # noqa: F401 shared identified owned database and scoped ASGI fixtures
from test_delivery_proofs import png

pytestmark = pytest.mark.integration


def _proof(case):
    case.prepare("read")
    created = _success(asyncio.run(case.upload()), 201)
    case.path, case.payload = created["url"].removeprefix("/api/v1"), {}
    return created


@pytest.mark.parametrize("change,expected", (
    ("inactive", 401), ("role", 401), ("epoch", 401), ("revoked", 401),
    ("session_expired", 401), ("access_expired", 401), ("session_clock_expired", 401),
    ("reassigned", 403), ("customer_unlinked", 403), ("proof_changed", 409), ("journal_changed", 409),
))
def test_private_read_reacquires_current_auth_access_and_receipt_after_unlocked_io(
    case, monkeypatch, change, expected,
):
    _proof(case)
    if change == "customer_unlinked":
        case.actor = case.customer
    before = snapshot(case)
    read = case.store.read
    advance = clock_expiry(monkeypatch, change) if change in {"access_expired", "session_clock_expired"} else None
    observed = False

    async def changed_after_verified_bytes(proof):
        nonlocal observed
        data = await read(proof)
        observed = True
        with Session(case.engine) as db:
            # Returning a byte buffer does not justify retaining auth/business locks during I/O.
            for statement in (
                select(User.id).where(User.id == case.actor.id),
                select(RefreshToken.id).where(RefreshToken.session_id == case.actor.session_id),
                select(Order.id).where(Order.id == case.order_id),
                select(Delivery.id).where(Delivery.id == case.delivery_id),
                select(DeliveryProof.id).where(DeliveryProof.id == proof.id),
                select(ProofUploadOperation.id).where(ProofUploadOperation.id == proof.upload_operation_id),
            ):
                db.execute(statement.with_for_update(nowait=True))
            if change == "reassigned":
                db.execute(update(Delivery).where(Delivery.id == case.delivery_id).values(
                    partner_id=case.other_partner_id,
                ))
            elif change == "customer_unlinked":
                db.execute(update(User).where(User.id == case.customer.id).values(customer_id=None))
            elif change == "proof_changed":
                db.execute(update(DeliveryProof).where(DeliveryProof.id == proof.id).values(sha256="0" * 64))
            elif change == "journal_changed":
                db.execute(update(ProofUploadOperation).where(
                    ProofUploadOperation.id == proof.upload_operation_id,
                ).values(state="reserved"))
            elif advance is None:
                db.execute(auth_change(case.actor, change))
            db.commit()
        if advance is not None:
            advance()
        return data

    case.store.read = changed_after_verified_bytes
    response = asyncio.run(case.request(method="GET"))
    assert observed and response.status_code == expected
    assert response.content != png()
    if case.actor.token in response.text:
        pytest.fail("Private read rejection exposed a session credential", pytrace=False)
    unchanged(case, before, ignore={
        "deliveries" if change == "reassigned" else "delivery_proofs" if change == "proof_changed" else
        "proof_upload_operations" if change == "journal_changed" else "unused",
    })
    with Session(case.engine) as db:
        assert db.scalar(select(DeliveryProof.id).where(DeliveryProof.tenant_id == case.tenant_id)) is not None
        assert db.scalar(select(ProofUploadOperation.id).where(ProofUploadOperation.tenant_id == case.tenant_id)) is not None


@pytest.mark.parametrize("stage", ("user", "session", "order", "delivery", "proof", "journal"))
@pytest.mark.parametrize("expiry", ("access_expired", "session_clock_expired"))
def test_private_byte_return_checks_auth_after_every_post_io_row_wait(case, monkeypatch, stage, expiry):
    created = _proof(case)
    before = snapshot(case)
    advance = clock_expiry(monkeypatch, expiry)
    read = case.store.read
    ready, release = threading.Event(), threading.Event()
    with Session(case.engine) as db:
        proof = db.scalar(select(DeliveryProof).where(DeliveryProof.tenant_id == case.tenant_id))
        proof_id, journal_id = proof.id, proof.upload_operation_id
    statements = {
        "user": select(User.id).where(User.id == case.actor.id),
        "session": select(RefreshToken.id).where(RefreshToken.session_id == case.actor.session_id),
        "order": select(Order.id).where(Order.id == case.order_id),
        "delivery": select(Delivery.id).where(Delivery.id == case.delivery_id),
        "proof": select(DeliveryProof.id).where(DeliveryProof.id == proof_id),
        "journal": select(ProofUploadOperation.id).where(ProofUploadOperation.id == journal_id),
    }

    async def paused_after_verified_bytes(proof):
        data = await read(proof)
        ready.set()
        assert await asyncio.to_thread(release.wait, 10)
        return data

    case.store.read = paused_after_verified_bytes
    with case.engine.connect() as holder, ThreadPoolExecutor(max_workers=1) as workers:
        pending = workers.submit(lambda: asyncio.run(case.request(method="GET")))
        try:
            assert ready.wait(timeout=10)
            holder.execute(statements[stage].with_for_update())
            holder_pid = holder.scalar(select(func.pg_backend_pid()))
            release.set()
            _wait_for_lock(case, holder_pid)
            advance()
            holder.rollback()
            response = pending.result(timeout=20)
        finally:
            release.set()
            holder.rollback()
    assert response.status_code == 401 and response.content != png()
    assert created["url"].endswith(str(proof_id))
    unchanged(case, before)


@pytest.mark.parametrize("role", ("unknown_signed_role", "", "CUSTOMER"))
def test_unknown_persisted_and_signed_role_cannot_fall_through_private_access(case, role):
    from app.core.security import create_access_token

    _proof(case)
    with case.engine.begin() as connection:
        connection.execute(update(User).where(User.id == case.actor.id).values(role=role))
    token, _ = create_access_token(
        str(case.actor.id), str(case.tenant_id), role,
        session_id=case.actor.session_id, session_version=0,
    )
    case.actor = Actor(case.actor.id, case.actor.session_id, PrivateText(token))

    async def forbidden_storage(*args, **kwargs):
        pytest.fail("An unknown role reached private storage", pytrace=False)

    case.store.read = forbidden_storage
    response = asyncio.run(case.request(method="GET"))
    assert response.status_code == (401 if not role else 403)
    assert response.content != png()


@pytest.mark.parametrize("operation", ("deliver", "complete"))
@pytest.mark.parametrize("expiry", ("access_expired", "session_clock_expired"))
def test_completion_private_proof_io_cannot_outlive_auth_and_commit_financial_effects(
    case, monkeypatch, operation, expiry,
):
    case.prepare(operation)
    before = snapshot(case)
    advance = clock_expiry(monkeypatch, expiry)
    read = case.store.read
    observed = False

    async def expired_during_integrity_read(proof):
        nonlocal observed
        data = await read(proof)
        observed = True
        advance()
        return data

    case.store.read = expired_during_integrity_read
    assert case.call().status_code == 401
    assert observed
    unchanged(case, before)


def test_completed_private_evidence_remains_readable_without_new_receipts_or_resets(case):
    case.prepare("complete")
    result = _success(case.call())
    assert result["completed_at"] is not None
    before = snapshot(case)
    for reference in case.references.values():
        response = asyncio.run(case.request(
            path=reference.removeprefix("/api/v1"), payload={}, method="GET", actor=case.customer,
        ))
        assert response.status_code == 200 and response.content == png()
        assert response.headers["Cache-Control"] == "private, no-store"
        assert response.headers["X-Content-Type-Options"] == "nosniff"
    unchanged(case, before)


@pytest.mark.parametrize("operation", ("create", "payment", "deliver", "complete"))
def test_resolved_replay_rechecks_auth_after_idempotency_wait(case, monkeypatch, operation):
    from app.infrastructure.db.models.idempotency import IdempotencyRecord
    from test_command_authorization import held_command

    case.prepare(operation)
    _success(case.call(), 201 if operation in {"create", "payment"} else 200)
    before = snapshot(case)
    advance = clock_expiry(monkeypatch, "access_expired")
    name = {"create": "orders.create", "payment": "payments.record", "deliver": "orders.deliver",
            "complete": "deliveries.complete"}[operation]
    with held_command(case, select(IdempotencyRecord.id).where(
        IdempotencyRecord.tenant_id == case.tenant_id, IdempotencyRecord.actor_id == case.actor.id,
        IdempotencyRecord.operation == name, IdempotencyRecord.key == case.key,
    )) as (holder, pending):
        advance()
        holder.rollback()
        response = pending.result(timeout=20)
    assert response.status_code == 401
    unchanged(case, before)
