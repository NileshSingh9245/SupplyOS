# SupplyOS Codebase Snapshot and Memory Plan

Snapshot date: 2026-11-08. Workspace: `D:\SuppyOS`.

Inspection basis: backend feature/model/migration source, all 23 frontend source files, all 14 first-party Dart files across both apps, manifests/build configuration, all thirteen `.ai/` documents, CI, and saved test artifacts. No production-readiness claim is established by this inspection.

## Goal

Understand the actual codebase, preserve a dated project-memory snapshot, and explain the existing roadmap without treating documentation claims as verified behavior.

This plan contains the current static snapshot. The follow-on implementation is documentation-only: create `memory/CODEBASE_SNAPSHOT.md` from the verified observations below.

## Decisions and Scope

- Use the current working-tree source, including existing user edits, as the snapshot baseline.
- Keep the snapshot separate from the historical `memory/PRD.md` delivery log and the governing `.ai/` documents.
- Label capabilities as implemented in source, partial, planned/not found, or historically tested. Source presence is not proof of runtime correctness.
- Keep original project plans separate from recommendations arising from this inspection.
- Create one memory file. Do not add `AGENTS.md`, change Kilo configuration, enable Git snapshots, create a backup/archive, or change application code.
- Do not rewrite historical reports, roadmap checkboxes, or requirements as part of this task.
- Exclude environment values, credentials, tokens, dependency trees, caches, build outputs, and personal test-account data.
- Do not commit, push, deploy, start services, or run API tests against the old external preview deployment.

## Current Project Snapshot

SupplyOS is a supply-chain platform for Indian wholesalers, distributors, warehouses, and their customers. It targets INR/GST-aware catalog, stock reservation, ordering, delivery, credit, payments, and AI-assisted operations across five roles: super admin, warehouse manager, accountant, delivery partner, and customer.

| Area | Architecture and actual scope |
| --- | --- |
| Backend | FastAPI, SQLAlchemy async, PostgreSQL models, Alembic, Redis client, feature routers/services, and a Claude provider abstraction. Core operational APIs exist; several security and business guarantees remain incomplete. |
| Admin web | Declares Next.js 14.2.15, React 18.3.1, TypeScript, Tailwind, React Query, Zustand, Axios. Fourteen routes include eleven admin pages; locally persisted light/dark and responsive-shell source exists. Most pages have API calls, often list/create only; audit and reset UI are placeholders. |
| Customer mobile | Flutter, Riverpod, GoRouter, Dio. Real login and base-price catalog; orders screen is static. No cart, checkout, tracking, invoices, or credit UI. |
| Delivery mobile | Flutter, Riverpod, GoRouter, Dio. Real login and assigned-route list; stop interaction is empty. QR, OTP entry, proof capture, collection, and durable offline sync are absent. |
| Project knowledge | Thirteen `.ai/` governing documents, historical `memory/PRD.md`, root README/changelog/commit plan, and one saved backend test iteration. |

Mobile manifest constraints are Dart `>=3.3.0 <4.0.0`, Flutter `>=3.16.0`, Riverpod `^2.5.1`, GoRouter `^14.6.2`, and Dio `^5.7.0`. These are declared requirements, not verified installed versions. The advertised shared mobile package and platform runners are not present in the inspected first-party tree.

The backend has twelve mounted feature routers and 25 SQLAlchemy tables. The `.ai/` Clean Architecture/repository doctrine describes a target, not full compliance: domain/repository initializers are empty, services query SQLAlchemy, and delivery/payment logic lives in routers. Recharts, form/schema tooling, and mobile offline/scanner dependencies are declarations, not evidence of implemented features.

### Navigation Map

