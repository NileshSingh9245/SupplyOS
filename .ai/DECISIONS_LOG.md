# DECISIONS LOG - SupplyOS

Every meaningful architectural / product decision is captured below. Newest first.

Format:
```
## <YYYY-MM-DD> - <short title>
Context:
Decision:
Alternatives considered:
Tradeoffs:
```

---

## 2026-11-12 - Own-password retirement and coherent effective pricing
**Context:** Onboarding was authorized, but current users lacked a password-change form and mobile catalog prices were only product bases. Per-line mutable price lookups could mix tier/product/tax states during one order.
**Decision:** Add current-password reauthentication, User-first session/reset locking and atomic credential/audit/epoch retirement, with bounded durable rejection counters and no automatic login/replay. Keep only safe outcome notices across self-revocation; unknown responses cannot become success.
**Decision:** Add role-specific tier/override controls and tenant-owned UUID tier assignment. Retain existing60-character tier creation while restricting customer references to30; forbid renaming. Publish a minimal customer-own catalog with exact price/tax and tenant-declared currency, protecting eligibility/currency through authorization. Order creation consumes one immutable SQL batch, and historical snapshots never reprice.
**Dependencies:** `orders.service -> pricing.service`, `customers.router -> pricing.service`; pricing/accounting share pure decimal validation. Repositories use infrastructure models and no reverse feature dependency is introduced.
**Evidence:** Root full backend1078/3 unchanged skips573.51s; frontend208 dev/208 production, clean lint/types and22-page build. Cached Flutter verification:177 shared/62 customer/24 delivery,263 VM passes and three clean analyses. The legacy AI-alert assertion now follows the declared severity enum; no assertion is weakened to accept arbitrary output.
**Limits:** Cart/checkout, invoices/audit, warehouse association, typed operational settings/promotions, native delivery and live production acceptance remain. No new migration, deployment, provider activation, SDK/license provisioning, signing or Git publication; existing preview and private configuration preserved.

## 2026-11-12 - Authorized bootstrap and owner-controlled account lifecycle
**Decision:** Require private operator authorization before first-setup parsing, serialize the empty-database decision, preserve incomplete tenants and stop automatic verified-email claims. Add owner-only named staff with immutable owner/customer boundaries, whitelisted updates and atomic all-session/reset retirement. Authenticate owner/accountant customer intake with persisted tenant authority; legacy UUID is only an assertion. Normalize optional contacts and block credit edits invalidating commitments; lock partner eligibility before Delivery.
**Privacy:** Private route responses use static redacted validation/unexpected errors and no-store; SQL parameters hidden. Owned API/migration/tests and frontend workers explicitly avoid dotenv/private configuration. Holder passwords are never generated/shared/returned; no email/invitation/login success is invented.
**Evidence:** Root full backend954/3skips363.06s; frontend165 dev/165 production, lint/types and20-page build, preserving previous regression cases. Named staff is not email verification, profile linking, warehouse association or full business acceptance. No deployment/provider/SDK/signing/Git activity; existing preview preserved.

## 2026-11-12 - Shared online mobile session and read-only workflows
**Decision:** Replace duplicate prototype clients with one memory-only HttpOnly cookie/session transport. Bound renewal/replay, preserve exact customer/delivery-partner roles, cancel stale login/logout/query generations, scope caches and report unknown logout outcomes honestly. Require explicit release/profile public HTTPS API configuration; no default endpoint, plaintext persistence or certificate bypass. Keep all money/quantity values as exact server Decimal text; customer catalog/orders/detail/history and delivery routes are read-only.
**Evidence:** Root and owner VM verification: shared 177/customer 53/delivery 24, 254 passes, three clean analyses and offline dependency resolution. An independent renewal-barrier finding is fixed: late 401/in-flight 200/decoded results loop over every pending verification and recheck epoch/key before replay/publication. All 239 baseline cases remain plus 15 new races/cookie-domain/path cases. Unused native/persistence/image/codegen plugins were removed, not advertised as implemented features.
**Limits:** Browser SDK and Android build caches are absent, so no real-browser/APK execution or client-ready endpoint is claimed. Cart/checkout, native QR/OTP/proof/collection, encrypted offline outbox and operational locale remain future goals. Android resources/signing/transport guards are separate from runnable APK validation.

