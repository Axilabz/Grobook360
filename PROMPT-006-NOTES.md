# PROMPT-006 — Role & Permission Management: Design Record

## Conflict found — STOP and identify (per the global instruction)

This prompt requires using "the approved Role & Entitlement Matrix already
established in the project requirements" — but that matrix doesn't exist as
an actual supplied document. FRD's own **DEP-005** explicitly lists it as a
*dependency* (something needed but not yet provided), and API Contract §15's
permission-key examples are explicitly labeled *"representative"* — i.e. not
final. **Resolved by scoping the permission catalogue to only what this
codebase actually implements** (the `users.*` surface from PROMPT-005, plus
this prompt's own `roles.*`/`permissions.*` read endpoints) rather than
inventing codes for unbuilt modules (customer, product, sales, etc.) just
because the API Contract's illustrative list mentioned them.

## What this prompt actually did (formalization, not new policy)

PROMPT-005 already implemented Owner=full/Manager=read-only/Salesperson=none
access to `/users` via `require_role()`, explicitly flagged in
PROMPT-005-NOTES.md as a stopgap pending this prompt. PROMPT-006:

1. Defined the real permission catalogue (`app/core/permissions.py`):
   `users.view/create/update/activate/deactivate`, `roles.view`, `permissions.view`.
2. Populated `role_permission` for OWNER (all 7), MANAGER (view-only, 3),
   SALESPERSON (none) — the exact same access pattern, now backed by real data.
3. Migrated `/users` and the new `/roles`, `/permissions` endpoints from
   `require_role()` to `require_permission()`.
4. As a result, login/`/auth/me` now return **real** effective permissions
   instead of `[]` (the state PROMPT-003-NOTES.md documented as pending
   exactly this work).

## Database changes

- Migration `0007_rbac_permissions`: seeds the 7 permissions, backfills
  `role_permission` for every pre-existing `role` row (so tenants created
  before this migration get correct permissions without any action), and
  tightens `user_role`'s unique constraint from `(tenant_id, user_id, role_id)`
  to `(tenant_id, user_id)` — formalizing PROMPT-006 §36's own "one user, one
  primary role" recommendation, which the application code already behaved as
  if true (every role-change deletes the prior `user_role` row first) but the
  schema never actually enforced.
- New `Role` rows created after this migration (sign-up's OWNER; first
  MANAGER/SALESPERSON assignment via User Management) are auto-seeded with
  their default permission set via `seed_role_permissions()`, shared between
  `SignUpService` and `UserManagementService`.

## Read-only Role/Permission APIs

`GET /roles`, `GET /roles/{id}`, `GET /roles/{id}/permissions`,
`GET /permissions` — no create/update/delete, per §12/§14: custom roles and
custom permissions are explicitly not MVP scope. Tenant-isolated (a role ID
from tenant A returns 404 under tenant B, same anti-enumeration pattern used
throughout this codebase).

## Frontend

`AuthContext` gained `hasPermission(code)`. `Sidebar.tsx`'s "Users" nav item
and every action button in `UserManagement.tsx` (Add/Edit/Activate/Deactivate)
now check specific permission codes instead of `role === 'OWNER'`. Verified
live: Owner sees everything; Manager sees the list but zero action buttons;
Salesperson sees no "Users" nav item at all, and direct API calls to
`/users`/`/roles` return 403 regardless of what the UI shows.

## Open decisions (not silently resolved)

- **Platform Administrator permissions**: not defined — no platform module
  exists yet to define them against (FRD Module 11 is out of scope here and
  everywhere so far). Deferred to whenever Platform Administration is built.
- **Manager's exact write scope**: still officially undefined by any approved
  source (carried forward from PROMPT-005) — Manager remains view-only.
- **Future module permissions** (customer.*, product.*, sales.*, etc.): not
  created. Each future module prompt should add its own permissions to
  `app/core/permissions.py` and its `ROLE_DEFAULT_PERMISSIONS` entries when
  that module is actually built, following this same pattern.

## Known limitations

- No role/permission caching (§39) — every request resolves permissions from
  the JWT claims set at login; a role change takes effect on the affected
  user's *next* login/token refresh, not instantly mid-session. Given
  PROMPT-003's single-60-minute-token architecture (no refresh), this is a
  bounded, documented staleness window, not unbounded.
- `require_role()` remains in `app/core/deps.py`, now unused by any route,
  kept as available infrastructure for a future platform-scope check that
  isn't naturally a tenant permission code.
