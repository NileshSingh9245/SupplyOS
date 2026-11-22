# ROADMAP - SupplyOS

## Current Password and Pricing Checkpoint - 2026-11-12

- Authenticated `POST /auth/change-password` accepts only current/new passwords, supports all current active roles, and uses User-first persisted session/reset locks. Successful password/hash/audit/epoch retirement commits together, clears both cookies and requires a fresh login. Wrong-current attempts commit bounded durable counters; lockout is429 with bounded retry, not an automatic credential replay.
- Private `/change-password` keeps passwords out of URLs/storage, clears fields, coordinates cancellation/session/cache changes and preserves only safe outcome notices across self-revocation. Lost/408/5xx/unexpected-success replies are unconfirmed, never fabricated success.
- `/pricing` exposes owner/manager tier creation and discount-only editing, and owner/accountant customer tier/override controls. Assignments bind tenant-owned tier IDs, clear explicitly with null, and audit future-order changes. Existing60-character tier creation remains compatible; new assignable names fit the30-character customer reference and names cannot be renamed.
- Customer-only `GET /catalog` derives the linked customer and tenant from current authentication. Bounded pages/search return only ID/SKU/name/unit, exact effective price/tax and server-declared currency. Customer eligibility/currency stay protected through authorization; shadow tenant/customer/price queries are rejected. The customer app now reads this contract, not base-price guesses.
- Pricing precedence remains explicit override (including zero), tier, base. Order creation reads all price/product/tax values in one immutable PostgreSQL snapshot; earlier order money is not repriced. Shared exact decimal validation supports pricing/accounting without cross-feature duplication. `/products` and the existing resolver response stay compatible.
- Root verification: **1078 backend passes/3 unchanged skips in573.51s**, **208 development/208 production frontend passes**, clean lint/types and the **22-page production build**. Mobile: **177 shared +62 customer +24 delivery =263 VM passes**, three clean analyses. The earlier AI-alert assertion now uses the declared severity enum rather than rejecting legitimate warning alerts.
- No new migration, deployment, provider activation, SDK/license provisioning, signing or Git publication. Cached Flutter was reused; private configuration and existing preview/data were not reset or silently reloaded.
- Remaining application work includes warehouse association, cart/checkout, invoices/statements/audit, typed business settings/promotions and native delivery execution. Live services, broader security/RLS/jobs and production/APK gates remain distinct from these local regressions.

## Previous Onboarding Checkpoint - 2026-11-12

- Private `SETUP_AUTHORIZATION_TOKEN` is required before `/setup/initialize` parsing. Unconfigured returns503; missing/duplicate/wrong authorization403. PostgreSQL advisory serialization commits exactly one first owner; any existing/incomplete tenant is preserved. Owner email is not automatically verified; anonymous status hides tenant identity.
- Owner-only `/staff` now lists/creates named manager/accountant/partner accounts, edits whitelisted contact/role/activity and revokes access. Owner/customer/self conversion, deletion, password/email mutation and generated/shared credentials are excluded. Role/activity changes including reactivation atomically retire sessions/reset links; sorted FK-compatible User locks precede sessions/business rows.
- Customer records and new customer login accounts are separate owner/accountant-controlled actions. A caller tenant UUID is only a matching assertion, not signup authority. Contacts normalize blanks to null; credit edits cannot invalidate current exposure/debt/holds; partner assignment protects target eligibility under parent-before-Delivery locks.
- Private validation/unexpected errors are static/no-store and SQL parameters hidden. Owned backend `SUPPLYOS_OWNED_TEST_ENV=1` disables dotenv before API/Alembic/test imports; isolated frontend dev/production preload denies dotenv. These are fixture controls, not runtime credentials or authorization bypasses.
- Root full backend: **954 passed/3 unchanged skips in363.06s**. Frontend **165 dev/165 production**, lint/types and **20-page build**. All earlier102 UI cases and previous stock/finance/POD evidence remain; direct out-of-band credit reduction still tests reservation-time checks after the API correctly rejects unsafe reduction. No migration, deployment, provider/SDK/license/signing or Git action; preview data/processes preserved.
- Email/OTP/invitations, forced-password change/password editing, existing-record account linking, warehouse association, managed pricing and complete client workflows remain separate acceptance work.

## Previous Application Security Checkpoint - 2026-11-12

