"""AI Supervisor — rule-based analyzers + optional Claude summarization.

Runs on demand via `/ai/analyze` and periodically via a background task.
Persists alerts to `ai_alerts`.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import AlertCategory, AlertSeverity, StockMovementType
from app.infrastructure.db.models.ai_alert import AIAlert
from app.infrastructure.db.models.customer import Customer
from app.infrastructure.db.models.inventory import InventoryItem, StockMovement
from app.infrastructure.db.models.order import Order, OrderItem
from app.infrastructure.db.models.product import Product
from app.infrastructure.external.ai_provider import get_ai_provider


async def _persist_alert(
    db: AsyncSession, *, tenant_id: uuid.UUID, category: AlertCategory,
    severity: AlertSeverity, title: str, message: str,
    action_hint: str | None = None, resource_type: str | None = None,
    resource_id: str | None = None, meta: dict | None = None,
) -> AIAlert:
    # Dedupe: don't recreate the same undismissed alert for same resource within 6 hours
    if resource_id:
        recent_cutoff = datetime.now(timezone.utc) - timedelta(hours=6)
        exists = (await db.execute(
            select(AIAlert).where(
                AIAlert.tenant_id == tenant_id,
                AIAlert.category == category.value,
                AIAlert.title == title,
                AIAlert.resource_id == resource_id,
                AIAlert.is_dismissed == False,  # noqa
                AIAlert.created_at > recent_cutoff,
            ).limit(1)
        )).scalar_one_or_none()
        if exists:
            return exists

    alert = AIAlert(
        tenant_id=tenant_id, category=category.value, severity=severity.value,
        title=title, message=message, action_hint=action_hint,
        resource_type=resource_type, resource_id=resource_id, meta=meta or {},
    )
    db.add(alert)
    return alert


async def analyze_low_stock(db: AsyncSession, tenant_id: uuid.UUID) -> int:
    """Rule: available_qty <= low_stock_threshold for any active product."""
    stmt = (
        select(
            Product.id, Product.name, Product.sku, Product.low_stock_threshold, Product.reorder_level,
            func.coalesce(func.sum(InventoryItem.quantity - InventoryItem.reserved_qty), 0).label("avail"),
        )
        .join(InventoryItem, InventoryItem.product_id == Product.id, isouter=True)
        .where(Product.tenant_id == tenant_id, Product.is_active == True)  # noqa
        .group_by(Product.id, Product.name, Product.sku, Product.low_stock_threshold, Product.reorder_level)
    )
    rows = (await db.execute(stmt)).all()
    created = 0
    for pid, name, sku, threshold, reorder, avail in rows:
        avail_d = Decimal(str(avail))
        thr_d = Decimal(str(threshold))
        if avail_d <= 0:
            await _persist_alert(
                db, tenant_id=tenant_id, category=AlertCategory.INVENTORY,
                severity=AlertSeverity.CRITICAL,
                title=f"Out of stock: {name}",
                message=f"{name} ({sku}) has zero available stock.",
                action_hint=f"Reorder at least {reorder or threshold} units immediately.",
                resource_type="product", resource_id=str(pid),
                meta={"available": str(avail_d), "sku": sku},
            )
            created += 1
        elif avail_d <= thr_d:
            await _persist_alert(
                db, tenant_id=tenant_id, category=AlertCategory.INVENTORY,
                severity=AlertSeverity.WARNING,
                title=f"Low stock: {name}",
                message=f"{name} ({sku}) available: {avail_d}. Threshold: {thr_d}.",
                action_hint=f"Consider reordering {reorder or threshold} units.",
                resource_type="product", resource_id=str(pid),
                meta={"available": str(avail_d), "sku": sku},
            )
            created += 1
    return created


async def analyze_dead_stock(db: AsyncSession, tenant_id: uuid.UUID) -> int:
    """Rule: quantity > 0 AND no outbound movement in ≥ 90 days."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=90)

    # Products with positive on-hand
    on_hand = (await db.execute(
        select(Product.id, Product.name, Product.sku,
               func.sum(InventoryItem.quantity).label("total"))
        .join(InventoryItem, InventoryItem.product_id == Product.id)
        .where(Product.tenant_id == tenant_id)
        .group_by(Product.id, Product.name, Product.sku)
        .having(func.sum(InventoryItem.quantity) > 0)
    )).all()

    created = 0
    for pid, name, sku, total in on_hand:
        recent = (await db.execute(
            select(func.count()).select_from(StockMovement).where(
                StockMovement.tenant_id == tenant_id,
                StockMovement.product_id == pid,
                StockMovement.movement_type == StockMovementType.OUTBOUND.value,
                StockMovement.created_at > cutoff,
            )
        )).scalar_one()
        if recent == 0:
            await _persist_alert(
                db, tenant_id=tenant_id, category=AlertCategory.INVENTORY,
                severity=AlertSeverity.INFO,
                title=f"Dead stock: {name}",
                message=f"{name} ({sku}) has {total} units on hand with no outbound movement in 90+ days.",
                action_hint="Consider discount pricing or return to supplier.",
                resource_type="product", resource_id=str(pid),
                meta={"on_hand": str(total)},
            )
            created += 1
    return created


