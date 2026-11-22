"""Import all models so Alembic autogenerate & Base.metadata see them."""
from __future__ import annotations

from app.infrastructure.db.models.tenant import Tenant  # noqa: F401
from app.infrastructure.db.models.user import (  # noqa: F401
    User, RefreshToken, PasswordResetToken, LoginAttempt, AuditLog,
)
from app.infrastructure.db.models.warehouse import Warehouse, Rack, Shelf  # noqa: F401
from app.infrastructure.db.models.product import Category, Product, Batch  # noqa: F401
from app.infrastructure.db.models.inventory import InventoryItem, StockMovement  # noqa: F401
from app.infrastructure.db.models.customer import (  # noqa: F401
    Customer, CustomerPrice, PriceTier, LedgerEntry,
)
from app.infrastructure.db.models.order import (  # noqa: F401
    Order, OrderItem, OrderReservation, OrderStatusHistory, Payment, Delivery,
)
from app.infrastructure.db.models.ai_alert import AIAlert  # noqa: F401
from app.infrastructure.db.models.idempotency import IdempotencyRecord  # noqa: F401
from app.infrastructure.db.models.proof import DeliveryProof, ProofUploadOperation  # noqa: F401
