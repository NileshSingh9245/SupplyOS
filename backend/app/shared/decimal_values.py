"""Exact, finite NUMERIC validation shared by pricing and customer accounting."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, localcontext

from app.core.exceptions import DomainError


def validated_decimal(
    value: Decimal, *, name: str, precision: int = 14, scale: int = 2,
    minimum: Decimal | None = Decimal("0"),
) -> Decimal:
    """Reject precision loss, non-finite numbers, and NUMERIC overflow before writes."""
    try:
        number = value if isinstance(value, Decimal) else Decimal(str(value))
        with localcontext() as context:
            context.prec = 50
            quantum = Decimal(10) ** -scale
            maximum = Decimal(10) ** (precision - scale) - quantum
            if not number.is_finite() or number.copy_abs() > maximum:
                raise DomainError(f"{name} must be finite and fit Decimal({precision}, {scale})")
            if minimum is not None and number < minimum:
                raise DomainError(f"{name} must be at least {minimum}")
            rounded = number.quantize(quantum)
            if number != rounded:
                raise DomainError(f"{name} supports at most {scale} decimal places")
            return rounded
    except (InvalidOperation, ValueError, TypeError):
        raise DomainError(f"Invalid {name}") from None
