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

## Checkout and Timeline Foundations - 2026-11-16

```text
orders.service ---------> orders.amounts --------> shared.decimal_values
checkout.service -------> orders.service / orders.amounts / pricing.service / payments.service
checkout.router --------> shared auth / idempotency / audit, current OrderOut projection
orders.service ---------> shared.order_events <-------- payments.service
                               |
                               v
                       infrastructure.db.models
```

- `orders.amounts` is the pure server-only exact line/tax calculation reused by order creation and upcoming quote/checkout; no client pricing engine or changed rounding policy.
- `shared.order_events` writes a caller-owned history row using a real monotonically clamped timestamp under the already-held parent order lock. It imports models, not feature services, so payment-to-order feature cycles are not introduced.
- Existing history is not rewritten or causally ranked from ambiguous timestamps. The helper prevents new same-transaction ties/backward-clock reversal; legacy ambiguity remains explicit work.
- Neither helper commits transactions, performs allocation/stock decisions, emits client credentials or overrides current authorization. Payment's paid-event writer remains inside its outer caller-owned transaction.
- Customer quote/checkout is additive, not a change to legacy POST /orders pending semantics. Server-signed accepted terms plus existing actor/operation/request replay persistence bind a quote identity to exactly one atomic checkout; no client-supplied price authority or independent HTTP transition chain.

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
