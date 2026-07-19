# ARCHITECTURE — SupplyOS

## Layers (Clean Architecture)

```
┌──────────────────────────────────────────────┐
│   Frameworks & Drivers (FastAPI, Flutter,     │
│   Next.js, PostgreSQL, Redis, S3, Claude)    │
├──────────────────────────────────────────────┤
│   Interface Adapters (Routers, Repositories, │
│   HTTP clients, WebSocket handlers)          │
├──────────────────────────────────────────────┤
│   Use Cases (Feature Services: reserve_stock,│
│   place_order, complete_delivery, ...)       │
├──────────────────────────────────────────────┤
│   Entities / Domain (Order, Inventory,       │
│   Customer aggregates, Value Objects,        │
│   Domain Errors)                             │
└──────────────────────────────────────────────┘
```

Dependency arrow points inward: outer layers depend on inner, never the reverse.

## Stack

| Concern | Tech | Notes |
|---------|------|-------|
| Admin Dashboard | Next.js 14 + TypeScript + Tailwind + shadcn/ui + Zustand + React Query | App Router. |
| Mobile (Customer / Delivery) | Flutter 3 + Riverpod + GoRouter + Dio + Hive | Offline-first for delivery app. |
| Backend | FastAPI (Python 3.11) | async everywhere. |
| DB | PostgreSQL 15 | Prepared statements, connection pool 20+10. |
| ORM | SQLAlchemy 2.0 (async) + Alembic | Autogenerate migrations. |
| Cache / Pub-sub | Redis 7 | rate limit, session revocation, WebSocket fan-out. |
| Realtime | WebSockets via FastAPI + Redis pub/sub | `/api/v1/ws/*`. |
| Background jobs | Celery + Redis (queue) | Reservation TTL, AI cron, notifications, S3 uploads. |
| Storage | S3 abstraction (`StorageService`) | MinIO in dev, AWS S3 in prod. |
| AI | `AIProvider` abstraction (Claude via emergentintegrations) | GPT/Gemini plug-in without code changes. |
| Deployment | Docker + Docker Compose (dev) → Kubernetes (prod) | 12-factor. |

## Monorepo Layout

```
supplyos/
├── backend/
│   ├── app/
│   │   ├── core/            # config, security, database, enums, exceptions
│   │   ├── shared/          # deps, schemas, audit
│   │   ├── domain/          # value objects, domain services (framework-free)
│   │   ├── infrastructure/
│   │   │   ├── db/models/   # SQLAlchemy models
│   │   │   ├── repositories/# Data-access boundary
│   │   │   └── external/    # AI provider, storage, notifications
│   │   ├── features/        # bounded contexts
│   │   │   ├── auth/
│   │   │   ├── tenants/
│   │   │   ├── warehouses/
│   │   │   ├── products/
│   │   │   ├── inventory/
│   │   │   ├── customers/
│   │   │   ├── pricing/
│   │   │   ├── orders/
│   │   │   ├── deliveries/
│   │   │   ├── payments/
│   │   │   ├── ledger/
│   │   │   ├── ai_supervisor/
│   │   │   └── audit/
│   │   └── api/v1/          # versioned aggregate router
│   ├── alembic/
│   ├── tests/
│   └── requirements.txt
├── frontend/                # Next.js admin dashboard
├── mobile/
│   ├── customer_app/        # Flutter
│   ├── delivery_app/        # Flutter
│   └── packages/            # shared Dart packages (api_client, auth, models, ui_kit)
├── docs/
├── .ai/                     # source-of-truth
└── docker-compose.yml
```

## Cross-cutting

- **Multi-tenant** via `tenant_id` on every row. All queries filter by `tenant_id` from JWT.
- **Row-level locking** for inventory writes.
- **Idempotency keys** on order creation (`X-Idempotency-Key` header).
- **Correlation IDs** on every request (`X-Request-Id`) logged and returned.
- **WebSockets** for order status updates and AI alerts (Redis pub/sub fan-out).
