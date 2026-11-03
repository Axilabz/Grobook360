# Phase 1C implementation report — enforced tenant isolation

Branch: `feature/phase-1c-rls` (based on `feature/microservices-phase-1a`). Not merged, not deployed. Validated on a **local fresh database** (`saas_rls_dev`, Postgres 16, all 38 migrations applied as the owner role). **Supabase staging has not been touched.**

## 1. Security finding being fixed
RLS was enabled on 58 tables but never enforced: the runtime role owned every table (owners are exempt) and nothing was FORCEd. With one tenant's context set, a query returned all tenants' rows. Details: `database/documentation/rls-status.md`.

## 2. Roles and privileges
| Role | Attributes | Owns | Used for |
|---|---|---|---|
| `grobook_owner` (Supabase: existing `postgres`) | LOGIN, no superuser/bypass | all tables | Alembic migrations only |
| `grobook_app` | LOGIN, NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOCREATEDB | nothing | the API at runtime (`DATABASE_URL`) |
| `grobook_definer` | NOLOGIN, same restrictions | 6 functions only | executes the pre-login functions |

`grobook_app` table privileges (full per-table list: `phase-1c-policy-map.md`):
| Tables | SELECT | INSERT | UPDATE | DELETE | Other |
|---|---|---|---|---|---|
| 58 tenant tables + `tenant` (except below) | ✔ | ✔ | ✔ | ✔ | no TRUNCATE/REFERENCES/TRIGGER, no DDL |
| `audit_log`, `stock_ledger_entry` | ✔ | ✔ | ✘ | ✘ | append-only by privilege **and** by trigger |
| `permission` (global) | ✔ | ✔ | ✘ | ✘ | get-or-create of permission codes |
| `alembic_version` | ✘ | ✘ | ✘ | ✘ | — |

`grobook_definer` (column-level, read-only, verified by test): `user(id, tenant_id, phone, email)`, `password_reset_token(id, user_id, tenant_id, token_hash)`, `tenant(id)`, `idempotency_key(idempotency_key, endpoint, request_fingerprint, response_status, response_body)` — and a `FOR SELECT TO grobook_definer` policy on those four tables only. No password hash is readable by it.

## 3. Pre-login SECURITY DEFINER functions
| Function | Returns | Used by |
|---|---|---|
| `auth_find_login_tenant(phone)` | `(user_id, tenant_id)` iff exactly one account has the phone | login |
| `auth_find_reset_user(email)` | `(user_id, tenant_id)` iff exactly one account | forgot-password |
| `auth_find_reset_token(token_hash)` | `(token_id, user_id, tenant_id)` | reset-password (+validate) |
| `signup_tenant_count()` | bigint | tenant-code allocation |
| `signup_phone_in_use(phone)` | boolean | platform-wide phone check |
| `signup_idempotency_lookup(key)` | fingerprint/status/body, sign-up endpoint rows only | sign-up replay |

Each: `LANGUAGE sql`, no dynamic SQL, `SET search_path = pg_catalog, pg_temp`, input length validated, `EXECUTE` revoked from PUBLIC and granted only to `grobook_app`, owned by `grobook_definer`. Verified by `test_definer_functions_are_locked_down` etc. Everything after identification (password hash, role lookup, token record) is read under the identified tenant's RLS context.

## 4. Application changes (behaviour preserved)
- `db/tenant_context.py`: context remembered on the session and re-applied at the start of **every** transaction (fixes a latent trap: a mid-request `commit()` would otherwise drop transaction-local context). Still `set_config(..., true)`, never stored on the pooled connection.
- `core/deps.py`: tenant taken from the signature-verified JWT and applied **before** the revocation lookup (`auth_session` is now RLS-protected). Server-side revocation unchanged. Tokens without a tenant are rejected (401) — tenant-less users unsupported.
- `auth_service`, `password_reset_service`, `signup_service`, `idempotency_service`, `api/v1/auth.py`: use the functions above; sign-up chooses the new tenant id and sets context before inserting.
- `scripts/seed_demo_data.py`: tenant-existence check via the login function.
- **Cost:** login now makes ~2 extra tiny statements (function lookup + context), ≈ +2 round trips (≈ +0.4 s on Supabase from India). Not yet measured on staging.

## 5. Tests
See §7 for results. New: `tests/integration/test_rls_enforcement.py` (32 tests) — role attributes, per-table FORCE/USING/WITH CHECK, fail-closed, append-only, cross-tenant SELECT/UPDATE/DELETE matrix on every table, cross-tenant INSERT and row-move rejected by WITH CHECK, 14 privilege-escalation attempts, owner-role switch, function lockdown, definer column grants, pooled-connection leak and 60-way concurrent isolation.
Existing-test changes (no test removed, no assertion weakened): `tests/conftest.py` — `db_session` is a `TenantAwareTestSession` that follows the tenant under test (the tenant of the last API sign-up/login or of an object being added), because tests now run as the restricted role; explicit `set_tenant_context` in 4 tests that inspect a *different* tenant or create several tenants; `test_audit_log_update_rejected_at_db_level` is now rejected by the permission check before the trigger (trigger remains); Phase 1A's `test_rls_policy_isolates_tenants_when_enforced` seeds its own two tenants.
**Coverage limits (honest):** the INSERT/UPDATE matrix exercises tables that contain rows after the test's API calls; empty tables are covered by the catalogue test (FORCE + USING + WITH CHECK present on all 62) but not behaviourally. Staging seed data (`seed_demo_data.py`) will populate more tables.

