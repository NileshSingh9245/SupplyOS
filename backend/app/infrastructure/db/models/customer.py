"""Customer, CustomerPrice (per-customer product override), CreditLedger entries."""
from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import String, Boolean, Numeric, ForeignKey, Index, CheckConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.base import Base, TimestampMixin, UUIDPKMixin
from app.core.enums import CustomerType


class Customer(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "customers"
    __table_args__ = (
        Index("ix_customers_tenant_code", "tenant_id", "code", unique=True),
        CheckConstraint(
            "credit_limit >= 0 AND credit_limit <= 999999999999.99 "
            "AND outstanding >= -999999999999.99 AND outstanding <= 999999999999.99 "
            "AND credit_held >= 0 AND credit_held <= 999999999999.99 "
            "AND cash_funded_pending >= 0 AND cash_funded_pending <= 999999999999.99",
            name="financial_balances",
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(30), nullable=False)  # human-friendly code
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    business_name: Mapped[str | None] = mapped_column(String(200))
    gstin: Mapped[str | None] = mapped_column(String(20))
    phone: Mapped[str | None] = mapped_column(String(30))
    email: Mapped[str | None] = mapped_column(String(200))
    address: Mapped[str | None] = mapped_column(String(500))
    city: Mapped[str | None] = mapped_column(String(120))
    state: Mapped[str | None] = mapped_column(String(120))
    pincode: Mapped[str | None] = mapped_column(String(15))

    customer_type: Mapped[str] = mapped_column(
        String(20), default=CustomerType.CASH.value, nullable=False
    )
    credit_limit: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)
    outstanding: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)
    credit_held: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal("0"), server_default=text("0"), nullable=False,
    )
    cash_funded_pending: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal("0"), server_default=text("0"), nullable=False,
    )
    price_tier: Mapped[str | None] = mapped_column(String(30))  # e.g. "wholesale-a", "retail"
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    @property
    def credit_exposure(self) -> Decimal:
        return max(Decimal("0"), self.outstanding + self.credit_held + self.cash_funded_pending)

    @property
    def available_credit(self) -> Decimal:
        return max(
            Decimal("0"),
            self.credit_limit - self.outstanding - self.credit_held - self.cash_funded_pending,
        )

    @property
    def advance_balance(self) -> Decimal:
        return max(Decimal("0"), -self.outstanding)


class CustomerPrice(Base, UUIDPKMixin, TimestampMixin):
    """Overrides base_price for a specific (customer, product) pair."""
    __tablename__ = "customer_prices"
    __table_args__ = (
        Index("ix_cprice_customer_product", "customer_id", "product_id", unique=True),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    price: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)


class PriceTier(Base, UUIDPKMixin, TimestampMixin):
    """Named pricing tier applied to a set of customers (e.g. wholesale-a)."""
    __tablename__ = "price_tiers"
    __table_args__ = (Index("ix_tier_tenant_name", "tenant_id", "name", unique=True),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    discount_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0"), nullable=False)


class LedgerEntry(Base, UUIDPKMixin, TimestampMixin):
    """Double-entry style ledger for customer credit tracking."""
    __tablename__ = "ledger_entries"
    __table_args__ = (
        Index("ix_ledger_customer_created", "customer_id", "created_at"),
        CheckConstraint(
            "debit >= 0 AND debit <= 999999999999.99 "
            "AND credit >= 0 AND credit <= 999999999999.99 "
            "AND (debit = 0 OR credit = 0) "
            "AND balance_after >= -999999999999.99 AND balance_after <= 999999999999.99",
            name="financial_amounts",
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )
    debit: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)
    credit: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)
    balance_after: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    reference_type: Mapped[str | None] = mapped_column(String(30))  # order/payment
    reference_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    note: Mapped[str | None] = mapped_column(String(500))
