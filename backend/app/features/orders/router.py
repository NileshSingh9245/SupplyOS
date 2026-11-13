"""Orders API routes."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Body, Depends, Header, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.enums import OrderStatus, Role
from app.core.exceptions import Forbidden, NotFound
from app.features.orders import service as order_service
from app.features.payments.schemas import CollectRequest
from app.infrastructure.db.models.customer import Customer
from app.infrastructure.db.models.order import (
    Order, OrderItem, OrderStatusHistory, Delivery,
)
from app.shared.audit import audit
from app.shared import idempotency
from app.shared.deps import get_current_user, require_admin_or_manager
from app.shared.schemas import ORMModel, Paginated

router = APIRouter(prefix="/orders", tags=["orders"])


class OrderLineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_id: uuid.UUID
    quantity: Decimal = Field(gt=0, max_digits=16, decimal_places=3, allow_inf_nan=False)


class OrderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    customer_id: uuid.UUID | None = None  # required for staff; auto-derived for customer role
    warehouse_id: uuid.UUID
    channel: str = Field(default="app", min_length=1, max_length=20)
    is_credit: bool = False
    payment_mode: Literal["cash", "credit"] | None = None
    scheduled_delivery_date: date | None = None
    delivery_address: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=500)
    items: list[OrderLineIn] = Field(min_length=1, max_length=200)


class OrderItemOut(ORMModel):
    id: uuid.UUID
    product_id: uuid.UUID
    product_sku: str
    product_name: str
    quantity: Decimal
    unit_price: Decimal
    gst_rate: Decimal
    line_subtotal: Decimal
    line_tax: Decimal
    line_total: Decimal


class OrderOut(ORMModel):
    id: uuid.UUID
    order_number: str
    customer_id: uuid.UUID
    warehouse_id: uuid.UUID
    status: str
    channel: str
    subtotal: Decimal
    tax_total: Decimal
    discount_total: Decimal
    grand_total: Decimal
    amount_paid: Decimal
    payment_mode: str
    credit_hold_amount: Decimal
    payment_status: str
    amount_due: Decimal
    scheduled_delivery_date: date | None
    delivery_address: str | None
    notes: str | None
    created_at: datetime
    confirmed_at: datetime | None
    delivered_at: datetime | None
    items: list[OrderItemOut] = Field(default_factory=list)


class OrderHistoryOut(ORMModel):
    id: uuid.UUID
    from_status: str | None
    to_status: str
    actor_id: uuid.UUID | None
    note: str | None
    created_at: datetime


class StatusChangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: str | None = None


class OrderStats(BaseModel):
    total_orders: int
    pending: int
    confirmed: int
    reserved: int
    out_for_delivery: int
    delivered_today: int
    revenue_today: Decimal


async def _load_full(db: AsyncSession, order: Order) -> OrderOut:
    items = (await db.execute(
        select(OrderItem).where(
            OrderItem.order_id == order.id, OrderItem.tenant_id == order.tenant_id,
        ).order_by(OrderItem.created_at)
    )).scalars().all()
    out = OrderOut.model_validate(order)
    out.items = [OrderItemOut.model_validate(i) for i in items]
    return out


def _order_scope(user):
    conditions = [Order.tenant_id == user.tenant_id]
    if user.role == Role.CUSTOMER.value:
        if not user.customer_id:
            raise Forbidden("Customer profile missing")
        conditions.append(Order.customer_id == user.customer_id)
    elif user.role == Role.DELIVERY_PARTNER.value:
        conditions.append(select(Delivery.id).where(
            Delivery.tenant_id == user.tenant_id, Delivery.order_id == Order.id,
            Delivery.partner_id == user.id,
        ).exists())
    elif user.role not in {
        Role.SUPER_ADMIN.value, Role.WAREHOUSE_MANAGER.value, Role.ACCOUNTANT.value,
    }:
        raise Forbidden("Order access is not permitted")
    return conditions


async def _visible_order(db: AsyncSession, user, order_id: uuid.UUID) -> Order:
    order = (await db.execute(select(Order).where(
        Order.id == order_id, *_order_scope(user),
    ))).scalar_one_or_none()
    if not order:
        raise NotFound("Order not found")
    return order


@router.get("", response_model=Paginated[OrderOut])
async def list_orders(
    status: OrderStatus | None = None,
    customer_id: uuid.UUID | None = None,
    warehouse_id: uuid.UUID | None = None,
    q: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    stmt = select(Order).where(*_order_scope(user))
    if status:
        stmt = stmt.where(Order.status == status.value)
    if customer_id:
        stmt = stmt.where(Order.customer_id == customer_id)
    if warehouse_id:
        stmt = stmt.where(Order.warehouse_id == warehouse_id)
    if q:
        stmt = stmt.where(func.lower(Order.order_number).like(f"%{q.lower()}%"))

    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    stmt = stmt.order_by(Order.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    rows = (await db.execute(stmt)).scalars().all()
    outs = [await _load_full(db, o) for o in rows]
    return Paginated(items=outs, total=total, page=page, page_size=page_size)


@router.get("/stats", response_model=OrderStats)
async def order_stats(db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    from datetime import datetime, timezone, timedelta
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow = today + timedelta(days=1)
    scope = _order_scope(user)

    async def _cnt(*conds):
        return (await db.execute(
            select(func.count()).select_from(Order)
            .where(*scope, *conds)
        )).scalar_one()

    total = await _cnt()
    delivered_today = await _cnt(Order.delivered_at >= today, Order.delivered_at < tomorrow)
    revenue = (await db.execute(
        select(func.coalesce(func.sum(Order.grand_total), 0)).where(
            *scope,
            Order.delivered_at >= today, Order.delivered_at < tomorrow,
        )
    )).scalar_one()

    return OrderStats(
        total_orders=total,
        pending=await _cnt(Order.status == OrderStatus.PENDING.value),
        confirmed=await _cnt(Order.status == OrderStatus.CONFIRMED.value),
        reserved=await _cnt(Order.status == OrderStatus.RESERVED.value),
        out_for_delivery=await _cnt(Order.status == OrderStatus.OUT_FOR_DELIVERY.value),
        delivered_today=delivered_today,
        revenue_today=Decimal(str(revenue)),
    )


@router.post("", response_model=OrderOut, status_code=201)
async def create_order(
    payload: OrderCreate,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
    idempotency_key: uuid.UUID | None = Header(default=None, alias="X-Idempotency-Key"),
):
    customer_id = payload.customer_id
    if user.role == Role.CUSTOMER.value:
        if not user.customer_id:
            raise Forbidden("Customer profile missing")
        if customer_id is not None and customer_id != user.customer_id:
            raise Forbidden("Cannot order for another customer")
        customer_id = user.customer_id
    else:
        if user.role not in {Role.SUPER_ADMIN.value, Role.WAREHOUSE_MANAGER.value}:
            raise Forbidden("Order creation is not permitted")
        if customer_id is None:
            raise Forbidden("customer_id is required")

    claim = await idempotency.claim(
        db, tenant_id=user.tenant_id, actor_id=user.id, operation="orders.create",
        key=idempotency_key, payload={"request": payload, "customer_id": customer_id},
    )
    if claim is not None and claim.response_body is not None:
        await _visible_order(db, user, claim.resource_id)
        return OrderOut.model_validate(claim.response_body)
    order = await order_service.create_order(
        db, tenant_id=user.tenant_id, customer_id=customer_id,
        warehouse_id=payload.warehouse_id,
        items=[i.model_dump() for i in payload.items],
        channel=payload.channel, scheduled_delivery_date=payload.scheduled_delivery_date,
        delivery_address=payload.delivery_address, notes=payload.notes,
        created_by=user.id, is_credit=payload.is_credit, payment_mode=payload.payment_mode,
    )
    await audit(
        db, tenant_id=user.tenant_id, actor_id=user.id, actor_email=user.email,
        action="orders.create", resource_type="order", resource_id=str(order.id),
    )
    await db.flush()
    response = await _load_full(db, order)
    idempotency.remember(
        claim, response=response, status_code=201, resource_type="order", resource_id=order.id,
    )
    await db.commit()
    return response


@router.get("/{order_id}", response_model=OrderOut)
async def get_order(
    order_id: uuid.UUID, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)
):
    o = await _visible_order(db, user, order_id)
    return await _load_full(db, o)


@router.get("/{order_id}/history", response_model=list[OrderHistoryOut])
async def order_history(
    order_id: uuid.UUID, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)
):
    await _visible_order(db, user, order_id)
    return (await db.execute(
        select(OrderStatusHistory).where(
            OrderStatusHistory.tenant_id == user.tenant_id, OrderStatusHistory.order_id == order_id
        ).order_by(OrderStatusHistory.created_at.asc())
    )).scalars().all()


@router.post("/{order_id}/confirm", response_model=OrderOut)
async def confirm(
    order_id: uuid.UUID, db: AsyncSession = Depends(get_db), user=Depends(require_admin_or_manager)
):
    order = await order_service.confirm_order(
        db, order_id=order_id, tenant_id=user.tenant_id, actor_id=user.id
    )
    await audit(db, tenant_id=user.tenant_id, actor_id=user.id, actor_email=user.email,
                action="orders.confirm", resource_type="order", resource_id=str(order.id))
    await db.commit()
    await db.refresh(order)
    return await _load_full(db, order)


@router.post("/{order_id}/reserve", response_model=OrderOut)
async def reserve(
    order_id: uuid.UUID, db: AsyncSession = Depends(get_db), user=Depends(require_admin_or_manager)
):
    order = await order_service.reserve_order(
        db, order_id=order_id, tenant_id=user.tenant_id, actor_id=user.id
    )
    await audit(db, tenant_id=user.tenant_id, actor_id=user.id, actor_email=user.email,
                action="orders.reserve", resource_type="order", resource_id=str(order.id))
    await db.commit()
    await db.refresh(order)
    return await _load_full(db, order)


@router.post("/{order_id}/pick", response_model=OrderOut)
async def pick(order_id: uuid.UUID, db: AsyncSession = Depends(get_db), user=Depends(require_admin_or_manager)):
    order = await order_service.advance_status(
        db, order_id=order_id, tenant_id=user.tenant_id,
        to_status=OrderStatus.PICKED.value, actor_id=user.id,
    )
    await audit(db, tenant_id=user.tenant_id, actor_id=user.id, actor_email=user.email,
                action="orders.pick", resource_type="order", resource_id=str(order.id))
    await db.commit()
    await db.refresh(order)
    return await _load_full(db, order)


@router.post("/{order_id}/pack", response_model=OrderOut)
async def pack(order_id: uuid.UUID, db: AsyncSession = Depends(get_db), user=Depends(require_admin_or_manager)):
    order = await order_service.advance_status(
        db, order_id=order_id, tenant_id=user.tenant_id,
        to_status=OrderStatus.PACKED.value, actor_id=user.id,
    )
    await audit(db, tenant_id=user.tenant_id, actor_id=user.id, actor_email=user.email,
                action="orders.pack", resource_type="order", resource_id=str(order.id))
    await db.commit()
    await db.refresh(order)
    return await _load_full(db, order)


import secrets


def secrets_int() -> int:
    return secrets.randbelow(900_000) + 100_000  # 6-digit OTP


@router.post("/{order_id}/dispatch", response_model=OrderOut)
async def dispatch(order_id: uuid.UUID, db: AsyncSession = Depends(get_db), user=Depends(require_admin_or_manager)):
    order = await order_service.advance_status(
        db, order_id=order_id, tenant_id=user.tenant_id,
        to_status=OrderStatus.OUT_FOR_DELIVERY.value, actor_id=user.id,
    )
    # Create Delivery skeleton if not exists
    exists = (await db.execute(select(Delivery).where(
        Delivery.order_id == order.id, Delivery.tenant_id == user.tenant_id,
    ))).scalar_one_or_none()
    if not exists:
        db.add(Delivery(
            tenant_id=user.tenant_id, order_id=order.id,
            otp_code=f"{secrets_int()}",
        ))
    await audit(db, tenant_id=user.tenant_id, actor_id=user.id, actor_email=user.email,
                action="orders.dispatch", resource_type="order", resource_id=str(order.id))
    await db.commit()
    await db.refresh(order)
    return await _load_full(db, order)


def secrets_int_unused() -> int:  # kept to avoid import churn; use module-level secrets_int
    import secrets as _s
    return _s.randbelow(900_000) + 100_000


@router.post("/{order_id}/deliver", response_model=OrderOut)
async def deliver(
    order_id: uuid.UUID, payload: CollectRequest | None = Body(default=None),
    db: AsyncSession = Depends(get_db), user=Depends(require_admin_or_manager),
    idempotency_key: uuid.UUID | None = Header(default=None, alias="X-Idempotency-Key"),
):
    payload = payload or CollectRequest()
    await _visible_order(db, user, order_id)
    claim = await idempotency.claim(
        db, tenant_id=user.tenant_id, actor_id=user.id, operation="orders.deliver",
        key=idempotency_key, payload={"order_id": order_id, "request": payload},
    )
    if claim is not None and claim.response_body is not None:
        await _visible_order(db, user, claim.resource_id)
        return OrderOut.model_validate(claim.response_body)
    order = await order_service.deliver_order(
        db, order_id=order_id, tenant_id=user.tenant_id, actor_id=user.id,
        actor_role=user.role, actor_email=user.email, **payload.model_dump(),
    )
    await db.flush()
    response = await _load_full(db, order)
    idempotency.remember(
        claim, response=response, status_code=200, resource_type="order", resource_id=order.id,
    )
    await db.commit()
    return response


@router.post("/{order_id}/cancel", response_model=OrderOut)
async def cancel(
    order_id: uuid.UUID, payload: StatusChangeRequest,
    db: AsyncSession = Depends(get_db), user=Depends(require_admin_or_manager)
):
    order = await order_service.cancel_order(
        db, order_id=order_id, tenant_id=user.tenant_id, actor_id=user.id, note=payload.note
    )
    await audit(db, tenant_id=user.tenant_id, actor_id=user.id, actor_email=user.email,
                action="orders.cancel", resource_type="order", resource_id=str(order.id),
                meta={"note": payload.note})
    await db.commit()
    await db.refresh(order)
    return await _load_full(db, order)
