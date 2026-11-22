"""Private proof image integrity and delivery-bound references."""
from __future__ import annotations

import io
import uuid
import warnings
from PIL import Image, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.exceptions import Conflict, DomainError, NotFound
from app.infrastructure.db.models.order import Delivery, Order
from app.infrastructure.db.models.proof import DeliveryProof, ProofUploadOperation
from app.infrastructure.storage.contracts import StorageIntegrityError, StorageUnavailable
from app.infrastructure.storage.proof_store import ProofStore, get_proof_store

MAX_PROOF_BYTES = 5 * 1024 * 1024
MAX_PIXELS = 20_000_000
PROOF_PREFIX = "/api/v1/delivery-proofs/"


def validate_image(data: bytes) -> tuple[str, str]:
    if not data or len(data) > MAX_PROOF_BYTES:
        raise DomainError("Proof image must be nonempty and at most 5 MiB")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                if image.format not in {"PNG", "JPEG"} or image.width * image.height > MAX_PIXELS:
                    raise DomainError("Proof must be a bounded PNG or JPEG image")
                format_name = image.format
                image.verify()
            with Image.open(io.BytesIO(data)) as image:
                image.load()
    except DomainError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, Image.DecompressionBombWarning, Image.DecompressionBombError):
        raise DomainError("Proof image is invalid") from None
    return ("image/png", "png") if format_name == "PNG" else ("image/jpeg", "jpg")


async def lock_delivery_order(
    db: AsyncSession, *, tenant_id: uuid.UUID, delivery_id: uuid.UUID,
) -> Order:
    """Protect parent state before Delivery without reversing financial locks."""
    order_id = (await db.execute(select(Delivery.order_id).where(
        Delivery.id == delivery_id, Delivery.tenant_id == tenant_id,
    ))).scalar_one_or_none()
    if order_id is None:
        raise NotFound("Delivery not found")
    order = (await db.execute(select(Order).where(
        Order.id == order_id, Order.tenant_id == tenant_id,
    ).with_for_update(key_share=True).execution_options(populate_existing=True))).scalar_one_or_none()
    if order is None:
        raise NotFound("Delivery not found")
    return order


async def validate_proof_ownership(
    db: AsyncSession, proof: DeliveryProof, *, lock: bool = False,
) -> None:
    if proof.upload_operation_id is not None:
        statement = select(ProofUploadOperation).where(
            ProofUploadOperation.id == proof.upload_operation_id,
            ProofUploadOperation.tenant_id == proof.tenant_id,
            ProofUploadOperation.delivery_id == proof.delivery_id,
            ProofUploadOperation.uploaded_by == proof.uploaded_by,
            ProofUploadOperation.kind == proof.kind,
            ProofUploadOperation.object_key == proof.object_key,
            ProofUploadOperation.mime_type == proof.mime_type,
            ProofUploadOperation.size_bytes == proof.size_bytes,
            ProofUploadOperation.sha256 == proof.sha256,
            ProofUploadOperation.storage_backend == proof.storage_backend,
            ProofUploadOperation.storage_origin == proof.storage_origin,
            ProofUploadOperation.storage_bucket == proof.storage_bucket,
            ProofUploadOperation.state == "committed",
        )
        if lock:
            statement = statement.with_for_update(read=True)
        operation = (await db.execute(statement)).scalar_one_or_none()
        if operation is None:
            raise Conflict("Proof upload ownership is invalid")


async def read_stored_proof(
    db: AsyncSession, proof: DeliveryProof, *, store: ProofStore | None = None,
) -> bytes:
    await validate_proof_ownership(db, proof)
    try:
        return await (store or get_proof_store()).read(proof)
    except (StorageIntegrityError, StorageUnavailable):
        raise Conflict("Private proof identity or integrity is unavailable") from None


async def validate_delivery_proofs(
    db: AsyncSession, *, tenant_id: uuid.UUID, delivery_id: uuid.UUID,
    signature_url: str | None, proof_photo_url: str | None,
) -> None:
    for kind, reference in (("signature", signature_url), ("photo", proof_photo_url)):
        if not reference or not reference.startswith(PROOF_PREFIX):
            raise Conflict("Completion requires uploaded private signature and photo proofs")
        try:
            identifier = uuid.UUID(reference[len(PROOF_PREFIX):])
        except ValueError:
            raise Conflict("Proof reference is invalid") from None
        proof = (await db.execute(select(DeliveryProof).where(
            DeliveryProof.id == identifier, DeliveryProof.tenant_id == tenant_id,
            DeliveryProof.delivery_id == delivery_id, DeliveryProof.kind == kind,
        ))).scalar_one_or_none()
        if proof is None:
            raise Conflict("Proof does not belong to this delivery")
        await read_stored_proof(db, proof)
