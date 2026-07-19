"""API v1 aggregate router — the only place that mounts feature routers."""
from __future__ import annotations

from fastapi import APIRouter

from app.features.ai_supervisor.router import router as ai_router
from app.features.auth.router import router as auth_router
from app.features.customers.router import router as customers_router
from app.features.deliveries.router import router as deliveries_router
from app.features.inventory.router import router as inventory_router
from app.features.orders.router import router as orders_router
from app.features.payments.router import router as payments_router
from app.features.pricing.router import router as pricing_router
from app.features.products.router import router as products_router
from app.features.settings.router import router as settings_router
from app.features.tenants.router import router as tenants_router
from app.features.warehouses.router import router as warehouses_router

api_v1 = APIRouter()
api_v1.include_router(auth_router)
api_v1.include_router(tenants_router)
api_v1.include_router(settings_router)
api_v1.include_router(warehouses_router)
api_v1.include_router(products_router)
api_v1.include_router(customers_router)
api_v1.include_router(inventory_router)
api_v1.include_router(pricing_router)
api_v1.include_router(orders_router)
api_v1.include_router(deliveries_router)
api_v1.include_router(payments_router)
api_v1.include_router(ai_router)
