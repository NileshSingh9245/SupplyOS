"""One exact server line calculation for orders and accepted checkout quotes."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, localcontext

from app.shared.decimal_values import validated_decimal


@dataclass(frozen=True)
class LineAmounts:
    unit_price: Decimal
    gst_rate: Decimal
    subtotal: Decimal
    tax: Decimal
    total: Decimal


def calculate_line(price: Decimal, gst_rate: Decimal, *, quantity: Decimal) -> LineAmounts:
    unit_price = validated_decimal(price, name="Resolved unit price")
    tax_rate = validated_decimal(gst_rate, name="GST rate", precision=5)
    qty = validated_decimal(quantity, name="Quantity", precision=16, scale=3,
                            minimum=Decimal("0.001"))
    with localcontext() as context:
        context.prec = 50
        subtotal = (unit_price * qty).quantize(Decimal("0.01"))
        tax = (subtotal * tax_rate / Decimal("100")).quantize(Decimal("0.01"))
        total = subtotal + tax
    for amount in (subtotal, tax, total):
        validated_decimal(amount, name="Line amount")
    return LineAmounts(unit_price, tax_rate, subtotal, tax, total)
