# ROADMAP — SupplyOS

## Phase 1 — Foundation ✅ (in progress)
- [x] Monorepo scaffolding (`backend/`, `frontend/`, `mobile/`, `.ai/`).
- [x] PostgreSQL 15 + Redis 7 running under supervisor.
- [x] FastAPI skeleton + `/api/v1` versioned router.
- [x] JWT + refresh tokens + RBAC + audit logs.
- [x] Alembic wired.
- [x] First-launch setup wizard endpoint (`/setup/status`, `/setup/initialize`).
- [ ] CI: lint + tests + docker build.

## Phase 2 — Core Engines (this milestone)
- [x] Inventory engine (multi-warehouse, rack, shelf, batch, movements, `SELECT FOR UPDATE`).
- [x] Product catalog + categories.
- [x] Customer management + credit limits.
- [ ] Pricing engine (base, tier, customer overrides).
- [ ] Order engine (state machine, reservation, partial fulfillment).
- [ ] Delivery engine (assignment, OTP, proof, cash/UPI collect).
- [ ] Payments + Ledger.

## Phase 3 — Client apps
- [ ] Next.js Admin Dashboard (setup wizard, inventory, orders, customers, deliveries, finance, AI panel).
- [ ] Flutter Customer app (catalog, cart, order, tracking, invoices, credit history).
- [ ] Flutter Delivery app (route, QR scan, OTP, proof, offline sync).

## Phase 4 — Finance & Analytics
- [ ] GST invoice generation (PDF).
- [ ] Statements + P&L.
- [ ] Analytics dashboards (revenue, top movers, dead stock heatmap).

## Phase 5 — AI Supervisor
- [ ] Rule-based alerts (dead stock, low stock, credit).
- [ ] Claude Sonnet 4.5 hourly summaries.
- [ ] Forecasting (linear + XGBoost fallback for demand).
- [ ] Route optimization signals.

## Phase 6 — Optional AI modules (feature-flagged)
- [ ] WhatsApp parser → order.
- [ ] Voice-to-order.
- [ ] Smart chatbot.
- [ ] Price optimization.

## Phase 7 — Hardening
- [ ] Load tests (k6) — 1000 concurrent order placements.
- [ ] Chaos tests — DB failover, Redis flush.
- [ ] SOC2 audit prep (audit logs, encryption at rest, backup policy).
