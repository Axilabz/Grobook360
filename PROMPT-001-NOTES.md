# PROMPT-001 — Technical Foundation: Design Record

Source baselines used (from `Document/`): FRD v2.0, User Flow Specification v1.0,
API Contract Specification v1.0, Database Design & Data Dictionary v3.0 (Data
Dictionary / Table Register / Constraints & Indexes / Open Decisions / Design
Standards sheets), Sundar SaaS Updated ERD v2.0. No standalone "PRD v3.0" file
exists in the repo, but its relevant content is extensively quoted/restated across
the four documents above, which was sufficient for this foundation-only scope.

## What was implemented

- `backend/` — FastAPI + SQLAlchemy(async)/asyncpg + Alembic, PostgreSQL 16
  (local dev instance, port 5433, database `saas_mvp_dev`, role `saas_app`)
- Foundation tables only: `tenant`, `user`, `role`, `permission`, `user_role`,
  `role_permission`, `audit_log` (Table Register domains TENANCY + SECURITY)
- `/api/v1` versioning, standard success/list/error envelopes, correlation-id
  middleware, centralized exception handling, structured JSON logging
- Row-Level Security enabled (not forced) + tenant-context propagation
- `row_version` optimistic-concurrency helper (412 on mismatch)
- `AuditService` (append-only; DB revokes UPDATE/DELETE on `audit_log`)
- Frontend: `api/client.ts` (envelope parsing, correlation-id, If-Match,
  no auto-retry on mutations), PWA manifest + service worker (shell-cache only,
  never caches `/api/*`), `ErrorBoundary`, `LoadingState`, `EmptyState`
- Test suites: 15 backend (pytest, all passing against the live DB), 7 frontend
  (Vitest, all passing)

## Conflicts found in the baseline documents (flagged, not silently resolved)

1. **`tenant.created_by`/`updated_by` NOT NULL vs. bootstrap reality.** The Data
   Dictionary marks these NOT NULL with an FK to `user.id`, but the very first
   tenant has no creating user yet — and the very first user has no creating user
   either (`user.created_by` is self-referential). ERD v2.0 §3's own footnote
   explicitly anticipates this ("nullable only where creation can occur before a
   user exists, e.g. initial Tenant bootstrap"). **Resolved as NULLABLE** per that
   explicit ERD carve-out, documented in `app/models/tenant.py` and `user.py`.

2. **`role_permission.tenant_id` missing from the Data Dictionary's column list.**
   The Table Register marks `role_permission` TENANT SCOPED = YES, and
   Constraints & Indexes requires `idx_role_permission_tenant ON (tenant_id)` —
   but the detailed Data Dictionary column list for `role_permission` has no
   `tenant_id` column at all. **Resolved by including `tenant_id`**, following the
   majority of sources and consistency with every other SECURITY-domain table.
   Documented in `app/models/role_permission.py`.

3. **`audit_log.correlation_id` is not in the Data Dictionary at all.** PROMPT-001
   §10 itself requires audit records support a correlation ID "where applicable."
   Added as a genuine schema addition beyond the approved baseline — flagged here
   as needing a versioned change record against Database Design v3.0, per that
   document's own change-control rule (§20 of the ERD).

## Open decisions intentionally left open (not decided here)

- **RLS mandatory in production?** (ERD-DEC-01 / API-OD-07) — RLS is enabled with
  tenant-isolation policies on every SECURITY-domain table, but not `FORCE`d.
- **User phone uniqueness scope** (API-OD-03, platform-wide vs. per-tenant) —
  irrelevant to this prompt (no user-creation endpoint exists yet) but affects
  PROMPT-002.
- Audit-log immutability via `REVOKE UPDATE, DELETE ... FROM PUBLIC` only stops a
  non-owner application role from mutating it. If the app's DB role is ever the
  same role that owns the table (common in a quick local/dev setup), Postgres
  table-owner privileges bypass this — a real production deployment needs a
  distinct, non-owner application role. Documented as a known limitation, not
  fixed silently by inventing a production role-separation policy that wasn't
  asked for.
  **Update (post-PROMPT-010):** confirmed this was a real, exploitable gap, not
  just a theoretical one — the app's `saas_app` role does own `audit_log`, so
  the REVOKE enforced nothing against the app's own connection. Fixed in
  migration `0012_audit_log_immutability_trigger` with a BEFORE UPDATE/DELETE
  trigger (the same pattern PROMPT-010 used for `stock_ledger_entry`, since a
  trigger fires regardless of ownership). The REVOKE is kept for
  defense-in-depth documentation only.

## Known limitations

- No login/session issuance exists (PROMPT-002, per the task's own exclusion
  list) — `get_current_user` is real infrastructure but has nothing to
  authenticate against yet.
- PWA manifest ships with an empty `icons` array — no app icon/logo asset was
  provided, and inventing branding wasn't this prompt's call to make.
- Frontend routing foundation reuses the existing hand-rolled
  `NavigationContext` view-switching rather than introducing a URL-based router
  (e.g. React Router) — the existing prototype already had working navigation,
  and PROMPT-001 didn't ask for a routing rewrite. A future prompt should decide
  whether URL-addressable routes are needed.
