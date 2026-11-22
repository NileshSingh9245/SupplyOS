# SECURITY RULES — SupplyOS

## Authentication
- **JWT** access tokens (30 min TTL) + **refresh tokens** (7 days) stored in httpOnly, SameSite=Lax cookies.
- Refresh token rotation: each `/auth/refresh` issues a new token; old jti is invalidated. Reuse triggers full session revocation for the user.
- Passwords hashed with **bcrypt** (cost 12+). Never stored or logged in plain text.
- `POST /auth/login` requires 5-attempt lockout for 15 min per (IP, email) combo.
- Password reset tokens: 32-byte URL-safe secrets, single-use, 1 hour TTL.

### Implemented recovery boundary - 2026-11-10
- SMTP stays disabled by default; secrets are backend-only, excluded from settings repr/export/errors, and never requested in chat. Remote mail uses authenticated verified TLS; unauthenticated plaintext is development/test loopback only.
- All validated identities receive the same admission checks before account lookup. Accepted responses reveal neither eligibility nor SMTP outcome; unavailable admission is global `503`, and limits are generic `429` with bounded `Retry-After`.
- Recovery has HMAC-only Redis IP/identity keys, fixed-window limits plus cooldown, no-wait in-flight capacity, post-response owned SQL sessions and a current `User.email`/token recheck. No plaintext-token cache/outbox or mutable customer-contact recipient is permitted.
- Links use an owned HTTPS `/reset-password` URL in staging/production with a fragment token, not query/Host-derived redirects. The public UI strips history and retains the token only in memory; GET never consumes it, and successful reset clears cookies/revokes sessions without automatic login.
- Live relay/sender authorization, native Redis/Lua, whole DNS/delivery deadlines, durable retries, post-recheck race and ingress/proxy behavior require operational verification. This does not complete broader auth/CSRF/security policies.

### Implemented own-password boundary - 2026-11-12
- All current active roles may change only their own password through persisted signed identity/session and current-password reauthentication. Target/query authority and unknown fields are rejected; secret input repr/export/validation/log data is redacted.
- User-first locks and all remaining session/reset row waits precede final eligibility/expiry checks and self-revocation. Password, safe audit, global epoch, all sessions and reset links commit or roll back together. Only explicit reauthentication rejections commit bounded failure counters; hashing/audit/commit failures cannot partially rotate credentials.
- Successful changes clear cookies and require fresh login. Web secrets are memory-only and cleared on completion/unmount. Mutation replay is prohibited; unknown replies clear local identity/cache and preserve only an unconfirmed notice. This is not account recovery, forced onboarding password changes or broader global/IP rate-limit certification.

## Authorization (RBAC)
- Roles: `super_admin | warehouse_manager | accountant | delivery_partner | customer`.
- `require_roles(...)` decorator enforced at router level. No implicit "authenticated = allowed".
- **Customer app** may only hit `/api/v1/*` endpoints tagged `customer` scope.
- **Delivery app** may only hit endpoints tagged `delivery` scope.
- Inventory adjustments and warehouse/tier mutations require owner/manager roles. Tier reads retain staff access; customer tier/override writes require owner/accountant. Effective catalog reads require the exact customer role and its own active linked profile; resolver reads preserve existing staff/customer-own boundaries.
- Cross-tenant queries are impossible — every query filters by `tenant_id` from JWT.

## Rate limiting
Target policy is Redis-backed sliding window. The delivered opt-in recovery path uses atomic fixed-window counters with a 60-second cooldown; the defaults below are preserved. Other endpoint/global limits remain requirements, not implied implementation:
| Endpoint | Limit |
|---|---|
| `POST /auth/login` | 5/min/IP |
| `POST /auth/forgot-password` | 3/hour/IP |
| `POST /auth/register-customer` | 5/hour/IP |
| `POST /orders` | 60/min/tenant |
| Global authenticated | 300/min/user |

## Audit
- Every mutating endpoint writes an `audit_logs` row (actor, action, resource, IP, metadata).
- Login success/failure logged to `login_attempts`.
- Sensitive fields never captured in metadata.
- Audit rows are append-only. Deletion policy enforced by DB user privileges in prod.

## Transport & storage
- HTTPS enforced at ingress. HSTS enabled in production.
- Database connections use TLS in production.
- Secrets loaded from environment (Kubernetes Secrets in prod). `.env` files never committed.
- File uploads go to S3-abstracted storage; direct object access requires signed URLs (5 min TTL).

## Encryption
- Passwords: bcrypt.
- Refresh tokens stored as their raw jti (not the JWT itself). Compromise of DB doesn't leak signed tokens.
- Sensitive PII columns (aadhar, PAN if collected) encrypted at rest via pgcrypto (`pgp_sym_encrypt`).

## Input hardening
- All input via Pydantic models. Reject unknown fields (`model_config = ConfigDict(extra="forbid")` on write DTOs).
- SQL only via SQLAlchemy — no raw `text()` with user input.
- CORS uses explicit `frontend_url`; wildcard `*` disallowed when `allow_credentials=True`.

## Session hygiene
- Logout revokes the caller's refresh token.
- Password change revokes all refresh tokens for the user.
- Role change revokes all refresh tokens for the user.
- Individual own-session listing/revocation remains planned. Implemented owner staff revocation and own-password change retire all target/current-user sessions within their defined boundaries.

## App boundary
- Customer + Delivery apps must never receive admin data in a response payload. Use response DTOs that omit sensitive fields.