- `backend/server.py`: startup, middleware, health, and API mounting. Default feature prefix is `/api/v1`; legacy `/api` is also mounted.
- `backend/app/api/v1/__init__.py`: mounted auth, setup, settings, warehouses, products, customers, inventory, pricing, orders, deliveries, payments, and AI routers.
- `backend/app/core/` and `backend/app/shared/`: environment configuration, database/security/enums/errors/Redis, current-user/role dependencies, schemas, and audit helper.
- `backend/app/infrastructure/db/models/`: persisted tenant/auth, stock/catalog, customer/pricing/ledger, order/reservation/delivery/payment, and alert records.
- `backend/app/features/{inventory,pricing,orders}/service.py`: stock allocation and financial/order use cases; delivery/payment handlers remain in their feature routers.
- `frontend/src/app/{layout,providers,page}.tsx`: root shell, query/store initialization, and setup/login/dashboard redirects; `frontend/src/app/(admin)/`: the eleven admin pages and shell.
- `frontend/src/lib/{api,auth,settings,theme,utils}.ts`: HTTP and refresh handling, stores, theme persistence, and formatting; shared visual primitives live in `frontend/src/app/globals.css`.
- `mobile/{customer_app,delivery_app}/lib/main.dart`, `lib/core/api_client.dart`, and `lib/features/`: app routing, Dio clients, auth, and minimal feature screens.
- `.ai/`, `memory/PRD.md`, `.github/workflows/ci.yml`, `backend/tests/`, and `test_reports/`: rules/intent, historical backlog, CI definition, test source, and historical results.

### Local Configuration and Commands

- Backend connection names are `DATABASE_URL`, `DATABASE_URL_SYNC`, `REDIS_URL`, and `JWT_SECRET`; optional direct AI uses `ANTHROPIC_API_KEY`/`AI_MODEL`. Owners configure services privately; no hosted-builder key or SDK is required. This dated plan is historical; current setup is in the external-services guide.
- Backend Docker/CI declares Uvicorn `server:app` on port 8001. Database/Redis must be configured separately; the old README's supervisor environment is not evidence they run in this Windows workspace.
- Frontend variable names: `NEXT_PUBLIC_BACKEND_URL`, `NEXT_PUBLIC_API_BASE`, legacy `REACT_APP_BACKEND_URL`; Axios uses cookies. Default calls are same-origin `/api/v1`, and `next.config.js:6-8` has no forwarding rewrites. The legacy variable is not standard Next browser exposure.
- Frontend scripts, not executed: `npm run dev`/`npm start` run development mode on port 3000; `npm run build`, `npm run start:prod`, `npm run lint`, and `npm run typecheck` are declared in `frontend/package.json:5-12`.
- Both mobile clients use compile-time `SUPPLYOS_API_BASE` and default to an old external preview host. Do not copy that host into new setup instructions or run write tests against it; no runnable platform scaffolding or fresh Flutter validation was established.

### Actual Operational Data Flow

1. Setup initializes a tenant, admin, and warehouses; login establishes JWT access/refresh cookies, with Bearer support for API clients.
2. Catalog and customer APIs supply products, credit records, and pricing inputs. Pricing resolution implements customer override, then tier, then base price; the mobile catalog displays base prices instead.
3. Order creation computes prices and tax on the server. Confirmation changes status only; stock reservation is a separate action using inventory row locks.
4. Picking and packing advance whole-order status. Dispatch creates a delivery/OTP skeleton; per-line partial picking/backorders are not implemented.
5. Delivery finalization consumes inventory reservations and writes stock/ledger records. The direct staff order-delivery action bypasses the separate delivery OTP flow; proof presence is not consistently enforced.
6. Separate delivery completion can record cash/UPI and paid amounts. Standalone payments update the customer ledger but do not reconcile order paid amounts/status; `paid`/`completed` labels are not exposed as an operative API/client lifecycle. The ledger is customer running balances, not a complete general ledger.
7. AI rule scans and an LLM summary request path exist. Recurring scheduling, forecasts, and realtime streaming are not implemented.

## Important Evidence and Gaps

