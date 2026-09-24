# PROMPT-003 — Sign In & Session Management: Design Record

## What was implemented

`POST /api/v1/auth/login`, `POST /api/v1/auth/logout`, `GET /api/v1/auth/me`,
`GET /api/v1/auth/session-status` — completing PROMPT-001's stateless-JWT
scaffold with real credential verification, tenant/role/permission resolution,
server-side session revocation, login lockout, and rate limiting. Frontend:
`AuthContext` (centralized auth state), `ProtectedRoute`, a real `SignIn.tsx`
wired to the backend, session restoration on page load/refresh, and a working
Logout menu item.

## Architecture decision (S12 — required since PROMPT-001 didn't fully lock this)

| Aspect | Decision | Why |
|---|---|---|
| Token | Kept PROMPT-001's JWT exactly (HS256, 60 min) | Not redesigning established infra |
| Refresh token | **Not implemented** — documented dependency for a future prompt | Avoids inventing unapproved lifetime/rotation values |
| Browser storage | httpOnly, SameSite=Lax cookie (not localStorage) | Removes the XSS token-theft surface S12 explicitly flags |
| CSRF | SameSite=Lax only (no separate CSRF token) | Proportionate to MVP scope; revisitable |
| Revocation | New `auth_session` table (proposed schema addition, same pattern as PROMPT-002's `idempotency_key`) | A stateless JWT can't make logout real without one |

## Conflicts / gaps found (flagged, not silently resolved)

1. **PROMPT-003 S4 requires a user "name" field.** Neither the Data Dictionary's
   `user` table nor PROMPT-002's sign-up form has/captures one (only
   phone/email/password_hash exist). `UserSummary` in the login response
   returns `phone`/`email` instead of inventing a name. **Requires a schema
   change (a `display_name` or similar column) before a real name can be shown
   anywhere in the UI** — flagged for a future prompt, not added here.

2. **No `auth_session` table exists in Database Design v3.0** (auth wasn't
   designed when that baseline was written). Added via migration
   `0004_auth_session` — same proposed-change status as PROMPT-002's additions.

## Open decisions (implemented configurably, not silently chosen)

- **Phone uniqueness ambiguity in practice**: because API-OD-03 (phone
  uniqueness scope) is still open and PROMPT-002 defaults to tenant-scoped
  (unenforced at the DB level), login-by-phone can in principle match more
  than one active user across tenants. Handled honestly: an ambiguous match is
  refused with the same generic "invalid credentials" message (never guessed),
  logged server-side for ops visibility. This gets worse the longer API-OD-03
  stays open — recommend prioritizing that decision.
- **Login lockout threshold** (FRD FR-SI-09, explicitly "Legacy FRD; product
  confirmation required"): `settings.login_lockout_threshold = 5`,
  `login_lockout_duration_minutes = 15` — same numbers as the legacy FRD
  suggestion, but implemented only as a configurable placeholder, not as if
  approved.
- **Permissions remain empty**: `role_permission` is still unpopulated
  (carried forward from PROMPT-002) pending the Role & Entitlement Matrix
  (FRD DEP-005). Login correctly returns `permissions: []` for Owner — this is
  accurate given current data, not a bug.
- **Rate limiter and lockout tracker are in-memory/per-process**, same known
  limitation as PROMPT-002's sign-up rate limiter — needs a shared store
  (Redis etc.) for a real multi-instance deployment.

## Known limitations

- No `/auth/refresh` endpoint (see architecture decision above).
- Session/lockout state doesn't survive an app restart or scale beyond one
  process.
- Platform Administrator login audit is skipped (not silently faked) when
  `user.tenant_id` is null, since `audit_log.tenant_id` is a NOT NULL FK and no
  platform-level audit sink exists yet (FRD Module 11, out of scope) — no
  Platform Administrator account can even be created yet through any
  implemented flow, so this path isn't currently reachable, but the guard is
  there for when it is.
