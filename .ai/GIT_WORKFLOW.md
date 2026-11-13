# GIT WORKFLOW — SupplyOS

## Branches
- `main` — always deployable.
- `develop` — integration branch.
- `feat/<scope>` `fix/<scope>` `refactor/<scope>` `docs/<scope>` — short-lived, ≤ 3 days.

## Commit format (Conventional Commits)
```
<type>(<scope>): <short imperative summary>

<body: what & why, not how>

<footer: BREAKING CHANGE:, Closes #123>
```

Types: `feat` `fix` `refactor` `docs` `test` `chore` `perf` `build` `ci` `style`.

Examples:
- `feat(inventory): add row-level locking to reservation flow`
- `fix(orders): prevent double credit-limit deduction on retry`
- `docs(ai): document Claude provider abstraction`
- `refactor(auth): extract token rotation to service layer`

## Pull Request rules
- Squash-merge to `main`. Preserve issue linkage in the squash commit body.
- PR title = intended squash commit.
- PR body must reference `.ai/*` docs that were read/updated.
- Every PR touching a feature module must update the module's `README.md` if surface changes.
- Every PR that changes a public API bumps `docs/CHANGELOG.md`.

## Milestone push protocol
After every milestone:
1. Ensure all tests pass locally + CI green.
2. Update relevant `.ai/*` docs (`ROADMAP.md`, `DECISIONS_LOG.md`, module docs).
3. Update `CHANGELOG.md`.
4. Commit: `chore(release): milestone <name>`.
5. Tag: `git tag -a v<X.Y.Z> -m "..."`.
6. Only when explicitly requested, use normal Git/GitHub tooling for the intended reviewed files. Repository: `https://github.com/NileshSingh9245/SupplyOS.git`. No platform publishing action or automatic commit/push is required.

## Forbidden
- ❌ Direct commits to `main`.
- ❌ Force-pushing `main` or `develop`.
- ❌ Committing `.env`, secrets, or `.pyc` / `node_modules` artifacts.
- ❌ Merging without at least one review (in team setting).

## Hooks (pre-commit)
- `ruff check` + `ruff format --check`
- `pytest -q backend/tests/`
- `eslint` + `tsc --noEmit` for `frontend/`
- `flutter analyze` for `mobile/**`
- Secret scanner (`detect-secrets`).
