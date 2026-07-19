"""Central enums used across the domain."""
from __future__ import annotations

from enum import Enum


class Role(str, Enum):
    SUPER_ADMIN = "super_admin"
    WAREHOUSE_MANAGER = "warehouse_manager"
    ACCOUNTANT = "accountant"
    DELIVERY_PARTNER = "delivery_partner"
    CUSTOMER = "customer"


class OrderStatus(str, Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    RESERVED = "reserved"
    PICKED = "picked"
    PACKED = "packed"
    OUT_FOR_DELIVERY = "out_for_delivery"
    DELIVERED = "delivered"
    PAID = "paid"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class PaymentMode(str, Enum):
    CASH = "cash"
    UPI = "upi"
    BANK_TRANSFER = "bank_transfer"
    CREDIT = "credit"


class CustomerType(str, Enum):
    CASH = "cash"
    CREDIT = "credit"


class StockMovementType(str, Enum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"
    TRANSFER = "transfer"
    ADJUSTMENT = "adjustment"
    RESERVATION = "reservation"
    RELEASE = "release"
    DAMAGE = "damage"
    RETURN = "return"


class AlertSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertCategory(str, Enum):
    INVENTORY = "inventory"
    SALES = "sales"
    FINANCE = "finance"
    DELIVERY = "delivery"
    OPERATIONS = "operations"
