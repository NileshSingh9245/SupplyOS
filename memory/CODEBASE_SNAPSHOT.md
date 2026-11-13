# SupplyOS Codebase Snapshot

Initial snapshot date: 2026-11-08. Current password/pricing and security update: 2026-11-12.
Initial snapshot base Git revision: `06a9b7c55598b9788a8d891ff70b803a77213ca4` on `main`.
Basis: the working tree, including existing uncommitted changes, not just that revision.

This is dated project memory, not a full backup or a production-readiness certificate. The initial static inspection covered backend source, 23 original frontend source files, all 14 first-party Dart files, configuration, governance, and historical artifacts. Development and runtime verification subsequently began; the current checkpoint below supersedes resolved baseline observations.

## Current Password and Pricing Checkpoint - 2026-11-12

- Root full owned backend: **1078 passed/3 unchanged skips in573.51s**. Frontend: **208 development/208 production passes**, clean lint/types and **22-page build**; private password/pricing routes are dynamic/no-store/no-referrer. Mobile: **177 shared +62 customer +24 delivery =263 VM passes**, three clean analyses and verified Dart formatting. All earlier onboarding/finance/stock/proof/session cases remain; focused322 auth/staff and175 pricing/financial cases are inside full totals, not added to them.
- Authenticated own-password change accepts only current/new secrets and no query/target identity. All current active roles require persisted signed session and current-password reauthentication. User-first locks, all remaining session/reset waits, final eligibility/expiry checks, audit/hash/epoch retirement and cookie clearing are transactional; explicit wrong-current attempts retain bounded durable lockout without partial rotation.
- Web `/change-password` uses shared strict password validation, memory-only fields, coordinated cancellation/cache retirement and no automatic refresh/replay. Uncertain network/408/5xx/noncanonical200 replies clear identity and preserve only a safe unconfirmed notice; successful self-revocation cannot remove the confirmation before rendering.
- Web `/pricing` has owner/manager tier creation and discount-only editing; owner/accountant customer ID-bound tier assignment/clearing and override saving/removal. Changes are explicitly reviewed, role/tenant/user/epoch guarded, audited and re-read after failures. Legacy60-character tier creation stays compatible; new assignable names fit30 characters and names never change.
- Customer-only `/catalog` derives tenant/profile from authenticated state, rejects shadow/duplicate query authority, and returns bounded exact price/tax plus declared currency with ID/SKU/name/unit only. Eligibility/currency read locks remain through authorization. Native catalog now consumes this contract, including zero prices and non-INR currency, without a base-price or float fallback.
- Order creation shares one immutable SQL product/price/tax batch and pure common decimal validation. Override (including zero), tier and base precedence and v1 `/products`/resolver contracts remain; existing orders never reprice. Foreign targets, expiry/deactivation lock waits, audit rollback and coherent41.80 pricing are real PostgreSQL regressions. The existing AI-alert assertion follows the declared severity enum rather than rejecting warning alerts from combined finance fixtures.
- No new migration, deployment, provider activation, SDK/license provisioning, signing or Git publication. Existing private configuration, user preview/data and unrelated/staged edits were preserved. Cached Flutter was reused; only this session's generated TypeScript include paths were removed.
- Next authorized application work remains warehouse association, customer cart/checkout, invoices/statements/audit, typed business settings/promotions and native delivery execution. Live services, full security/RLS/ingress/jobs/durability and public-API/signed-APK acceptance remain separate gates, not completed by these local regressions.

## Previous Onboarding Checkpoint - 2026-11-12

- Root full verification: **954 passed/3 unchanged skips in363.06s**, frontend **165 dev/165 production**, lint/types and **20-page build**. Test helpers use authenticated owning actors, not anonymous tenant IDs; original login/reset/stock/financial/receipt coverage remains. Focused170 backend and63 UI onboarding cases are within full totals, not additive.
- Setup requires private operator authorization before parsing, serializes first-owner creation and refuses existing/incomplete tenants without automatically verifying email. Public status hides identity; authenticated status exposes only the caller's tenant.
- `features/staff/` and `/staff` implement owner-only named staff, safe contact/role/activity updates and all-session/reset retirement, including reactivation. Actor/target User locks are sorted and non-key; no owner/customer/self conversion/deletion or password/email editing.
- Customer records and new customer accounts are separate. Owner/accountant supplies tenancy; optional UUID is only an assertion. Blank contacts become null, new accounts remain unverified/cash with holder-selected passwords, credit edits preserve commitments and assignment locks eligibility before Delivery.
- `shared/private_route.py` masks credential input/errors, attaches no-store and logs only unexpected error type. SQL parameters are hidden. Owned backend marker disables dotenv for API/Alembic/tests; frontend test preload denies dotenv and supports fixture-only dev/production builds. No live credential/provider/SDK or preview reset occurred.
- Remaining: email/OTP/invitation delivery, password changes, existing-profile linking, warehouse association, managed pricing, checkout/native execution/invoices/audit, general limits/RLS/ingress/durability and release gates. Continue authorized code without full-security/production claims.

## Previous Application Security Checkpoint - 2026-11-12

