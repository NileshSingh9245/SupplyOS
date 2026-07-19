# DECISIONS LOG — SupplyOS

Every meaningful architectural / product decision is captured below. Newest first.

Format:
```
## <YYYY-MM-DD> — <short title>
Context:
Decision:
Alternatives considered:
Tradeoffs:
```

---

## 2026-01-19 — .ai/ directory as source of truth
**Context:** Multiple AI agents will contribute code. Without a canonical rulebook, drift is guaranteed.
**Decision:** Every architectural or business-rule change must update the relevant `.ai/*.md` file in the same commit.
**Alternatives:** Ad-hoc wiki, code comments only.
**Tradeoffs:** Slight overhead on each PR; huge win for consistency and onboarding.

## 2026-01-19 — Backend on FastAPI (not NestJS)
**Context:** Original spec suggested NestJS; environment is Python-first.
**Decision:** FastAPI + SQLAlchemy async + Pydantic v2.
**Alternatives:** NestJS (TS), Litestar, Django REST.
**Tradeoffs:** Loses TS end-to-end typing; gains async performance, minimal code, first-class Pydantic. Contracts stay language-neutral via OpenAPI.

## 2026-01-19 — PostgreSQL as primary DB
**Context:** Inventory reservation, credit ledger, and finance all require strict transactional guarantees.
**Decision:** PostgreSQL 15 with `SELECT ... FOR UPDATE` for stock locks. Redis for caching + queues only, never for accounting state.
**Alternatives:** MongoDB (rejected — no true transactions across shards without cost), MySQL (fine but Postgres has better constraints/JSONB).
**Tradeoffs:** Slightly heavier schema migration overhead. Worth it.

## 2026-01-19 — Multi-tenant via `tenant_id` column (shared schema)
**Context:** Onboarding SMBs — dozens to hundreds of tenants expected before scaling to schema-per-tenant matters.
**Decision:** Shared schema with `tenant_id` on every row + tenant filter derived from JWT.
**Alternatives:** Schema-per-tenant (Postgres), DB-per-tenant.
**Tradeoffs:** Simpler ops; must be disciplined about `tenant_id` filters. Row-level security policy planned for phase 7.

## 2026-01-19 — JWT in httpOnly cookies (not localStorage)
**Context:** XSS is a bigger risk than CSRF given SameSite=Lax and same-origin API.
**Decision:** Access + refresh tokens in httpOnly, SameSite=Lax cookies. Bearer header fallback for mobile.
**Alternatives:** localStorage (rejected — XSS-visible), pure Bearer only (mobile-friendly but web must store somewhere).
**Tradeoffs:** Slightly more work on refresh rotation and CSRF-safe design.

## 2026-01-19 — Claude Sonnet 4.5 as default AI provider
**Context:** Need reliable structured output for alerts; instruction-following matters more than raw creativity.
**Decision:** Claude Sonnet 4.5 via `emergentintegrations` behind `AIProvider` protocol.
**Alternatives:** GPT-4o / GPT-5.2, Gemini 3 Flash.
**Tradeoffs:** Locked-in provider abstraction so switch is one-line config change.

## 2026-01-19 — Reserved qty stored as column, not derived
**Context:** Computing "available = quantity − sum(reservations)" on every catalog view is expensive at 10k SKUs × 100 concurrent viewers.
**Decision:** `inventory_items.reserved_qty` is a first-class column, updated inside the same locked transaction as reservations. `CHECK (reserved_qty <= quantity)` enforces invariant.
**Alternatives:** Compute at read time (slow), materialized view (staleness risk).
**Tradeoffs:** Must audit every path that touches `reserved_qty`. Reservation and release must always come in pairs. Enforced by service layer + `OrderReservation` audit trail.
