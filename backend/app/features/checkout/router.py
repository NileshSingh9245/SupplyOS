from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import DomainError, NotFound
from app.features.checkout import service
from app.features.checkout.proof import decode_quote
from app.features.checkout.schemas import CheckoutCreate, QuoteCreate, QuoteOut
from app.features.orders.router import OrderOut, _load_full
from app.infrastructure.db.models.order import Order
from app.shared import idempotency
from app.shared.audit import audit
from app.shared.deps import get_current_user, get_db, lock_current_user
from app.shared.private_route import PrivateInputRoute

router = APIRouter(tags=["customer-checkout"], route_class=PrivateInputRoute)


class CheckoutOut(OrderOut):
    currency_code: str
    quote_id: uuid.UUID


def no_query(request: Request) -> None:
    if request.query_params:
        raise DomainError("Checkout requests do not accept query authority")


@router.post("/order-quotes", response_model=QuoteOut, status_code=201)
async def create_quote(payload: QuoteCreate, request: Request,
                       key: Annotated[uuid.UUID, Header(alias="X-Idempotency-Key")],
                       db: AsyncSession = Depends(get_db)):
    no_query(request)
    user = await lock_current_user(request, db)
    await service.customer_context(db, user)
    claim = await idempotency.claim(db, tenant_id=user.tenant_id, actor_id=user.id,
                                    operation="orders.quote", key=key, payload=payload.model_dump())
    if claim.response_body is not None:
        await get_current_user(request, db)
        return claim.response_body
    result = await service.quote(db, user=user, request=payload, identity=key, secret=get_settings().jwt_secret)
    body = result.model_dump(mode="json")
    idempotency.remember(claim, response=result, status_code=201, resource_type="order_quote", resource_id=key)
    await audit(db, tenant_id=user.tenant_id, actor_id=user.id, actor_email=user.email,
                action="checkout.quote", resource_type="order_quote",
                resource_id=str(key), meta={"warehouse_id": str(payload.warehouse_id)})
    await db.flush()
    await get_current_user(request, db)
    await db.commit()
    return body


@router.post("/orders/checkout", response_model=CheckoutOut, status_code=201)
async def place_order(payload: CheckoutCreate, request: Request,
                      key: Annotated[uuid.UUID, Header(alias="X-Idempotency-Key")],
                      db: AsyncSession = Depends(get_db)):
    no_query(request)
    user = await lock_current_user(request, db)
    await service.customer_context(db, user)
    accepted = decode_quote(payload.quote_proof, secret=get_settings().jwt_secret)
    service.authorize_claim(accepted, user)
    if key != payload.quote_id or accepted.id != payload.quote_id:
        raise DomainError("Checkout must retain its accepted quote request identity")
    claim = await idempotency.claim(db, tenant_id=user.tenant_id, actor_id=user.id,
                                    operation="orders.checkout", key=key, payload=payload.model_dump())
    if claim.response_body is not None:
        visible = await db.scalar(select(Order.id).where(Order.id == claim.resource_id,
                                                         Order.tenant_id == user.tenant_id,
                                                         Order.customer_id == user.customer_id))
        if visible is None:
            raise NotFound("Order not found")
        await get_current_user(request, db)
        return claim.response_body
    row = await service.checkout(db, user=user, claim=accepted)
    await db.flush()
    result = OrderOut.model_validate(await _load_full(db, row))
    values = {**result.model_dump(), "currency_code": row.meta["checkout_currency"], "quote_id": accepted.id}
    checkout = CheckoutOut(**values)
    body = checkout.model_dump(mode="json")
    idempotency.remember(claim, response=checkout, status_code=201, resource_type="order", resource_id=row.id)
    await audit(db, tenant_id=user.tenant_id, actor_id=user.id, actor_email=user.email,
                action="checkout.place", resource_type="order", resource_id=str(row.id))
    await db.flush()
    await get_current_user(request, db)
    await db.commit()
    return body
