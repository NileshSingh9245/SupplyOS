from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, hide_input_in_errors=True)


class QuoteLine(InputModel):
    product_id: uuid.UUID
    quantity: Decimal = Field(gt=0, max_digits=16, decimal_places=3, allow_inf_nan=False)


class QuoteCreate(InputModel):
    warehouse_id: uuid.UUID
    payment_mode: Literal["cash", "credit"] | None = None
    scheduled_delivery_date: date | None = None
    delivery_address: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=500)
    items: tuple[QuoteLine, ...] = Field(min_length=1, max_length=200)


class QuotedItem(InputModel):
    product_id: uuid.UUID
    sku: str
    name: str
    unit: str
    quantity: Decimal
    unit_price: Decimal
    gst_rate: Decimal
    subtotal: Decimal
    tax: Decimal
    total: Decimal


class PriceSnapshot(InputModel):
    currency_code: str = Field(pattern=r"^[A-Z]{3}$")
    payment_mode: Literal["cash", "credit"]
    items: tuple[QuotedItem, ...]
    subtotal: Decimal
    tax_total: Decimal
    grand_total: Decimal


class Availability(InputModel):
    product_id: uuid.UUID
    required_quantity: Decimal
    available_quantity: Decimal


class QuoteOut(PriceSnapshot):
    id: uuid.UUID
    quote_proof: str
    warehouse_id: uuid.UUID
    expires_at: datetime
    availability: tuple[Availability, ...]
    blockers: tuple[Literal["insufficient_stock", "credit_limit_exceeded"], ...]


class QuoteClaim(InputModel):
    id: uuid.UUID
    actor_id: uuid.UUID
    tenant_id: uuid.UUID
    customer_id: uuid.UUID
    authorization_epoch: int = Field(ge=0)
    expires_at: datetime
    request: QuoteCreate
    prices_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class CheckoutCreate(InputModel):
    quote_id: uuid.UUID
    quote_proof: str = Field(min_length=1, max_length=32768, repr=False, exclude=False)