| Observation | Source evidence |
| --- | --- |
| Roadmap status is stale: pricing/orders/deliveries/payments/admin/AI remain unchecked despite implementation claims and existing source. | `.ai/ROADMAP.md:18-38`, `README.md:48-63`, `memory/PRD.md:35-57`. |
| Initial Alembic revision has no schema operations; startup unconditionally creates tables, including production. | `backend/alembic/versions/3a7b2a03cd3b_initial_schema.py:16-30`, `backend/server.py:31-36`. |
| Shared-schema tenant columns do not provide a complete multi-tenant account flow: registration chooses the first tenant and login/reset query email without tenant context. | `backend/app/features/auth/router.py:52-57`, `backend/app/features/auth/service.py:43-44,193-194`, `backend/app/infrastructure/db/models/user.py:17-23`. |
| Tenant-scoped records do not imply customer privacy or valid relationships: customer/order reads are too broad, delivery write guards let non-partner roles bypass assignment checks, and related warehouse/order/partner/location IDs lack consistent tenant validation. | `backend/app/features/customers/router.py:101-157,180-188`, `backend/app/features/orders/router.py:142-171,218-226`, `backend/app/features/deliveries/router.py:95-102,111-169`, `backend/app/features/orders/service.py:76-105`. |
| Auth hardening is partial: non-secure cookies, reset tokens printed rather than delivered, nonrotating refresh, and no password-reset session revocation. | `backend/app/features/auth/router.py:22,99-105`, `backend/app/features/auth/service.py:151-174,208-230`. |
| Credit protection is conditional on request flags, lacks a customer lock at creation, and is not rechecked during reservation/delivery. | `backend/app/features/orders/service.py:128-134,164-193,281-293`. |
| Existing-row stock locks are present, but nullable location uniqueness and per-item lock ordering create unverified duplicate-row/deadlock risks. | `backend/app/infrastructure/db/models/inventory.py:20-25,40-47`, `backend/app/features/inventory/service.py:24-40`, `backend/app/features/orders/service.py:180-189`; static inference, not reproduced failures. |
| Direct order delivery bypasses OTP/proof/collection; separate completion checks OTP but accepts optional raw proof URLs. | `backend/app/features/orders/router.py:315-324`, `backend/app/features/deliveries/router.py:50-54,152-214`. |
| Standalone payment recording leaves order financial state unchanged. | `backend/app/features/payments/router.py:45-80`. |
| Request-key storage/replay and unique payment references are absent, despite the documented idempotency contract. | `.ai/API_GUIDELINES.md:53-54`, `backend/app/features/payments/router.py:45-80`, `backend/app/infrastructure/db/models/order.py:110-125`; application-source inspection found no idempotency implementation. |
| Business-rule settings are stored/displayed but not consumed by operational services; currency updates have a branch/override defect. | `backend/app/features/settings/router.py:25-73,92-145`; operational-source search finds no settings consumers outside this router. |
| Inventory/order pages share a React Query key with incompatible response shapes. | `frontend/src/app/(admin)/inventory/page.tsx:59-63,178`, `frontend/src/app/(admin)/orders/page.tsx:226-230,337`. |
| Web auth/session cache isolation and role-aware navigation are incomplete. | `frontend/src/app/providers.tsx:11-18`, `frontend/src/lib/auth.ts:43-46`, `frontend/src/lib/api.ts:23-28`, `frontend/src/app/(admin)/layout.tsx:56-83,114-133`. |
| Currency/default settings are not reflected consistently in displays or creation forms. | `frontend/src/lib/utils.ts:8-20,34-51`, `frontend/src/app/(admin)/products/page.tsx:139-147`, `frontend/src/app/(admin)/customers/page.tsx:159-172`. |
| Customer orders and delivery stop workflows are placeholders, not API-connected end-to-end features. | `mobile/customer_app/lib/features/orders/orders_screen.dart:3-10`, `mobile/delivery_app/lib/features/route/route_screen.dart:35-37`. |
| Customer 401 refresh is unreachable for ordinary expired-session responses; delivery has no refresh interceptor. Sessions use in-memory cookie jars. | `mobile/customer_app/lib/core/api_client.dart:19-35`, `mobile/delivery_app/lib/core/api_client.dart:7-14`. |
| Delivery login accepts staff roles that the assigned-route endpoint rejects. | `mobile/delivery_app/lib/features/auth/auth_provider.dart:35-39`, `backend/app/features/deliveries/router.py:75-87`. |
| Redis is health-checked, not an implemented queue/cache/pubsub layer; worker, scheduler, WebSocket, PDF, S3 proof storage, attendance, and forecasting implementations were not found. | `backend/server.py:77-85`; inspected backend source compared with `.ai/ARCHITECTURE.md:33-38` and `.ai/PRODUCT_REQUIREMENTS.md:16-25`. |
| Audit is only partially written, with no mounted read API; many master-data/pricing mutations are unaudited. | `backend/app/shared/audit.py:12-34`, `backend/app/api/v1/__init__.py:6-31`, `frontend/src/app/(admin)/audit/page.tsx:3-24`; audit feature initializer is empty. |

