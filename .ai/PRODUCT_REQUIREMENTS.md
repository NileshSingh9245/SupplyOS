# PRODUCT REQUIREMENTS — SupplyOS

## Vision
SupplyOS is an **AI-powered operating system** for wholesalers, distributors, warehouses, and retailers. It replaces WhatsApp orders, paper ledgers, manual stock checks, and disconnected finance workflows with one connected system.

## Applications
| # | App | Stack | Users |
|---|-----|-------|-------|
| 1 | Admin Dashboard | Next.js / React + TS + Tailwind | Super Admin, Warehouse Manager, Accountant |
| 2 | Customer Application | Flutter (iOS / Android / Web) | Customers |
| 3 | Delivery Application | Flutter (Android / iOS) | Delivery Partners |
| 4 | Backend API | FastAPI + PostgreSQL + Redis | All apps |
| 5 | AI Supervisor | FastAPI micro-service + Claude Sonnet 4.5 | Admin & Ops |

## Core Modules
- **Inventory** — multi-warehouse, rack, shelf, batch, expiry, damage, returns, transfers, reservations, barcode/QR.
- **Warehouses** — hierarchy of Warehouse → Rack → Shelf, per-warehouse manager.
- **Orders** — full state machine (`pending → confirmed → reserved → picked → packed → out_for_delivery → delivered → paid → completed`), partial fulfillment, backorders, scheduled, repeat orders.
- **Deliveries** — route planning, QR scan, OTP, signature/photo proof, cash/UPI collect, offline sync.
- **Customers** — cash/credit types, credit limits, ledger, per-customer pricing, tiered pricing.
- **Pricing** — base price, tier discounts, customer overrides, promotional windows.
- **Finance** — GST invoices, payments, ledger, statements, profit & loss.
- **Attendance** — employees, shifts, punch-in/out.
- **Analytics** — KPIs, sparklines, revenue charts, top movers, dead stock, heatmaps.
- **AI Supervisor** — dead stock, low-stock prediction, reorder suggestions, peak hours, customer trends, payment risk, delivery delay prediction.

## Business Goals
1. Eliminate manual inventory checks.
2. Kill WhatsApp dependency for order intake.
3. Prevent stock conflicts (two customers claiming same stock).
4. Manage customer credit within enforceable limits.
5. Track every delivery with proof.
6. Forecast demand and prevent stockouts.
7. Provide always-on AI insights to management.

## Roles
| Role | Access |
|------|--------|
| Super Admin | Everything. |
| Warehouse Manager | Inventory, warehouse, orders, deliveries. |
| Accountant | Customers, payments, ledger, invoices, reports. |
| Delivery Partner | Assigned deliveries only. |
| Customer | Own orders, invoices, payments, catalog. |

## Success Metrics
- < 1s p95 API latency on hot endpoints (list inventory, place order).
- Zero over-selling events (verified via audit log).
- 100% of orders traceable through state history + reservations.
- AI supervisor generates ≥ 3 actionable alerts per active tenant per week.
- Onboarding of a new tenant (setup wizard → first order) in under 15 minutes.
