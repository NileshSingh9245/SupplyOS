# SupplyOS

Supply-chain software for Indian wholesalers, distributors, and warehouses. Development is active: core APIs and an admin MVP exist, while the mobile and several operational workflows remain incomplete. This repository is not yet a verified production release.

Repo: https://github.com/NileshSingh9245/SupplyOS.git

---

## Start Here

- [External services and connector setup](docs/EXTERNAL_SERVICES.md): required PostgreSQL/Redis, secure configuration, optional providers, and what remains unimplemented.
- [Codebase memory](memory/CODEBASE_SNAPSHOT.md): source-backed implementation status and known gaps.
- [Development roadmap](.ai/ROADMAP.md): release phases and the current verified checkpoint.
- Read all governing `.ai/` documents before making changes.

## Components

### Client Review Preparation - 2026-11-12

- Main publication is authorized for the audited core only. Dependencies, private configuration, signing keys, generated APK/build output and disposable review data are excluded; the original working-tree index is preserved.
- The web runtime is upgraded to pinned Next16.4.6, Axios1.21.1 and Zod4.6.7 with matching form/lint interfaces. Production dependency audit reports zero findings. Payment/completion retry drafts, session/tenant barriers and exact monetary validation are preserved, not bypassed for deployment.
- Approved Android36/build-tools36/NDK28.2/Gradle9.3.1 preparation, private review signing and an isolated Android35 emulator are ready. Both review package IDs use `.review`, cannot sign production artifacts and are non-debuggable.14 release-guard checks,263 VM cases and three analyses pass. No final APK or installation is claimed without a verified public HTTPS API origin.
- Review setup used blanket SDK license processing once and acknowledged extra XR/microXR terms outside the requested packages. No XR components were installed; further acceptance is restricted to approved package-specific Android terms. C: capacity is low, so large review-only caches/temp work are on ignored D: runtime storage.
- No hosting charge is authorized. Connected Vercel Hobby is ineligible for a commercial client app, and connected Supabase data belongs to another application. Neither a billable trial nor that unrelated database is used. A dedicated approved commercial-compatible free review host/API is still required before live web/API or APK acceptance.

**Client target:** independently hosted Vercel/Supabase/Render web/API with durable private proof storage and Android APKs using a real public HTTPS API. Your PC is build/verification tooling, not a deployed dependency. Free-mode code does not assume localhost DB/cache, local models or a PC tunnel. Hosting/free-quota/commercial eligibility and release signing/storage gates are tracked in the service guide; no cloud URL or client-ready APK is claimed yet.

| Path | Purpose |
|---|---|
| `backend/` | FastAPI + SQLAlchemy async + Alembic + PostgreSQL 15 + Redis 7 |
| `frontend/` | Patched Next.js16 admin MVP with tested sessions/recovery/pricing, authoritative finance displays, manual allocation and guarded POD workflow |
| `mobile/customer_app/` | Flutter customer catalog and paginated order/detail/history viewer; cart/checkout still incomplete |
| `mobile/delivery_app/` | Flutter exact-role assigned-route viewer; native proof/collection/offline sync still incomplete |
| `mobile/packages/supplyos_core/` | Shared secure memory session/cookie transport, typed read contracts and account-scoped queries |
| `.ai/` | 13 governing documents (architecture, DB rules, API, security, roadmap, decisions log). Read these before any change. |
| `docs/` | Ancillary documentation |

## Quick Preview (Temporary)

The existing local preview is at `http://localhost:3000/setup`, backed by the real API on port `8001`. Open it if it is already running; do not start another instance or reset/restart its data. The setup wizard lets you choose your own administrator details privately; there are no shared login credentials.

**Temporary-data warning:** preview accounts, orders, receipts, and proof files belong to a disposable database/directory. Ending/restarting the preview discards that dataset. Do not put permanent business records or production data into it.

For a later start, after installing backend/frontend dependencies and only when ports 3000/8001 are free, run from the repository root:

