# ARCHITECTURE - SupplyOS

## Current Password/Pricing Boundary - 2026-11-12

- Auth now supports current-password reauthentication and atomic password/audit/session/reset retirement with User-first locking and private web outcomes. All remaining row waits precede self-revocation; lost responses do not imply success or credential replay.
- Pricing has DTO/service/repository separation, role-controlled tier/customer writes, and a signed-profile self-catalog. Customer eligibility/currency are held for authorized reads. Price/product/tax batches are immutable per order; account and pricing use one pure shared decimal validator rather than a cross-feature financial dependency.
- Admin `/pricing` and `/change-password` have server-side dynamic/no-store/no-referrer boundaries plus current-user/tenant/role/epoch client guards. Native catalog consumes exact effective prices, tax and declared currency; it does not infer a base/discount or add checkout claims.
- Root validation:1078 backend/3 unchanged skips;208 dev/208 production frontend;22-page build;263 VM passes and three clean analyses. Existing migrations remain through `20261112_0006`; hosted services, jobs/security expansion, full workflows and real release APKs remain gated.

## Layers (Clean Architecture)

```text
+----------------------------------------------------+
| Frameworks/Drivers: FastAPI, Next, PostgreSQL, files |
| Optional/planned: AI, Redis jobs, S3, native apps    |
+----------------------------------------------------+
| Adapters: routers, HTTP clients, private file API   |
+----------------------------------------------------+
| Use cases: stock, orders, money, delivery finalizer |
+----------------------------------------------------+
| Entities: inventory, customer, order, proof/replay  |
| Value objects and domain errors                    |
+----------------------------------------------------+
```

Dependencies should point inward. This is the design target, not a claim that current direct-SQLAlchemy feature services/repository stubs fully satisfy Clean Architecture.

## Stack

| Concern | Tech | Notes |
|---------|------|-------|
| Admin Dashboard | Next.js 14 + TypeScript + Tailwind + Zustand + React Query | App Router; public fragment-safe recovery, auth-scoped queries, finance/POD forms and private previews. |
| Mobile (Customer / Delivery) | Flutter/Dart + Riverpod + GoRouter + Dio, shared memory-only session/query package | Real read-only workflows and offline VM tests; native capture/outbox and APK/platform execution remain incomplete. |
| Backend | FastAPI (Python 3.11) | Async DB use; blocking image/filesystem work is offloaded. |
| DB | PostgreSQL 15 | Prepared statements, connection pool 20+10. |
| ORM | SQLAlchemy 2 asyncpg + Alembic/psycopg2 | Frozen migrations through journal `0006`; online legacy preflight/startup guards, never implicit DDL. |
| Cache / Pub-sub | Redis 7 client | Deep health and opt-in HMAC fixed-window recovery limits/cooldown. General queues/sliding-window/pub-sub remain planned; auth revocation is persisted in PostgreSQL. |
| Reset email | Opt-in stdlib SMTP with verified TLS | Bounded post-response work, auth-recipient recheck, private credentials and fragment links; best-effort, no durable retry/outbox. |
| Realtime | Planned WebSockets + Redis pub/sub | No mounted realtime/client integration yet. |
| Background jobs | Planned durable worker/scheduler | Reservation TTL, recurring AI, notifications and cleanup are not implemented by a setting. |
| Storage | Private local held-handle reads, proof ownership journal and gated exact-version hosted transport | Local Windows checks are real; hosted capability/retention and production durability remain unverified. |
| AI | `AIProvider` with direct Anthropic Messages via core `httpx` | Optional/manual `ANTHROPIC_API_KEY`; current accepted provider is `anthropic`. Other providers need code. |
| Deployment | Dockerfile/CI source, owned Windows disposable verifier/preview | Permanent services, remote Actions/Docker and production orchestration are not verified; no Compose file is present. |

### Previous Runtime Boundary - 2026-11-10

- The table labels actual versus planned components. Local private proof storage, manual finance/replay and SMTP recovery code/UI are implemented. Native Redis recovery execution, live sender setup, durable workers/realtime, external S3, shared mobile packages and production orchestration are not verified or remain pending.
- Metadata/mixins are in `app/infrastructure/db/base.py`, independent of runtime credentials. The historical no-op is followed by frozen baseline/auth/stock/financial/proof revisions. Current head `20261109_0005` matches 27 models; startup checks revision/tables/columns.
- Online financial `0004` proves every receipt is credited exactly once via an owned payment reference or verifiable legacy delivery-payment group. Orphan/duplicate/unaccounted/phantom credits stop for review without history rewriting. Offline SQL generation does not execute this guard. Financial/proof downgrade refuses populated money/replay/proof/reference history; baseline destructive opt-in does not override those guards.
- Private settings are validated and immutable. Production/staging require explicit HTTPS origins, secure cookies, and database TLS. Migration configuration needs the synchronous database URL, not AI/application secrets.
- Admin source uses a same-origin `/api/*` proxy with server-only `BACKEND_URL`; default backend is port 8001. Session-scoped caches and query shapes have frontend regressions.
- AI is owner-configured direct Anthropic through `ANTHROPIC_API_KEY`, not a platform SDK or automatic provider. `AI_MODEL` retains a compatibility Sonnet 4.5 default; availability/deprecation, privacy and budget need deliberate owner review. SMTP is also opt-in/private: unavailable admission returns `503`, limits `429`, and accepted requests do not reveal eligibility or transport outcomes. Redis keys contain only HMAC identities/IPs; no plaintext reset-token queue exists.
- Latest coordinator-owned backend checkpoint: 507 passed/3 skipped in 270.45 seconds, including real PostgreSQL auth-recipient checks and offline SMTP contracts; frontend passes 100 in each dev/prod mode plus lint/types/19-page build. Live AI and two native Linux filesystem cases are skipped. Native Redis/Lua, live SMTP/provider accounts, production, remote CI and complete business/security acceptance remain unverified.
- The current preview at `http://localhost:3000/setup` uses owned temporary PostgreSQL/API 8001 and proof files; `run_preview.py` does not start Redis or create permanent business storage. Leave the existing preview/data untouched.
- See `docs/EXTERNAL_SERVICES.md` and `memory/CODEBASE_SNAPSHOT.md` for verified scope and remaining boundaries.