- Goal continuation is application completion, not publishing. Preserve prior financial/stock/POD safeguards and complete cross-role workflows without a fabricated provider/localhost release substitute.
- Full owned backend: **781 passed/3 skipped in 295.51 seconds**. Frontend: **102 dev/102 production**, lint/types and the **19-page build**; **10 separate isolated Chrome browser-security tests** pass. The missing local bundled Playwright browser was handled with the installed Chrome channel, not skipped assertions.
- `BrowserSecurityMiddleware` guards all unsafe JSON/multipart routes before body parsing with explicit trusted origin/referrer checks; no-header native compatibility remains. UUID IDs, nosniff/framing/referrer/partial CSP headers and appropriate HSTS are tested. Proxy/header preservation, broader rate limits and comprehensive XSS/production security remain unverified.
- Proof journal migration head is `20261112_0006`. Every new write has committed ownership first; final auth/session/assignment/state is rechecked through commit. A non-key User lock blocks auth changes while permitting partner FK checks. Real PostgreSQL tests cover revocation/receipt winning contention, assignment/upload races, ambiguous commits and actual anon/authenticated journal ACL/RLS denial. Serving uses verified bytes from held native handles, not `FileResponse` reopening a checked path.
- Hosted proof-store integration remains default-off: `PROOF_STORAGE_BACKEND=local`, `APPROVED_FREE_STORAGE=false`, `SUPABASE_VERSIONING_VERIFIED=false`. Receipt project/bucket/version/operation identity is persisted; private ENABLED versioning, metadata and hash are verified without public/signed/latest fallback or automatic deletion. Public v1.94.0 REST source and offline fixtures are not deployed capability, WORM retention or backup/restore attestation.
- Local site preview `http://localhost:3000` uses fresh temporary resources because the earlier preview was unreachable; it was not reset after startup. Later source fixes were tested in fresh isolated verifier APIs; the existing preview is not silently restarted to import them. Redis/recovery/live providers remain unavailable or disabled there.
- Flutter 3.47.9/Dart 3.13.7 are available. Shared core/customer/delivery root verification is **177/53/24 tests, 254 VM passes**, three clean analyses, zero failures/skips. Renewal barriers protect delayed 401s, in-flight 200s and asynchronous decoding before replay/publication; epoch/key and replacement barriers are rechecked after waits. All 239 earlier cases remain plus 15 new race/cookie-isolation tests. Source has exact roles, scoped caches and real customer order/history reads. Android source/resources/bootstrap are validated, not APK runtime; SDK36/engines/targetGradle/NDK/AGP/Kotlin, licensing/signing/public API and uncached Flutter web SDK remain gates.

- That checkpoint's next onboarding work is now recorded above. Continue remaining workflows with its credential/session, audit/revocation and FK-compatible foundations, not fake verification or deployment claims.

### Android Runner Evidence

- Forty Android-only files prepare customer/delivery runners; IDs are `com.supplyos.customer` and `com.supplyos.delivery`, with `.debug` diagnostic variants. Internet-only permission stress merges, twenty strict XML documents, eighteen compiled resource files/four static links and thirty-eight source/resource assertions passed using cached SDK35 tools. Static ZIP libraries are not APKs; Gradle/Kotlin/runtime was not tested.
- Main/profile/release use system CAs, no cleartext, disabled backup and no unsigned/debug release fallback. Debug resource exceptions allow only exact emulator/loopback hosts. No signing material was read or generated.
- Cached Gradle8.9/JDK21 generated modern launcher/JAR files offline without URL validation. SHA256 `498495120a03b9a6ab5d155f5de3c8f0d986a449153702fb80fc80e134484f17` matches the official8.9 bootstrap; target9.3.1 archive remains SHA-pinned. Bytecode verifies hashing before extraction and safe archive paths. The earlier2.10 bootstrap also supported checksum enforcement; the version-only suspicion was corrected, not recorded as a proven bypass.
- Existing unrelated/staged changes and Git history were preserved. Filename-only inspection found no tracked root/backend/frontend environment or mobile signing-key files; this is not a complete credential scan or a clean-index certification. No provider credentials were inspected or activated.

## Previous Cloud/Fee-Policy Checkpoint - 2026-11-11

- User runtime target is independently hosted Vercel/Supabase/Render web/API with Android APKs, NOT developer-PC services/tunnels. Local tools serve build/verification only. Hosted private proof persistence, a real public HTTPS API and reproducible private Android signing are required before client distribution.
- `FREE_ONLY_MODE=true` denies known paid AI even with a populated key; `APPROVED_FREE_SMTP=false` denies unapproved external mail before limiter/token work. Hosted DB/cache configuration remains valid; provider fee/quality approval is not inferred from hostname. Rule checks remain available and summary capabilities/status are honest, with no fabricated local substitute.
- Full owned backend: **520 passed/3 unchanged skips in 223.12 seconds**. Frontend: **102 dev and 102 production passes**, lint/types and **19-page build**. Embedded Alembic now preserves preexisting safety loggers; privacy/log assertions remain intact. Counts are not performance/cloud proof.
- Available Vercel scope is Hobby, not selected for a client-commercial deployment under its terms. Render Free sleep/ephemeral disk/SMTP restrictions and Supabase Free quotas/pauses remain release constraints. No accounts, plans, application-provider credentials or deployment were activated.
- Hosted proof adapter and APK scaffold/readiness research are source-only; no public bucket, ephemeral file, placeholder/localhost APK, or unproven local model is shipped as an equivalent capability. Prior private/staging/history/preview safeguards remain. Current setup and held gates are in `docs/EXTERNAL_SERVICES.md`.

## Previous Recovery Checkpoint - 2026-11-10

- Opt-in SMTP recovery and public `/forgot-password`/`/reset-password` pages are implemented. HMAC Redis admission and no-wait capacity precede lookup; post-response owned SQL work rechecks current auth email/token state after committed issuance. Disabled/unavailable admission is `503`, limits `429`, and accepted eligibility/delivery outcomes share generic `200`.
- Links use fragments, are stripped from browser history and stay only in memory. Recovery survives anonymous bootstrap/session revocation; an older response cannot discard a newer link. Successful reset clears cookies, revokes sessions and requires new login.
- Source: `backend/app/features/auth/recovery.py`, `backend/app/infrastructure/external/smtp.py`, auth router/repository/settings, and frontend `(account)`/recovery/session code. Existing issuance/redemption logic and migration head `20261109_0005` remain unchanged.
- Full owned backend: **507 passed, 3 skipped in 270.45 seconds**, including real PostgreSQL recipient/token/cookie checks and offline SMTP/admission/cancellation coverage. Skips remain live AI and two native Linux filesystem cases. Counts are not additive with earlier baselines.
- Frontend: **100 passed in both development and production**, lint/types and a **19-page production build**. Installed Chrome was selected through the supported executable override; test servers/database/proofs were isolated from the user preview.
- Noncredential working-tree metadata, empty retired-platform directories and stale compiled code were cleaned without changing historical report counts/timestamps. Private credential artifacts, Git index/history and unrelated staging were not changed or certified clean.
- SMTP is disabled by default; owned runners clear all SMTP/recovery settings. No other provider stack was selected or activated. Native Redis/Lua, live sender/TLS/DNS, whole DNS deadlines, durability, finite post-recheck race and production trust remain operational work. Private setup is in `docs/EXTERNAL_SERVICES.md`.

