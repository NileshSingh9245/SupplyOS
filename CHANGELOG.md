# CHANGELOG

All notable changes to this project.

## [0.1.0] — 2026-01-19 · Milestone 1 + 2

### Added

**.ai/ charter**
- `AGENT_INSTRUCTIONS.md`, `PRODUCT_REQUIREMENTS.md`, `BUSINESS_SCENARIOS.md`,
  `ARCHITECTURE.md`, `DATABASE_RULES.md`, `API_GUIDELINES.md`, `CODING_STANDARDS.md`,
  `SECURITY_RULES.md`, `GIT_WORKFLOW.md`, `AI_SUPERVISOR.md`, `ROADMAP.md`,
  `MODULE_DEPENDENCIES.md`, `DECISIONS_LOG.md`.

**Infrastructure**
- PostgreSQL 15 + Redis 7 provisioned under supervisor.
- FastAPI + SQLAlchemy 2 (async) + Alembic wired.
- Auto schema creation on boot; first Alembic revision `3a7b2a03cd3b_initial_schema`.

**Backend features (`/api/v1/*`)**
- `auth` — login, register-customer, refresh, logout, /me, forgot & reset password. JWT + refresh tokens in httpOnly cookies. Brute-force lockout. Audit trail.
- `setup` — status + initialize wizard (tenant + admin + warehouses).
- `settings` — 30+ admin-editable rules: currency (INR default), GST type & rate, credit thresholds, order rules, delivery requirements, inventory defaults, AI cadence.
- `warehouses` — warehouses / racks / shelves.
- `products` — SKUs + categories with GST rate, HSN, reorder levels.
- `inventory` — multi-warehouse rows, `SELECT FOR UPDATE` reservation engine, adjustments, movements audit trail, stats.
- `customers` — cash/credit, credit limits, per-customer price overrides, ledger.
- `pricing` — tiers + resolve endpoint (customer_override → tier discount → base).
- `orders` — full state machine (pending→…→completed), reservation w/ row locking, cancel with release, delivery ripple (inventory + ledger + audit atomic).
- `deliveries` — assign, start, OTP verify, complete with cash/UPI collection + payment + ledger update.
- `payments` — standalone payment recording with ledger update.
- `ai_supervisor` — rule-based analyzers (dead stock, low stock, credit risk) + Claude Sonnet 4.5 executive summaries (via `AIProvider` abstraction).

**Admin dashboard (Next.js 14 + TS + Tailwind)**
- Industrial dark theme (`.ai/BUSINESS_SCENARIOS.md`-compliant volt-green accents).
- Setup wizard, login screen with warehouse background.
- Sidebar shell with role-aware navigation.
- Pages: Overview / Inventory / Warehouses / Products / Customers / Orders / Deliveries / Finance / AI Supervisor / Rules & Settings / Audit Log.
- Full order state-machine UI (confirm → reserve → pick → pack → dispatch → deliver → cancel).
- INR formatting with Indian numbering (`en-IN`).

**Mobile scaffolds (Flutter)**
- `customer_app/` — Riverpod + go_router + Dio + INR formatters, login + catalog + orders stubs.
- `delivery_app/` — dark theme, Riverpod, login + route screen, mobile_scanner + signature + hive deps declared.

### Verified
- Setup wizard → login → create warehouse → create product → adjust +200 stock → create credit customer with ₹50k limit → per-customer price override (₹40) → order 100 units (grand total ₹4,200) → confirm → reserve (`reserved_qty=100`) → attempt second order for 150 units → **409 InsufficientStock** → pick → pack → dispatch (auto-creates delivery + OTP) → assign partner → start → verify OTP → complete with ₹4,200 cash collection → inventory `qty=100 reserved=0`, customer `outstanding=0`, ledger updated → AI analyzer runs rule checks → Claude Sonnet 4.5 generates real executive summary from live metrics.

### Notes
- Frontend `yarn start` runs `next dev -p 3000 -H 0.0.0.0` — Kubernetes ingress preview URL preserved.
- Redis is running but Celery worker not yet started; reservation-TTL job planned for Milestone 3.
- Flutter apps cannot be run in this container (no Flutter SDK); code is push-ready for `flutter run` locally.