- Current work resumes application goal completions, not deployment. Continue the cross-role onboarding -> order -> stock/fulfillment -> delivery/collection -> invoice/statement journey; individual test counts are not full application acceptance.
- Unsafe browser mutations now require one approved Origin or trusted Referer before parsing, including auth/setup/finance/multipart proofs and canonical/legacy/custom prefixes. Headerless native API clients remain compatible. UUID request IDs and security headers are enforced; ingress trust, comprehensive XSS prevention and general rate limits remain release work.
- Migration `20261112_0006` persists pre-write proof ownership and exact hosted receipt provenance. Upload I/O holds no delivery/auth locks; final commits serialize a non-key User lock -> active session -> Delivery -> journal against revocation while allowing partner FK checks. Ambiguous upload/commit replies retain private bytes/journal rather than deleting evidence. Local reads serve bytes from the verified native held handle.
- Supabase REST transport is integrated but disabled by default and not live-attested. Approval requires a reviewed free account, deployed version-selector capability and retention, private ENABLED bucket versioning, exact version identity and SHA256 verification. Public/signed URLs, latest-version fallback and automatic deletion are not used. Native Linux/backup/restore/whole-app RLS remain unverified.
- Latest full owned backend: **781 passed/3 unchanged skips in 295.51 seconds**. Frontend: **102 dev and 102 production passes** with installed Chrome, lint/types and the **19-page build**; **10 separate isolated browser-security cases** also pass. Revocation and assignment/upload lock races have real PostgreSQL regressions; no independent post-fix certification is claimed.
- A fresh isolated local preview was started only after the previous preview was unreachable; it is temporary data, not deployment. Preserve its running processes/data. Subsequent source edits are validated in separate fresh verifier processes, not silently reloaded into that preview.
- Flutter 3.47.9/Dart 3.13.7 are installed. Shared cookie/session/role/cache and real customer order list/detail/history are implemented; delivery is read-only. Root verification: **177 shared + 53 customer + 24 delivery = 254 VM passes**, three clean analyses, zero failures/skips. The independent overlapping-renewal finding is corrected with held second/third verification barriers before dispatch/retry/result/decoded-query publication; all 239 earlier tests remain plus 15 new cases. Cart/checkout, native QR/OTP/proof/collection/outbox and real browser integration remain incomplete.
- Both Android runners/resources have static/native-tool validation, not APK compilation. Verified Gradle8.9 bootstrap enforces the pinned target Gradle9.3.1 archive SHA before extraction; transport, backup, permissions and release-signing guards are retained. SDK36/engines/targetGradle/NDK/AGP/Kotlin caches, licenses, signing and a real public API prevent APK acceptance. No SDK/license provisioning, provider activation, paid plan or Git publication occurred.

## Next Application Milestone

- Continue warehouse access, customer cart/checkout, invoices/statements/audit and native delivery using the authorized onboarding and effective-pricing foundation. Keep money, stock and transitions server-owned; do not fake messaging/gateway/model availability.
- Broader limits/XSS/RLS/ingress, expiry/jobs, durable storage, live verification and the independent deployment/signing/license gates remain. Maintain existing credential/session mode, audit/revocation and deterministic FK-compatible locking.
- Source entry points include `features/staff/`, customer/pricing/orders/payments/invoicing/audit APIs and their role-gated web/mobile clients. Existing-profile linking and warehouse association remain distinct from named staff creation.
- Continue application implementation and fresh isolated verification without deployments, unapproved SDK/licenses/signing/provider/paid activation, or preview/data reset. External gates do not justify skipping the remaining authorized code work.

## Cloud/APK and Fee-Policy Checkpoint - 2026-11-11

- Deployment target is client-shareable Vercel/Supabase/Render web/API and Android APKs, independent of the developer PC. Local tooling is for development/build/verification only. Hosted private proof persistence, real public HTTPS API configuration and proper private Android signing are release gates, not placeholder values.
- `FREE_ONLY_MODE=true` is default-on and blocks the known paid AI transport even with an existing key. `APPROVED_FREE_SMTP=false` blocks unapproved external mail before cache/token work; local capture remains development/test only. Hosted PostgreSQL/cache URLs remain valid; their account cost cannot be inferred from hostname. Rule checks remain available and the AI UI reports held/unavailable summaries without a false queued claim.
- Full owned backend: **520 passed/3 unchanged skips in 223.12 seconds**. Frontend: **102 dev and 102 production passes**, lint/types and a **19-page build**. Embedded Alembic preserves existing app safety loggers; no failed assertion was removed or skipped. These are regression facts, not cloud availability or throughput certification.
- Available Vercel scope is Hobby; official policy restricts it to non-commercial use, so it is not selected for this client-business deployment. Render Free sleeps/loses local files and blocks standard SMTP ports; Supabase Free has quotas/inactivity pauses. No provider was provisioned, upgraded or called with application credentials. Production-quality/free-account validation remains on hold.
- Generative parity, native Redis/Lua, hosted proof/backup durability, live mail and release APK/cloud ingress remain unverified. No local coding model, test inbox, manual receipt or in-app channel is treated as an equivalent replacement for a paid capability.