## 2026-11-12 - Journaled private proofs and browser-origin enforcement
**Context:** Prior hosted storage existed only as a transport; local image serving reopened verified paths, uncertain commits could delete evidence, and final auth checks could precede blocking receipt locks.
**Decision:** Persist ownership before upload; preserve private bytes/journal on every ambiguous outcome. Persist exact backend/project/bucket/object/version provenance and reject latest/public fallback. Serve local verified bytes through native held handles. Final receipts serialize User -> active session -> Delivery -> journal and recheck auth after waits, without auth/delivery locks during external upload. Gate Supabase on explicit account/versioning review plus private ENABLED bucket and exact retained-version/hash verification. Add a global pre-parser Origin/Referer boundary, UUID request IDs and nonblocking security headers; preserve explicit no-header native compatibility.
**Alternatives:** Delete on lost commit replies, infer a version from latest metadata, make buckets public, trust CORS/Host/forwarded headers alone, or silently disable native refresh (rejected).
**Tradeoffs:** Reserved rows need reviewed reconciliation, not automatic deletion. A non-key User auth lock permits partner FK checks while blocking eligibility updates; real assignment/upload contention is tested. Public REST source/offline mocks are not deployed retention/WORM proof. Ingress/whole-app RLS/general limits/XSS, native Linux, backup/restore and hosted completion lock duration remain release work. Root full regression: 781 passed/3 skipped in 295.51 seconds; frontend 102 dev/102 prod, 10 separate browser-security cases, lint/types/19-page build. No deployment, provider activation, SDK/license provisioning, private signing or Git publication.

## 2026-11-11 - Enforced fee gates with hosting-neutral configuration
**Decision:** `FREE_ONLY_MODE` defaults true and denies the Anthropic transport at selection and direct-call boundaries. The rule engine remains usable. `/ai/capabilities` and analyze `summary_status` explicitly describe held/unavailable/queued work; the UI cannot claim a generative job was queued when it was held. No lower-quality model or fabricated summary is substituted.
**Decision:** Free-mode SMTP needs explicit `APPROVED_FREE_SMTP`; otherwise only development/test loopback capture is permitted. Guards run before limiter/token work and at transport boundaries. Account approval, quotas and live quality remain operator evidence, not a hostname inference. PostgreSQL/cache cloud URLs remain valid for the client-hosted target.
**Evidence:** Full owned backend 520/3 in 223.12 seconds, frontend 102 dev/102 production, lint/types and 19-page build. An import-order regression exposed Alembic disabling preexisting application loggers; `fileConfig(..., disable_existing_loggers=False)` and a migration regression preserve sanitized failure observability instead of weakening capture/privacy assertions.
**Constraints:** Available Vercel scope is Hobby and is not selected for client-commercial hosting under its non-commercial terms. Render Free ephemeral files/idle sleep/SMTP restrictions and Supabase Free quotas/pauses require explicit release gates. No account/plan/private credential change or deployment occurred; workstation tooling is not a production dependency. Hosted proof transport and properly signed, public-API Android releases are next.

## 2026-11-10 - Cloud client sharing and Android delivery supersede machine-local runtime
**Context:** The application must be reachable by clients without the developer PC running, with Android APKs as well as the web app. The zero-service-fee and no-quality-degradation requirements still apply.
**Decision:** Target independently hosted web/API, hosted PostgreSQL/private proof storage and release APKs bound to a real public HTTPS API. Vercel/Supabase/Render are candidate deployment providers, not automatically activated accounts. Building/testing on the workstation is permitted; production must not depend on its database, filesystem, Ollama, SMTP inbox or a PC tunnel.
**Decision:** Free mode gates known optional billable providers; it does not reject cloud database/cache URLs or infer price from localhost/hostname. Generative alternatives stay held until cloud-compatible quality evidence exists. SMTP in free mode requires an explicit verified free-account approval; a local test inbox remains capture-only. Secrets remain private and no paid plan/account or publishing action is authorized.
**Tradeoffs:** Render Free sleeps after 15 idle minutes, loses local files on restart/spindown, expires its free database after 30 days and blocks standard SMTP ports. Supabase Free has database/storage/egress quotas and inactivity pauses. Provider limits cannot be called production-quality equivalence or bypassed with keep-awake tricks. Hosted private proof storage and deployment/connection validation must precede client use; no APK with a localhost/placeholder release endpoint can be called ready.