## Previous Finance/POD Checkpoint - 2026-11-09

- Latest coordinator-owned full backend verification: **354 passed, 3 skipped in 260 seconds**. It includes the previous auth/privacy/stock/schema/process coverage and financial/POD corrections. Skips are one unconfigured live-AI case and two native Linux filesystem cases; no native Linux filesystem success is claimed on this Windows host.
- Frontend: **87 passed in both development and production configurations**, all earlier 47 retained plus 40 new cases; lint/typecheck and the 17-page production build pass. Browser/proxy fixtures are separate from backend integration and live provider validation.
- Auth `0002` and canonical stock `0003` remain verified foundations. Financial `20261109_0004` adds cash/credit modes, gross holds, signed balances, pending cash funding, constraints, and transactional replay. Proof `20261109_0005` adds delivery-bound private receipts; it is current migration head.
- Financial paths lock Order -> Customer -> Delivery -> canonically sorted product/inventory rows. Cash delivery needs full allocated cash/UPI/bank funds; approved credit may remain unpaid. Payment allocation changes actual paid/due amounts, never treats credit notes as funds, and reaches order `paid` only after physical delivery.
- Local PNG/JPEG proof upload/authenticated read and a shared OTP/signature/photo/funding finalizer are implemented. Actual request bytes are bounded before multipart parsing; Pillow 13 verifies/decodes images within 5 MiB/20M pixels. File ownership/permissions, metadata, digest, tenant/delivery/kind are checked at their boundaries.
- Windows storage creates/verifies process-owner/SYSTEM/Admin ACLs without repairing unsafe existing paths. The returned `Path` is not an open read handle; subsequent reopen still requires trusted ancestry/owner processes. Failed writes may leave private partial orphans; native Linux/filesystem/deployment guarantees remain unverified.
- Core requirements install from public packages without a private platform SDK. Settings are immutable/validated, signing material can be generated without printing it, and secret values are hidden from representation/error/export paths. Private configuration still needs operator-owned OS permissions.
- Pure metadata lives in `backend/app/infrastructure/db/base.py`. Frozen baseline `20261108_0001` has real DDL, validates a matching legacy schema without recreating its data, and rejects mismatches. Startup checks revision/tables/columns instead of running `create_all`.
- The admin now has one typed product-query shape, bounded/shared auth refresh including bootstrap, cancelled superseded requests, cleared account/tenant/role caches, role-aware page guards, and a server-only `BACKEND_URL` same-origin proxy.
- Direct Anthropic Messages API uses core `httpx` and manually configured `ANTHROPIC_API_KEY`; no private-SDK/provider fallback is present in current source. No live AI account was called/verified. Unconfigured reset email returns `503`, not a logged token or false delivery claim.
- Earlier checkpoints (76 backend/one skip, initial 8 migration cases; later 171 backend/one skip, separate PostgreSQL-tooling 23 and frontend 47) are retained as dated history, not counts to add to the latest full run. Unavailable Redis is not claimed healthy.
- Review corrections enforce exact legacy columns, valid unconditional indexes, destructive rollback opt-in, explicit settings-over-environment precedence, and bounded kill-on-close child ownership, including abrupt-parent-exit tests.
- PostgreSQL 15.19 verification runs in owned disposable Windows clusters, not an existing database or Windows service. API runners use generated private credentials, a loopback test identity, bounded lifetime, and owned process cleanup. Redis, Flutter, persistent deployment, and live provider setup remain unavailable/unverified here.
- The current preview is `http://localhost:3000/setup`, backend port 8001, on a real temporary PostgreSQL database. Its initial setup page/proxy response was checked by the coordinator; documentation maintenance did not re-poll, reset, restart, or write to it. `run_preview.py` starts a fresh disposable dataset, not permanent business storage, and does not start Redis.
- Next work: staff provisioning/OTP messaging, email/reset UI, external S3/gateway/maps/WhatsApp/voice, broader security/CSRF/rate limits, operative locale/settings, mobile/platform workflows, invoices/full audit, jobs/realtime/forecasts, and production durability/backups. The tested financial/local-POD milestone is not all twelve scenarios or a complete release.
- Entry points: `backend/tools/init_env.py`, `backend/tools/run_preview.py`, `backend/tools/verify_backend.py`, `frontend/tests/`, and `docs/EXTERNAL_SERVICES.md`. CI source was updated, but no remote Actions/Docker/deployment execution occurred. This maintenance only read source/docs; it did not repeat tests or inspect private configuration/accounts.

## Reading Order and Authority

1. Read `.ai/AGENT_INSTRUCTIONS.md` and the other `.ai/` documents before changing the project. They define required architecture, security, database, API, and business behavior.
2. Use this snapshot to navigate the implementation and identify gaps. Recheck source references before relying on an observation after subsequent changes.
3. Treat `memory/PRD.md`, `README.md`, `CHANGELOG.md`, and `COMMITS.md` as product/history/planning context, not independent proof that a feature works or a release occurred.

Requirements and observations are deliberately separate: `.ai/` describes intended behavior; this memory records current implementation and verified limits. The roadmap has a current checkpoint; historical PRD/changelog/test records are preserved, not relabelled as fresh results.

## Product and Intended Roles

SupplyOS, also described as Smart Supply Chain OS, targets Indian wholesalers, distributors, warehouses, and retailers. It connects stock, customer-specific pricing, orders, delivery, credit, payments, and AI-assisted operations through an admin web app and two mobile apps. INR and GST are central product requirements.

| Role | Intended access |
| --- | --- |
| `super_admin` | Business configuration and all operational modules. |
| `warehouse_manager` | Warehouses, inventory, orders, and deliveries. |
| `accountant` | Customers, payments, ledger, invoices, and reports. |
| `delivery_partner` | Assigned deliveries and their completion workflows. |
| `customer` | Own ordering, invoices, payments, credit history, and catalog. |

