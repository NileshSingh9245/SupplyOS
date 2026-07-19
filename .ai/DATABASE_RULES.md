# DATABASE RULES — SupplyOS

## Core rules
- **PostgreSQL only.** No MongoDB, no SQLite (except in unit tests via mocking).
- **UUIDv4 primary keys** on every table (`id UUID PRIMARY KEY DEFAULT gen_random_uuid()` or Python-side default).
- **Foreign keys with explicit `ON DELETE`** (`CASCADE` for owned data, `RESTRICT` for referenced core data like products, `SET NULL` for optional soft references).
- **Soft deletes** via `deleted_at TIMESTAMPTZ NULL` on user-facing entities (Customer, Product, Warehouse). All queries filter `deleted_at IS NULL` by default. Hard delete only via admin tool + audit entry.
- **Indexes** on:
  - Every `tenant_id`.
  - Every foreign key.
  - Every column used in `WHERE`, `ORDER BY`, or `JOIN` on hot paths.
  - Unique composite indexes for natural keys (`(tenant_id, sku)`, `(tenant_id, order_number)`).
- **`created_at` / `updated_at`** on every table (timezone-aware).
- **Alembic migrations only.** No manual `CREATE TABLE`. Migrations run in CI/CD and locally via `alembic upgrade head`.
- **Naming convention** enforced by SQLAlchemy `MetaData(naming_convention=...)`.

## Inventory locking contract

Any write path that changes `quantity` or `reserved_qty` **MUST**:

1. Open a single async DB session (`AsyncSessionLocal`).
2. `SELECT ... FOR UPDATE` on the target `inventory_items` row(s).
3. Apply mutation in-memory (checked against `CHECK` constraints).
4. Insert a `stock_movements` row.
5. `COMMIT` atomically.

Application-level mutexes, in-memory counters, or Redis-based locks are **forbidden** for stock accounting. Redis may only be used for user-facing rate limiting or session revocation.

## Transactions

- Every service method that mutates ≥ 2 rows across ≥ 2 tables **must** be one transaction.
- Use `async with db.begin()` for explicit blocks when the session was opened externally.
- Never call `db.commit()` inside a repository. Only in the service / router.
- On any exception inside a transaction: rollback + re-raise. Never swallow.

## Audit
- `audit_logs` table is **append-only**.
- Every mutating endpoint must write at least one `audit_logs` row (see `app/shared/audit.py`).
- Sensitive fields (`password_hash`, tokens) never appear in audit metadata.

## Migrations rules
- One logical change per migration.
- Migration file names: `YYYYMMDD_HHMM_<short_slug>.py`.
- Backwards-compatible ordering: **add** columns nullable → deploy → **backfill** → deploy → **enforce** NOT NULL.
- `downgrade()` must be reversible for the last 5 migrations minimum.

## Constraints
- `CHECK (quantity >= 0)`
- `CHECK (reserved_qty >= 0)`
- `CHECK (reserved_qty <= quantity)`
- `CHECK (credit_limit >= 0)`
- `CHECK (grand_total >= 0)`
- Unique `(tenant_id, product_id, warehouse_id, rack_id, shelf_id, batch_id)` on inventory rows.
