# Row-Level Security: actual status (verified 2026-11-02)

Verified against the local development database (`saas_mvp_dev`, Postgres 16, same migrations as Supabase):

| Fact | Result |
|---|---|
| Tables with RLS `ENABLE`d in `public` | 58 |
| Tables with `FORCE ROW LEVEL SECURITY` | **0** |
| Application role | `saas_app`, not superuser, no `BYPASSRLS` — but **owns** the tables |
| Effect | PostgreSQL exempts a table's owner from its RLS policies unless FORCE is set. With `app.tenant_id` set to one tenant, a query on `customer` still returned all 5,079 rows across 4,951 tenants. |

**Conclusion: DB-level tenant isolation is configured but not currently enforced for the application role.** Production isolation today rests on application-level `tenant_id` filtering in every repository/service (covered by the cross-tenant tests, including `tests/integration/test_tenant_isolation.py`). This is the same class of problem previously found for `audit_log` (REVOKE ineffective for an owner).

The test `test_rls_policy_isolates_tenants_when_enforced` proves the policies themselves are correct when enforced (it applies FORCE inside a rolled-back transaction).

## Not changed in Phase 1A (by instruction: preserve RLS policies, no destructive migrations)

## Options for Phase 1C (needs approval)
1. **Separate runtime role** (recommended): migrations/DDL run as the owner; each service connects as a non-owner role (`grobook_<service>_rw`) with `GRANT` only on its own schema. RLS then applies with no FORCE needed.
2. `ALTER TABLE … FORCE ROW LEVEL SECURITY` on tenant tables. Simpler, but every code path that legitimately reads across tenants (login by phone, sign-up, platform tasks) must be reworked first, or it will return zero rows.
3. Do nothing and rely on application filtering (current state) — not recommended for a multi-tenant financial system.

Supabase note: the pooler user (`postgres.<ref>`) is a privileged role; confirm its BYPASSRLS/ownership before relying on any option.
