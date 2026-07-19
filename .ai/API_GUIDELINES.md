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
