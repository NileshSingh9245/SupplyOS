# SupplyOS

**Production-grade AI-powered supply chain OS** for Indian wholesalers, distributors, and warehouses.

Repo: https://github.com/NileshSingh9245/SupplyOS.git

---

## What's included

| Path | Purpose |
|---|---|
| `backend/` | FastAPI + SQLAlchemy async + Alembic + PostgreSQL 15 + Redis 7 |
| `frontend/` | Next.js 14 (App Router) + TypeScript + Tailwind — Admin Dashboard |
| `mobile/customer_app/` | Flutter + Riverpod + GoRouter (customer ordering) |
| `mobile/delivery_app/` | Flutter + Riverpod + Hive (delivery partner, offline-first) |
| `.ai/` | 13 governing documents (architecture, DB rules, API, security, roadmap, decisions log). Read these before any change. |
| `docs/` | Ancillary documentation |

## Tech stack (per `.ai/ARCHITECTURE.md`)

- **Backend**: FastAPI, SQLAlchemy 2 (async), Alembic, PostgreSQL 15, Redis 7, Claude Sonnet 4.5.
- **Admin**: Next.js 14 + Tailwind + Zustand + React Query.
- **Mobile**: Flutter + Riverpod + GoRouter + Dio.
- **Patterns**: Clean Architecture, SOLID, Repository, Service Layer, Dependency Injection, Feature-based modules.
- **Multi-tenant** from day one (`tenant_id` on every row).
- **Row-level locking** for all inventory writes.

## Local development

```bash
# PostgreSQL + Redis are managed by supervisor in this container.
# Health check
curl http://localhost:8001/api/health/deep

# Setup wizard status
curl http://localhost:8001/api/v1/setup/status

# Initialize (create tenant + admin + first warehouse)
curl -X POST http://localhost:8001/api/v1/setup/initialize -H 'Content-Type: application/json' -d '{...}'
```

## API Documentation
- OpenAPI JSON: `/api/openapi.json`
- Swagger UI: `/api/docs`
- ReDoc: `/api/redoc`

## What's live now (Milestone 1 + 2)

- ✅ First-launch setup wizard (`/api/v1/setup/*`)
- ✅ JWT auth with refresh tokens, cookie + Bearer, brute force lockout, audit log (`/api/v1/auth/*`)
- ✅ Multi-warehouse + rack + shelf (`/api/v1/warehouses/*`)
- ✅ Products + categories with GST rate, HSN, reorder levels (`/api/v1/products/*`)
- ✅ Inventory engine with **SELECT FOR UPDATE** row locking (`/api/v1/inventory/*`)
- ✅ Customers with credit limits + ledger + per-customer pricing (`/api/v1/customers/*`)
- ✅ Pricing tiers + price resolution (customer_override → tier → base) (`/api/v1/pricing/*`)
- ✅ Order state machine: pending→confirmed→reserved→picked→packed→out_for_delivery→delivered→paid→completed (`/api/v1/orders/*`)
- ✅ Deliveries: assign, OTP, signature, photo proof, cash/UPI collect (`/api/v1/deliveries/*`)
- ✅ Payments + ledger auto-update (`/api/v1/payments/*`)
- ✅ AI Supervisor: rule-based (dead stock, low stock, credit risk) + Claude Sonnet 4.5 summaries (`/api/v1/ai/*`)
- ✅ Admin-configurable business rules (currency, GST, credit, delivery, AI cadence) (`/api/v1/settings/*`)
- ✅ Next.js admin dashboard: login, setup wizard, overview, inventory, warehouses, products, customers, orders (full state machine UI), deliveries, finance, AI supervisor, settings
- ✅ Flutter customer + delivery app scaffolds

## Verified business scenarios
See `.ai/BUSINESS_SCENARIOS.md`. All 12 scenarios pass end-to-end. Highlights:

- **S1**: Two customers cannot claim the same physical stock (verified via 409 InsufficientStock).
- **S3**: Delivery completion ripples through inventory, ledger, and audit atomically.
- **S5**: Customer-specific price override wins over tier and base.

## Milestones ahead
See `.ai/ROADMAP.md`. Next up: Alembic migrations tightening, warehouse racks/shelves UI, GST invoice PDFs, WebSocket live-order updates, Celery-backed reservation TTL, Flutter feature completion.
