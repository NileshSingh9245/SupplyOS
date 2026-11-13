# CHANGELOG

All notable changes to this project.

## [Unreleased] - 2026-11-09 Finance and Private-POD Checkpoint

### Finance and Proof Follow-On
- Financial `20261109_0004`: server-owned cash/credit defaults, gross credit holds, signed balances/account credits, pending cash-funded exposure, constraints and guarded actual receipt allocation.
- Order/customer/delivery/canonical stock lock ordering and one shared finalizer across both completion routes. Cash needs full allocated cash/UPI/bank funds; verified credit can finish delivered/unpaid. Actual order paid/due/status follow receipt allocation and physical delivery.
- Optional-v1 UUID `X-Idempotency-Key` for order creation, payments and guarded completion; actor/tenant/operation/payload-scoped original response replay, changed-payload conflict, concurrent serialization and transaction rollback of failed claims/effects. Legitimate identical payments remain separate intents.
- Strict online legacy preflight now accounts for every receipt exactly once through owned payment references or verifiable delivery-payment groups. Orphan/duplicate/phantom/unaccounted credits reject adoption without rewriting history; financial downgrade refuses populated data/replay.
- Private local `PROOF_STORAGE_DIR`, proof `20261109_0005` receipts, authenticated delivery-scoped upload/read, image MIME/size/SHA256 checks, mandatory signature/photo/OTP finalization and no arbitrary URL bypass.
- ASGI actual-byte bounds before multipart parsing, including absent/chunked/false length and invalid-ID/legacy routes; Pillow 13 verification/full decoding of PNG/JPEG within 5 MiB/20M pixels and sanitized corrupt-CRC DomainError.
- Explicit Windows process-owner/SYSTEM/Admin protected ACL roots/files; existing unsafe paths are refused without permission repair, overwrite or adoption. Linux owner/no-follow descriptor implementation is present but native Linux cases are skipped here. Returned paths still need trusted ancestry at reopen; partial orphans and durable storage/backup/retention remain operational limits.
- Proof downgrade refuses existing receipts/canonical references rather than erasing evidence. No external S3 adapter is needed/configured for the implemented local workflow.
- Admin cash/credit mode, authoritative customer/order finance displays, linked receipt versus advance/credit-note forms, page-scoped retry keys, start/OTP/signature canvas/photo/private previews and unified completion. No client authorization math, gateway or OTP sender is inferred.
- Optional API payment-list `order_id` filter added; current UI uses only `customer_id`, delivery lists and existing order reads rather than inventing a delivery-detail endpoint.
- Existing local preview/setup is backed by real disposable PostgreSQL/API 8001 and temporary proof files. `run_preview.py` is temporary demonstration tooling, not permanent business storage; maintenance left preview/data untouched.

### Current Local Evidence
- Latest coordinator-owned full backend run: **354 passed, 3 skipped in 260 seconds**, including previous auth/privacy/stock/migration checks and financial/POD corrections. No sub-suite totals are guessed or added.
- Skips are one unconfigured live-AI case and two native Linux filesystem cases. Windows protected ACL behavior is actually checked; Linux metadata simulation is not native filesystem validation.
- Frontend: **87 passed in development and production modes**, all earlier 47 retained plus 40 new cases; lint/typecheck and a 17-page production build pass. Test-only browser/proxy fixtures do not validate provider accounts or production mounts.
- This maintenance read source/docs only; no repeated programming/test work, secret reads, preview mutation, provider/provisioning calls, staging, commit or push. Concurrent source configuration cleanup is not a new test claim.

### Core Security And Stock Follow-On
- Auth revision `20261109_0002`: stable sessions, single-use rotated refresh JTIs, global revocation version, and current database identity/session authorization.
- Tenant identity context, preserved unambiguous legacy login, customer-only registration, safe auth validation/no-store, and 12-character/72-byte new-password policy preserving existing hashes.
- Reset digests/single-use/global session revocation; email transport remains explicitly unconfigured.
- Core customer/partner/staff privacy/mutation roles, tenant foreign-ID checks, and invalid-write validation.
- Stock revision `20261109_0003`: `NULLS NOT DISTINCT` location key, atomic insert-or-load, reviewed duplicate-legacy rejection, and product/row lock order separate from FIFO allocation.
- Replay-after-relogin/reset cannot repeatedly invalidate fresh sessions; malformed Unicode OTP is rejected before comparison; mixed stock operations prove actual PostgreSQL wait-chain behavior.
- Earlier auth/stock checkpoint: 171 passed, one unconfigured live-summary skip, including core/privacy/schema/process checks. Retained as dated history and superseded by the current 354/3 checkpoint, not added to it.

