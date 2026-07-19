# Commit plan (push via Emergent "Save to GitHub")

Squash the current working tree into these commits (in order) for a clean history on
`https://github.com/NileshSingh9245/SupplyOS.git`:

## 1. `docs(ai): add .ai/ governing charter (13 docs)`
- `.ai/AGENT_INSTRUCTIONS.md`
- `.ai/PRODUCT_REQUIREMENTS.md`
- `.ai/BUSINESS_SCENARIOS.md`
- `.ai/ARCHITECTURE.md`
- `.ai/DATABASE_RULES.md`
- `.ai/API_GUIDELINES.md`
- `.ai/CODING_STANDARDS.md`
- `.ai/SECURITY_RULES.md`
- `.ai/GIT_WORKFLOW.md`
- `.ai/AI_SUPERVISOR.md`
- `.ai/ROADMAP.md`
- `.ai/MODULE_DEPENDENCIES.md`
- `.ai/DECISIONS_LOG.md`

## 2. `chore(infra): postgres + redis via supervisor`
- `/etc/supervisor/conf.d/postgres.conf`
- README documenting local infra bring-up.

## 3. `feat(backend): FastAPI skeleton, config, security, DB base`
- `backend/app/core/*` (config, database, security, enums, exceptions, redis_client)
- `backend/app/shared/*` (deps, schemas, audit)
- `backend/requirements.txt`
- `backend/.env`
- `backend/server.py`

## 4. `feat(backend): SQLAlchemy models — tenants, users, warehouses, products, inventory, customers, orders, ai_alerts`
- `backend/app/infrastructure/db/models/*.py`
- Alembic init + first autogenerate.

## 5. `feat(auth): JWT + refresh + RBAC + audit + brute-force lockout`
- `backend/app/features/auth/*`

## 6. `feat(setup): first-launch tenant + admin + warehouse wizard`
- `backend/app/features/tenants/router.py`

## 7. `feat(settings): admin-configurable business rules (INR, GST, credit, delivery, AI)`
- `backend/app/features/settings/*`

## 8. `feat(catalog): warehouses, racks, shelves, products, categories`
- `backend/app/features/{warehouses,products}/*`

## 9. `feat(inventory): row-locked reservation engine + stock movements`
- `backend/app/features/inventory/*`

## 10. `feat(customers): CRUD, credit ledger, per-customer pricing`
- `backend/app/features/customers/*`
- `backend/app/features/pricing/*`

## 11. `feat(orders): state machine, reservation, credit check, deliver ripple`
- `backend/app/features/orders/*`

## 12. `feat(deliveries): assign, OTP, proof, cash/UPI collect`
- `backend/app/features/deliveries/*`
- `backend/app/features/payments/*`

## 13. `feat(ai): Claude Sonnet 4.5 supervisor via provider abstraction`
- `backend/app/features/ai_supervisor/*`
- `backend/app/infrastructure/external/ai_provider.py`

## 14. `feat(admin-web): Next.js 14 dashboard shell + auth + setup`
- `frontend/*` (package.json, tailwind, tsconfig, layout, providers)
- `frontend/src/app/{page,login,setup}/*`
- `frontend/src/app/(admin)/layout.tsx`

## 15. `feat(admin-web): inventory, warehouses, products, customers pages`
- `frontend/src/app/(admin)/{inventory,warehouses,products,customers}/page.tsx`

## 16. `feat(admin-web): orders (state machine UI), deliveries, finance`
- `frontend/src/app/(admin)/{orders,deliveries,finance}/page.tsx`

## 17. `feat(admin-web): AI supervisor + rules & settings + audit`
- `frontend/src/app/(admin)/{ai-supervisor,settings,audit}/page.tsx`

## 18. `feat(mobile): Flutter customer + delivery scaffolds`
- `mobile/README.md`
- `mobile/customer_app/**`
- `mobile/delivery_app/**`

## 19. `docs: README + CHANGELOG`
- `README.md`
- `CHANGELOG.md`

**When ready to push**, click **Save to GitHub** in Emergent chat — it will commit everything on the current branch to `NileshSingh9245/SupplyOS`. Squash locally with `git rebase -i` if you want the plan above.
