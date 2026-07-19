# CODING STANDARDS — SupplyOS

## Python (backend)
- Python 3.11+, `from __future__ import annotations` at top of every module.
- Type hints on every public function and method. Use `mypy --strict` in CI.
- Line length 100. Formatter: **ruff format**. Linter: **ruff check** with rules `E, F, I, N, UP, B, SIM, RUF`.
- Docstrings: Google style. Every module top has a one-line summary.
- Small functions: ≤ 40 lines / ≤ 3 arguments (keyword-only when > 2).
- Dataclasses or Pydantic models — never bare dicts across boundaries.
- Prefer `pathlib.Path` over `os.path`, `datetime.now(timezone.utc)` over `utcnow()`.
- No `print()` in production paths; use structured logging (`app.core.logging`).

## TypeScript (Next.js)
- `strict: true` in tsconfig. No `any` without explicit `// eslint-disable-next-line`.
- ESLint (`next/core-web-vitals`, `plugin:@typescript-eslint/recommended`) + Prettier.
- Components ≤ 100 lines, feature-based folder layout.
- Data fetching via React Query. State via Zustand. Forms via `react-hook-form` + `zod`.
- No inline styles beyond one-off; Tailwind + shadcn/ui.

## Dart / Flutter
- `flutter analyze` clean. `flutter format .` clean.
- Riverpod providers for all state. GoRouter for navigation.
- Feature-based folders. UI never imports repositories directly — only providers.
- Business logic lives in server. Mobile computes only presentation (formatting, filtering already-loaded lists).

## Feature folders
```
features/<domain>/
├── router.py         # HTTP surface, thin
├── service.py        # use cases, all business rules
├── repositories.py   # DB access (SQLAlchemy queries)
├── schemas.py        # Pydantic DTOs
└── tests/
```

## Naming
- Snake_case for Python, kebab-case for URLs, PascalCase for classes, camelCase for TS/Dart vars.
- Booleans start with `is_`, `has_`, `can_`.
- Table names plural (`orders`), model class names singular (`Order`).

## Tests
- Backend: `pytest` + `pytest-asyncio` + `httpx.AsyncClient`. Coverage ≥ 80% on `features/*/service.py`.
- Contract tests for every state transition and every "Business Scenario" in `.ai/BUSINESS_SCENARIOS.md`.
- Frontend: Playwright for e2e critical flows (login, place order, view inventory).
- Mobile: `flutter_test` unit + widget tests for shared packages.

## No-go
- ❌ Global mutable state (no module-level dicts as caches — use Redis).
- ❌ Broad `except Exception:` without re-raise.
- ❌ Business logic in DB triggers (except audit `updated_at`).
- ❌ Formatting numbers as `float`.
- ❌ Blocking calls in async routes.