```powershell
& ".\backend\.venv\Scripts\python.exe" -B ".\backend\tools\run_preview.py"
```

The Windows/Python 3.11 helper owns temporary PostgreSQL 15.19/API/Next processes, migrates the schema, supplies temporary signing configuration, and explicitly disables external AI and SMTP. It does not start Redis or provision a permanent database. Deep health may honestly return `503` for unavailable Redis while the setup page loads. Verification used separate resources; the existing preview was not manually stopped, reset, or restarted.

## Persistent Local Development

You need Python3.11, supported Node22, a dedicated PostgreSQL15 database and a compatible Redis TCP/TLS service. Python packages do not install these services. Docker/WSL, hosting and optional provider choices are explained in the setup guide; no service is automatically provisioned by this README.

### 1. Prepare Backend Dependencies

From the repository root, create the virtual environment if it does not already exist:

```powershell
python -m venv backend/.venv
& ".\backend\.venv\Scripts\python.exe" -m pip install -r backend/requirements.txt
& ".\backend\.venv\Scripts\python.exe" backend/tools/init_env.py
```

The initializer creates `backend/.env` with generated signing material without printing it and leaves existing root/backend private files unchanged. Configure `DATABASE_URL`, `DATABASE_URL_SYNC`, and `REDIS_URL` privately; the database URLs must target the same dedicated database using asyncpg and psycopg2 respectively. Check Git exclusion and OS privacy yourself: configuration-file creation is not the proof helper's protected Windows ACL guarantee. Optional AI keys stay empty unless intentionally configured.

### 2. Migrate and Start the Backend

From `backend/`, after configuring your own database:

```powershell
& ".\.venv\Scripts\python.exe" -m alembic upgrade head
& ".\.venv\Scripts\python.exe" -m uvicorn server:app --host 127.0.0.1 --port 8001
```

Startup checks current migration head `20261112_0006` and required tables/columns; it never creates tables implicitly. The baseline refuses mismatched legacy schemas. Financial `0004` requires each historical receipt to be credited exactly once through a valid owned payment reference or verifiable legacy delivery group; unsafe/ambiguous history fails for review without rewriting balances. Proof `0005` and upload-journal `0006` refuse history-erasing downgrades, and financial rollback preserves populated money/replay history. Back up before online migration; do not blindly stamp, delete evidence, or treat offline `--sql` as legacy validation. The baseline's separate destructive opt-in does not override financial/proof guards.

### 3. Start the Admin Web App

From `frontend/`:

```powershell
npm ci
npm run dev
```

Open `http://localhost:3000`. First initialization requires privately configured backend `SETUP_AUTHORIZATION_TOKEN` and the operator's authorization input; there is no default or discovery endpoint. The token travels only as `X-Setup-Authorization`, not a URL. Existing/incomplete tenant records cannot be overwritten. Next forwards `/api/*` to backend8001; `BACKEND_URL` stays server-only.

External accounts/DB/cache connections remain your own manual configuration. Optional direct AI uses backend-only `ANTHROPIC_API_KEY`, `AI_PROVIDER=anthropic`, and a deliberately reviewed `AI_MODEL`; no platform SDK/account linking or automatic paid model choice is needed. Leave the key empty for rule-only operation.

`FREE_ONLY_MODE=true` is default-on and blocks that paid AI path even with an existing key; the AI page displays held/unavailable summaries while rule checks remain available. External reset mail requires `APPROVED_FREE_SMTP=true` only after its free account/quota/quality is verified. These flags do not authorize a paid plan, infer hosted database price, or certify public deployment.

### 4. Set Up Local Proof Storage

No S3 account or bucket is required. Backend `PROOF_STORAGE_DIR` defaults to `backend/.runtime/proofs`; for persistent development use a dedicated private directory and keep its files with the database. Upload/read and Windows owner/SYSTEM/Admin ACL checks are implemented; unsafe existing paths are refused, not repaired. The preview/verifier use temporary directories instead.

