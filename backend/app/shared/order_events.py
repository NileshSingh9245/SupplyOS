"""Append caller-owned order history without transaction-clock ties or feature cycles."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models.order import Order, OrderStatusHistory


async def record_status(
    db: AsyncSession, *, order: Order, to_status: str, actor_id: uuid.UUID | None,
    note: str | None = None,
) -> OrderStatusHistory:
    """Caller owns the new order or holds its row lock; this helper never transitions/commits."""
    with db.no_autoflush:
        latest = (await db.execute(select(func.max(OrderStatusHistory.created_at)).where(
            OrderStatusHistory.order_id == order.id,
            OrderStatusHistory.tenant_id == order.tenant_id,
        ))).scalar_one()
    pending = [event.created_at for event in db.new if isinstance(event, OrderStatusHistory)
               and event.order_id == order.id and event.tenant_id == order.tenant_id
               and event.created_at is not None]
    previous = max([latest, *pending] if latest is not None else pending, default=None)
    created_at = datetime.now(timezone.utc)
    if previous is not None:
        created_at = max(created_at, previous + timedelta(microseconds=1))
    event = OrderStatusHistory(
        tenant_id=order.tenant_id, order_id=order.id, from_status=order.status,
        to_status=to_status, actor_id=actor_id, note=note, created_at=created_at,
    )
    db.add(event)
    return event
