# SupplyOS External Services Setup

This guide explains what SupplyOS needs outside its own code, where to configure it, and what is still being built. It is for someone setting up the project for the first time.

Onboarding checkpoint: 2026-11-12. Full owned backend **954 passed/3 skipped in363.06s**, frontend **165 dev/165 production**, lint/types and **20-page build**. Earlier102 UI cases remain plus63 onboarding cases. These checks are not live hosting/provider certification; private bootstrap/staff/intake is implemented, but email/OTP/invitations remain unconnected.

## Private Initial Setup and Account Intake

Before initializing an empty database, the operator must privately configure backend `SETUP_AUTHORIZATION_TOKEN`: URL-safe32..256 characters with at least12 distinct characters, no default or public retrieval. It travels only as `X-Setup-Authorization` to `/setup/initialize`; the UI clears it/password before awaiting. Unconfigured requests503, missing/duplicate/wrong authorization403 before parsing. PostgreSQL serialization permits one committed first-owner setup and refuses any existing/incomplete tenant; contact blanks normalize to null and email is not automatically verified.

The authenticated owner manages `/staff` individual manager/accountant/partner accounts and safe contact/role/activity/session changes. Holder-selected final passwords are never generated/shared/returned or automatically logged in. Owner/customer/self conversion, deletion and password/email changes are not exposed. Role/activity changes retire refresh families/reset links and advance session epochs, including reactivation. User locks are sorted/non-key before tokens/business rows; assignment now protects partner eligibility.

Only owner/accountant may create customer records or new customer login accounts. `/auth/register-customer` now requires that authentication; supplied legacy tenant UUID only asserts the caller's own tenant. Records are not login accounts, and creating a new account does not merge an existing record or verify email. Credit limit/type edits preserve existing exposure/debt/commitments. API inputs/errors are redacted/no-store; private authorization/header values never belong in frontend env, URLs, logs or chat.

Owned backend marker `SUPPLYOS_OWNED_TEST_ENV=1` disables dotenv for isolated API/Alembic/tests; frontend test preload sanitizes env and denies dotenv for dev/production workers. Runtime private configuration remains operator-owned. No installed services, credentials, preview data/processes, provider plans, SDK/licenses or release signing were altered by these tests.

## Client Hosting and Android Target

The client application must run on independently hosted web/API, PostgreSQL and durable PRIVATE proof storage, with Android APKs calling a real public HTTPS API. The developer PC, its files/databases/models, or a PC tunnel are not deployment dependencies. The local preview below is only development tooling.

`FREE_ONLY_MODE=true` is default-on. Known paid generative calls are denied even when a key exists; rule checks remain usable. `APPROVED_FREE_SMTP=false` prevents unapproved external email before token issuance. Hosted DB/cache URLs are supported: free account cost and quotas must be verified, not inferred from hostname. A local capture inbox never becomes production mail because a flag is enabled.

