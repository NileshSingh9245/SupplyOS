"""Tenant settings — business rules editable by Super Admin from the dashboard.

All numbers are in INR unless overridden. Every rule below has a sensible default
and can be changed via `PATCH /api/v1/settings`. Front-ends must read these on
first load and re-fetch on `settings.updated` websocket event (future).
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.infrastructure.db.models.tenant import Tenant
from app.shared.audit import audit
from app.shared.deps import get_current_user, require_admin

router = APIRouter(prefix="/settings", tags=["settings"])


DEFAULTS: dict[str, Any] = {
    # Currency / locale
    "currency_code": "INR",
    "currency_symbol": "₹",
    "locale": "en-IN",
    "money_rounding": "round_half_up",  # round_half_up | bankers | floor | ceil
    "money_decimals": 2,

    # Tax (Indian GST)
    "default_gst_rate": "5.00",
    "gst_type": "cgst_sgst",  # cgst_sgst (intra-state) | igst (inter-state)
    "gstin_required_for_credit": True,
    "hsn_required": False,

    # Pricing
    "allow_below_base_price": False,
    "min_margin_pct": "0.00",
    "price_list_priority": ["customer_override", "tier_discount", "base_price"],

    # Credit / finance
    "default_credit_limit": "0.00",
    "credit_warning_threshold_pct": "80.00",
    "block_orders_over_credit": True,
    "auto_send_payment_reminder_days": 7,

    # Order rules
    "auto_confirm_orders": False,
    "auto_reserve_on_confirm": True,
    "reservation_ttl_hours": 48,
    "allow_partial_fulfillment": True,
    "cancellation_window_minutes": 60,

    # Delivery
    "otp_length": 6,
    "require_photo_proof": True,
    "require_signature": False,
    "delivery_priority_default": 5,

    # Inventory
    "low_stock_threshold_default": 10,
    "reorder_level_default": 50,
    "dead_stock_days": 90,
    "warehouse_selection": "nearest_first",  # nearest_first | most_stock_first

    # AI supervisor cadence
    "ai_analyze_interval_minutes": 15,
    "ai_summary_interval_minutes": 60,
    "ai_enabled": True,
}


class SettingsOut(BaseModel):
    tenant_id: str
    company_name: str
    currency_code: str
    currency_symbol: str
    locale: str
    values: dict[str, Any]
    applied_keys: list[str] | None = None


class SettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # Free-form patch — only known keys will be applied
    patch: dict[str, Any] = Field(default_factory=dict)


def _effective(tenant: Tenant) -> dict[str, Any]:
    merged = dict(DEFAULTS)
    merged.update(tenant.settings or {})
    # Currency values come from tenant top-level too
    merged["currency_code"] = tenant.currency or merged["currency_code"]
    return merged


@router.get("", response_model=SettingsOut)
async def get_settings(db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    t = (await db.execute(select(Tenant).where(Tenant.id == user.tenant_id))).scalar_one()
    values = _effective(t)
    return SettingsOut(
        tenant_id=str(t.id),
        company_name=t.name,
        currency_code=values["currency_code"],
        currency_symbol=values["currency_symbol"],
        locale=values["locale"],
        values=values,
    )


@router.patch("", response_model=SettingsOut)
async def update_settings(
    payload: SettingsUpdate, db: AsyncSession = Depends(get_db),
    user=Depends(require_admin),
):
    t = (await db.execute(select(Tenant).where(Tenant.id == user.tenant_id))).scalar_one()
    current = dict(t.settings or {})
    # Whitelist: only allow known keys
    applied: dict[str, Any] = {}
    for k, v in payload.patch.items():
        if k in DEFAULTS:
            current[k] = v
            applied[k] = v
        elif k == "company_name" and isinstance(v, str) and v.strip():
            t.name = v.strip()
            applied[k] = v
        elif k == "currency_code" and isinstance(v, str):
            t.currency = v.strip().upper()
            applied[k] = v
    t.settings = current
    await audit(
        db, tenant_id=t.id, actor_id=user.id, actor_email=user.email,
        action="settings.update", resource_type="tenant", resource_id=str(t.id),
        meta={"applied_keys": list(applied.keys())},
    )
    await db.commit()
    await db.refresh(t)
    values = _effective(t)
    return SettingsOut(
        tenant_id=str(t.id), company_name=t.name,
        currency_code=values["currency_code"], currency_symbol=values["currency_symbol"],
        locale=values["locale"], values=values, applied_keys=list(applied.keys()),
    )


@router.get("/defaults")
async def defaults(user=Depends(get_current_user)):
    """Read-only defaults for reference in the dashboard."""
    return {"defaults": DEFAULTS}