These are intended boundaries, not a claim that current authorization enforces all of them. Source: `.ai/PRODUCT_REQUIREMENTS.md:3-43` and `.ai/SECURITY_RULES.md:10-16`.

## Architecture and Declared Stack

| Component | Current implementation and declarations |
| --- | --- |
| Backend | FastAPI 0.115.6, SQLAlchemy 2.0.36 async, Alembic 1.14.0, Pydantic 2.10.4, PostgreSQL drivers, Redis client, bcrypt/PyJWT, and Pillow 13. Thirteen feature router groups include proof/replay/journal records. Docker/CI target Python 3.11. |
| Database/cache target | PostgreSQL 15/Redis 7 remain the deployment target. Disposable PostgreSQL 15.19 is verified locally; Redis/persistent production services remain unconfigured/unverified. |
| AI | Optional direct Anthropic Messages through core HTTP with owner-supplied private key. AI remains part of the backend, not a supervisor microservice; current configuration accepts only `anthropic`. |
| Admin web | Next.js 14, React 18, TypeScript, Tailwind, React Query, Zustand, Axios, Lucide and Sonner; exact versions are in current manifests/lockfiles. Recovery/finance/POD source exists; the latest production build reports 19 pages. |
| Customer mobile | Flutter/Riverpod/GoRouter with shared core, exact customer role, real paginated catalog/orders, read-only detail/history and visible logout/retry. |
| Delivery mobile | Flutter/Riverpod/GoRouter with shared core, exact delivery-partner role and real read-only assigned routes; no simulated stop action. |
| Shared mobile | `mobile/packages/supplyos_core`: Dio/cookie/browser transport, typed failure/decimal/date/pagination, session/query generation and shared credential widgets. |

Both apps retain version `0.1.0+1`, Riverpod `^2.5.1` and GoRouter `^14.6.2`. Their shared package imposes the effective Dart `>=3.13.0`/Flutter `>=3.47.0` toolchain. Core lock resolves Dio 5.11.1, CookieJar 4.0.9, CookieManager 3.5.0 and WebAdapter 2.2.2 offline. Unused scanner/location/persistence/image/codegen dependencies were removed; their former declarations were never implemented capabilities.

The Clean Architecture/repository pattern in `.ai/ARCHITECTURE.md` is a target, not full compliance. Backend services query SQLAlchemy directly; money/finalization lives in shared feature services, assignment/OTP remains in routers and some domain/repository initializers remain stubs. Frontend visual primitives are primarily shared CSS. Shared mobile core and Android runners now exist; this does not establish Android/browser runtime acceptance.

Web payment form/schema and signature-canvas/private-preview code are now implemented. Recharts/Framer Motion, mobile scanner/signature dependencies, and Hive are not evidence of implemented analytics, native capture, or offline synchronization.

Declaration sources: `backend/requirements.txt`, `backend/app/api/v1/__init__.py`, `backend/app/infrastructure/db/models/`, `frontend/package.json`, the finance/delivery feature source, and both mobile `pubspec.yaml` declarations.

## Navigation Map

| Path | Purpose |
| --- | --- |
| `backend/server.py` | FastAPI startup, CORS, request IDs, health endpoints, and API mounting. |
| `backend/app/api/v1/__init__.py` | Mounts auth, setup, settings, warehouses, products, customers, inventory, pricing, orders, deliveries, proofs, payments, and AI routers. |
| `backend/app/core/` | Environment settings, database sessions, security, enums, exceptions, and Redis client. |
| `backend/app/shared/` | Current-user/role dependencies, common schemas, audit helper, and transactional idempotency claims/replay. |
| `backend/app/infrastructure/db/models/` | Tenant/auth/audit, warehouse/catalog/stock, customer/pricing/ledger, order/reservation/delivery/payment, alert, replay, and proof receipt records. |
| `backend/app/infrastructure/db/base.py` | Pure declarative metadata/mixins, shared by models and Alembic without loading runtime secrets. |
| `backend/app/features/` | Routers plus stock, pricing, orders, money, and proof-image/integrity services. |
| `backend/app/infrastructure/storage/` | Private local held-handle reads, exact-version Supabase transport, immutable configuration and provenance-selected proof-store facade. |
| `backend/app/infrastructure/external/ai_provider.py` | AI provider boundary. |
| `backend/alembic/` | Historical no-op followed by frozen baseline, auth0002, stock0003, financial0004, proof0005 and uploadjournal0006. Online financial attribution and evidence-preserving downgrade guards are included. |
| `frontend/src/app/` | Root layout/providers/redirect, setup/login, and `(admin)` shell/pages. |
| `frontend/src/lib/` | HTTP/session/stores/theme/formatting, typed product/finance queries, UUID request intents, and role/page policy. |
| `frontend/src/features/` | Payment form, authoritative finance summaries, delivery/OTP/collection workflow, signature canvas, and authenticated blob previews. |
| `backend/tools/run_preview.py` | Windows-owned disposable PostgreSQL/API/Next preview on ports 8001/3000; temporary data, no Redis start or live AI. |
| `frontend/src/app/globals.css` | Shared visual primitives, theme variables, and responsive layout rules. |
| `mobile/customer_app/lib/` | `main.dart`, core clients/theme/formatters, and auth/catalog/orders features. |
| `mobile/delivery_app/lib/` | `main.dart`, core client/theme, and auth/route features. |
| `backend/tests/` and `test_reports/` | Stateful backend API tests and historical results. |
| `.github/workflows/ci.yml` | Backend tests, frontend lint/typecheck/build, and Docker build definitions. |
| `.ai/` and `memory/PRD.md` | Governing intent and the historical prioritized delivery backlog. |

## Actual Operational Flow

