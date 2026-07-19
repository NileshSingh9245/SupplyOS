# SECURITY RULES — SupplyOS

## Authentication
- **JWT** access tokens (30 min TTL) + **refresh tokens** (7 days) stored in httpOnly, SameSite=Lax cookies.
- Refresh token rotation: each `/auth/refresh` issues a new token; old jti is invalidated. Reuse triggers full session revocation for the user.
- Passwords hashed with **bcrypt** (cost 12+). Never stored or logged in plain text.
- `POST /auth/login` requires 5-attempt lockout for 15 min per (IP, email) combo.
- Password reset tokens: 32-byte URL-safe secrets, single-use, 1 hour TTL.

## Authorization (RBAC)
- Roles: `super_admin | warehouse_manager | accountant | delivery_partner | customer`.
- `require_roles(...)` decorator enforced at router level. No implicit "authenticated = allowed".
- **Customer app** may only hit `/api/v1/*` endpoints tagged `customer` scope.
- **Delivery app** may only hit endpoints tagged `delivery` scope.
- Admin endpoints (`inventory.adjust`, `warehouses.*`, `pricing.*`) require `super_admin` or `warehouse_manager`.
- Cross-tenant queries are impossible — every query filters by `tenant_id` from JWT.

## Rate limiting
Redis-backed sliding window:
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
- `GET /auth/sessions` lists active sessions; user can revoke individually.

## App boundary
- Customer + Delivery apps must never receive admin data in a response payload. Use response DTOs that omit sensitive fields.
