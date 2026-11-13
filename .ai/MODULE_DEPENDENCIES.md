# MODULE DEPENDENCIES — SupplyOS

Direction of dependency: **A → B** means A depends on B (A imports / calls into B).

```
                     ┌────────────┐
                     │  auth      │
                     └────┬───────┘
                          │
                          ▼
                     ┌────────────┐
                     │  tenants   │
                     └────┬───────┘
                          │
       ┌──────────────────┼───────────────────┐
       ▼                  ▼                   ▼
┌────────────┐     ┌────────────┐      ┌────────────┐
│ warehouses │     │  products  │      │ customers  │
└────┬───────┘     └────┬───────┘      └────┬───────┘
     │                  │                   │
     └────────┬─────────┘                   │
              ▼                             │
       ┌────────────┐                       │
       │ inventory  │◄──────────────────────┤
       └────┬───────┘                       │
            │                               │
            │        ┌──────────┐           │
            └───────►│  orders  │◄──────────┤
                     └────┬─────┘           │
                          │                 │
                          ▼                 │
                     ┌────────────┐         │
                     │ deliveries │         │
                     └────┬───────┘         │
                          │                 │
                          ▼                 │
                     ┌────────────┐         │
                     │  payments  │─────────┤
                     └────┬───────┘         │
                          │                 │
                          ▼                 ▼
                     ┌──────────────────────┐
                     │        ledger        │
                     └──────────┬───────────┘
                                │
                                ▼
                     ┌──────────────────────┐
                     │    ai_supervisor     │
                     └──────────┬───────────┘
                                │
                                ▼
                     ┌──────────────────────┐
                     │   analytics / audit  │
                     └──────────────────────┘
```

## Effective Pricing Dependencies - 2026-11-12

```text
orders.service --------> pricing.service --------> pricing.repositories
customers.router ------> pricing.service                 |
pricing.service -------> shared.decimal_values           v
payments.service ------> shared.decimal_values    infrastructure.db.models
```

- `orders.service -> pricing.service` supplies one immutable product/price/tax batch; pricing never imports order services.
- `customers.router -> pricing.service` supplies audited tenant-bound tier assignment and override removal. Pricing repositories import infrastructure models, not customer/product feature services, so there is no feature cycle.
- Pricing and payments share pure `shared.decimal_values.validated_decimal`; accounting keeps its existing import surface without copying money validation or introducing a pricing-to-payments service dependency.
- The self-catalog router belongs to pricing, not a new financial engine. It holds eligibility/currency read protection, derives signed tenant/profile scope, and publishes a minimal exact-price DTO. Web/mobile consume it without local financial rules.

## Rules
- Opt-in `auth.recovery -> core.redis_client` supplies HMAC admission counters only, never financial state. `auth.recovery -> infrastructure.external.smtp` supplies the mail transport; the adapter depends on settings, not feature modules. Recovery calls its own auth service/repository and owns background SQL sessions. No new cross-feature dependency or durable queue is introduced.
- **`inventory` may not depend on `orders`** — orders call inventory, not the reverse. Any need for orders to know inventory state goes via `inventory.service` functions.
- **`ledger` is a passive sink.** Only `payments`, `orders`, and admin corrections may write. Nothing reads except `customers` (aggregate `outstanding`) and `ai_supervisor`.
- **`ai_supervisor` is read-only** on operational data. It writes only to `ai_alerts`.
- **`audit`** is written by every mutating feature module — via `app.shared.audit.audit()` — but no module reads it (only observability tools).

## Import contract
- `features/A/service.py` may import from `features/B/service.py` **only if** the dependency is listed in this doc.
- Repositories (`repositories.py`) never import other modules.
- Schemas (`schemas.py`) never import services.

## Adding a new dependency
1. Draw the arrow in this file.
2. Confirm no cycles.
3. Add to `DECISIONS_LOG.md` with rationale.
4. Commit `docs(architecture): allow feature X to depend on Y`.