## 2026-11-10 - Opt-in bounded SMTP recovery with private configuration
**Context:** Reset issuance/redemption already had digest-only storage, transactional single-use and global session revocation, but no transport/public UI. Direct synchronous mail could leak account eligibility, and frontend session remounts could discard a stripped fragment token.
**Decision:** Add disabled-by-default native SMTP with verified TLS, backend-only credentials and a canonical owned `/reset-password` URL. Admit all validated identities through HMAC Redis fixed-window IP/identity counters and cooldown before lookup; use no-wait app-owned capacity and post-response work with a new SQL session. Global unavailable admission is `503`, limits are `429`, and accepted eligibility/delivery outcomes share generic `200`. Recheck the current auth email and token after committed issuance; close SQL work before SMTP. Reject exhausted IPs before allocating more identity keys.
**Decision:** Reset links carry fragments, not query tokens. Public recovery pages survive anonymous bootstrap/session revocation, strip URLs, retain secrets only in memory, and require new login. Old responses cannot discard a newer opened link. Auth cookies are cleared on successful reset. Cancelled SMTP retains capacity until the offloaded thread closes; ASGI level cancellation is shielded rather than busy-waited.
**Alternatives:** Personalized errors, logged/reset-response secrets, synchronous recipient-only SMTP, plaintext-token durable queues, mutable customer contact recipients, public browser secrets, or auto-authentication (rejected).
**Tradeoffs:** Fixed-window recovery limits implement this bounded opt-in path, not the broader intended sliding-window policy. Delivery is best-effort, not durable; a finite post-recheck race and whole DNS/shutdown deadlines remain operational limits. Live SMTP/sender/DNS, native Redis/Lua, production proxy/ingress and broader security need verification. No other provider stack was selected, no accounts/paid plans were activated, and credentials are configured privately rather than handed over in chat.
**Evidence:** Coordinator-owned full backend: 507 passed/3 skipped in 270.45 seconds, including real PostgreSQL recipient-state cases. Frontend: 100 dev and 100 production passes, lint/types and 19-page build. Source: `features/auth/recovery.py`, `infrastructure/external/smtp.py`, auth router/repository, private settings, and frontend `(account)`/recovery/session code. Finance/POD migration head remains `0005`.

## 2026-11-10 - Working-tree metadata cleanup without rewriting private or Git state
**Decision:** Remove obsolete test setup, inactive identity metadata, empty retired-platform directories and untracked stale bytecode. Normalize old report/path metadata while preserving original result counts/timestamps. The current noncredential source/config/docs scope is checked independently from Git index/history and private credential artifacts; those excluded scopes remain untouched and are not certified clean. No commit, staging reset or history rewrite is authorized by cleanup.

## 2026-11-09 - Atomic manual finance and per-intent replay
**Context:** Caller-selected credit flags, unallocated receipts, clamped balances and separate delivery paths could misstate funding/capacity or repeat effects after a lost response. Legacy credits also needed actual receipt attribution before adopting new exposure fields.
**Decision:** Frozen financial `0004` uses server cash/credit defaults, gross credit holds, signed balances and pending cash funding. Lock Order -> Customer -> Delivery -> canonical stock; recheck live state and commit stock/sale/receipt ledger/history/audit/replay together. Linked actual cash/UPI/bank receipts update paid/due; orderless receipts are advances/account credits and credit notes never count as collected funds. Cash delivery must be fully funded; approved unpaid credit can finish delivered. Order `paid` follows physical delivery, not a prepayment badge.
**Decision:** Optional-v1 UUID `X-Idempotency-Key` is actor+tenant+operation scoped for orders/payments/completion. Same modeled payload replays original JSON/status; changed payload conflicts, failure rolls back claim/effects, concurrent requests serialize in PostgreSQL. New legitimate identical payments are new intents. UI retains keys for uncertain network/408/5xx/auth refresh and same-page reopen, not durable reload/offline state. Twenty-four-hour expiry metadata does not automatically permit reuse of retained records.
**Alternatives:** Client credit/remainder math, global body deduplication, raw URL proof, clamping account credits, implicit cash credit, or automatic rewriting/merging of historical money (rejected).
**Tradeoffs:** Online `0004` requires every receipt to be credited exactly once by a valid owned payment reference or verifiable legacy delivery group; unknown/orphan/duplicate/phantom credits stop for operator review without rewriting original history. Implied opening balances are preserved, not independently reconstructed/certified. Financial downgrade refuses populated records; offline SQL skips the online preflight. Bank/gateway settlement, refunds, full general ledger, completed-order closeout and partial shipments remain future work.
**Sources:** `features/orders/service.py`, `features/payments/{service,schemas,router}.py`, customer/order models, `shared/idempotency.py`, financial `0004`, and frontend finance/intent components. Latest owned backend 354/3 and frontend 87 dev/prod checkpoints are reported separately, not guessed financial subcounts.

