"""Pricing management and the customer's minimal effective-price catalog."""
from __future__ import annotations

import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.shared.schemas import ORMModel


class TierCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=60)
    discount_pct: Decimal = Field(ge=0, le=100, max_digits=5, decimal_places=2)


class TierUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    discount_pct: Decimal = Field(ge=0, le=100, max_digits=5, decimal_places=2)


class TierOut(ORMModel):
    id: uuid.UUID
    name: str
    discount_pct: Decimal


class TierAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tier_id: uuid.UUID | None


class ResolvedProduct(ORMModel):
    id: uuid.UUID
    sku: str
    name: str
    unit: str
    price: Decimal
    gst_rate: Decimal


class CatalogProduct(ResolvedProduct):
    currency_code: str
