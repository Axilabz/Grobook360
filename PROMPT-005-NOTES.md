# PROMPT-005 — User Management: Design Record

## Authorization approach (critical architectural gap carried forward)

`role_permission` is still empty — no Role & Entitlement Matrix has ever been
approved (FRD DEP-005, flagged since PROMPT-002). Permission-code
authorization (`require_permission`) would therefore deny *everyone*,
including Owner. Since PROMPT-005 comes before PROMPT-006 (Role & Permission
Management, which is expected to populate the catalogue), authorization here
uses a new `require_role(*roles)` dependency that checks
`AuthenticatedContext.role` directly. Call sites should migrate to
`require_permission` once PROMPT-006 lands.

**Access granted** (conservative reading, since neither source fully defines
Manager's write scope):
- **Owner**: full CRUD (create, edit, activate, deactivate) — FRD FR-USR-01
  explicitly names only Owner for creation.
- **Manager**: read-only (list + detail) — User Flow Matrix says "Limited",
  exact scope undefined anywhere; defaulted to the less-privileged
  interpretation. **Open decision**: exact Manager write permissions.
- **Salesperson**: no access — FR-USR-04 explicit.

## Schema gap resolved (not just flagged this time)

`user.name` didn't exist (flagged in PROMPT-003-NOTES.md as a future need).
PROMPT-005 explicitly requires it for list/detail/create, crossing the
threshold from "nice to have" to "needed now". Added as nullable (migration
`0006_user_name`) — existing sign-up-created users have none.

## Initial password mechanism (S11/S23)

No admin-visible password is ever created. `create_user` hashes a random,
never-revealed value and immediately issues a PROMPT-004-style password-reset
token, delivered through the same dev-stub `PasswordRecoveryService`. Reuses
existing infrastructure rather than inventing a new invitation channel.

## Owner protection (S16/S24 — followed verbatim, not invented)

No other approved source defines this, so the prompt's own recommended
baseline was implemented exactly as stated: a tenant always retains ≥1 active
Owner; both role changes away from OWNER and deactivation are blocked if the
target is the last active Owner. Applies uniformly whether the actor is
acting on themselves or another user.

## What was implemented

- `GET/POST /api/v1/users`, `GET/PATCH /api/v1/users/{id}`,
  `POST /api/v1/users/{id}/activate`, `POST /api/v1/users/{id}/deactivate`
- `UserManagementService`: tenant-scoped list/search/filter/pagination, create
  (with duplicate-phone check reusing the same configurable
  `phone_uniqueness_scope` from PROMPT-002/003/004), update (with role-change
  handling), activate/deactivate (with session revocation on deactivate)
- Frontend: `UserManagement.tsx` (responsive table/card list, search, filters,
  pagination, Add/Edit modals, activate/deactivate confirmation dialogs),
  role-gated "Users" nav item in `Sidebar.tsx`

## Real bug found and fixed during live browser verification

The list endpoint (`UserListItem`) initially omitted `row_version`, while the
detail endpoint (`UserDetail`) included it. The frontend correctly used
`row_version` from whichever record it had in hand (the list, in the common
case) for activate/deactivate/edit — which silently sent `undefined` and
failed with 422. The automated test suite didn't catch this because its
concurrency-related tests happened to always fetch the detail endpoint first.
Fixed by including `row_version` in the list response too. This is exactly
why the live end-to-end browser pass matters even after a green test suite.

## Known limitations

- Login identifier (phone) is not editable after creation — PROMPT-005 §14
  says "if permitted"; restricted here to avoid reopening the
  uniqueness/auth-identifier can of worms in this prompt's scope. Documented
  restriction, not silently dropped.
- Manager's exact write permissions remain undefined (see above).
- Cross-tenant lookups (`GET /users/{id}` for another tenant's user) return
  the same 404 as "not found" — correct anti-enumeration behavior, verified.

## Open decisions

- Exact Manager write scope within User Management.
- Multiple Owners: supported structurally (no upper bound enforced), matches
  the prompt's own recommended baseline of "at least one," not "exactly one."
- Real password-recovery delivery provider (carried forward from PROMPT-004).