## 2026-11-09 - Local private proof receipts before an external object store
**Context:** A URL field does not prove image ownership/privacy; parser-side buffering and permissive existing filesystem access were unsafe. Downgrading proof metadata could erase completed evidence even while files/URLs remained.
**Decision:** Implement local `PROOF_STORAGE_DIR` (default backend/.runtime/proofs), authenticated upload/read and DeliveryProof receipts in frozen `0005`. Completion requires both verified OTP and delivery/tenant/kind-bound signature/photo records. Pillow 13 verifies/full-decodes bounded PNG/JPEG, and ASGI caps actual bytes before multipart parsing, including misleading/absent lengths and legacy/invalid-ID routes. Proof reads/finalization recheck private permissions and size/MIME/digest; `0005` downgrade refuses rows/references.
**Decision:** New Windows roots/files have explicit process-user owner and protected owner/SYSTEM/Admin-only ACLs; unsafe existing objects are rejected without permission repair. Linux uses restrictive creation modes/owner checks/no-follow descriptors; native Linux filesystem tests remain skipped on Windows. The fixed returned-Path API does not hold a read handle across FileResponse; trusted ancestry and owner/admin processes remain a stated assumption.
**Alternatives:** Public proof buckets, arbitrary external URLs, blind chmod of existing data, unbounded multipart spool, or deleting receipts to downgrade (rejected).
**Tradeoffs:** Local development needs no S3 subscription/key. Production requires durable private mounts, paired database/file backup-restore, TLS, retention and native-platform verification. Failed writes can leave private partial orphans; cleanup/jobs and external S3/signed access remain future choices, not configured adapters. Privileged host admins can read by design; no encryption/SOC2/host-compromise guarantee is implied.
**Sources:** `features/proofs/{router,service,middleware}.py`, `infrastructure/storage/local.py`, proof `0005` and frontend delivery/capture components. Latest coordinator run: 354 passed/3 skipped in 260 seconds, including prior core and these corrections; skipped scopes are live AI and two native Linux cases. Frontend 87 passes in dev/prod with lint/types/17-page build. Maintenance did not rerun tests, retest concurrent configuration cleanup, or touch preview/data.

## 2026-11-09 - Direct optional AI and owner-controlled service configuration
**Context:** Cloud/DB/provider setup must remain explicit and private; obsolete private-SDK/provider configuration is not needed for the core application.
**Decision:** Current AI accepts only the implemented direct Anthropic adapter through core `httpx`, manually configured with backend-only `ANTHROPIC_API_KEY`, `AI_PROVIDER=anthropic` and reviewed `AI_MODEL`. Missing key means no external summary call. PostgreSQL/Redis/proof paths and later SMTP/S3/maps/gateway/WhatsApp/voice remain owner-configured; no chat credential handoff, provisioning, vendor or payment choice is made.
**Alternatives:** Automatic cloud linking, private platform SDK dependency, hidden provider fallback, or selecting a paid model merely to parallelize work (rejected).
**Tradeoffs:** Model availability/deprecation must be reviewed deliberately; compatibility default Sonnet 4.5 is not a promise of current access. Earlier transport/regression reports are local or mocked, not live accounts. Setup can use the existing disposable localhost preview, but its temporary data is not permanent business storage. Dated earlier milestones are retained below; their adapter/rollout status is superseded by current source.

