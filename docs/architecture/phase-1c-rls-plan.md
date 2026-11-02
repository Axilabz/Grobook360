# Phase 1C — database role separation and enforced RLS (PLAN, not implemented)

Branch: `feature/microservices-phase-1a` (a new `feature/phase-1c-rls` branch is proposed for the work). Nothing here has been run against Supabase or production.

## 1. Verified starting point (local DB, 2026-11-02)
| Fact | Value |
|---|---|
| Tables / with RLS enabled / FORCEd | 63 / 58 / **0** |
| Without RLS | `alembic_version`, `permission` (global), `tenant`, `auth_session`, `idempotency_key`, `password_reset_token` |
| Policy shape (all 58 identical) | `FOR ALL USING (tenant_id::text = current_setting('app.tenant_id', true))`, no explicit `WITH CHECK` |
| Nullable `tenant_id` | `user` (platform admins), `auth_session`, `idempotency_key`, `password_reset_token` |
| Runtime role | `saas_app` — **owner** of every table (owners bypass RLS) |
| Supabase | pooler user `postgres.<ref>` is the privileged `postgres` role. In Supabase that role normally has `BYPASSRLS` (**to verify on staging**), so FORCE alone would NOT bind it. A new non-owner role is mandatory. |

## 2. Target roles
| Role | Purpose | Privileges |
|---|---|---|
| `grobook_owner` (the current migration/owner login) | Alembic/DDL only. Never used by running services. | Owns objects. |
| `grobook_app` | Runtime role of the monolith (later `grobook_identity`, `grobook_tenant`, `grobook_master_data` in 1B) | `LOGIN`, `NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS`; **not an owner**; `SELECT/INSERT/UPDATE/DELETE` on tenant tables; `USAGE` on schema; no `TRUNCATE`, `REFERENCES`, `TRIGGER`, DDL; no access to `alembic_version`. `audit_log` and `stock_ledger_entry`: **`SELECT, INSERT` only** (real immutability, in addition to the existing triggers). |

## 3. Policy changes (new migration 0039, additive, reversible)
1. `ALTER TABLE … FORCE ROW LEVEL SECURITY` on every tenant table (defence in depth if ownership ever drifts).
2. Replace/add explicit `USING` **and** `WITH CHECK` (cross-tenant INSERT/UPDATE blocked, not only hidden). Fail-closed: empty/unset `app.tenant_id` ⇒ zero rows.
3. Add the missing policies: `tenant` (by `id`), `auth_session`, `password_reset_token`, `idempotency_key`.
4. A coverage test fails the build if any table with `tenant_id` lacks RLS+FORCE+policy (so future tables cannot silently skip it).

## 4. The hard part: flows that run BEFORE a tenant is known
Enforcing RLS breaks anything that reads across tenants or before authentication. Audit needed (and each fix reviewed by you):

| Flow | Why it needs special handling | Proposed fix |
|---|---|---|
| Login by phone | looks up `user` by phone with no tenant | `SECURITY DEFINER` function `auth_find_user_by_phone(phone)`, fixed `search_path`, owned by `grobook_owner`, `EXECUTE` granted only to `grobook_app`, returns only the columns login needs |
| Sign-up | creates `tenant`, owner `user`, roles, role links for a tenant that does not exist yet | single `SECURITY DEFINER` provisioning function, or set context to the *new* tenant id before inserting |
| Password reset (token lookup) | token → user, no tenant | definer function by token hash |
| Session check (`get_current_user`) | reads `auth_session` before `set_tenant_context` | set context from the signed JWT `tenant_id` first (token is signature-verified), then query |
| Tenant-less users (`tenant_id IS NULL`) | invisible under tenant policy | explicit decision: platform-admin policy/function (no such role exists today) |
| `idempotency_key` / rate limits | nullable tenant | policy allowing own tenant or `NULL` + app-scoped key |
| Reports parallel lanes | already set context per lane session | verify only |

Definer functions are the narrowest option (no broad policy hole, no GUC an injected query could flip). Alternative considered and rejected: a global "auth mode" GUC bypass policy.

## 5. Connection-pool safety (preserved)
Context stays `set_config('app.tenant_id', …, true)` (transaction-local). New tests: (a) context never visible in the next transaction on the same pooled connection, (b) concurrent requests for different tenants on one pool never see each other's rows, (c) works through Supabase's session pooler (port 5432).

## 6. Test plan
- **RLS matrix on the real runtime role** for *every* tenant table (generated from the catalogue): tenant A context × {SELECT, INSERT, UPDATE, DELETE} against B's rows ⇒ 0 rows / policy violation; empty context ⇒ 0 rows; spoofed `tenant_id` in INSERT ⇒ rejected.
- Privilege tests as `grobook_app`: cannot `ALTER`, `TRUNCATE`, `DROP`, disable RLS, `SET ROLE`/bypass, update/delete `audit_log`/`stock_ledger_entry`, read `alembic_version`.
- Existing **779 backend tests + 20 new + gateway/shared** run with the app connecting as `grobook_app` (test fixtures that seed data directly may need an owner-role connection; coverage is not reduced — any such change is listed in the report).
- Auth/frontend compatibility: login, logout, sign-up, reset, `/auth/me`, one full invoice → payment flow via the real UI against staging.
- Migration tests: upgrade from the current head on a copy, downgrade, re-upgrade; row counts identical before/after (no data change).

## 7. Staging and rollout
1. **Local fresh database** (restored from migrations + sample data) — build and test everything here first.
2. **Supabase staging project** (needs your decision: a separate free/paid project, or a branch of the existing one). Verify `BYPASSRLS` on `postgres`, role creation, pooler login as `grobook_app.<ref>`, latency.
3. Only after your approval: production — migration as owner role; switch `DATABASE_URL` to the `grobook_app` login (the one environment-variable change); keep `MIGRATION_DATABASE_URL` for Alembic.

## 8. Rollback
- Instant (no deploy): point `DATABASE_URL` back to the previous owner login — behaviour returns to today's.
- Schema: migration `0039` downgrade drops the new policies/functions, `NO FORCE`, restores previous grants. No table/column/data is dropped or altered, so rollback loses nothing.
- Keep the old credentials until the new role has run cleanly for an agreed period.

## 9. Risks
| Risk | Mitigation |
|---|---|
| A missed pre-auth path returns empty results ("login broken") | exhaustive grep + full test suite on the restricted role + staging UI walkthrough before prod |
| Supabase pooler/role specifics differ from local | staging step is a hard gate |
| Definer functions are privileged code | minimal columns, fixed `search_path`, parameterised, tested, reviewed |
| Per-request cost of extra statements (Supabase RTT ≈190 ms) | no extra round trips in the hot path; definer calls replace existing lookups 1:1 |

## 10. Decisions needed from you
1. Staging: fresh local DB first (I will do this regardless) — and for Supabase staging, will you create a separate project, or authorise a branch/schema copy?
2. Approve the definer-function approach for the pre-auth flows (§4).
3. Tenant-less (platform admin) users: keep unsupported/invisible for now?
4. Start implementation on a new branch `feature/phase-1c-rls`?
