# AGENT INSTRUCTIONS — SupplyOS

> **Source of truth. Every code contribution must obey these rules.**

## Non-negotiables

- **Production-grade only.** No demo code, no toy implementations, no mocked flows shipped to `main`.
- **No duplication.** Reuse shared packages, services, and helpers. Extend rather than fork.
- **Backward compatibility.** Never break a versioned public API (`/api/v1/*`). Add `/api/v2/*` and deprecate.
- **Business logic lives on the server.** Flutter and Next.js apps are presentation only. They must never own inventory math, credit rules, or state transitions.
- **PostgreSQL transactions are sacred.** Never bypass row locking. Every stock, order, and ledger mutation runs inside a transaction with `SELECT ... FOR UPDATE`.
- **Maintainability > speed.** If a shortcut violates SOLID / Clean Architecture, reject it.

## Architectural doctrine

- Clean Architecture (Entities → Use Cases → Interface Adapters → Frameworks).
- SOLID (SRP, OCP, LSP, ISP, DIP).
- Domain-Driven Design: bounded contexts = feature modules.
- Repository Pattern for all data access.
- Service Layer Pattern for business logic.
- Dependency injection everywhere (FastAPI `Depends`, Riverpod providers).
- Feature-based folders (`app/features/<domain>/{router,service,schemas,repositories}`).
- Reusable shared packages under `app/shared/` and `mobile/packages/`.

## Workflow discipline

- **Read `.ai/*` before any change.** Update relevant `.ai/*` docs in the same commit that changes architecture or business logic.
- **Push meaningful commits** using Conventional Commits (`feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `chore:`).
- Every architectural decision goes into `DECISIONS_LOG.md`.
- Every business rule change goes into `BUSINESS_SCENARIOS.md`.

## Forbidden

- ❌ Business logic inside Flutter widgets or Next.js pages.
- ❌ Application-level stock locks (mutexes, in-memory counters). Only DB-level.
- ❌ Silent breaking changes in `/api/v1`.
- ❌ Storing secrets in code or committing `.env`.
- ❌ Copy-pasting a helper. Refactor to a shared package.
- ❌ Deleting audit log rows.