1. First-launch setup creates a tenant, admin, and warehouses. Login creates JWT access/refresh cookies; backend current-user dependencies also support Bearer authentication and reload the database user's role/tenant.
2. Pricing resolves customer override (including zero), then tier discount, then base price. Order creation consumes one immutable product/pricing/GST SQL snapshot with exact Decimal totals, defaults cash/credit mode from the customer, and creates a pending order without stock reservation. Credit mode acquires a gross total hold under the customer lock. Legacy `is_credit=False` cannot bypass capacity checks. The mobile catalog displays authenticated customer-effective prices/tax and tenant-declared currency from `/catalog`, not `/products` base prices.
3. Confirmation changes status only. Reservation follows Order -> Customer and canonical product/row lock order, rechecks live financial commitments, then allocates FIFO separately from lock order. It requires the whole quantity; available stock is quantity minus reserved quantity.
4. Picking and packing advance whole-order status. Dispatch creates a delivery/OTP record. Physical stock is consumed on delivery, not dispatch; cancellation releases unfulfilled reservations.
5. Both staff order delivery and delivery `/complete` invoke one guarded finalizer: Order -> Customer -> Delivery -> canonical stock, verified OTP, both delivery-bound private proofs, and actual funding checks. It updates stock, sale/receipt ledger, holds, history/audit and replay within one transaction. Cash must be fully allocated; approved credit may be delivered unpaid. No arbitrary proof URL bypass is accepted.
6. Cash/UPI/bank receipts with `order_id` allocate the actual amount and update paid/due. Orderless receipts are explicit advances; credit-note mode is orderless and not collected funds. Every delivered sale is debited once; receipts are credited once; signed negative outstanding is retained as account credit. Payment status and physical order status are distinct; `paid` order transition requires physical delivery. This remains a customer ledger, not a full general ledger/provider settlement system.
7. Rule analysis and optional Claude summaries are request-triggered. A background summary attached to a request is not a recurring scheduler or durable worker.

The exposed progression is `pending -> confirmed -> reserved -> picked -> packed -> out_for_delivery -> delivered -> paid` where funding allows; direct `pending -> reserved` is also allowed. Prepayment can make `payment_status=paid` before physical delivery without advancing the physical order. `completed` exists in the state definitions but has no exposed administrative closeout action. Partial fulfillment/backorders are not implemented.

Flow sources: setup/dependencies, pricing/inventory service, `backend/app/features/orders/service.py` (`create_order`, `reserve_order`, `finalize_delivery`), `backend/app/features/payments/service.py`, and both delivery routers.

### Finance and Proof DTO/Retry Boundaries

| Contract | Actual fields/behavior |
| --- | --- |
| Order | `payment_mode`, `payment_status`, `grand_total`, `amount_paid`, `amount_due`, `credit_hold_amount`. Default mode follows the server customer type. |
| Customer finance | Signed `outstanding`, `credit_held`, `cash_funded_pending`, `credit_exposure`, `available_credit`, `advance_balance`. Exposure/available-credit are server-calculated; an unallocated advance or credit note is not cash-order funding. |
| Payment | Decimal `amount`, `mode`, optional `order_id`, and `allocation_kind=order_payment/unallocated_advance/credit_note`. GET supports customer/order filters; the admin list currently sends customer only. |
| Proof upload | Multipart `kind` plus `file`; `ProofOut` fields are `id`, `delivery_id`, `kind`, `mime_type`, `size_bytes`, `created_at`, canonical `/api/v1/delivery-proofs/{id}` `url`. Read is authenticated, private/no-store, nosniff, delivery/tenant/ownership scoped. |
| Completion | `cash_amount`, `upi_amount`, `signature_url`, `proof_photo_url`; returns DeliveryOut or the legacy order resource. Both proof kinds are required and file integrity is rechecked. |
| Replay | Optional UUID `X-Idempotency-Key` for order creation, payments, and completion. Scope is actor+tenant+operation; same normalized payload replays original JSON/status, changed payload `409`, failed claim/effect rollback, database-serialized concurrency. Legacy order/delivery completion have distinct operation names. |

Replay records have 24-hour expiry metadata but retained records remain protected; there is no automatic key-reuse promise. UI keys survive network/408/5xx, automatic auth refresh, and same-page modal reopen; success/definitive other `4xx`/new payload gets a new intent. They are not durable across page reload/offline restart. Legitimate identical payments use new keys rather than body deduplication. Idempotency is not bank-reference verification and does not cover every mutation/upload.

Sources: `payments/schemas.py`, customer/order/payment models and controllers, `proofs/router.py`, `shared/idempotency.py`, `frontend/src/lib/finance.ts`, `frontend/src/lib/intent.ts`, and finance/delivery feature components. Image limits are 5 MiB/20M pixels with Pillow 13 verification/full decode; actual pre-multipart body cap is 5 MiB+64 KiB, including chunked/false Content-Length/legacy/invalid-ID paths.

## Implementation Status

Status language: **present** means source exists, **partial** means only part of the intended workflow exists, **not found** means no implementation was found in inspected first-party source, and **historical** means a saved result rather than current runtime validation.

