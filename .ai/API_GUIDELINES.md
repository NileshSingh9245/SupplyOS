# API GUIDELINES — SupplyOS

## Base
- All endpoints under `/api/v1/*`. Future breaking changes go to `/api/v2/*`.
- RESTful nouns, lowercase, plural: `/orders`, `/customers`, `/inventory`.
- Sub-resources: `/customers/{id}/prices`, `/orders/{id}/status`.
- Actions on resources use verbs at the end when non-CRUD: `POST /orders/{id}/confirm`, `POST /orders/{id}/cancel`.

## Auth
- JWT in **httpOnly cookie** (`access_token`) + `Authorization: Bearer` fallback.
- Refresh token in httpOnly cookie only.
- `POST /auth/refresh` rotates access token.

### Authenticated password change (implemented 2026-11-12)
- `POST /auth/change-password` accepts exactly `current_password` and `new_password` in a redacted body, no query/target/tenant fields. New passwords are at least12 characters and at most72 UTF-8 bytes; current-password compatibility preserves existing valid hashes.
- Current signed identity, eligibility/session expiry and current-password reauthentication are checked under User-first locks, including after waits/offloaded hashing. Password, safe audit, session epoch/all refresh sessions and outstanding reset links retire atomically. Return `200` with `Password changed. Sign in again.` only after commit, clear both cookies and never return authentication tokens.
- Wrong-current rejection is400 with durable bounded attempt counters; lockout429 has bounded `Retry-After`. Private web forms never refresh/replay this mutation. Uncertain or noncanonical success replies require re-login and cannot become a success notice.

### Password recovery (implemented 2026-11-10)
- `POST /auth/forgot-password` is opt-in. Disabled/unavailable admission returns static `503`; quota/cooldown returns generic `429` plus bounded `Retry-After`. Accepted requests return the same generic `200` message before recipient lookup/delivery, including nonexistent/inactive/ambiguous accounts.
- `POST /auth/reset-password` accepts token/password only in its redacted body, consumes a valid link once, revokes sessions, clears cookies and never auto-authenticates. Browser links use a canonical first-party `/reset-password#token=...` fragment; GET must not redeem.
- Auth responses are `no-store`; eligibility, SMTP replies, credentials and bearer links must not appear in responses/logs. The intentional `/api` alias mirrors these routes.
- Recovery uses HMAC Redis fixed-window counters/cooldown and bounded post-response work. Broader sliding-window/ingress policies remain intended future work, not a production certification.

## Response envelope
- Success = the resource / paginated envelope directly. No extra wrapping.
- Errors: FastAPI's `{"detail": "message"}` for simple cases, structured for validation:
  ```json
  { "detail": [{"loc": ["body","email"], "msg": "invalid email", "type": "value_error.email"}] }
  ```

## Pagination
Standardized query params: `?page=1&page_size=50` (max 200).
Envelope:
```json
{ "items": [...], "total": 1234, "page": 1, "page_size": 50 }
```

## Filtering & Sorting
- Filter params: exact-match on column name (`?status=confirmed&warehouse_id=uuid`).
- Free-text search: `?q=<term>` (server picks columns).
- Sort: `?sort=field` or `?sort=-field` (prefix `-` for desc). Whitelist of sortable fields per resource.

## Managed Pricing and Customer Catalog
- Tier reads retain staff access; owner/manager tier creation is201 and discount-only `PATCH /pricing/tiers/{id}` is200. Names remain immutable; duplicate names409 and invalid fields422. Existing60-character creation is preserved, while managed customer assignment requires a name that fits the30-character stored reference.
- Owner/accountant `PATCH /customers/{id}/pricing-tier` accepts only nullable `tier_id`, validates tenant ownership and audits the change. Existing `POST /customers/{id}/prices` keeps its200 resource response; `DELETE /customers/{id}/prices/{product_id}` is204 and audits actual removals only. No historical order is repriced.
- Customer-only `GET /catalog` derives the linked profile/tenant from authentication, accepts only `q`, `page`, `page_size` with the bounded envelope above, and rejects shadow/duplicate query authority. Each item has `id`, `sku`, `name`, `unit`, exact Decimal-text `price`, `gst_rate`, and server `currency_code`. Unlinked/inactive/unavailable profiles fail closed; responses are private/no-store.
- `/products` remains the v1 base-product resource and `/pricing/resolve` retains its original response shape. Override (including zero), tier and base precedence is shared with one-snapshot order pricing; clients never calculate or infer a customer price.

## DTO validation
- Pydantic v2 for all request/response schemas.
- Enums via `str` subclass Enum → automatic OpenAPI + validation.
- Money = `Decimal(14, 2)`. Never `float`. Reject `str` money with commas.
- Dates: ISO-8601 UTC. `datetime` with tz-aware.

## Consistent status codes
| Case | Status |
|------|--------|
| Success (read) | 200 |
| Success (create) | 201 |
| Success (no body) | 204 |
| Bad input | 400 |
| Missing auth | 401 |
| Auth ok, forbidden | 403 |
| Not found | 404 |
| Domain conflict (over-sell, credit limit) | 409 |
| Rate-limited | 429 |
| Server error | 500 |

## Idempotency
- `POST /orders` accepts `X-Idempotency-Key: <uuid>`; server stores hash keyed by tenant + key for 24h and returns the same response.

## Correlation
- Every request emits `X-Request-Id: <uuid>` (accepted from caller or generated). Included in logs and error responses.

## OpenAPI
- Auto-generated at `/openapi.json`; UI at `/docs` (dev only) and `/redoc`.
- Every route has `summary`, `description`, and tag.
- Every request/response schema is a named Pydantic model.

## Versioning strategy
- Additive changes stay in `v1`.
- Field renames, removals, semantic changes ship in `v2` with `v1` maintained for ≥ 6 months.

## Rate limiting
- `POST /auth/login` → 5 req/min/IP
- `POST /orders` → 60 req/min/tenant
- Global: 300 req/min/user (adjustable)
Redis-backed sliding window.