### Money and Proof Boundaries

- Orders default cash/credit mode from the server customer; legacy false-is-credit is not a bypass. Gross credit holds start at creation, and signed outstanding plus live holds/pending cash funding are rechecked under locks. Cash must have actual allocated cash/UPI/bank funds before delivery; approved credit can remain delivered/unpaid.
- Linked receipts update exact `amount_paid`/`amount_due`. Orderless receipts are advances/account credits; payment `mode=credit` is an orderless credit note, not funds. A payment-status badge before dispatch is not physical delivery; order `paid` only follows delivered history. Administrative `completed` closeout, refunds and full general ledger remain unexposed/future.
- Order/payment/completion UUID replay claims share the effect transaction and actor+tenant+operation scope. Same normalized request returns original JSON/status; changed payload `409`, failures roll back claim/effects, concurrent claims serialize in PostgreSQL. Records have 24-hour expiry metadata but retained records still prevent second effects; no key-cleanup/reuse job is promised.
- `orders.deliver` and `deliveries.complete` are distinct replay operations invoking one guarded finalizer. Retry the same endpoint. Financial lock order is Order -> Customer -> Delivery -> canonical product/inventory; assignment/start/OTP only take Delivery and do not acquire financial locks afterward.
- Proof uploads accept multipart `kind`/`file`; response fields are `id`, `delivery_id`, `kind`, `mime_type`, `size_bytes`, `created_at`, and canonical `/api/v1/delivery-proofs/{id}` `url`. Private reads and completion check tenant/delivery/kind, ownership/access, size/MIME/digest. No raw URL or Settings toggle bypass replaces receipts.
- Pillow 13 verifies and fully decodes PNG/JPEG within 5 MiB/20M pixels, with corrupt CRC mapped to DomainError. ASGI caps actual bytes at 5 MiB+64 KiB before multipart parsing, including chunked/missing/false Content-Length and legacy/invalid-ID upload paths. Ingress/concurrency limits still need production review.
- Windows creates owner/SYSTEM/Admin-only protected ACL roots/files and refuses unsafe existing objects without repair. Linux targets restrictive `0700`/`0600` creation modes and no-follow descriptors; native Linux validation remains skipped on Windows. The returned `Path` is not a held read handle: trusted ancestry/owner/admin processes remain necessary at reopen. Failed writes may leave private partial orphans; durable mounts, paired DB/file backups/restore and retention remain production obligations.
- Frontend consumes server credit/due/exposure/advance fields, never authorizes money in JavaScript. Intent keys survive uncertain responses/auth refresh/same-page modal reopen but not reload/offline restart. The API has customer/order payment filters; admin currently uses customer only. No duplicate-money collection, bank-reference verification, OTP sender, or gateway is inferred from these forms.

Sources: `features/orders/service.py`, `features/payments/service.py` and schemas, `shared/idempotency.py`, `features/proofs/{router,service,middleware}.py`, `infrastructure/storage/local.py`, financial `0004`/proof `0005`, and frontend finance/intent/delivery components. See the snapshot/guide for exact fields and limits.

## Historical Selected Layout - 2026-11-10

```text
supplyos/
+-- backend/
|   +-- app/
|   |   +-- core/            # settings, security, database, enums/errors
|   |   +-- shared/          # deps, schemas, audit, idempotency
|   |   +-- domain/          # domain/value-object stubs and existing code
|   |   +-- infrastructure/
|   |   |   +-- db/base.py   # credential-independent metadata/mixins
|   |   |   +-- db/models/   # 27 tables, including proof/replay
|   |   |   +-- repositories/
|   |   |   +-- external/    # direct optional AI and opt-in SMTP adapters
|   |   |   +-- storage/     # private local file helper
|   |   +-- features/        # auth/setup/settings/catalog/inventory/pricing
|   |   |                   # customers/orders/deliveries/payments/proofs/AI
|   |   +-- api/v1/          # aggregate router, plus legacy /api mounting
|   +-- alembic/             # historical revision and frozen0001-0005
|   +-- tests/
|   +-- tools/               # signing initializer, verifier, preview
|   +-- requirements.txt
+-- frontend/                # Next admin, finance/POD components/tests
+-- mobile/
|   +-- customer_app/        # Flutter prototype
|   +-- delivery_app/        # Flutter prototype
+-- docs/
+-- memory/
+-- .ai/                     # governance
+-- .github/workflows/ci.yml # source only; remote run not claimed
```

This is the earlier selected tree, not the current acceptance claim. The password/pricing checkpoint above includes the implemented shared mobile package and newer journal revision; complete audit/ledger, Compose and realtime workers remain separate work.

## Cross-cutting

- **Multi-tenant:** business rows are tenant-scoped; authenticated DB identity/session and current customer/partner/role ownership constrain API access. UI guards are not authorization.
- **Row-level locking:** canonical stock and Order/Customer/Delivery financial ordering are implemented, with representative real contention; arbitrary load/failure proof is future work.
- **Idempotency keys:** optional-v1 UUID `X-Idempotency-Key` for order creation, payment and guarded completion; not a global replay guarantee for all mutations/uploads.
- **Correlation IDs** on every request (`X-Request-Id`) logged and returned.
- **WebSockets:** planned, not an implemented order/AI fan-out.