| Capability | Source-backed state | Missing or incomplete work |
| --- | --- | --- |
| Setup/auth | Private serialized setup, owner-controlled staff/customer intake, own-password changes, tenant identity, role/foreign-ID privacy, stable sessions and recovery/browser/mobile session/cache boundaries are covered locally. | Email/invitation verification, forced onboarding changes, profile linking/warehouse association, live sender/Redis, broader ingress/limits and tenant administration remain. |
| Master data | Warehouses/racks/shelves and categories have list/create APIs; products/customers have list/create/detail/patch; tier/override management and an exact self-catalog are implemented. | Do not call every module full CRUD. Admin lacks many editing/detail controls, promotional windows, rack/shelf management and multiple addresses. |
| Inventory | Adjustments/movements/stats, canonical nullable-location uniqueness/upserts, locked reservation/release/consume, nonnegative constraints, and representative real mixed contention pass. | Transfer/damage/return, expiry-aware/batch/barcode workflows, reservation TTL, production load/chaos and wider operational coverage. |
| Orders/deliveries | Whole-order cash/credit state, gross holds, paid/due allocation, delivered/paid transition, assignment/OTP, and unified private-proof/funding finalization. | Staff provisioning/OTP transport, partial shipments/backorders, best-warehouse/geographic routing, administrative completed closeout and complete mobile execution. |
| Finance | Guarded manual receipt allocation, signed customer ledger/advance, orderless credit-note distinction, pending funding exposure, constraints, and same-intent replay. | Gateway/webhooks/settlement/refunds, GST PDFs, statements/P&L, full receivables reporting and general-ledger workflows. |
| Proof storage | Private local held-handle reads, journal/receipt integrity, post-I/O auth serialization, strict image/body limits, Windows ACL checks and gated exact-version Supabase REST facade. | Live provider capability/retention/backup-restore, durable production mount, native Linux, generic S3 and manual orphan reconciliation/cleanup jobs. |
| AI | Present low-stock/dead-stock/credit-risk checks, peak-hour aggregation, stored/dismissible alerts, and manual summary requests. | Scheduled cadence, forecasts, richer sales/finance/delivery intelligence, realtime alert delivery, and optional intake/optimization modules. |
| Settings | Whitelisted JSON persistence and admin editor; safety rules are enforced by source, not automatically by every saved option. | Locale/currency patch handling and operational consumption are partial. Saved signature/OTP/scheduling toggles do not override the implemented mandatory finalizer. |
| Admin web | Responsive/theme/session/role/query/proxy, recovery/password changes, staff/customer intake, reviewed pricing, finance/retry, private proofs;208 dev/prod plus earlier separate browser-security tests. | Audit UI, charts/PDFs, warehouse association, wider editing/pagination/locale and live business acceptance. |
| Customer mobile | Exact-role session, customer-effective catalog with declared currency/tax, paginated orders/detail/history and actual server decimals/loading/empty/error/retry/navigation/logout. | Cart/checkout, live tracking, invoices/credit/payment UI, encrypted persistent/offline session and real APK/browser acceptance. |
| Delivery mobile | Exact-role session/cache/logout, bare assigned-route DTOs, safe identifiers and scaled layouts; route is explicitly read-only. | QR/OTP, native proofs/collection, maps/GPS, encrypted outbox/sync and real APK/browser acceptance. |
| Infrastructure/audit | Guarded migrations through `0006`, schema startup, owned runners, Docker/CI source, browser boundary, journal RLS, selected audit and recovery HMAC limiter. | Whole-app RLS/least-privilege runtime, durable jobs/mail, native Redis/general limits/realtime, comprehensive audit, native Linux and production policies. |

Admin pages are under `frontend/src/app/(admin)/`. Customer order views are under `mobile/customer_app/lib/features/orders/`; delivery execution beyond `features/route/` remains deliberately absent rather than a fake tappable action. Shared mobile contracts live under `mobile/packages/supplyos_core/lib/`.

## Important Gaps and Failure Modes

The following are static observations or explicitly labeled risks, not reproduced production incidents.

| Gap | Evidence |
| --- | --- |
| Resolved baseline gap: real DDL/strict legacy validation and startup follow the no-op; financial receipt attribution fails closed and proof/money downgrade preserve history. Online guards, not offline SQL, are required for legacy adoption. | Baseline plus financial0004/proof0005 migrations, `backend/server.py`, and the latest owned suite. |
| Resolved core identity gap: login/registration/reset use tenant context or preserved unambiguous legacy lookup, not arbitrary first-tenant choice; foreign IDs are validated. Staff provisioning/tenant administration remains incomplete. | Auth schemas/service/repository and current-user dependencies plus access-control regressions. |
| Resolved core privacy gap: customers access own CRM/order/stat/history/ledger/payment data, partners access assigned orders/deliveries, and mutation roles are explicit. Broader security review remains. | Updated controllers and real access-control regressions. |
| Resolved lifecycle gap: refresh rotates stable sessions; reset/reuse and reauthenticated own-password changes revoke access, and old-epoch replay cannot revoke new logins. SMTP recovery code/UI exists; live transport and broader security remain pending. | Auth `20261109_0002`, service/repository/security/dependencies/recovery/smtp and real PostgreSQL regressions. |
| Resolved pricing-read gap: tier/override controls bind real owned IDs, the self-catalog reports exact effective price/tax/currency, and order creation does not mix mutable per-line lookups. Historical snapshots remain unchanged. | Pricing DTO/service/repository/router, shared decimal validation, order creation, web controls and62 customer VM/real PostgreSQL cases within full totals. |
| Resolved financial-capacity gap: server customer mode replaces caller-flag bypass; Order/Customer locks, gross holds, signed balances and live pending cash funding are rechecked at reserve/deliver. UI displays server capacity/due. | Orders/money services, customer/order models, financial0004 and frontend finance/order code. |
| Resolved canonical stock gap: nullable key uniqueness, atomic first-row upsert, product/row lock order separate from FIFO, and representative mixed-operation PostgreSQL wait chains pass. This is not arbitrary production-load proof. | Inventory model/service, stock0003 migration, and owned contention coverage. |
| Resolved delivery bypass gap: both routes share verified OTP plus uploaded signature/photo ownership/integrity and cash funding. Mandatory proof is not a raw URL/settings placeholder. | `orders.service.finalize_delivery`, delivery router, proof service/API, local storage and POD regressions. |
| Resolved allocation/retry gap: actual order paid/due/status, explicit advances and transactional per-intent UUID replay are implemented. Bank references remain unverified/non-unique provider strings; page reload can lose the UI key. | Money service/controller, shared idempotency, financial0004 and frontend intent/payment form. |
| Stored settings/locale remain partially operative. Generic currency patch handling can be overwritten by tenant currency; persisted OTP/signature/rounding/jobs options are not complete runtime enforcement. | Settings controller and current orders/proof/formatting source. |
| Resolved local path-reopen gap: image reads retain the validated native handle and serve verified bytes. Unsafe existing permissions are refused, not repaired. Privileged owner/admin processes and production durability remain trust boundaries. | `storage/local.py`, `storage/proof_store.py`, proof journal0006 and real Windows tests; two native Linux cases remain skipped. |
| Resolved baseline gap: inventory/orders share one typed array query; account/tenant/role/logout transitions clear caches and stale requests. Cross-tab auth synchronization and server-side offline revocation are not established. | `frontend/src/lib/products.ts`, `frontend/src/lib/auth.ts`, `frontend/src/app/providers.tsx`, and regression tests. |
| Resolved bootstrap/navigation gap: `/auth/me` can refresh with bounded retries, and restricted staff pages are guarded before mounting. Formatting/default business rules still need end-to-end enforcement. | `frontend/src/lib/api.ts`, `frontend/src/lib/navigation.ts`, `frontend/src/lib/utils.ts`, and frontend tests. |
| Resolved mobile transport gap: renewal is bounded, active identity barriers are joined before retry/publication, exact roles and generation/key checks protect caches. Cookies remain memory-only; browser/native APK integration remains unverified. | `supplyos_core` session/transport/cookie/query, both app providers and263 VM regressions. |
| Audit is only partially written, has no mounted read API, and has no verified production immutability/archival implementation. | `backend/app/shared/audit.py:12-34`; `backend/app/api/v1/__init__.py:6-31`; `frontend/src/app/(admin)/audit/page.tsx:3-24`. |

