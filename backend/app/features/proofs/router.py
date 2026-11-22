"""Authenticated proof upload/read; no public media directory."""
from __future__ import annotations

import hashlib
from asyncio import to_thread
import uuid
from datetime import datetime
from typing import Literal
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import get_settings
from app.core.database import get_db
from app.core.enums import Role
from app.core.exceptions import Conflict, DomainError, Forbidden, NotFound
from app.features.proofs import service
from app.infrastructure.db.models.order import Delivery, Order
from app.infrastructure.db.models.proof import DeliveryProof, ProofUploadOperation
from app.infrastructure.storage.contracts import (
    StorageConflict, StorageIntegrityError, StorageUnavailable, StorageWriteUncertain,
)
from app.infrastructure.storage.proof_store import ProofStore, get_proof_store
from app.shared.audit import audit
from app.shared.deps import get_current_user, lock_current_user, require_roles
from app.shared.schemas import ORMModel

router = APIRouter(tags=["delivery_proofs"])
require_proof_writer = require_roles(Role.SUPER_ADMIN, Role.WAREHOUSE_MANAGER, Role.DELIVERY_PARTNER)


class ProofOut(ORMModel):
    id: uuid.UUID
    delivery_id: uuid.UUID
    kind: str
    mime_type: str
    size_bytes: int
    created_at: datetime
    url: str


async def visible_delivery(db: AsyncSession, user, delivery_id: uuid.UUID, *, lock=False) -> Delivery:
    statement = select(Delivery).where(
        Delivery.id == delivery_id, Delivery.tenant_id == user.tenant_id,
    ).execution_options(populate_existing=True)
    if lock:
        statement = statement.with_for_update()
    delivery = (await db.execute(statement)).scalar_one_or_none()
    if delivery is None:
        raise NotFound("Delivery not found")
    if user.role == Role.DELIVERY_PARTNER.value and delivery.partner_id != user.id:
        raise Forbidden("Not your delivery")
    if user.role == Role.CUSTOMER.value:
        order = (await db.execute(select(Order.id).where(
            Order.id == delivery.order_id, Order.tenant_id == user.tenant_id,
            Order.customer_id == user.customer_id,
        ))).scalar_one_or_none()
        if order is None:
            raise NotFound("Delivery not found")
    return delivery


