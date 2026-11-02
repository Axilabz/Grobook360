# Database documentation

- `schema-ownership.json` — table → future owning schema/service (63 tables). **Documentation only: every table is still in `public`.** Enforced against the ORM by `backend/tests/unit/test_schema_ownership.py`.
- `rls-status.md` — what RLS really does today (not enforced for the app role) and options.
- Migrations still live in `backend/migrations/` (Alembic, 38 revisions). `database/migrations/` and `database/seeds/` are intentionally empty placeholders; no migration was added in Phase 1A.

## Tenant conventions (already in the schema)
`tenant_id UUID NOT NULL` on tenant-owned tables, audit columns (`created_by/at`, `updated_by/at`, `row_version`), tenant-scoped unique constraints (e.g. SKU, document numbers), `tenant_isolation_*` RLS policies keyed on `current_setting('app.tenant_id')`, set per transaction by `app/db/tenant_context.py`.

## Phase 1C proposal (not implemented)
Create schemas `identity, tenant, master_data, inventory, sales, purchase, accounting, gst, payroll, analytics` and move tables with `ALTER TABLE … SET SCHEMA` (non-destructive, data preserved) **only after** raw SQL, Alembic history, RLS policies, sequences/triggers and ORM `__table_args__` are audited, tested on a staging copy, and per-service non-owner DB roles are in place. Cross-service foreign keys are kept inside the transactional boundary until services separate.