### Validation Evidence, Not Current Test Results

- `test_reports/pytest/pytest_results.xml:1` records 30 backend tests, zero errors/failures/skips, dated 2026-07-19. This is historical external-environment evidence, not a current local test run.
- `test_reports/iteration_1.json:30` explicitly states frontend was not tested. No frontend/mobile end-to-end success is established.
- `README.md:65-70` claims all twelve business scenarios pass, but the saved suite does not substantiate that claim.
- The insufficient-stock test is sequential, not simultaneous reservation contention: `backend/tests/test_supplyos_e2e.py:308-334`.
- The delivery test calls the direct staff endpoint without the separate OTP/proof workflow: `backend/tests/test_supplyos_e2e.py:380-386`.
- The AI summary test can succeed with zero operations alerts: `backend/tests/test_supplyos_e2e.py:471-488`.
- The backend tests are synchronous `pytest`/`requests` end-to-end tests, not service-level unit/concurrency coverage. They share session state, depend on a pre-initialized server, and perform writes. The fixture's historical frontend environment-file fallback is not portable to this Windows workspace: `backend/tests/conftest.py:8-20,36-57`.
- No first-party frontend or mobile automated test setup was found. Frontend `data-testid` attributes and lint/typecheck/build scripts are not evidence of passing functional tests.
- CI defines backend API tests, frontend lint/typecheck/build, and Docker builds; no backend lint/typecheck, mobile checks, or browser end-to-end jobs are defined: `.github/workflows/ci.yml:59-149`.
- No builds, test runs, service startup, or live external requests were performed during this inspection.

## Existing Project Plans

The authoritative intent is in `.ai/PRODUCT_REQUIREMENTS.md`, `.ai/BUSINESS_SCENARIOS.md`, and `.ai/ROADMAP.md`. `memory/PRD.md:68-98` adds a prioritized historical backlog; its status needs to be interpreted against current source.

| Original phase | Planned outcomes | Current interpretation |
| --- | --- | --- |
| 1. Foundation | Monorepo, PostgreSQL/Redis, API versioning, JWT/RBAC/audit, Alembic, setup, CI. | Foundations exist; real migrations, auth/tenant guarantees, audit completeness, and reproducible validation remain unfinished. |
| 2. Core engines | Inventory/catalog/customers, base/tier/override pricing, order state machine and partial fulfillment, delivery proof/collection, payments/ledger. | Core APIs exist. Complete reservation/credit guarantees, partial fulfillment, returns/damage/transfers, proof enforcement, and payment reconciliation remain. |
| 3. Client apps | Full admin dashboard; customer catalog/cart/orders/tracking/invoices/credit; delivery routes/QR/OTP/proof/offline sync. | Admin is substantially API-connected but incomplete; both mobile apps remain prototypes. |
| 4. Finance and analytics | GST PDF invoices, statements/P&L, revenue charts, top movers, dead-stock heatmaps. | Payments/ledger/basic metrics exist; document generation, statements/P&L, and charts are planned. |
| 5. AI supervisor | Rule alerts, hourly Claude summaries, linear/XGBoost demand forecasts, route-optimization signals. | On-demand rule/summary paths exist; cadence, forecasting, and delivery intelligence remain planned. |
| 6. Optional AI | Feature-flagged WhatsApp-to-order, voice-to-order, chatbot, price optimization. | Future work; implementations were not found. |
| 7. Hardening | k6 concurrent-order tests, DB/Redis chaos tests, SOC2 preparation, encryption/backup/audit policies. | Planned; essential correctness/security work should precede expanding production usage. |