## 6. Rollback — tested
| Level | Command | Effect | Tested |
|---|---|---|---|
| 1 (seconds, no deploy, no schema change) | `rls_emergency_relax.sql` as owner + `DATABASE_URL`→owner login | un-FORCE all tables; new code keeps working | ✔ 80 auth/signup/customer/reset tests pass on the relaxed DB via the owner login; owner then sees all rows (229,623) vs 0 before |
| 2 (full schema rollback) | `alembic downgrade 0037_so_cancel_reason` (+ redeploy Phase 1A code) | restores old policies, drops functions/grants | ✔ 64 tables, **row counts identical per table** (240,143 before/after); 58 old-style policies, 0 FORCEd, 0 functions, 0 app grants; **Phase 1A code ran 80 tests green** on the downgraded DB |
| re-upgrade | `alembic upgrade head` | re-applies 0038 | ✔ counts identical (250,663), 39 RLS/isolation tests green |
| optional | `rls_rollback_roles.sql` | drop roles | script written, not executed |
Order for Level 2 in production: Level 1 → deploy previous code → downgrade → (optionally) drop roles. New code needs the functions, so do **not** downgrade while new code is still serving traffic.

## 7. Results (local fresh DB, API running as `grobook_app`)
| Suite | Result |
|---|---|
| Full backend suite (all existing + new), final run | **829 passed, 2 failed** |
| The 2 failures re-run in full (`test_sales_orders.py`, `test_rls_enforcement.py`, `test_tenant_isolation.py`) | **76 passed, 0 failed** |
| Baseline before Phase 1C (owner role) | 779 passed |
| Gateway / shared kit | 21 / 7 passed |
| Frontend (Vitest) | 47 passed |
| Live pooled-server walkthrough | passed (sign-up, login, replay, 80 concurrent mixed-tenant reads, logout revocation) |

The two failures in the full run (a 401 where a 422 was expected, and one RLS-matrix test) did not reproduce in isolation or when their files were re-run. That run took 9 h 52 min instead of ~80 min, which indicates the machine was suspended mid-run; a suspended run can outlive the 60-minute login token. This is the probable cause, not a proven one.

## 8. Open items / risks
- Supabase: confirm `postgres` has BYPASSRLS (why a separate role is needed), role creation, `grobook_app.<ref>` pooler login, latency — **staging step pending your go-ahead**.
- FORCE also binds the owner: future data-fix migrations that touch tenant tables must set `app.tenant_id` per tenant (or temporarily relax). Documented in the migration docstring.
- Tenant-less/platform-admin users unsupported by design.
- Per-service roles (Phase 1B) will reuse `rls_bootstrap_roles.sql` with additional roles.
- Docker, GitHub CI, forwarded-IP verification remain pending (Phase 1A list).

## 9. Addendum — defect found by the all-tables synthetic matrix (fixed before staging)
The new `test_every_tenant_table_enforces_cross_tenant_writes_including_empty_tables` (seeds two skeleton rows per table inside a rolled-back owner transaction, then checks SELECT/UPDATE/DELETE/INSERT/row-move per table, including empty tables) found that the `pre_auth_definer_select` policy (`TO grobook_definer USING (true)`) also applied to the **owner/migration role**, because `TO role` matches every member of the role and the owner must be a member to hand function ownership over. Effect: the owner (never the runtime role) could read all rows of `user`, `tenant`, `password_reset_token`, `idempotency_key` despite FORCE. Fix: policy is now `USING (current_user = 'grobook_definer')`, true only inside the definer functions. Migration 0038 was re-applied locally (downgrade + upgrade, data untouched) and all RLS/isolation/auth tests re-run green (40 + 95 passed).
Also corrected: the statement "FORCE also binds the owner" now holds for all 62 tables.

## 10. Root cause of the two failures in the long run (evidence)
- `test_rls_enforcement::...with_check` → `TimeoutError (asyncio/timeouts.py)`: Windows System log shows the machine **slept 2026-11-02 18:34:07Z → 18:54:06Z (00:04–00:24 IST)**; `auth_session.issued_at` shows exactly a 20 min 10 s hole in test activity (00:04:02 → 00:24:13 IST) and the DB connection timed out when the machine resumed.
- `test_sales_orders::test_create_inactive_product` → 401: the last session issued before an **8 h 48 m hole in activity (00:29:54 → 09:18:33 IST)** belongs to tenant "Sales Order Test Co" with exactly the rows this test creates (1 product, 1 customer, 0 sales orders); its token expired at 01:29:54 (60-min lifetime) and the test resumed at 09:18 (Windows wake event 09:18:26–29 IST) → expired token → 401.
Both tests pass in isolation and in their full-file re-runs. Cause is the host sleeping during the run, not Phase 1C.