## 2026-11-09 - Persisted auth sessions, tenant identity, and canonical stock locking
**Context:** Refresh did not rotate/revoke access, identity could select another tenant, authenticated customers could access broader operations, and nullable stock keys permitted duplicate first rows. Mixed lock orders could deadlock.
**Decision:** Frozen `0002`/`0003` persist stable sessions/revocation versions and canonical stock uniqueness. Enforce tenant identity and server read/write scopes. Acquire stock locks in product/row ID order, separately from FIFO allocation. Old-epoch replay cannot invalidate fresh reset/reauthenticated sessions; reject malformed OTP before constant-time comparison.
**Alternatives:** Client business logic, in-memory stock mutexes, arbitrary tenant selection, or automatic merging of stock rows (rejected).
**Tradeoffs:** Duplicate legacy stock needs reviewed reconciliation. Existing hashes remain valid; new password policy is stricter. At this earlier checkpoint the runner was 171 pass/one live-AI skip and financial/POD work was pending; the later 354/3 milestone above supersedes that status. Broader security, email and mobile remain incomplete.

## 2026-11-09 - Fail-closed schema adoption and bounded verification ownership
**Context:** Review found extra mandatory legacy columns, partial/invalid indexes, implicit destructive rollback, settings alias precedence, and unbounded/orphanable verification subprocesses.
**Decision:** Require exact frozen legacy columns and matching valid index predicates/options; gate destructive baseline downgrade with explicit opt-in. Normalize constructor values to canonical aliases. Run verification children in a kill-on-close Windows Job with deadlines, and migrate separately created CI child databases for regressions.
**Alternatives:** Accept unknown schema extensions, rely on rollback comments, clear ambient variables instead of fixing precedence, or only kill a virtualenv launcher (rejected).
**Tradeoffs:** Unsafe legacy schemas stop for review, not silent adoption. Evidence: 76 backend checks with one live-AI skip, 8 native/CI-path PostgreSQL cases, and abrupt-parent-exit coverage; remote CI/live deployment remain unverified.

## 2026-11-08 - Explicit migrations and guarded legacy baseline
**Context:** The initial revision contained no DDL, while startup created tables even in production. Schema metadata also depended on runtime credentials.
**Decision:** Preserve the historical revision, add frozen table/index definitions in baseline `20261108_0001`, validate a matching legacy schema before adoption, and reject mismatches. Declarative metadata lives in `app/infrastructure/db/base.py`; startup verifies revision/tables/columns and never performs implicit DDL.
**Alternatives:** Keep `create_all` on boot or blindly stamp existing databases (rejected).
**Tradeoffs:** Operators must migrate before startup and back up before destructive rollback; review corrections add explicit opt-in. Eight PostgreSQL migration regressions now cover fresh, matching legacy, mismatches, rollback, and startup behavior.

## 2026-11-08 - Validated private configuration and same-origin web proxy
**Context:** Import-time environment lookups, insecure cookie constants, stale auth caches, and missing proxy/configuration made local startup/session recovery unreliable.
**Decision:** Use immutable validated settings with hidden secret repr/errors, explicit origins, production TLS/secure-cookie defaults, and migration-only configuration. Keep the cookie/Bearer API shape and `/api/v1` plus legacy `/api`; the Next server proxies `/api/*` using server-only `BACKEND_URL` (backend port 8001). Auth-scoped web caches and superseded requests are cleared/cancelled.
**Alternatives:** Browser localStorage tokens, wildcard credentialed CORS, or moving business calculations into clients (rejected).
**Tradeoffs:** Existing API success contracts remain; misconfigured transport fails clearly. Refresh/tenant/privacy hardening was pending at this checkpoint and followed in the dated `0002` milestone. CSRF/rate limits and complete production authorization/security still are not certified.