### Historical Priority Backlog

- **P0:** GST PDF invoices; reservation TTL/Celery worker; production migration enforcement; audit viewer; rack/shelf visual editor; best-fit warehouse selection.
- **P1:** Redis-backed live order updates; customer cart/order/tracking/PDF workflows; delivery QR/OTP/signature/photo/offline queue; analytics charts; multiple customer addresses; Redis sliding-window rate limiting.
- **P2:** WhatsApp Business order parsing; Whisper voice orders; price optimization; Google Maps route optimization; SOC2/encryption/backups.
- **Additional product requirements:** batch/expiry/damage/returns/transfers/barcode inventory behavior; backorders and scheduled/repeat order workflows; promotional pricing windows; employee attendance/shifts; deeper reorder, sales, payment-risk, and delivery intelligence. Some scheduled/channel fields and peak-hour aggregation exist, but fields or declared dependencies must not be counted as complete workflows.
- **Historical release instructions:** `COMMITS.md` is a proposed sequence, not release evidence or authorization to push. Use normal Git/GitHub tooling only on explicit request; no platform publishing task is required.

## Recommended Follow-On Order

These recommendations are derived from the inspected source, not newly approved feature work.

1. Establish a reproducible local/test baseline: real migrations, environment/API routing, CI, isolated test fixtures, and artifact/secret hygiene.
2. Repair tenant/account boundaries, role enforcement, secure refresh/session behavior, and per-session query-cache isolation.
3. Prove stock/credit/ledger invariants under contention and retries; enforce proof requirements, payment reconciliation, and effective settings. Add targeted regression tests before expanding features.
4. Implement reliable background reservations and AI cadence, realtime notifications, secure proof storage, and an audit read/view workflow.
5. Finish the original P0/P1 operational features: invoices, rack/shelf management, warehouse routing, then complete customer ordering and delivery apps on stable authenticated API contracts.
6. Add financial reports, analytics, demand/route intelligence, and only then optional AI intake/optimization modules; keep load/security/backup validation continuous rather than postponing it to the final phase.

## Memory Implementation Tasks

1. Re-read current instructions and check whether user changes or new memory files appeared since this dated inspection. Preserve all unrelated source/staged changes.
2. Create `memory/CODEBASE_SNAPSHOT.md` with the date, scope/verification limits, product/roles, component map, actual declared stack, local configuration/commands, data flow, implementation-status matrix, concrete risks, all seven roadmap phases, P0/P1/P2 backlog, and separately labeled recommendations. Distinguish list/create support from full CRUD, stored settings from enforced behavior, and model/status fields from exposed workflows.
3. Add source references for material claims and local command/config variable names only after checking their actual declarations. Avoid copying old preview URLs, environment values, account fixtures, or unverified infrastructure claims.
4. Include a maintenance note: re-check affected source and refresh the snapshot after meaningful milestones; `.ai/` remains the requirements/rules authority and the snapshot remains dated observation.
5. Verify the new document with file reads and inspect status/diffs when permitted, including untracked document contents without staging. Then report the memory path and summarize implemented versus planned work. Do not implement any listed fixes.

## Validation and Rollout

- Confirm every referenced first-party path exists and each key observation matches the current source, not just README/roadmap language.
- Check that the snapshot distinguishes historical passing tests from current static inspection and planned infrastructure from installed/operating infrastructure.
- Check that no credential values, dependency/vendor source, generated caches, or unrelated worktree changes enter the snapshot.
- The follow-on change adds one Markdown file. No API, schema, data migration, runtime rollout, restart, compatibility layer, or deployment is required.
- Review the final diff to ensure the memory file is the only implementation change; do not stage or commit unless separately requested.

## Out of Scope

Automatic agent-memory loading, changes to the governing charter, roadmap checkbox cleanup, new application features, runtime correctness claims, and decisions about multi-tenant onboarding, accounting semantics, proof policy, or offline replay are not part of this memory task. The snapshot should identify these boundaries, not silently choose product behavior.
