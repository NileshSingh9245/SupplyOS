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

## Rules
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