## Local Configuration and Commands

Only variable names and source-declared topology are recorded; configured environment values and credentials are excluded.

- Backend required variables: `DATABASE_URL`, `DATABASE_URL_SYNC`, `REDIS_URL`, `JWT_SECRET`.
- Opt-in SMTP uses `SMTP_ENABLED`, relay/auth/sender/TLS fields, canonical `PASSWORD_RESET_URL` and bounded `PASSWORD_RESET_*` limits. Supported names/defaults are in `backend/.env.example` and the service guide; credentials are never chat inputs. Owned preview/verifier explicitly disable/reset these values.
- Backend optional variables include app/auth settings plus `ANTHROPIC_API_KEY`, `AI_PROVIDER=anthropic`, deliberately reviewed `AI_MODEL`, `FRONTEND_URL`, `COOKIE_SECURE`, `COOKIE_SAMESITE`, and `PROOF_STORAGE_DIR` (default backend/.runtime/proofs). Local proof storage needs no S3 key. Accounts/credentials remain manual owner configuration, not chat inputs.
- Backend default feature prefix is `/api/v1`; legacy `/api` is also mounted. Health is `/api/health` and `/api/health/deep`; Swagger/ReDoc/OpenAPI are `/api/docs`, `/api/redoc`, and `/api/openapi.json`. Deep health `503` distinguishes unavailable dependencies. Source: `backend/server.py`.
- Frontend server-only `BACKEND_URL` controls the `/api/*` proxy; default backend origin is loopback port 8001. Documented public overrides are `NEXT_PUBLIC_BACKEND_URL` and `NEXT_PUBLIC_API_BASE`. No secrets belong in public configuration.
- Cookie-auth cross-origin setup needs explicit allowed origins; the global browser guard rejects wildcard/malformed trust at startup. Approved origins/referrers are checked before unsafe request parsing; native requests without browser headers remain compatible. Production/staging TLS/cookie checks are not complete security certification.
- Mobile `SUPPLYOS_API_BASE` has no default. Release/profile requires an explicit reviewed public HTTPS `/api/v1`; debug accepts an explicit diagnostic development origin only. Missing/unsafe configuration disables sign-in/transport, not a fake account. The offline `api.supplyos.app` fixture is not a real approved endpoint. Source: `supplyos_core/lib/src/api_config.dart` and app factories.

| Directory | Declared command or script | Qualification |
| --- | --- | --- |
| Repository root | `backend/tools/init_env.py` via the backend virtualenv | Generates signing material without printing it; never overwrites private files. Database/Redis and OS file privacy are operator configuration. |
| Repository root | `backend/tools/run_preview.py` via the backend virtualenv | Later Windows start only when ports 8001/3000 are free; owns temporary PostgreSQL/API/Next data, not production/permanent records. Leave the existing preview untouched. |
| `backend/` | `alembic upgrade head`, then `uvicorn server:app --host 127.0.0.1 --port 8001` | Persistent instance needs configured PostgreSQL/Redis and reviewed migrations through `0006`; no startup DDL. |
| `backend/` | `tools/verify_backend.py --test-timeout 1200` via the virtualenv with `SUPPLYOS_OWNED_TEST_ENV=1` | Owned disposable backend/proof dataset, not user preview/customer data. Latest full result1078/3 in573.51 seconds. |
| `backend/` | `pytest tests -q` | Stateful API tests require a prepared isolated backend; do not run against an old external deployment by default. |
| `frontend/` | `npm run dev` or `npm start` | Both start Next development mode on port 3000. |
| `frontend/` | `npm run build`, then `npm run start:prod` | Production build passed locally; deployment/runtime integration still needs verification. |
| `frontend/` | `npm run lint`, `npm run typecheck`, `npm run test` |208 dev/prod passes plus lint/types/22-page build; isolated build/start preload denies private dotenv. Local Chrome may use `PLAYWRIGHT_CHANNEL=chrome`; this is not full supply-chain/provider acceptance. |
| Each mobile app and `mobile/packages/supplyos_core/` | Existing Flutter SDK: `pub get --offline`, `analyze --no-pub`, `test --no-pub --concurrency=1` |263 VM passes/three clean analyses; no APK/real-browser build or toolchain download. |

Commands describe current entrypoints; the dated checkpoint records actual isolated verification. The user preview was not manually restarted/reset. Native Redis/Lua, live SMTP, Docker/Actions/production and mobile platform execution remain unverified.

## Test and CI Evidence

- `test_reports/pytest/pytest_results.xml:1` records **30 backend tests, zero failures/errors/skips, dated 2026-07-19**. This is historical external-environment evidence, not a current local result.
- The saved `iteration_1.json` still reports historical frontend `not_tested`; current frontend regressions are separately recorded above. No full mobile success is established.
- Legacy backend API tests share session state, but no longer discover external previews. `TEST_API_URL`, explicit write opt-in, generated credentials, and the expected loopback test identity are required. New configuration, AI, environment-init, schema, and tooling regressions are separate from historical results.
- The initial 2026-11-08 static review recorded sequential stock tests, a direct delivery bypass, and weak optional-summary evidence. Subsequent auth/stock/financial/POD regressions and the guarded finalizer supersede those as current gaps; unconfigured live AI is explicitly skipped rather than advertised as passing.
- The old README's twelve-scenario claim was removed; `.ai/BUSINESS_SCENARIOS.md` remains the contract, not passing evidence.
- Latest full owned backend is1078/3 in573.51 seconds; frontend208 passes separately in dev/prod and mobile263 VM cases. Windows ACL checks are real; native Linux cases remain skipped. All earlier auth/stock/finance/POD/recovery/onboarding cases remain; no sub-suite totals are added.
- Frontend API/browser/proxy/recovery/finance/POD regressions exist under `frontend/tests/`; mobile/full business acceptance remain unfinished. Isolated checks were rerun without provider account calls or production data.
- CI source now migrates before startup, generates private verification credentials, and runs frontend browser tests as well as existing checks/builds. Remote CI/Docker execution and backend lint/typecheck/mobile jobs remain unverified or absent.