## Previous Recovery Checkpoint - 2026-11-10

- Disabled-by-default native SMTP, private configuration, canonical fragment reset links, current auth-recipient/token recheck and bounded post-response work are implemented. HMAC Redis fixed-window IP/identity counters and cooldown precede all account lookup; global unavailable admission is `503`, limits `429`, accepted outcomes generic `200`.
- Public recovery pages preserve token memory across bootstrap/revocation, strip history, validate UTF-8 password size and require re-login. Cancellation retains SMTP capacity until the offloaded thread closes without ASGI level-cancellation spinning. Delivery is not a durable outbox/retry worker.
- Latest owned full backend: **507 passed/3 skipped in 270.45 seconds**, including real PostgreSQL recipient-state/cookie cases and offline SMTP/admission coverage. Frontend: **100 passes in both development and production**, lint/types and a **19-page production build**.
- Noncredential working-tree metadata/empty directories/stale bytecode were cleaned while preserving report history, private credential artifacts and Git index/history. The user preview was not manually reset/restarted. No extra provider stack, paid plan or live account call was activated.
- Native Redis/Lua, real SMTP/sender/DNS, whole DNS/delivery deadlines, finite recheck-to-send race, durability and production trust remain operational work. Private configuration and future provider requirements are documented in `docs/EXTERNAL_SERVICES.md`.

## Previous Finance/POD Checkpoint - 2026-11-09 (Started 2026-11-08)

- First stabilization checkpoint: reproducible public core install, validated/private settings, explicit real migrations/startup guard, safer cookie defaults, isolated test identity, native optional AI transport, and admin session/query/proxy fixes.
- Latest full coordinator-owned backend verification: **354 passed, 3 skipped in 260 seconds**, including previous auth/privacy/stock/schema plus reviewed finance/POD. Skips are one unconfigured live-AI case and two native Linux filesystem cases; Windows ACL checks are real, not Linux validation.
- Frontend: **87 passed in both development and production configurations**, all earlier 47 plus 40 new cases; lint/typecheck and a 17-page production build pass. Earlier 171/one skip, separate tooling 23 and frontend 47 are dated checkpoints, not added totals.
- Financial `0004`/proof `0005` add signed balances/gross holds/pending cash funding, manual allocation/replay, guarded OTP/private POD and fail-closed legacy/history migration checks. S3 is not needed for the implemented local store.
- These are bounded local scopes, not all twelve business scenarios or a complete application. Provider/browser contracts use test fixtures where stated. Native Linux filesystems, live accounts, permanent services, production and mobile remain unverified; this documentation maintenance did not rerun tests.
- A Windows-owned temporary preview exists at `http://localhost:3000/setup` (backend 8001). Leave its processes/data untouched; `run_preview.py` is a disposable demonstration, not permanent business storage, and does not start Redis. Concurrent source configuration cleanup is not a new test claim.
- CI source is updated for migrations, generated credentials, and frontend tests. Remote CI and Docker execution were not performed on this workstation.

## Phase 1 - Foundation (in progress)

- [x] Monorepo scaffolding (`backend/`, `frontend/`, `mobile/`, `.ai/`).
- [ ] Persistent local/production PostgreSQL + Redis setup verified; disposable PostgreSQL 15.19 tooling works locally, Redis remains unconfigured here.
- [x] FastAPI skeleton + `/api/v1` versioned router.
- [x] JWT rotation, stable-session/global revocation, reset single-use/digests, tenant context, and core customer/partner/staff privacy covered on real PostgreSQL.
- [x] Opt-in SMTP/public recovery code with HMAC admission, current-recipient checks and fragment-only reset UI; live sender/Redis and durability remain unverified.
- [x] Browser-origin/CSRF boundary, UUID request IDs and nonblocking security headers; tested headerless-native compatibility remains explicit.
- [x] Serialized private setup, redacted credentials, owner-only staff lifecycle and tenant-derived customer intake with audit/session retirement.
- [ ] Broader security/authorization, ingress/global limits, email/invitation verification, warehouse association and comprehensive audit; tested scope is not all security requirements.
- [x] Real baseline/auth/stock/finance/POD/journal migrations through `20261112_0006`; strict legacy validation, exact-once receipt attribution, evidence-preserving downgrade guards, and no implicit startup DDL.
- [x] First-launch setup wizard endpoint (`/setup/status`, `/setup/initialize`).
- [x] Frontend lint/types/22-page build and208 dev/prod regressions; full owned backend1078/3 checkpoint plus separate browser-security tests.
- [ ] CI/Docker runtime verified remotely; workflow source updated, not executed here.