The admin supports drawn/uploaded signatures, PNG/JPEG photos, authenticated previews, and guarded cash/UPI completion. Files are limited to 5 MiB/20M pixels; browser origin and actual body bytes are checked before multipart parsing. New uploads reserve ownership before writing and retain evidence on uncertain upload/commit replies. Reads serve verified bytes from a held native handle; final receipts serialize against auth revocation. Both proofs and a verified recipient OTP are required. Named staff provisioning is implemented, but OTP messaging remains unconnected, so setup alone does not complete delivery onboarding.

`PROOF_STORAGE_BACKEND=local` remains the default. The private Supabase REST facade is integrated but held by `APPROVED_FREE_STORAGE=false` and `SUPABASE_VERSIONING_VERIFIED=false` until the actual account, deployed version selectors and retained-version/backup policy are reviewed. Private storage credentials stay backend-only; public/signed/latest-version fallback and automatic evidence deletion are not used. See the service guide for exact private fields and operational limits.

### 5. Check Readiness

```powershell
Invoke-RestMethod -Uri "http://localhost:8001/api/health"
Invoke-RestMethod -Uri "http://localhost:8001/api/health/deep"
```

Liveness is separate from readiness. Deep health returns `503` if database or Redis is unavailable. A healthy endpoint does not prove stock/finance invariants or all client workflows.

### 6. Configure Password-Recovery Email Privately

The login page now links to `/forgot-password`; emailed links open `/reset-password` with a token fragment, not a query parameter. Recovery is opt-in and requires a working PostgreSQL database, Redis limiter, authorized SMTP sender, and canonical public reset-page URL.