## 2026-11-08 - Native optional AI without a private core-install dependency
**Context:** An unavailable private SDK prevented reproducible public core installation.
**Decision:** Move optional native Anthropic Messages calls to core `httpx` and backend-only `ANTHROPIC_API_KEY`. Historical adapter compatibility was retained at that checkpoint; current direct-only source supersedes it. Missing/failed providers do not block core rules or masquerade as successful summaries, and errors are sanitized.
**Alternatives:** Add an unknown private package index to every install or silently substitute a different provider/model (rejected).
**Tradeoffs:** HTTP contracts have nine mocked-response regressions, not live account validation. The existing Sonnet 4.5 default is retained for compatibility; model availability, privacy, and budget must be reviewed before enabling calls.

## 2026-01-19 — .ai/ directory as source of truth
**Context:** Multiple AI agents will contribute code. Without a canonical rulebook, drift is guaranteed.
**Decision:** Every architectural or business-rule change must update the relevant `.ai/*.md` file in the same commit.
**Alternatives:** Ad-hoc wiki, code comments only.
**Tradeoffs:** Slight overhead on each PR; huge win for consistency and onboarding.

## 2026-01-19 — Backend on FastAPI (not NestJS)
**Context:** Original spec suggested NestJS; environment is Python-first.
**Decision:** FastAPI + SQLAlchemy async + Pydantic v2.
**Alternatives:** NestJS (TS), Litestar, Django REST.
**Tradeoffs:** Loses TS end-to-end typing; gains async performance, minimal code, first-class Pydantic. Contracts stay language-neutral via OpenAPI.

## 2026-01-19 — PostgreSQL as primary DB
**Context:** Inventory reservation, credit ledger, and finance all require strict transactional guarantees.
**Decision:** PostgreSQL 15 with `SELECT ... FOR UPDATE` for stock locks. Redis for caching + queues only, never for accounting state.
**Alternatives:** MongoDB (rejected — no true transactions across shards without cost), MySQL (fine but Postgres has better constraints/JSONB).
**Tradeoffs:** Slightly heavier schema migration overhead. Worth it.

## 2026-01-19 — Multi-tenant via `tenant_id` column (shared schema)
**Context:** Onboarding SMBs — dozens to hundreds of tenants expected before scaling to schema-per-tenant matters.
**Decision:** Shared schema with `tenant_id` on every row + tenant filter derived from JWT.
**Alternatives:** Schema-per-tenant (Postgres), DB-per-tenant.
**Tradeoffs:** Simpler ops; must be disciplined about `tenant_id` filters. Row-level security policy planned for phase 7.

## 2026-01-19 — JWT in httpOnly cookies (not localStorage)
**Context:** XSS is a bigger risk than CSRF given SameSite=Lax and same-origin API.
**Decision:** Access + refresh tokens in httpOnly, SameSite=Lax cookies. Bearer header fallback for mobile.
**Alternatives:** localStorage (rejected — XSS-visible), pure Bearer only (mobile-friendly but web must store somewhere).
**Tradeoffs:** Slightly more work on refresh rotation and CSRF-safe design.

## 2026-01-19 — Claude Sonnet 4.5 as default AI provider
**Context:** Need reliable structured output for alerts; instruction-following matters more than raw creativity.
**Decision:** Historical Claude Sonnet 4.5 selection behind an `AIProvider` adapter; current direct HTTP/manual configuration above supersedes the original private-SDK mechanism.
**Alternatives:** GPT-4o / GPT-5.2, Gemini 3 Flash.
**Tradeoffs:** Provider abstraction was intended to support future implementations. Actual switching needs a supported adapter plus deliberate configuration/model/budget review, not an arbitrary one-line provider flag.

## 2026-01-19 — Reserved qty stored as column, not derived
**Context:** Computing "available = quantity − sum(reservations)" on every catalog view is expensive at 10k SKUs × 100 concurrent viewers.
**Decision:** `inventory_items.reserved_qty` is a first-class column, updated inside the same locked transaction as reservations. `CHECK (reserved_qty <= quantity)` enforces invariant.
**Alternatives:** Compute at read time (slow), materialized view (staleness risk).
**Tradeoffs:** Must audit every path that touches `reserved_qty`. Reservation and release must always come in pairs. Enforced by service layer + `OrderReservation` audit trail.