## Phase 2 - Core Engines (financial/local-POD milestone, still partial)

- [x] Baseline inventory API/service source (warehouse locations, movements, existing-row locks).
- [x] Canonical nullable location uniqueness, atomic first-row upsert, consistent product/row locks, real mixed-operation contention checks, and duplicate-legacy rejection.
- [x] Representative real stock/credit/ledger contention and same-key replay checks; preserve canonical locks and server-only money rules.
- [ ] Production load/failure coverage and damage/return/transfer/expiry workflows.
- [x] Product catalog + categories.
- [x] Customer management + credit limits.
- [x] Pricing API, role-controlled tier/customer override UI and exact self-catalog; coherent order snapshots. Promotions/time windows remain.
- [x] Whole-order/reservation cash-credit foundation, gross holds/signed exposure, actual allocation/due and delivered/paid transitions.
- [x] Assignment/OTP API, local signature/photo receipts, authenticated reads and shared proof/funding completion.
- [x] Manual payments/customer ledger, orderless advances/credit notes and transactional per-intent UUID replay.
- [ ] Staff warehouse association, OTP delivery transport, partial fulfillment/backorders and administrative order closeout.
- [x] Private proof-store selection, durable pre-write journal, provenance-bound exact-version Supabase transport and held-handle local reads; provider approval stays fail-closed.
- [ ] Durable hosted private proof storage/restore/retention and native Linux validation; Supabase REST code is not live provider/retention proof. Generic S3/gateway adapters remain pending; ephemeral Render files are not production evidence.
- [ ] Complete effective locale/settings, promotional pricing and wider operational/accounting policies.

## Phase 3 - Client Apps

- [x] Admin session/bootstrap/cache/role/proxy, recovery/password changes, staff/customer intake, controlled pricing, finance/retry and private proof preview;208 dev/prod regressions preserve earlier coverage.
- [x] Shared mobile session/cookie/role/cache transport; exact customer/delivery-partner scope and explicit release/profile HTTPS API configuration,263 offline VM regressions.
- [x] Customer effective-price/currency/tax catalog and order pagination, read-only detail/history, real loading/error/empty/retry/navigation/logout; no client financial/stock calculations.
- [ ] Next.js Admin Dashboard (setup wizard, inventory, orders, customers, deliveries, finance, AI panel).
- [ ] Flutter Customer app (catalog, cart, order, tracking, invoices, credit history).
- [ ] Flutter Delivery app (route, QR scan, OTP, proof, offline sync).
- [x] Android runner source, native resource/permission/transport/backup checks, diagnostic-only debug IDs and verified checksum-capable bootstrap; no APK compilation claim.
- [ ] Android scaffolding/build/signing and release APKs using a real public HTTPS API, without developer-PC endpoints or private backend keys.

## Phase 4 - Finance and Analytics

- [ ] GST invoice generation (PDF).
- [ ] Statements + P&L.
- [ ] Full general ledger, refunds and actual bank/gateway reconciliation; manual customer ledger does not complete these.
- [ ] Analytics dashboards (revenue, top movers, dead stock heatmap).

## Phase 5 - AI Supervisor

- [x] Direct optional Anthropic through core HTTP, manually configured owner key and sanitized failures (mocked transport, no live provider validation or platform SDK).
- [x] On-demand rule alert foundation (dead stock, low stock, credit); richer intelligence remains.
- [ ] Recurring/hourly summary jobs. Review Sonnet 4.5 availability/deprecation and deliberately choose approved `AI_MODEL`; no model/provider/billing change is implied.
- [ ] Forecasting (linear + XGBoost fallback for demand).
- [ ] Route optimization signals.

## Phase 6 - Optional AI Modules (feature-flagged)

- [ ] WhatsApp parser to order.
- [ ] Voice-to-order.
- [ ] Smart chatbot.
- [ ] Price optimization.

## Phase 7 - Hardening

- [x] Bounded local Windows private-root/file creation and ACL verification; unsafe existing paths are not repaired. Returned paths still require trusted ancestry before reopen.
- [ ] Native Linux filesystem/security and production-volume/backup/restore verification.
- [ ] Load tests (k6) - 1000 concurrent order placements.
- [ ] Chaos tests - DB failover, Redis flush.
- [ ] SOC2 audit prep (audit logs, encryption at rest, backup policy).