The candidate providers have real limits: [Vercel Hobby](https://vercel.com/docs/plans/hobby) is non-commercial and the available scope is Hobby, so it is not selected for this business deployment. [Render Free](https://render.com/docs/free) sleeps after 15 idle minutes, can take about a minute to resume, loses local files on restart/spindown, expires free PostgreSQL after 30 days and blocks SMTP ports 25/465/587. [Supabase Free](https://supabase.com/pricing) has database/storage/egress quotas and inactivity pauses. None is represented as unlimited or production-quality parity; no upgrade, paid plan or keep-awake circumvention is authorized.

Hosted proof storage must preserve authenticated first-party URLs, tenant/delivery/kind binding and exact-byte size/MIME/hash checks; public buckets or ephemeral Render files are not replacements. Switching a storage setting without copying/verifying existing receipts is unsafe. Android release signing must stay private/reproducible, and an APK with localhost, a placeholder API or an unverified signing setup is not client-ready. Cloud release and functional APK distribution remain on hold until these gates pass.

## Start Here

You do not need to buy an AI, S3 storage, maps, messaging, or payment subscription to try the core application. Delivery photos and signatures now have private local storage.

1. Prepare Python and Node using the current [root setup instructions](../README.md). Use isolated development/test environments, not an old preview deployment.
2. Choose a development PostgreSQL database and a Redis service. Local services or a dedicated hosted sandbox are both options.
3. Run `backend/tools/init_env.py` to generate signing material without displaying it, then configure `DATABASE_URL`, `DATABASE_URL_SYNC`, and `REDIS_URL` privately. Existing private files are left unchanged; protect their operating-system permissions too.
4. Connect the admin web app using its same-origin proxy (`BACKEND_URL` on the frontend server), then check API/database/Redis health.
5. Test the existing core workflows with a fresh test business. Add an optional service only when its connector is implemented and you need that feature.

**Important:** service setup does not complete missing application features. The customer app currently has login and a catalog; its orders screen is a placeholder. The delivery app has login and an assigned-delivery list; proof capture, collections, navigation, and offline synchronization are not complete mobile workflows.

### Fastest Local Look: Temporary Preview

The current local preview is at `http://localhost:3000/setup`, with the real backend on port `8001`. If it is already running, open it; do not start a second instance, reset its data, or restart it for these documentation changes. Use the setup wizard privately rather than looking for shared/default login credentials.

**Temporary-data warning:** this preview uses a new disposable PostgreSQL database and a temporary proof directory. Ending/restarting it discards that working dataset; it is not for permanent business records or production.

For a future preview start, only when ports 3000 and 8001 are free and backend/frontend dependencies are installed, run from the repository root:

```powershell
& ".\backend\.venv\Scripts\python.exe" -B ".\backend\tools\run_preview.py"
```

The helper owns its temporary PostgreSQL/API/Next processes, applies migrations, supplies temporary signing/configuration values, and disables external AI and SMTP. It uses the supported Windows/Python 3.11 portable PostgreSQL tooling, not a permanent database service. It does not start Redis: the page can load while deep health honestly reports Redis unavailable. The separate setup below is for a persistent development database and proof directory.

## What Connects to What?

```text
Admin web app / Customer app / Delivery app
                    |
                    v
              SupplyOS backend
                    |
          +---------+----------+-------------------+
          |         |          |                   |
          v         v          v                   v
      PostgreSQL  Redis    Private local      Optional providers
                           proof files        (when configured/
                                              implemented)
                                              AI, email, S3, maps,
                                              payments, messaging, voice
```

- **Backend/API:** the server all apps call. It owns stock, order, and payment rules.
- **PostgreSQL:** the permanent database for products, stock, customers, orders, and ledger records.
- **Redis:** a separate fast service. It is not the stock or finance database.
- **Connector:** code that talks to an outside provider. A settings field alone is not a connector.
- **Environment variable:** a named configuration value supplied to a running app.
- **Origin:** the scheme, host, and port, such as `http://localhost:3000`. It does not include `/api/v1`.
- **Secret:** a password, signing secret, or provider key. Keep it on the server, not in browser or mobile builds.
- **Driver/SQLAlchemy:** the library that connects the backend to PostgreSQL and runs database operations.
- **Migration/Alembic:** a versioned update to database tables, managed by the project's migration tool.
- **TLS/HTTPS:** encryption for data traveling between computers. Certificate checks verify the server's identity.
- **Least privilege:** give an account only the permissions it needs for its job.
- **Proof of delivery (POD):** the signature/photo evidence attached to a particular delivery.

## Which Services Are Needed?

| Service | Needed for the core? | What it does | Current boundary |
| --- | --- | --- | --- |
| PostgreSQL | Yes | Stores business data and provides database transactions. | Real migrations and a startup revision/schema guard are present; fresh and matching legacy schemas have local PostgreSQL coverage. Your own provider/database still needs configuration and validation. |
| Redis | Required by current backend configuration and before enabled email recovery | Health checks and opt-in password-reset throttling; future cache/jobs/realtime. | Fixed-window HMAC identity/IP counters and cooldown are implemented for recovery. Native Redis/Lua and general queues/sliding-window/realtime remain unverified or pending. |
| App hosting, domain, and HTTPS | Only for production or remote access | Makes the backend/web app reachable securely. | No new deployment or live domain is established by this guide. |
| Claude/AI | No | Produces optional summaries of aggregated business metrics. | Direct Anthropic Messages API uses the core HTTP client and an owner-supplied key. Mocked transport checks are not live account verification. |
| SMTP/email | No for basic local flows; needed before offering real email recovery | Sends private reset links for existing accounts. | Real opt-in SMTP adapter, bounded background work, recipient recheck, and public recovery UI are implemented. Disabled/unavailable transport returns `503`; live relay/sender verification and durable delivery remain pending. |
| Private local proof files | Yes when completing deliveries; no external account needed | Stores delivery signatures/photos on the backend's private filesystem. | Authenticated upload/read, image checks, delivery-bound receipts, and Windows private ACL enforcement are implemented. Production durability/permissions still need verification. |
| S3-compatible storage | No; optional future storage alternative | Stores objects outside the backend host. | An S3 adapter and signed-object access are pending. Do not configure S3 keys to enable the implemented local store. |
| Maps/route API | No | Geocodes addresses and calculates navigation or optimized routes. | Priority-sorted delivery lists exist. No geographic routing connector is present. |
| Payment gateway | No for manual cash/UPI/bank recording | Collects or verifies money electronically. | Guarded manual allocation, ledger updates, and request replay exist. Checkout, bank/provider verification, and webhooks are pending. |
| WhatsApp Business | No | Receives orders or sends approved business messages. | An order channel label exists; a WhatsApp connector does not. |
| Voice transcription | No | Turns recorded speech into text for review. | Audio upload, transcription, and voice-to-order integration are pending. |

Optional does not mean unimportant: real email recovery, production-ready proof storage, and an approved way to deliver OTPs are needed before advertising those complete workflows to customers. Staff/delivery-partner provisioning and OTP messaging are not connected yet.

## Choose a Development Setup

### Option A: Local Services

Run PostgreSQL and Redis on your own computer. The declared targets are PostgreSQL 15 and Redis 7.

- Docker Desktop with WSL2 (Windows Subsystem for Linux) can run these services in containers, which are isolated runtime environments. Docker must be installed and working first; review its resource needs and licensing before choosing it.
- Without Docker, PostgreSQL can run as a local Windows service. Redis can run inside WSL/Linux. Installing Python packages does not install either database service.
- Use the current root runtime instructions for supported service/start commands. Do not assume a Compose file exists because historical documentation mentioned one. The Windows verification helper runs disposable PostgreSQL without a machine service; it is not a permanent database installation.
- Keep database/cache ports on loopback or a private network. Do not expose them to the public internet.

### Option B: Hosted Development Sandbox

Use a dedicated test database and Redis instance from providers you choose. No vendor or paid plan is required by this guide.

- Choose PostgreSQL with a normal database connection, not just a web dashboard or HTTP data API.
- Choose Redis with a direct TCP/TLS connection. A Redis REST-only offering is not compatible with the current client.
- Keep development and production separate. Do not run setup, migrations, or stateful tests against customer data.
- Review free-tier expiry, storage/connection limits, backup costs, network access rules, and deletion/export options before enabling anything billable.

### Initial Workstation Preflight

The initial workstation preflight found Python 3.11.6 and Node 22, no Docker command or permanent/default PostgreSQL/Redis listener, and no Flutter on `PATH`. Core dependencies install from public packages without a private platform SDK. PostgreSQL 15.19 runs in owned disposable verification/preview clusters, and the admin frontend has local checks. That does not establish permanent PostgreSQL/Redis services, a Flutter platform build, or live providers.

These PowerShell checks are read-only:

```powershell
python --version
node --version
Test-NetConnection -ComputerName localhost -Port 5432
Test-NetConnection -ComputerName localhost -Port 6379
```

`TcpTestSucceeded: True` only proves something accepts connections on that port. It does not prove the credentials, schema, or application are correct. If using hosted services or different ports, check their configured host/port instead.

## Where Configuration Goes

| Configuration | Local development | Production | Never put it here |
| --- | --- | --- | --- |
| Backend database/Redis URLs, `JWT_SECRET`, provider secrets | Private backend process environment or untracked `backend/.env`, following the current runtime instructions. | Hosting secret manager or private backend environment. | Git, admin settings JSON, `NEXT_PUBLIC_*`, mobile build flags, screenshots, support messages. |
| Frontend backend origin/path | Untracked `frontend/.env.local`. | Frontend server/build environment, as appropriate for each variable. | Do not embed credentials in a backend URL. |
| `PROOF_STORAGE_DIR` | Optional backend environment value; default is `backend/.runtime/proofs`. | A durable private mount owned by the backend service identity. | Public web/media directories, browser variables, or an untrusted/shared filesystem tree. |
| Mobile API address | `SUPPLYOS_API_BASE` compile-time value. | Your approved HTTPS API address in the app build. | No signing secrets or provider secret keys in mobile builds. |
| Non-secret business settings | SupplyOS Settings, for settings the release actually supports. | The same application UI/API. | Do not use it as a substitute for a server secret manager. |

Validated settings read the repository-root `.env` and `backend/.env`; the backend file overrides the root file, process variables override both, and explicit constructor values override inherited aliases. Settings are immutable after startup. Migration configuration needs only `DATABASE_URL_SYNC` plus environment mode, not AI/application secrets.

Only placeholder values belong in an example/template. Verify private files are ignored by Git and have appropriate OS access restrictions before filling them in. The signing initializer does not provide the proof helper's protected Windows ACL guarantee for configuration files. Never print the full environment, copy a private file into an issue, or paste a connection URL into logs. Restart your own persistent development instance after changing settings; leave the currently running temporary preview alone. Rebuild apps after changing build-time values.

### Core Backend Template

This is a **shape reference, not a ready-to-run configuration**. Replace every `<...>` privately with your own values. This document contains no usable password or signing secret.

```dotenv
APP_ENV=development
API_V1_PREFIX=/api/v1
DATABASE_URL=postgresql+asyncpg://<DB_USER>:<URL_ENCODED_PASSWORD>@<DB_HOST>:5432/<DB_NAME>
DATABASE_URL_SYNC=postgresql+psycopg2://<DB_USER>:<URL_ENCODED_PASSWORD>@<DB_HOST>:5432/<DB_NAME>
REDIS_URL=redis://<REDIS_HOST>:6379/0
JWT_SECRET=<PRIVATE_RANDOM_SIGNING_SECRET>
FRONTEND_URL=http://localhost:3000
ANTHROPIC_API_KEY=
COOKIE_SAMESITE=lax
# Optional PROOF_STORAGE_DIR defaults to backend/.runtime/proofs.
```

- The two PostgreSQL variables point to the **same database**, not two different databases.
- Generate a unique, cryptographically random `JWT_SECRET` privately; use at least 32 random bytes for the default HS256 signing setup. Do not reuse it across test and production.
- Empty `ANTHROPIC_API_KEY` leaves the external provider disabled. Configure your own direct provider key privately only when deliberately enabling AI.
- `FRONTEND_URL` accepts explicit browser origins separated by commas. Do not include API paths or credentials.
- `APP_ENV=production` or `staging` enables secure cookies by default and validates explicit HTTPS origins and database TLS. This does not prove every security/business requirement is complete.
- `COOKIE_SECURE` is an optional override; insecure production cookies are rejected. `COOKIE_SAMESITE=none` requires secure cookies. Prefer same-origin proxy routing instead of weakening browser protections.

Other existing settings include `APP_NAME`, `JWT_ALGORITHM`, `ACCESS_TOKEN_MINUTES`, `REFRESH_TOKEN_DAYS`, `PASSWORD_RESET_HOURS`, `ACCOUNT_LOCK_MINUTES`, and `MAX_LOGIN_ATTEMPTS`. Keep the documented defaults unless there is a reviewed reason to change them. There is no implemented `AI_FEATURES` environment switch merely because it appears in the architecture plan.

## PostgreSQL: Get the Connection Right

PostgreSQL is required. SQLite, MongoDB, and a hosted provider's REST URL are not drop-in replacements for this application.

1. Prepare a fresh development database and a limited database user.
2. Obtain its host, port, database name, user, and TLS requirements. Keep the password private.
3. Set `DATABASE_URL` with `postgresql+asyncpg://`. The running API uses the async driver.
4. Set `DATABASE_URL_SYNC` with `postgresql+psycopg2://`. Alembic uses the synchronous migration driver.
5. Follow the current schema/migration instructions before initializing a test business.

A provider may display `postgres://...` or `postgresql://...`. Those are provider connection strings, not the explicit async driver selection the API needs. Preserve the connection details while choosing the correct SQLAlchemy scheme for each variable.

If a username/password contains characters such as `@`, `:`, `/`, `?`, `#`, or `%`, URL-encode that component. Do not encode the entire connection URL, and do not double-encode a password already encoded by the provider.

For hosted/production databases, require TLS and prefer certificate/hostname verification according to provider instructions. The migration URL uses `sslmode=require`/`verify-ca`/`verify-full`; the async URL uses `ssl` with those modes. Configuration normalizes an async URL's `sslmode` to `ssl` and rejects conflicting parameters. Confirm provider CA requirements rather than disabling certificate checks. Merely using `require` is not a claim that hostname verification is configured.

Prefer a direct database connection for migrations. Transaction-pooling endpoints may need special asyncpg/prepared-statement handling; they are not automatically interchangeable. Check the provider's connection limits against SQLAlchemy's pool and the number of backend processes.

**Migration requirement:** run online `alembic upgrade head` before the API. Current head is `20261109_0005`, after the real baseline, auth sessions, canonical stock, and financial `0004` revisions. Startup checks revision/tables/columns and never creates tables implicitly.

The baseline refuses mismatched legacy schemas. Financial `0004` additionally requires every historical receipt to have exactly one valid credit attribution: an owned payment reference or a verifiable legacy delivery-payment group. Orphans, duplicate/phantom credits, mismatched amounts, and ambiguous history stop for reviewed reconciliation; original money/history is not rewritten. Stop old writers and arrange backups/maintenance before adopting a real legacy database.

Never blindly stamp a schema or delete evidence to force migration. Financial downgrade refuses populated money/replay history; proof `0005` downgrade refuses stored receipts or canonical delivery references. The baseline's separate destructive opt-in does not override these protections. Offline `--sql` generation does not run the online legacy/history checks and is not evidence of safe legacy adoption.

## Redis: TCP Is Not REST

The backend uses `redis-py`, which speaks Redis over a network socket.

```dotenv
# Local development without Redis authentication, private/loopback only:
REDIS_URL=redis://<REDIS_HOST>:6379/0

# TLS service with an ACL username and password:
REDIS_URL=rediss://<REDIS_USER>:<URL_ENCODED_PASSWORD>@<REDIS_HOST>:<TLS_PORT>/0
```

- `redis://` is plain TCP. Use it only on an appropriate private development network.
- `rediss://` is Redis over TLS. Use the provider's actual TLS port and certificate requirements.
- `https://...` is an HTTP/REST endpoint, not a usable `REDIS_URL` for this client. A REST token is not automatically a Redis password.
- A password-only provider may use an empty username, for example `rediss://:<URL_ENCODED_PASSWORD>@<REDIS_HOST>:<TLS_PORT>/0`.
- `/0` selects Redis database zero. Some hosted offerings only support zero.

Redis is checked by deep health and used for opt-in password-reset fixed-window counters/cooldown, never as the source of stock or finance balances. The recovery account needs `EVAL`, `SET`, `INCR`, and `TTL` on its `supplyos:auth:password-reset:*` key namespace. Use a restricted native TCP/TLS endpoint; a successful ping does not verify Lua/ACL compatibility. Starting Redis does not add reservation expiry jobs, a durable worker, real-time updates, or general sliding-window limits. Those features need implementation and tests of their own.

## Connect the Web and Mobile Apps

### Admin Web: Preferred Same-Origin Connection

The Next.js server now forwards `/api/*` requests to the backend, keeping `/api/v1` intact. The browser can call the web application's own origin instead of calling a separate backend address.

```dotenv
# frontend/.env.local, non-secret routing values only:
BACKEND_URL=http://127.0.0.1:8001
NEXT_PUBLIC_BACKEND_URL=
NEXT_PUBLIC_API_BASE=/api/v1
```

Open the local admin app at `http://localhost:3000`. `BACKEND_URL` is server-only and must be an HTTP(S) origin with no API suffix, credentials, query, or fragment. The proxy defaults to `http://127.0.0.1:8001` if no override is supplied. Leave the public backend-origin override empty for same-origin routing.

This proxy is code present, not a claim that your backend is running or that a hosted deployment has been verified. It requires a running Next.js server or an equivalent hosting/ingress proxy; a static-only file host cannot execute Next.js rewrites. Set the approved backend origin before building/deploying the frontend and rebuild after changing routing configuration.

For the frontend Docker build, provide the non-secret `BACKEND_URL` build argument for the backend reachable from that container. Container `127.0.0.1` means the frontend container itself. The image uses the lockfile with `npm ci`; Docker contexts exclude private environment files and generated dependencies. Docker execution is not verified on this workstation because Docker is unavailable.

### Alternative: Direct Browser-to-Backend Connection

For local direct browser-to-backend requests, use the same hostname consistently:

```dotenv
# frontend/.env.local, non-secret addresses only:
NEXT_PUBLIC_BACKEND_URL=http://localhost:8001
NEXT_PUBLIC_API_BASE=/api/v1
```

The corresponding backend value is `FRONTEND_URL=http://localhost:3000`. These examples use the existing backend port 8001 and frontend port 3000; match any changed runtime ports.

`NEXT_PUBLIC_BACKEND_URL` is an origin only. Adding `/api/v1` there duplicates the path because `NEXT_PUBLIC_API_BASE` is appended. All `NEXT_PUBLIC_*` values are public in the browser bundle. Use these documented routing variables, never server/provider secrets.

For a separate API origin, configure exact trusted origins and review cookie `SameSite`, `Secure` and third-party-cookie behavior. Wildcard/malformed `FRONTEND_URL` now fails startup. Unsafe requests need one approved Origin or trusted Referer before body parsing; no-header native clients remain compatible. Ingress must preserve browser provenance and restrict trusted proxy scheme/IP metadata. CORS and the deliberately partial CSP do not establish complete CSRF/XSS/production security.

### Customer and Delivery Apps

Both apps use compile-time `SUPPLYOS_API_BASE`, including the full `/api/v1` path:

```text
--dart-define=SUPPLYOS_API_BASE=https://api.your-domain.example/api/v1
```

This is a flag example, not a release endpoint. Flutter 3.47.9/Dart 3.13.7 are installed; SDK36, Android engine artifacts, Gradle9.3.1 and licensing prerequisites prevent an offline APK build. No SDK/license provisioning or release signing was performed. Mobile source/test readiness is separate from APK creation and client distribution.

Android runners for both apps are prepared and statically validated with cached SDK35 tools. Main/profile/release deny cleartext and backups, retain only Internet permission and require private release signing without debug fallback. Debug IDs/labels are diagnostic, with exact loopback/emulator-only HTTP exceptions. Verified Gradle8.9-generated bootstrap files enforce the pinned Gradle9.3.1 archive SHA before safe extraction; no target bootstrap/APK build ran. Actual SDK36/engine/targetGradle/NDK28.2/AGP9.1/Kotlin2.4 caches are missing and licenses remain unaccepted. Static resource ZIPs are not runnable APK previews.

For Android Emulator development, `10.0.2.2` normally reaches the host computer; `localhost` inside an emulator/phone refers to that device. A physical phone needs a reachable development host on the same private network, with an appropriate backend bind address and firewall rule. Do not open PostgreSQL or Redis publicly to solve mobile connectivity.

Neither mobile app has an API default. Release/profile validates an explicit public HTTPS `/api/v1` and rejects private/loopback/reserved/placeholder hosts, credentials, query/fragment and ambiguous paths. Debug may use an explicit diagnostic development origin; phone loopback is not the host computer. Replace the example host with a real reviewed endpoint, never an old preview or the offline `api.supplyos.app` fixture. Invalid configuration disables transport/sign-in visibly.

Both apps share memory-only HttpOnly native cookies, credentialed browser transport, bounded renewal, exact roles and generation-scoped caches. Every pending identity barrier is joined before dispatch/replay/result publication, including later barriers appearing during decoding. Customer catalog/orders/detail/history and delivery route reads have no client financial/stock logic. Root verification: **254 VM passes** (177 shared, 53 customer, 24 delivery), three clean analyses. Cart/checkout, QR/OTP/proof/collection/outbox, real browser CORS/cookie/TLS and Android APK execution remain unverified or absent.

## Local Delivery Proofs: Implemented

No S3 account, bucket, or key is needed for the current local proof workflow. `PROOF_STORAGE_DIR` is a recognized backend setting; if omitted, the backend uses its private `backend/.runtime/proofs` directory. The temporary preview/verifier instead supplies an owned temporary directory.

For an authorized delivery with an available recipient OTP, the admin workflow can start the delivery, verify the OTP, draw/upload a signature, upload a delivery photo, and record cash/UPI collection before completion. Both signature and photo are currently required by the server, even if a saved Settings toggle suggests otherwise. Automatic OTP messaging and staff provisioning remain pending, so first-launch setup alone is not a turnkey delivery operation.

| API | Request/result |
| --- | --- |
| `POST /api/v1/deliveries/{delivery_id}/proofs` | Multipart form fields `kind=signature` or `kind=photo` and `file`. Returns `201` with `id`, `delivery_id`, `kind`, `mime_type`, `size_bytes`, `created_at`, and canonical `url`. Let the HTTP client generate the multipart boundary; do not force a JSON content type. |
| `GET /api/v1/delivery-proofs/{proof_id}` | Authenticated, tenant/ownership-scoped private image read. It is not a public or signed S3 URL; responses use private/no-store and nosniff headers. |
| `POST /api/v1/deliveries/{delivery_id}/complete` | `cash_amount`, `upi_amount`, `signature_url`, and `proof_photo_url`; returns the delivery resource. Use the returned canonical proof references, not arbitrary external URLs. |

Images must be nonempty PNG/JPEG, no larger than **5 MiB** or **20 million pixels**. Pillow 13 verifies and fully decodes them, including rejecting broken PNG checksums. The ASGI middleware caps actual received request bytes at 5 MiB plus 64 KiB multipart overhead before parsing, including chunked/missing/false length headers and legacy/invalid-ID upload paths. A web ingress still needs its own reviewed limits and timeouts.

Upload/read/completion validate ownership, delivery, kind, permissions, size, MIME and SHA256. New uploads commit a journal reservation before storage I/O and retain evidence on ambiguous results. Final receipts lock User (NO KEY UPDATE) -> active auth session -> Delivery -> journal through commit, rechecking after waits and permitting partner FK key-share checks; upload I/O holds no delivery/auth locks. Legacy staff `/orders/{id}/deliver` uses the same guarded finalizer, not an OTP/photo/signature/funding bypass.

### Private Filesystem and Production Limits

- New Windows proof roots/files have explicit process-user ownership and a protected ACL allowing only that user, SYSTEM, and Builtin Administrators. Administrators can read by design; this is not encryption or protection against host compromise.
- Existing unsafe roots/files are refused, not permission-repaired, overwritten, or made public. Use a dedicated service-owned path and an operator-reviewed transfer plan; do not delete an existing store to make an error disappear.
- The Linux implementation targets restrictive `0700` directories/`0600` files, owner checks, and no-follow descriptor traversal. Native Linux filesystem validation was not performed on this Windows host; those two cases are skipped. Other ACL models/network filesystems are not automatically supported.
- Serving now reads bounded bytes from the same native handle whose privacy was verified, then checks the exact size/hash and sends those bytes. It does not reopen a checked path in `FileResponse`. Privileged owner/admin processes and host security remain trusted. Uncertain writes retain private orphans and journal ownership; no automatic retention/deletion/reconciliation worker is claimed.
- Production must provide a durable private mount, approved access permissions, TLS, backup/restore checks for **both database receipts and image files**, and a retention plan. Default `.runtime` storage or disposable preview data is not a production persistence strategy.

### Private Supabase Proof Transport: Integrated, Held

Configure only backend private settings; a stored key never activates a provider automatically:

| Field | Boundary |
| --- | --- |
| `PROOF_STORAGE_BACKEND` | `local` by default; explicit `supabase` selects new hosted writes. Existing receipts retain their own provenance. |
| `APPROVED_FREE_STORAGE` | Default `false`; review actual free account/quotas/billing and acceptable quality before any approval. |
| `SUPABASE_VERSIONING_VERIFIED` | Default `false`; requires actual deployed REST selector/versioning capability and reviewed retention/restore evidence. A flag alone is not attestation. |
| `SUPABASE_STORAGE_ORIGIN` | Exact canonical `https://<project>.supabase.co` origin, without credentials/path/query/fragment. |
| `SUPABASE_STORAGE_BUCKET` | One private bucket with matching ID/name and literal `versioning_status=ENABLED`. Missing/disabled/suspended capability is rejected. |
| `SUPABASE_STORAGE_KEY` | Private supported service credential, never frontend/mobile/tenant Settings/chat. Target authentication remains unverified. |
| `PROOF_STORAGE_TIMEOUT_SECONDS`, `PROOF_STORAGE_CAPACITY` | Bounded transport deadline `0.1..30` seconds (default10), no-wait capacity `1..16` (default4). |

Receipts keep project, bucket, object/version and journal operation identity. Create-only uploads require an exact acknowledgement; all metadata/content reads use the recorded version and verify owner marker, retained-version flags, MIME, size and SHA256. URLs remain authenticated first-party `/api/v1/delivery-proofs/{id}` paths. No public/signed/latest fallback or automatic DELETE is used on failure/cancellation/uncertain commit. Review the preserved reservation before retrying/reconciling; setting changes do not copy/verify existing local proof bytes.

Public Storage v1.94.0 source supports these REST shapes; offline HTTP fixtures and real PostgreSQL journal checks do not certify the target's deployment or WORM/indefinite retention. The operation marker is correlation, not provider-enforced ownership. Privileged/lifecycle deletion, paired DB/object backup-restore, whole-app RLS/least-privilege runtime, native Linux and completion-time lock duration remain release validation. This is not a generic S3 adapter or an approved cloud deployment.

## Optional Connectors

### Claude / AI Summaries

**Purpose:** turn aggregated order/delivery metrics into a short summary. Low-stock, dead-stock, and credit-risk rule checks do not require an external model.

**Code present:** `AnthropicProvider` calls the direct Messages API through core `httpx`; no extra/private SDK or platform account is required. Your own Anthropic account/key is optional and configured manually. `include_summary=true` requests are not an hourly scheduler or a durable job.

```dotenv
# Backend only. Leave the key empty when AI is not wanted.
ANTHROPIC_API_KEY=<PRIVATE_NATIVE_ANTHROPIC_KEY>
AI_PROVIDER=anthropic
AI_MODEL=claude-sonnet-4-5-20250929
```

Only `AI_PROVIDER=anthropic` is accepted by current configuration. Other providers need an implemented adapter; a flag does not create one. Review Sonnet 4.5 availability/deprecation and deliberately set `AI_MODEL` to an approved supported model before enabling calls. This maintenance keeps the compatibility default unchanged and makes no provider or billing decision.

For development, leave AI disabled until the core is healthy. Request/response/error contracts have mocked HTTP coverage, not live account validation. Core requirements already contain the public HTTP client; do not install a private SDK or unknown package index for AI. Failures are sanitized and reported unavailable, not a successful executive summary.

Before enabling production AI, approve what business metrics leave your server, review retention/region terms, and set spending/usage limits. Calls may consume paid tokens even when the UI does not display a successful result. Treat summaries as recommendations, not authorization to change stock or financial records.

### SMTP / Email

**Purpose:** send password-reset links and future notifications. SMTP is the mail server protocol; validating an email address is not sending mail.

**Code present, disabled by default:** the native SMTP adapter uses verified STARTTLS or implicit TLS, offloads blocking work, suppresses protocol debug output, and sends only after committed issuance and a current auth-recipient/token recheck. Real PostgreSQL checks cover that recipient query; SMTP/limiter orchestration is tested with offline dependencies, not live provider credentials.

The web login links to `/forgot-password`; reset emails use the canonical `/reset-password#token=...` page. The fragment never reaches the server and is stripped from history; the browser keeps it only in memory, does not redeem on GET, and requires a new login after success. Reloading the stripped page loses the token: reopen the email link. Reset links/passwords must never be pasted into chat, logs, issue reports, or tracking systems.

#### Supported Private Configuration

Configure these in `backend/.env` or the backend secret manager, never in public app variables or tenant Settings. The existing temporary preview/verifier explicitly disable and clear SMTP, even if a private configuration exists; use your own configured persistent instance for real delivery.

| Field | Required setup / default |
| --- | --- |
| `FREE_ONLY_MODE` | Defaults `true`; blocks known paid AI and unapproved external mail, without rejecting hosted DB/cache URLs. Disabling it is outside the zero-fee deployment scope. |
| `APPROVED_FREE_SMTP` | Defaults `false`; requires evidence of a free account, no auto-billing, reviewed quotas and acceptable real delivery before approval. Does not bypass Render port restrictions or certify transport. |
| `SMTP_ENABLED` | `false` until the relay, Redis and public reset page are ready. |
| `SMTP_HOST`, `SMTP_PORT` | One relay hostname/IP and port; default `587`. No URL or embedded credentials. |
| `SMTP_TLS_MODE` | `starttls` for STARTTLS or `tls` for implicit TLS; certificates are verified. |
| `SMTP_USERNAME`, `SMTP_PASSWORD` | Configure the authentication pair privately. Remote SMTP requires authenticated TLS. |
| `SMTP_FROM`, `SMTP_FROM_NAME` | One authorized mailbox; display name defaults to `SupplyOS` and rejects header controls. |
| `PASSWORD_RESET_URL` | One owned HTTP(S) URL with exact `/reset-password` path, no query/fragment/credentials. HTTPS is mandatory in staging/production. This is not the `FRONTEND_URL` CORS list. |
| `SMTP_TIMEOUT_SECONDS` | Socket-operation timeout, default `10`, allowed `1..30`; not a whole DNS/delivery deadline. |
| `PASSWORD_RESET_HOURS` | Existing token expiry, default `1`. |
| `PASSWORD_RESET_CAPACITY` | No-wait in-flight bound, default `4`, allowed `1..32`; cancelled SMTP retains its slot until the thread closes. |
| `PASSWORD_RESET_WINDOW_SECONDS` | Fixed rate window, default `3600`, allowed `60..86400`. |
| `PASSWORD_RESET_MAX_REQUESTS_PER_IP`, `PASSWORD_RESET_MAX_REQUESTS_PER_IDENTITY` | Default `3` per window; configure reviewed limits for NAT/shared-email usage. |
| `PASSWORD_RESET_COOLDOWN_SECONDS` | Default `60`; must not exceed the window. |
| `PASSWORD_RESET_RATE_LIMIT_TIMEOUT_SECONDS` | Cache/admission timeout, default `0.5`, allowed `0.05..5`. |
| `PASSWORD_RESET_WORK_TIMEOUT_SECONDS` | Database preparation deadline, default `10`, allowed `1..60`; not an SMTP deadline. |

For a local email-capture service such as Mailpit, unauthenticated `plain` SMTP is permitted only on development/test loopback. Authenticated plaintext and TLS-verification bypasses are not supported. A production relay needs sender authorization, SPF/DKIM/DMARC, reviewed quotas/charges, and disabled reset-link tracking/rewriting. Do not infer DNS or delivery success from syntax-valid settings.

Requests return `503` before issuance when disabled or globally unavailable, and `429` with bounded `Retry-After` when limited. Accepted requests return the same generic `200` for matching, nonexistent, inactive, ambiguous and wrong-tenant accounts; subsequent SMTP failure is not exposed. The authoritative recipient is `User.email`, never independently editable customer contact data. Staff invitations/email verification and delivery OTP transport are separate unfinished workflows.

**Operational limits:** delivery is in-process best-effort, with no durable outbox or retry worker. A finite race remains after the final recipient/token recheck; DNS/shutdown behavior, native Redis/Lua, live relay authentication/TLS/delivery and production ingress/proxy trust need verification before public use. Review SMTP/provider data retention and sending budgets before enabling any real message.

#### Setup Packet Without Sharing Secrets

Non-secret decisions needed: relay provider/host/port/TLS mode, authorized sender/domain, owned public reset-page origin, PostgreSQL/Redis topology, and sandbox versus production. Authentication passwords, database/cache connection credentials and API keys belong only in the private backend configuration. No extra provider stack has been selected; account creation, paid plans and live calls are not authorized by this guide.

### Credential Requirements by Service

This is a private setup checklist, not a request to send secrets. Supported bindings are distinguished from future connectors; adding a future key does not enable missing code.

| Service | Non-secret decisions to agree | Secret handling / implementation boundary |
| --- | --- | --- |
| PostgreSQL | Dedicated database, host/port, user, TLS/pooling and backup policy. | Password stays in private `DATABASE_URL`/`DATABASE_URL_SYNC` components; both target one database. Supported. |
| Redis | Native TCP/TLS endpoint, database, ACL user and recovery command/key permissions. | Authentication stays in private `REDIS_URL`; REST tokens are not compatible. Supported client/limiter, native execution still needs verification. |
| SMTP recovery | Relay, host/port/TLS mode, authorized sender/domain and public reset-page URL. | `SMTP_USERNAME`/`SMTP_PASSWORD` stay backend-only. Supported opt-in adapter; live sending must be deliberately verified. |
| Anthropic summaries | Approved provider/model, allowed aggregate data, retention/region and spend limits. | `ANTHROPIC_API_KEY` stays backend-only. Existing direct adapter; live account/model validation is separate. |
| Private proof storage | Durable private filesystem with paired DB/file backups, or reviewed private Supabase REST bucket/version/retention capability. | Local store needs no external key; integrated Supabase fields stay private and default-held. Generic S3/workload-identity adapter remains future work. |
| Payment gateway | Provider, merchant country/currency, sandbox, settlement/refund scope and public webhook origin. | Merchant API/signing secrets remain backend-only. Checkout/provider verification/webhooks are not implemented. |
| OTP / WhatsApp / SMS | Channel/provider, same-tenant recipient source, verified sender, opt-in/templates, phone format and TTL/resend/attempt policy. | Sender/API and webhook secrets remain private. No messaging transport is connected; generation is not delivery. |
| Maps / routing | Provider, navigation versus geocoding/optimization, location consent, coverage and quotas/key restrictions. | Server keys are private; a restricted browser key is separate only when a real map UI requires it. Connector pending. |
| Voice | Device/browser/telephony input, provider/model/languages, recording consent and retention. | Hosted transcription secrets stay private; on-device options need a toolchain. Audio/transcription/voice-to-order is pending. |

Provide only provider names, capabilities, non-secret topology and approval decisions when continuing setup. Configure actual passwords/keys through the private backend environment or secret manager, never chat or checked-in documentation.

### S3-Compatible Storage: Future Alternative

**Purpose:** store delivery photos and signatures. S3-compatible means an object store with an S3-style API; it does not mean the bucket should be public.

**Pending generic S3 adapter:** local storage and a specific gated Supabase REST transport are implemented above. There is no generic S3 adapter or signed-object access. An S3 key cannot activate that missing integration, and a public URL cannot replace the required delivery-bound receipt.

If an S3 adapter is later implemented, development could use a private compatible test store, such as MinIO; it is unnecessary for today's local workflow. A chosen hosted store would need a private bucket, endpoint, region, least-privilege credentials/workload identity, encryption, retention, and authorized short-lived access. No vendor or paid plan has been selected by this guide.

Keep credentials server-side. A robust implementation stores a durable object key and creates expiring read URLs when needed; an expiring signed URL should not become the permanent proof identifier. Do not "fix" missing access by making proofs public. Check storage, operation, and download/egress charges.

### Maps and Route APIs

**Purpose:** convert addresses to coordinates, calculate directions, or optimize multiple delivery stops.

**Pending:** `/deliveries/my-route` is a priority-sorted list, not geographic navigation. Addresses/coordinates, routing settings, and installed mobile packages do not constitute a maps integration.

Use manual stop priority in development. For production navigation, choose a provider only after its connector is implemented, confirm coverage for your delivery region, and set quotas. Keep server routing keys in the backend. If a future browser map needs a public key, use a separate restricted key with approved origins and APIs, not a server secret. Geocoding, directions, and optimization can have separate charges.

### Payment Gateway Versus Manual Recording

**Purpose:** a gateway processes or verifies electronic payments. A manual payment record only records what staff say was received.

**Code present:** super-admin/accountant users can record cash, UPI, bank-transfer receipts, or orderless credit notes. Authorized delivery operators can record cash/UPI through guarded completion. SupplyOS records declared receipts; it does not initiate a UPI transfer or verify bank/provider settlement.

Choose the payment action carefully:

- Select `order_id` to allocate the actual receipt amount to that customer's order. The server updates `amount_paid` and `amount_due`, rejects overpayment/wrong ownership, and sets order status `paid` only after physical delivery.
- Leave `order_id` empty for an explicit unallocated advance/account credit. This changes the signed customer balance, not an order's funding. A negative `outstanding` is account credit; do not clamp it to zero or assume it pays a cash order.
- Payment `mode=credit` means an orderless credit note, not collected money. It cannot fund an order. Order `payment_mode=credit` is a different field: it means an approved credit sale.

Order mode defaults to the customer's type on the server. Legacy `is_credit=False` does not bypass credit checks. Credit orders hold the gross total from creation; reservation/delivery recheck signed balance and live commitments under database locks. Pending cash funding is accounted for so prepaid cash orders do not falsely create extra credit capacity. Cash-mode delivery requires full allocated cash/UPI/bank funding, including any recorded collection; approved credit orders may finish delivered while unpaid. A `payment_status=paid` badge before dispatch does not mean physical delivery occurred. A full order `completed`/closeout workflow is still not exposed.

The admin displays authoritative server amount/credit/advance fields rather than authorizing money in JavaScript. The API now accepts payment-list `customer_id` and `order_id` filters; the current admin payment list uses only `customer_id`.

**Pending external finance:** checkout, a gateway SDK/API, signed webhooks, provider-event deduplication, actual refunds/settlement reconciliation, invoice PDFs, and a complete general ledger. The implemented customer ledger is not bank verification or full accounting software.

Use test-only records in an isolated development business. For real manual collections, independently confirm the money arrived and reconcile with the bank/cash book. Never collect the money again merely because an HTTP response was lost.

### Retrying an Order, Payment, or Completion

`X-Idempotency-Key: <UUID_FOR_THIS_INTENT>` is implemented for order creation, payment recording, and the guarded completion endpoints. The header remains optional for existing v1 clients; new clients should send it. The same key, normalized payload, actor, tenant, and operation recovers the original committed JSON/status without repeating effects. Changed payload with an already used key returns `409`; a failed transaction rolls back its claim and effects. Concurrent same-key requests wait through PostgreSQL, not a client/body-only deduplication rule.

Records carry 24-hour expiry metadata; retained records remain replay-protected beyond that minimum. There is no automatic cleanup/reuse promise. Retry the same endpoint/operation: legacy order delivery and delivery completion have separate replay operation names, even though they use the same guarded finalizer.

The admin retains an intent key on network failures, `408`, `5xx`, automatic auth refresh, and same-page modal close/reopen. Success, definitive other `4xx`, or changed fields starts a new intent. Two legitimate identical payments get different keys. Retry state is page-scoped, not durable across reload/offline/app restart; if it is lost, inspect recorded receipts before starting another payment. Idempotency does not verify a bank reference or make every API mutation replay-safe.

When online collection is implemented, start in the provider's sandbox. Keep test/live credentials separate, verify webhook signatures on the backend, and test failed, duplicate, delayed, and refunded payments before live use. Use provider-hosted checkout/tokenization; never collect or store raw card data or gateway secret keys in SupplyOS clients. A live gateway may require business/KYC (identity) approval and charge transaction, settlement, or refund fees.

### WhatsApp Business

**Purpose:** receive order messages or send approved delivery/business notifications.

**Pending:** `channel="whatsapp"` on an order is just a label. There is no business-account connection, inbound webhook, message parser, sender, or verified WhatsApp-to-order workflow.

Begin with provider test numbers only after code exists. Production may require business/phone verification, approved templates, customer opt-in, and a public HTTPS webhook. Keep access credentials and webhook verification/signing secrets in the backend. Incoming orders must go through the same stock/credit validation and human review rules as other channels. Review current message-category/provider fees; a personal WhatsApp account is not an automated Business API connector.

### Voice Transcription

**Purpose:** turn an audio recording into text that a person can review before creating an order.

**Pending:** there is no audio-upload/transcription/voice-order connector. A planned Whisper or cloud speech provider is not an installed, usable feature.

Development should use consented, non-sensitive sample audio when implementation begins. Choose local processing or a hosted provider based on language accuracy, compute cost, privacy, and retention. Hosted credentials belong on the backend; microphone access belongs in the app's permission flow. Require review of products, quantities, and customer identity before committing an order. Budget for audio minutes, storage, and possibly local GPU/compute costs.

### Pending Configuration Labels

These are **illustrative planning names, not supported environment variables or an installation recipe**. Final contracts remain unresolved. Do not add keys expecting the current application to consume them.

| Future connector | Possible labels to agree when implementing | Secure location |
| --- | --- | --- |
| External S3 storage | `S3_ENDPOINT_URL`, `S3_BUCKET`, `S3_REGION`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`; signed-access settings still to be agreed. These are not needed for implemented `PROOF_STORAGE_DIR`. | Private backend environment or workload identity. |
| Maps | `MAPS_API_KEY`; provider and API selection unresolved. | Backend secret store; separate restricted public key only if an implemented map UI needs one. |
| Payments | `PAYMENT_WEBHOOK_SECRET`; other key/merchant names depend on the chosen gateway. | Backend secret store, with distinct sandbox/live configuration. |
| WhatsApp | Account/phone IDs, access key, webhook verification/signing secrets; exact names unresolved. | Backend secret store. |
| Voice | Provider/model selection and optional provider key; exact names unresolved. | Backend environment/secret store. |

Do not put any of these secrets into the admin Settings page. Existing rule settings also do not automatically start jobs or enforce every advertised business rule.

## Simple Preflight Checklist

- [ ] Python/Node and isolated project dependencies are ready; Flutter is separately ready if testing mobile.
- [ ] A fresh test PostgreSQL database exists; both SQLAlchemy URLs target it with the correct drivers.
- [ ] A compatible Redis TCP/TLS service is reachable; its credentials are not REST credentials.
- [ ] Private configuration is excluded from Git, and every template placeholder has been replaced privately.
- [ ] Backend/frontend ports, API prefix, proxy behavior, and exact allowed browser origin agree.
- [ ] The release's real schema setup/migrations have been verified on a clean database.
- [ ] The local proof root has safe ownership/permissions, and authorized uploads/private reads work for the correct delivery and proof kind.
- [ ] API health and database/Redis connectivity pass.
- [ ] Setup/login/catalog/order/collection tests use only your isolated test business, with no old preview defaults.
- [ ] AI and other billable connectors stay disabled unless implementation, privacy, and budget checks are complete.

After starting your own local backend, these read-only PowerShell requests check the existing health endpoints:

```powershell
Invoke-RestMethod -Uri "http://localhost:8001/api/health"
Invoke-RestMethod -Uri "http://localhost:8001/api/health/deep"
```

The first endpoint reports application liveness. Deep health performs a database `SELECT 1` and Redis ping, returning per-dependency status and `503` when either is unavailable. Redis is not started by the temporary preview. Health does not prove every workflow/provider or mobile app works. An unauthenticated `/auth/me` response of 401 is expected; it is not a provider outage. These commands are examples, not fresh requests made against the running preview by this documentation task.

## Troubleshooting

| Symptom | Check this first |
| --- | --- |
| Backend fails with a missing `DATABASE_URL`, `DATABASE_URL_SYNC`, `REDIS_URL`, or `JWT_SECRET` | Supply all four to the backend process. Check the launch directory/environment-file option, without printing values. Restart it. |
| `ModuleNotFoundError` for FastAPI, SQLAlchemy, asyncpg, or Redis | The isolated backend environment is not installed/selected. A working global Python command is not enough; follow the current runtime instructions. |
| PostgreSQL connection refused | Check that the database service is running and the host/port are correct. Container `localhost` means that container, not another database container. |
| Async database driver or TLS parameter error | Check `postgresql+asyncpg://`; async `sslmode` is normalized to `ssl`, but conflicting values are rejected. The migration URL needs the synchronous driver and `sslmode`. |
| Password authentication, certificate, or network-policy failure | Verify credentials privately, component URL encoding, CA/TLS settings, and provider allowlists. Do not disable security or share the full URL to troubleshoot. |
| Redis rejects the URL or cannot connect | Use `redis://`/`rediss://`, the actual TCP/TLS port, and correct ACL credentials, not an `https://` REST endpoint/token. |
| Web requests return 404 or contain `/api/v1/api/v1` | Separate the backend origin from the API prefix. For same-origin calls, verify a proxy really exists. |
| Web login succeeds but later requests return 401 | Check cookies, exact frontend origin, credentials-enabled CORS, and `SameSite`/`Secure` rules. Use one local hostname consistently. Do not switch to storing tokens in browser localStorage. |
| Delivery route returns 403 or is empty | The route endpoint expects a delivery-partner role and that user's assigned unfinished deliveries for today/unscheduled. A maps account will not fix role or assignment problems. |
| Health is OK but tables or workflows fail | Liveness/connectivity are not schema/business tests. Check the actual migration contents and isolated application tests. |
| AI summary is absent or configuration rejects a provider | Empty `ANTHROPIC_API_KEY` disables AI. Current `AI_PROVIDER` accepts only `anthropic`. Configure your own key privately and review model availability/budget and sanitized errors; no SDK/provider is installed automatically. |
| Local photo/signature upload fails | Use PNG/JPEG within 5 MiB/20M pixels, real multipart boundaries, and an authorized delivery. `400`/`413` can indicate invalid image/body limits; a private-storage conflict means root/file permissions or integrity need review, not public access. |
| Completion returns an OTP/proof/funding conflict | Use the verified recipient OTP, both uploaded canonical references, and enough allocated cash/UPI/bank funding for cash mode. Credit is approved server-side. Do not bypass the finalizer or relax Settings to hide the error. |
| Payment result is unconfirmed | Retry unchanged within the same intent; do not receive money twice. After losing page state, review receipts first. A reused key with changed payload correctly returns `409`. |
| Reset email returns `503` or `429` | Check the supported private SMTP/reset fields and native Redis readiness/ACLs; unavailable admission never issues a token. Respect `Retry-After`; the temporary preview deliberately keeps SMTP disabled. |
| Reset request is accepted but no email arrives | The acknowledgement does not reveal eligibility/delivery. Check authorized sender/DNS/quota and sanitized failure categories privately; best-effort work has no durable retries. Never share a reset link or SMTP reply containing private data. |
| S3, maps, WhatsApp, or voice never starts | These connectors remain pending; no illustrative planning key or saved setting enables missing code. |
| Flutter command is missing, or mobile cannot reach localhost | Install/select the mobile toolchain separately and finish platform setup; then use a device-reachable API address. Never fall back to an old preview URL. |

Share only sanitized error type, request ID, command name, and non-secret topology when seeking help. Remove credentials, reset links, cookies, customer data, and connection URLs from logs/screenshots.

## Before Production Launch

Treat this as a release gate, not a statement that these protections already exist:

- [ ] Choose hosting/providers explicitly, verify region/privacy terms, and agree budgets, quotas, alerts, and ownership. No paid subscription is implied by this document.
- [ ] Use your own domain with valid TLS/HTTPS, correct proxy routing, certificate renewal, and production transport/header policies.
- [ ] Keep PostgreSQL/Redis private or strictly allowlisted, with verified TLS where required. Use least-privilege runtime users and separately controlled migration permissions.
- [ ] Keep signing/provider credentials in a secret manager; separate dev/staging/prod; plan key rotation and remove sensitive token/error logging.
- [ ] Validate production cookie security, refresh rotation/revocation, password recovery, CSRF/rate limiting, and tenant/customer/delivery role isolation. Current source gaps cannot be fixed merely by changing a URL.
- [ ] Run reviewed real migrations against a clean staging database, check the revision and resulting schema, back up before production migration, and prohibit automatic schema creation in production.
- [ ] Use a durable private proof mount with verified service ownership/ACLs, trusted ancestry, and TLS. Back up/restore database receipts and image files together; agree encryption and retention. Validate native Linux/filesystem behavior before deploying that platform; S3/signed access is not implemented yet.
- [ ] Preserve the verified stock/credit/payment/replay/OTP/POD guards, then check real staging concurrency, reconciliation, and failure behavior. Both delivery paths share a guarded finalizer, but this does not establish staff provisioning, OTP messaging, full audit, or complete mobile operations.
- [ ] Verify API readiness and critical authenticated app flows in staging. Configure sanitized monitoring/alerts; health alone is not an end-to-end acceptance test.
- [ ] For each optional connector used, verify sandbox delivery/callbacks, least privilege, consent, failure behavior, and budget before enabling live traffic.
- [ ] Advertise only workflows verified in this release. Security/SOC2 requirements in planning documents are not SOC2 certification or verified compliance.

## Keeping This Guide Accurate

The implementation boundaries above were checked against the [.ai governance](../.ai/AGENT_INSTRUCTIONS.md), [codebase snapshot](../memory/CODEBASE_SNAPSHOT.md), [backend settings](../backend/app/core/config.py), [requirements](../backend/requirements.txt), [database engine](../backend/app/core/database.py), [Redis client](../backend/app/core/redis_client.py), [server/health endpoints](../backend/server.py), [Alembic environment](../backend/alembic/env.py), [AI provider](../backend/app/infrastructure/external/ai_provider.py), [AI analysis](../backend/app/features/ai_supervisor/service.py), [auth](../backend/app/features/auth/router.py), [deliveries](../backend/app/features/deliveries/router.py), [payments](../backend/app/features/payments/router.py), [web API client](../frontend/src/lib/api.ts), and [Next configuration](../frontend/next.config.js).

Milestone sources: [financial migration 0004](../backend/alembic/versions/20261109_1543_financial_core.py), [proof migration 0005](../backend/alembic/versions/20261109_1640_private_delivery_proofs.py), [money service](../backend/app/features/payments/service.py), [shared finalizer](../backend/app/features/orders/service.py), [request replay](../backend/app/shared/idempotency.py), [proof API](../backend/app/features/proofs/router.py), [image/integrity checks](../backend/app/features/proofs/service.py), [pre-parser byte cap](../backend/app/features/proofs/middleware.py), [private filesystem helper](../backend/app/infrastructure/storage/local.py), [preview helper](../backend/tools/run_preview.py), [frontend finance DTOs](../frontend/src/lib/finance.ts), and [frontend intent handling](../frontend/src/lib/intent.ts).

The current 781-pass/3-skip backend checkpoint includes prior core/finance/POD/recovery plus browser-origin, journal/version, auth/assignment locks and real journal ACL/RLS regressions. Skips remain live AI and two native Linux cases. Frontend 102 dev/prod plus 10 separate browser-security cases, lint/types and the 19-page build pass; mobile 254 VM passes/three clean analyses are separate from APK/browser acceptance. Earlier 520/102, 507/100, 354/87 and smaller reports are dated, not additive. Verification used owned disposable resources; no private credential inspection, Git publication, live application-provider call, SDK/license provisioning or paid activation occurred. Native Redis/Lua, hosted proof/backup, live mail, cloud quality and release APKs remain unverified or held. Regression results are not availability/performance certification.