Keep `SMTP_ENABLED=false` until setup is ready. Configure `SMTP_HOST`, `SMTP_PORT`, `SMTP_TLS_MODE`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM`, and `PASSWORD_RESET_URL` privately in `backend/.env` or a backend secret manager. Never paste passwords, keys, cookies, or reset links into chat. See the [supported SMTP fields and private setup packet](docs/EXTERNAL_SERVICES.md#smtp--email).

Delivery is bounded, post-response and best-effort, not a durable mail queue. Global unavailability returns `503`; request limits return `429`; accepted requests never reveal account eligibility or SMTP outcomes. A successful reset revokes sessions, clears auth cookies, and requires a new login. Live relay/DNS/sender authorization and native Redis/Lua execution are not certified by the offline tests.

## API Documentation
- OpenAPI JSON: `/api/openapi.json`
- Swagger UI: `/api/docs`
- ReDoc: `/api/redoc`

## Finance and Delivery Milestone

Owner-only `/staff` creates named manager/accountant/partner accounts with a holder-selected final password, no generated/emailed credentials or automatic verification/login. Role/activity changes retire all sessions/reset links atomically. Customer records and new customer login accounts are distinct owner/accountant-controlled actions; anonymous tenant UUIDs cannot authorize signup and existing profiles are not silently merged.

- Orders default to server-owned customer cash/credit mode. `is_credit=False` is not a credit-check bypass. Gross credit holds, signed balances, and pending cash funding are checked under locks; cash delivery must be fully funded by allocated cash/UPI/bank receipts, while approved unpaid credit may finish delivered.
- Select an order when recording a receipt to update its actual allocated amount/due; otherwise it is an explicit unallocated advance/account credit. Credit-note mode is not collected funds and cannot fund an order. `paid` order status follows physical delivery; full order closeout remains unexposed.
- `X-Idempotency-Key` provides per-actor/tenant/operation UUID replay for order creation, payment recording, and guarded completion. The same normalized request recovers its original result; changed payload conflicts and failures roll back effects/claim. New legitimate identical payments get new keys, not body-based deduplication.
- The admin keeps keys across uncertain network/408/5xx results and automatic auth refresh, including same-page modal reopen. Draft/retry state is not durable across page reload/offline restart; check recorded receipts before initiating again if the key is lost.
- Delivery completion now shares OTP/private-proof/funding validation across staff and partner paths, then updates stock, sale/receipt ledger entries, history, audits, and replay in one transaction. This is manual receipt accounting, not a live gateway, bank verification, refund system, or complete general ledger.

## Verification

The Windows-only disposable PostgreSQL tooling uses an official portable archive in an owned temporary cache. It does not install a Windows service, change global PATH, or modify an existing database. This is verification tooling, not a production database setup.

From `backend/`:

```powershell
& ".\.venv\Scripts\python.exe" -B tools/verify_backend.py --test-timeout 600
```

This runner migrates its own new PostgreSQL database, starts a bounded loopback API, creates a fresh test business with generated credentials, and runs the configured auth/privacy/SMTP/stock/schema/finance/POD/process checks. Its proof files and data are disposable and separate from the user preview. Credentials are not displayed; API write tests reject a server without the expected isolated identity. SMTP and live AI are explicitly disabled in the isolated API; SMTP orchestration uses offline injected dependencies.

Current isolated checkpoint, 2026-11-12:

- Latest full backend verifier: **1078 passed, 3 skipped in573.51 seconds**, including private bootstrap/staff/intake, own-password/effective-pricing and all prior stock/finance/POD/security cases. Skips remain live AI and two native Linux cases; no native Linux validation is claimed on Windows.
- Frontend: **208 development and208 actual production passes** on patched Next16.4.6; lint/types and the optimized release build pass with installed Chrome. **10 earlier separate isolated browser-security checks** remain separate evidence. Production dependency audit reports zero findings; these are not live-provider, hosting or APK acceptance claims.
- Actual Windows proof ownership/protected ACL and held-handle byte-read checks are included. No production filesystem, provider retention or deployment certification is implied.
- Mobile: **263 VM tests pass** (177 shared,62 customer,24 delivery), all three analyses clean using Flutter3.47.9/Dart3.13.7. Overlapping renewal/identity checks block premature replay/publication. Approved Android toolchain and protected review signing now pass preparation/guard checks; a verified public API, final APK build/install and authenticated review still prevent APK acceptance. No runnable APK or Flutter browser build is claimed.
- Earlier 354/3 finance/POD and 353/3 cleanup baselines, smaller sub-suites, and frontend 87 are historical checkpoints, not counts to add to this full run. Noncredential working-tree metadata and stale compiled code were cleaned; private credential artifacts, Git index/history and unrelated staged work were not modified or certified clean.

The saved July report is historical. All twelve business scenarios in `.ai/BUSINESS_SCENARIOS.md` are not yet established as passing by current end-to-end coverage.

## Remaining Release Work

Core auth/privacy/stock, browser-origin guards, private bootstrap/staff/customer intake, SMTP recovery, manual finance/replay and private journaled POD have local evidence; the application is still incomplete. Email/invitation/OTP messaging, warehouse association/profile linking/managed pricing, live SMTP/Redis, retained hosted proofs/backup-restore, external connectors, broader limits/ingress and effective locale/settings remain. No provider stack was activated. Mobile execution/APK acceptance, invoices, audit/reporting, durable jobs/realtime/expiry, forecasts and closeout remain. Native Linux, remote CI/Docker, live providers and all twelve scenarios are not verified.

Source anchors: [money service](backend/app/features/payments/service.py), [order/credit/finalizer service](backend/app/features/orders/service.py), [request replay](backend/app/shared/idempotency.py), [proof API/validation](backend/app/features/proofs/router.py), [private storage](backend/app/infrastructure/storage/local.py), [financial 0004](backend/alembic/versions/20261109_1543_financial_core.py), [proof 0005](backend/alembic/versions/20261109_1640_private_delivery_proofs.py), [frontend DTOs](frontend/src/lib/finance.ts), and [frontend intents](frontend/src/lib/intent.ts).