@router.post("/deliveries/{delivery_id}/proofs", response_model=ProofOut, status_code=201)
async def upload_proof(
    delivery_id: uuid.UUID, request: Request, kind: Literal["signature", "photo"] = Form(...),
    file: UploadFile = File(...), db: AsyncSession = Depends(get_db), user=Depends(require_proof_writer),
    store: ProofStore = Depends(get_proof_store),
):
    delivery = await visible_delivery(db, user, delivery_id)
    if delivery.completed_at is not None:
        raise Conflict("Completed delivery proofs are immutable")
    try:
        data = await file.read(service.MAX_PROOF_BYTES + 1)
        mime, extension = await to_thread(service.validate_image, data)
    finally:
        await file.close()
    identifier = uuid.uuid4()
    settings = get_settings()
    backend = settings.proof_storage_backend
    operation = ProofUploadOperation(
        id=uuid.uuid4(), tenant_id=user.tenant_id, delivery_id=delivery.id, uploaded_by=user.id,
        kind=kind, object_key=f"{identifier.hex}.{extension}", mime_type=mime,
        size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest(),
        storage_backend=backend, state="reserved",
        storage_origin=settings.supabase_storage_origin if backend == "supabase" else None,
        storage_bucket=settings.supabase_storage_bucket if backend == "supabase" else None,
    )
    try:
        store.check_location(operation)
    except (StorageIntegrityError, StorageUnavailable):
        raise DomainError("Private proof storage is unavailable", code=503) from None
    delivery = await visible_delivery(db, user, delivery_id, lock=True)
    if delivery.completed_at is not None:
        raise Conflict("Completed delivery proofs are immutable")
    db.add(operation)
    # Commit ownership before I/O. Reserved rows may have uncertain external outcomes.
    await db.commit()
    try:
        try:
            stored = await store.create(operation, data)
        except StorageConflict:
            raise Conflict("Private proof object already exists") from None
        except (StorageIntegrityError, StorageUnavailable, StorageWriteUncertain):
            raise DomainError("Private proof upload is unavailable; outcome retained for review", code=503) from None
        current_user = await lock_current_user(request, db)
        if current_user.role not in {
            Role.SUPER_ADMIN.value, Role.WAREHOUSE_MANAGER.value, Role.DELIVERY_PARTNER.value,
        }:
            raise Forbidden("Proof upload is no longer permitted")
        delivery = await visible_delivery(db, current_user, delivery_id, lock=True)
        if delivery.completed_at is not None:
            raise Conflict("Completed delivery proofs are immutable")
        operation = (await db.execute(select(ProofUploadOperation).where(
            ProofUploadOperation.id == operation.id,
            ProofUploadOperation.tenant_id == current_user.tenant_id,
            ProofUploadOperation.uploaded_by == current_user.id,
        ).with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()
        if operation is None or operation.state != "reserved":
            raise Conflict("Proof upload reservation is not valid")
        await get_current_user(request, db)
        if backend == "supabase" and (
            stored is None or stored.key != operation.object_key or stored.operation_id != operation.id
            or not isinstance(stored.object_id, uuid.UUID) or not isinstance(stored.version, uuid.UUID)
        ):
            raise Conflict("Private proof upload identity is invalid")
        proof = DeliveryProof(
            id=identifier, tenant_id=operation.tenant_id, delivery_id=operation.delivery_id,
            uploaded_by=operation.uploaded_by, kind=operation.kind, object_key=operation.object_key,
            mime_type=operation.mime_type, size_bytes=operation.size_bytes, sha256=operation.sha256,
            storage_backend=backend, storage_origin=operation.storage_origin,
            storage_bucket=operation.storage_bucket, upload_operation_id=operation.id,
            provider_object_id=stored.object_id if stored is not None else None,
            provider_version=stored.version if stored is not None else None,
        )
        operation.state = "committed"
        db.add(proof)
        await audit(db, tenant_id=user.tenant_id, actor_id=user.id, actor_email=user.email,
                    action="deliveries.proof_upload", resource_type="delivery_proof", resource_id=str(proof.id),
                    meta={"delivery_id": str(delivery.id), "kind": kind, "size_bytes": len(data)})
        await db.commit()
    except BaseException:
        # Never delete on rollback: a lost COMMIT reply is not proof of no receipt.
        await db.rollback()
        raise
    await db.refresh(proof)
    return ProofOut(id=proof.id, delivery_id=proof.delivery_id, kind=proof.kind, mime_type=proof.mime_type,
                    size_bytes=proof.size_bytes, created_at=proof.created_at, url=f"{service.PROOF_PREFIX}{proof.id}")


@router.get("/delivery-proofs/{proof_id}")
async def read_proof(
    proof_id: uuid.UUID, db: AsyncSession = Depends(get_db), user=Depends(get_current_user),
    store: ProofStore = Depends(get_proof_store),
):
    proof = (await db.execute(select(DeliveryProof).where(
        DeliveryProof.id == proof_id, DeliveryProof.tenant_id == user.tenant_id,
    ))).scalar_one_or_none()
    if proof is None:
        raise NotFound("Proof not found")
    await visible_delivery(db, user, proof.delivery_id)
    data = await service.read_stored_proof(db, proof, store=store)
    extension = "png" if proof.mime_type == "image/png" else "jpg"
    return Response(data, media_type=proof.mime_type, headers={
        "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
        "Content-Disposition": f'inline; filename="proof-{proof.id}.{extension}"',
    })
