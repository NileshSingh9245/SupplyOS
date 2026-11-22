"""Validated collection values shared by both delivery finalization routes."""
from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class CollectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cash_amount: Decimal = Field(
        default=Decimal("0"), ge=0, max_digits=14, decimal_places=2, allow_inf_nan=False,
    )
    upi_amount: Decimal = Field(
        default=Decimal("0"), ge=0, max_digits=14, decimal_places=2, allow_inf_nan=False,
    )
    signature_url: str | None = Field(default=None, min_length=1, max_length=500)
    proof_photo_url: str | None = Field(default=None, min_length=1, max_length=500)