async def analyze_credit_risk(db: AsyncSession, tenant_id: uuid.UUID) -> int:
    """Rule: customer.outstanding / credit_limit > 0.8"""
    rows = (await db.execute(
        select(Customer).where(
            Customer.tenant_id == tenant_id, Customer.is_active == True,  # noqa
            Customer.credit_limit > 0,
        )
    )).scalars().all()
    created = 0
    for c in rows:
        limit = Decimal(str(c.credit_limit))
        out = Decimal(str(c.outstanding))
        if limit <= 0:
            continue
        ratio = out / limit
        if ratio > Decimal("1.0"):
            sev, title = AlertSeverity.CRITICAL, f"Over credit limit: {c.name}"
        elif ratio > Decimal("0.8"):
            sev, title = AlertSeverity.WARNING, f"Approaching credit limit: {c.name}"
        else:
            continue
        await _persist_alert(
            db, tenant_id=tenant_id, category=AlertCategory.FINANCE, severity=sev,
            title=title,
            message=f"{c.name} outstanding ₹{out:.2f} / limit ₹{limit:.2f} ({ratio*100:.0f}%).",
            action_hint="Follow up for payment or increase credit review.",
            resource_type="customer", resource_id=str(c.id),
            meta={"outstanding": str(out), "credit_limit": str(limit), "ratio": f"{ratio:.2f}"},
        )
        created += 1
    return created


async def peak_hour_summary(db: AsyncSession, tenant_id: uuid.UUID) -> dict[str, Any]:
    """Return revenue distribution by hour of day for the last 30 days."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    rows = (await db.execute(
        select(
            func.extract("hour", Order.delivered_at).label("hr"),
            func.sum(Order.grand_total).label("revenue"),
            func.count(Order.id).label("orders"),
        ).where(
            Order.tenant_id == tenant_id,
            Order.delivered_at >= cutoff,
        ).group_by("hr").order_by("hr")
    )).all()
    return {"buckets": [{"hour": int(r.hr), "revenue": str(r.revenue), "orders": r.orders} for r in rows]}


async def run_all_analyses(db: AsyncSession, tenant_id: uuid.UUID) -> dict[str, int]:
    """Runs all rule-based analyzers. Returns count of alerts created per rule."""
    result = {
        "low_stock": await analyze_low_stock(db, tenant_id),
        "dead_stock": await analyze_dead_stock(db, tenant_id),
        "credit_risk": await analyze_credit_risk(db, tenant_id),
    }
    await db.commit()
    return result


async def claude_summarize(db: AsyncSession, tenant_id: uuid.UUID) -> str | None:
    """Aggregate today's metrics and ask Claude for a human summary."""
    provider = get_ai_provider()
    if not provider:
        return None
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    orders_24h = (await db.execute(
        select(func.count(), func.coalesce(func.sum(Order.grand_total), 0)).where(
            Order.tenant_id == tenant_id, Order.created_at >= since
        )
    )).one()
    delivered_24h = (await db.execute(
        select(func.count(), func.coalesce(func.sum(Order.grand_total), 0)).where(
            Order.tenant_id == tenant_id, Order.delivered_at >= since
        )
    )).one()
    low_stock = (await db.execute(
        select(func.count()).select_from(AIAlert).where(
            AIAlert.tenant_id == tenant_id, AIAlert.category == "inventory",
            AIAlert.severity.in_(["warning", "critical"]),
            AIAlert.is_dismissed == False,  # noqa
        )
    )).scalar_one()

    metrics = {
        "orders_placed_24h": orders_24h[0],
        "orders_revenue_24h": str(orders_24h[1]),
        "delivered_24h": delivered_24h[0],
        "delivered_revenue_24h": str(delivered_24h[1]),
        "active_inventory_alerts": low_stock,
    }
    system = (
        "You are the AI Supervisor for a wholesale distribution business. "
        "You produce concise, actionable executive summaries. "
        "Always be specific with numbers. Output must be plain text, ≤ 4 sentences."
    )
    prompt = (
        "Given these 24-hour operational metrics, produce an executive summary "
        "with one specific recommendation. Metrics JSON:\n" + json.dumps(metrics)
    )
    try:
        text = await provider.analyze(system_prompt=system, user_prompt=prompt, max_tokens=400)
    except Exception as e:  # never let AI failure block the app
        import traceback
        tb = traceback.format_exc()
        print(f"[ai-summary-error]\n{tb}", flush=True)
        text = f"AI summary unavailable: {e.__class__.__name__}: {e}"

    await _persist_alert(
        db, tenant_id=tenant_id, category=AlertCategory.OPERATIONS,
        severity=AlertSeverity.INFO,
        title="Daily AI Executive Summary",
        message=text[:1000],
        action_hint=None, resource_type="tenant", resource_id=str(tenant_id),
        meta=metrics,
    )
    await db.commit()
    return text