### Added
- Validated immutable configuration, private signing-material initializer, sanitized example configuration, and beginner external-services guide.
- Pure declarative metadata independent of runtime secrets; real frozen schema baseline with matching-legacy validation and startup revision/table/column checks.
- Owned disposable PostgreSQL 15.19 verification tooling and a bounded API runner with generated private credentials and clean Windows process-tree teardown.
- Direct optional Anthropic Messages adapter through core HTTP dependencies and manually supplied private backend key, without a platform SDK/core install dependency.
- Frontend regression tooling, noninteractive lint, same-origin proxy, auth-scoped cache/request guards, role-aware pages, and one typed product-query shape.

### Fixed
- Removed the unavailable private AI package from unconditional core installation.
- Removed implicit startup DDL and sensitive reset/AI error logging; unconfigured password-reset email now reports unavailable instead of claiming delivery.
- Fixed expired-access bootstrap recovery, concurrent refresh handling, superseded session responses, stale account/tenant/role caches, and inventory/order query-shape conflicts.
- API write tests no longer discover old preview hosts; they require a deliberately isolated loopback test identity.
- CI source now migrates before startup, generates test signing/password material without printing it, and runs frontend regressions.

### Earlier Local Evidence (Preserved)
- Backend runner: 76 configuration, mocked AI-contract, private-config, authenticated-bootstrap, legacy-workflow, and owned-process tests passed; one unconfigured live-summary case skipped. Test identity/credentials are isolated, and unavailable Redis is not claimed healthy.
- Real PostgreSQL migrations: 8 cases passed on native and CI-style child databases, including strict extra-column/partial-index rejection, preserved legacy data, destructive rollback gating, and startup behavior.
- PostgreSQL tooling: 23 opted-in tests, including actual lock blocking, authentication, and cleanup/ownership safeguards.
- Frontend: 47 API/session/browser/proxy regressions, lint, typecheck, and production build.

These foundation/sub-scope results preceded the financial/POD checkpoint. They remain historical observations, not extra counts or current full-release acceptance.

### Remaining
- Not a complete production release. Preserve verified core auth/privacy/canonical stock/manual finance/local-POD/replay; staff provisioning, OTP/email/reset transport/UI, broader security/CSRF/rate limits, locale/settings, invoice PDFs/full audit/general ledger, jobs/realtime/forecasts and mobile/platform workflows remain.
- Durable proof mounts/paired backup restores/native Linux checks, permanent DB/Redis readiness and production policies remain. S3/gateway/maps/WhatsApp/voice are pending external adapters. Sonnet 4.5 availability/deprecation needs an explicit approved `AI_MODEL` decision; no model/provider/billing change is made here.
- No live provider account, production deployment, remote Actions/Docker runtime, formal SOC2 or complete twelve-scenario acceptance was verified. The historical report below is not a fresh result.

### Review Corrections
- Explicit constructor values are normalized to canonical aliases before settings source merging, preventing ambient database/mode/key overrides.
- Verification subprocesses have deadlines and a reusable Windows kill-on-close Job for the entire child tree; abrupt parent exit is tested.
- Legacy adoption verifies exact column shape and PostgreSQL index predicate/options/readiness/validity; destructive rollback requires opt-in.

## [0.1.0] — 2026-01-19 · Milestone 1 + 2

Historical release-report text is retained below, not adopted as current installation or acceptance evidence. The current notes supersede implicit schema creation, full-state-machine and live-provider claims. Old preview/configuration must not be reused; no current secrets or external accounts are supplied here.

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
- The historical frontend ran `next dev` on 3000. Current local routing uses the owner's backend/proxy; historical preview deployment details are not current configuration.
- Redis is running but Celery worker not yet started; reservation-TTL job planned for Milestone 3.
- Flutter apps cannot be run in this container (no Flutter SDK); code is push-ready for `flutter run` locally.
