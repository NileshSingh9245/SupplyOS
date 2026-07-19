# BUSINESS SCENARIOS — SupplyOS

> Every scenario below is a test contract. Behavior must remain identical across releases.

## S1 — Concurrent stock reservation
**Given** Product `SUGAR-50` has 100 available units in `WH-1`
**When** Customer A places an order for 100 units *and* Customer B places an order for 60 units at the same instant
**Then** Customer A's order is `RESERVED` (100 units), Customer B's request returns `409 InsufficientStock`. Inventory row's `reserved_qty` becomes 100. No over-selling, ever.
**How**: `SELECT ... FOR UPDATE` on candidate inventory rows inside one transaction.

## S2 — Credit limit enforcement
**Given** Customer `CUS-A1B2C3` has `credit_limit = 50_000`, `outstanding = 37_000`
**When** A new credit-mode order with grand_total = 18_000 is created
**Then** Order creation returns `409 CreditLimitExceeded` before any stock is reserved.

## S3 — Delivery finalization ripple
**When** Delivery is marked `DELIVERED` with OTP verified + proof captured
**Then** In a single transaction:
- `OrderReservation.fulfilled_at` set for each line.
- `InventoryItem.quantity` and `reserved_qty` reduced by picked qty.
- `StockMovement` row inserted with type `outbound`.
- `Order.status` → `DELIVERED`, `Order.delivered_at` set.
- `Customer.outstanding` incremented if credit sale.
- `LedgerEntry` inserted (debit customer) with `balance_after`.
- `AuditLog` entry.

## S4 — Reservation timeout
**Given** Order is `RESERVED` but not `PICKED` for > 48 hours
**Then** Background job releases all `OrderReservation` rows: reduces `InventoryItem.reserved_qty` by the reserved amounts, moves order to `CANCELLED` (or `PENDING` re-review), logs `stock_movement` type `release`, and creates an `AIAlert` (warning).

## S5 — Customer-specific pricing
**Given** Product `SUGAR-50` has `base_price = 44`, Customer A has override `price = 40`, Customer B has none but is in tier `wholesale-a` (discount 5%)
**When** Each customer views the catalog / places an order
**Then**:
- Customer A pays ₹40.
- Customer B pays ₹44 × 0.95 = ₹41.80.
- Customer with no override or tier pays ₹44.

## S6 — Best-warehouse selection
**Given** Product available in `WH-1` (200 units, distance 30km) and `WH-2` (50 units, distance 5km) from customer address
**When** Order is placed
**Then** Selection algorithm prefers full-fulfillment closest warehouse (`WH-1`). If nearest can fully cover, prefer nearest. Configurable per tenant (`nearest_first` | `most_stock_first`).

## S7 — Partial fulfillment / backorder
**Given** Customer orders 100 units but only 60 are available in target warehouse
**Then** Order splits: 60 reserved (child order `-A` continues state machine), 40 becomes a `backorder` (state: `pending`, meta.backorder = true) linked to parent. AI alert raised to procurement.

## S8 — Damaged / return
**Given** Delivery partner marks 5 units damaged during pickup, or customer returns 2 units after delivery
**Then**:
- Damage: `damaged_qty` incremented, `quantity` decremented, movement type `damage`.
- Return: `quantity` incremented (back to stock), movement type `return`, credit note appended to ledger.

## S9 — Multi-channel order intake
Orders may arrive via `app`, `phone`, `whatsapp`, `manual`. All flow through the same order service — no fast paths that skip reservation/credit checks.

## S10 — AI supervisor alerts
Cron job runs analytics every 15 minutes and Claude Sonnet 4.5 is invoked once per hour with aggregated metrics. Alerts are persisted to `ai_alerts` and streamed to admin dashboards via WebSocket.

## S11 — Refresh token rotation
On `/auth/refresh`, old refresh token's `jti` is revoked and a new one issued. Reuse of a revoked jti triggers global logout of all sessions for the user (potential compromise).

## S12 — Audit immutability
Audit log rows are append-only. Deletes are forbidden by policy. Rotation is by archival to cold storage after 2 years.
