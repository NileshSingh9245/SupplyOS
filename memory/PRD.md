# SupplyOS — PRD

_Product requirements & delivery log. Updated every milestone._

## Original problem statement
Build a production-grade SaaS platform named **Smart Supply Chain OS** (branded **SupplyOS**) that digitizes the full wholesale/distribution workflow. Eliminate manual inventory checks, WhatsApp orders, stock conflicts, credit disputes, delivery inefficiencies. Three apps, one backend, one database, AI supervisor. Indian market — INR + GST, admin controls all pricing/tax/credit rules.

## Architecture — as delivered
- **Backend**: FastAPI + SQLAlchemy 2 (async) + Alembic + PostgreSQL 15 + Redis 7.
- **AI**: Claude Sonnet 4.5 via `emergentintegrations` behind `AIProvider` abstraction.
- **Auth**: JWT + refresh in httpOnly cookies, RBAC (5 roles), brute-force lockout, audit log.
- **Admin dashboard**: Next.js 14 (App Router) + TS + Tailwind + Zustand + React Query.
- **Mobile**: Flutter (customer + delivery) scaffolds — Riverpod, GoRouter, Dio.
- **Multi-tenant** via `tenant_id` on every row.
- **Row-level locking** (`SELECT ... FOR UPDATE`) on every inventory mutation.

## User personas
- **Super Admin** — configures rules, manages users, sees everything.
- **Warehouse Manager** — inventory, orders, deliveries.
- **Accountant** — customers, payments, ledger, invoices.
- **Delivery Partner** — assigned deliveries only (route, OTP, proof, cash).
- **Customer** — own catalog with per-customer pricing, orders, credit history.

## Core requirements (static)
- Multi-warehouse + rack + shelf + batch + expiry + damage.
- Order state machine: `pending → confirmed → reserved → picked → packed → out_for_delivery → delivered → paid → completed` + `cancelled`.
- Two customers cannot claim same stock (verified via `SELECT FOR UPDATE`).
- Customer-specific + tier-based pricing.
- Credit limits enforced before reservation.
- OTP + photo + signature on delivery, cash/UPI collection.
- INR currency, GST-aware invoices.
- AI supervisor: dead stock, low stock, reorder, credit risk, Claude summaries.
- Admin can edit **35 business rules** from dashboard (currency, GST, credit, delivery, AI cadence).

## What's implemented (2026-01-19)
### Backend `/api/v1`
- `auth` — login, refresh, logout, /me, register-customer, forgot/reset password, brute-force lockout, audit.
- `setup` — status + initialize (tenant + admin + warehouses).
- `settings` — 35 admin-editable rules; PATCH returns `applied_keys`.
- `warehouses` — CRUD + racks + shelves.
- `products` + categories with GST, HSN, reorder levels.
- `inventory` — row-locked reservation engine, adjustments, movements, stats.
- `customers` — CRUD + credit ledger + per-customer price overrides.
- `pricing` — tiers + resolve endpoint.
- `orders` — full state machine, reservation, credit check, cancel releases reservation, deliver ripples atomically.
- `deliveries` — assign, OTP, signature/photo, cash/UPI collect.
- `payments` — standalone recording + ledger.
- `ai_supervisor` — rule-based (dead stock, low stock, credit risk) + Claude Sonnet 4.5 summaries.

### Admin dashboard (Next.js)
- Setup wizard, login, sidebar shell.
- Overview, Inventory, Warehouses, Products, Customers, Orders (full state UI), Deliveries, Finance, AI Supervisor, Rules & Settings, Audit Log stub.
- Industrial dark theme, volt-green accents, INR formatting (`en-IN`).

### Mobile scaffolds
- `customer_app` — Riverpod, GoRouter, login, catalog. Push-ready for `flutter run`.
- `delivery_app` — dark theme, login, route screen; mobile_scanner + signature + hive declared.

### Verified (testing agent iteration 1 — 30/30 pass)
- Row locking → 409 InsufficientStock.
- Per-customer pricing (₹80 override on ₹100 base → 50 × ₹80 × 1.05 = ₹4,200).
- Order state machine progression.
- Cancel releases reservation.
- Delivery finalization updates inventory + ledger + audit atomically.
- Claude summary generation (no AttributeError).
- RBAC blocks customer role from admin endpoints.

## Prioritized backlog

### P0 — next milestone
- [ ] GST invoice PDF generation.
- [ ] Reservation TTL background job (Celery worker under supervisor).
- [ ] Alembic migrations enforced (drop `create_all` at boot in prod).
- [ ] Audit log viewer UI in admin.
- [ ] Racks & shelves visual editor.
- [ ] Warehouse "best-fit" order routing (`nearest_first` / `most_stock_first`).

### P1
- [ ] WebSocket live order updates (Redis pub/sub).
- [ ] Flutter customer app — cart, place-order, tracking, invoice PDF.
- [ ] Flutter delivery app — QR scan, OTP verify, signature, photo, offline queue.
- [ ] Analytics charts (recharts) — revenue over time, top movers, dead stock heatmap.
- [ ] Multi-address per customer.
- [ ] Rate limiting via Redis sliding window.

### P2
- [ ] WhatsApp Business webhook → order parser (Claude structured output).
- [ ] Voice-to-order (Whisper).
- [ ] Price optimization module.
- [ ] Route optimization (Google Maps Distance Matrix).
- [ ] SOC2 audit prep (encryption at rest, backup policy).

## Next tasks list
1. Push current tree to `NileshSingh9245/SupplyOS` via **Save to GitHub** in Emergent.
2. Test frontend UI flows end-to-end with a testing pass focused on the admin dashboard.
3. Ship P0 items above.
4. Add Celery worker + reservation TTL sweeper.
5. Kick off Flutter feature completion for customer_app first (larger user base).