## Existing Seven-Phase Roadmap

The roadmap preserves the seven-phase development intent and now marks implemented financial/local-POD foundations separately from remaining work. Checked items are limited capabilities, not a complete release/security/compliance commitment.

| Phase | Original planned outcomes | Current interpretation |
| --- | --- | --- |
| 1. Foundation | Monorepo, PostgreSQL/Redis, versioned API, JWT/RBAC/audit, Alembic, setup, CI. | Validated config/bootstrap/proxy, auth/privacy and migration head `0005` are present; staff administration, broader security/audit and persistent/remote services remain. |
| 2. Core engines | Inventory/catalog/customers, pricing, orders/partial fulfillment, delivery proof/collection, payments/ledger. | Canonical stock, gross credit holds/signed exposure, allocation/replay and guarded private POD pass locally. Partial shipments, damage/return/transfer/expiry and external bank/gateway reconciliation remain. |
| 3. Client apps | Full admin; customer cart/orders/tracking/invoices/credit; delivery QR/OTP/proofs/offline sync. | Admin recovery/finance/POD and 100 dev/prod regressions pass; staff/OTP onboarding and both mobile platforms remain incomplete. |
| 4. Finance and analytics | GST invoice PDFs, statements/P&L, revenue/top-mover/dead-stock dashboards. | Payments/ledger/basic metrics exist; document generation, financial statements, and analytics charts remain planned. |
| 5. AI supervisor | Rule alerts, hourly Claude summaries, linear/XGBoost forecasts, route-optimization signals. | On-demand rule/summary paths and peak-hour aggregation exist; scheduling, forecasting, and richer delivery intelligence remain. |
| 6. Optional AI | Feature-flagged WhatsApp orders, voice orders, chatbot, price optimization. | Future work; implementations were not found. |
| 7. Hardening | k6 concurrent-order load tests, DB/Redis chaos tests, SOC2 preparation, encryption/backups/audit policies. | Planned. Essential security/correctness validation must not be assumed complete or deferred until after production expansion. |

### Historical P0/P1/P2 Backlog

Source: `memory/PRD.md:68-98`. These labels belong to the historical backlog, not to newly approved implementation work.

- **P0:** GST PDF invoices; reservation TTL/Celery worker; production Alembic enforcement; audit viewer; rack/shelf visual editor; best-fit warehouse selection.
- **P1:** WebSocket/Redis live order updates; customer cart/order/tracking/invoice workflows; delivery QR/OTP/signature/photo/offline queue; revenue/top-mover/dead-stock charts; multiple customer addresses; Redis sliding-window rate limiting.
- **P2:** WhatsApp Business order parsing; Whisper voice orders; price optimization; Google Maps route optimization; SOC2/encryption/backup policies.

Additional requirements in `.ai/PRODUCT_REQUIREMENTS.md:16-25` and `.ai/AI_SUPERVISOR.md:22-71` include expiry/batch/barcode/damage/return/transfer behavior, backorders and scheduled/repeat order workflows, promotional pricing windows, employee attendance/shifts, reorder/overstock forecasts, sales/customer trends, payment-risk/delay predictions, digest notifications, and feature flags. Existing enum/model/config fields and peak-hour aggregation are not complete implementations of those workflows.

`COMMITS.md` is a proposed commit sequence, not actual release history or permission to commit/push. Historical publishing notes do not establish a current deployment or service connection.

## Recommended Follow-On Order

These recommendations distinguish completed stabilization from remaining application work. User-authorized development is continuing; no recommendation is evidence that its feature is already complete.

1. Preserve1078/3 backend,208 dev/prod frontend and263 VM baselines and safe auth/pricing/migration/proxy/cache/stock/finance/POD behavior; do not redo resolved defects or test against the user preview.
2. Complete customer cart/checkout and invoice/statement/audit workflows on the authenticated effective-price and immutable-order foundation. Keep all prices, quantities, funding and transitions server-owned.
3. Finish warehouse association, typed operational locale/settings/promotions, profile linking/email verification and recipient OTP delivery, without claiming live sender/Redis or broader ingress/limits are verified.
4. Complete native delivery capture/collection and encrypted offline synchronization, and reservation expiry/AI cadence/realtime/comprehensive audit. Use only explicitly approved free services; unavailable providers stay held.
5. Verify durable private storage/retention/backup restores, native Linux, persistent DB/cache readiness and reviewed legacy adoption. Public HTTPS API, Android toolchains/licenses/signing and deployment remain independent gates.
6. Finish wider warehouse/fulfillment/reporting/analytics and demand/route intelligence, then intentionally selected optional intake/optimization modules. Keep load/security/backup checks continuous rather than postponing them to the final phase.

## Keeping This Memory Current

- Refresh the date, base revision, source references, and status after meaningful milestones. Working-tree changes may differ from the base commit.
- Re-read affected first-party source before promoting a partial/planned item to implemented. Check exposed API/client workflows, not just model fields, dependency lists, comments, or UI copy.
- Record fresh validation separately with command, date, scope, and outcome; never relabel the saved July test report as a current result.
- Keep governing requirements in `.ai/` and preserve historical PRD/changelog/test records. Architectural/business-rule changes still follow the charter's documentation requirements.
- Do not store environment values, credentials, tokens, private test-account data, dependency/vendor trees, caches, or build artifacts in this memory.
- This memory is explicitly readable; no automatic agent loader or Kilo setting change was added. Subsequent development added the verified changes above, with no commit/push/deployment or live provider provisioning.
