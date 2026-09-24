# PROMPT-002 — Tenant Sign-Up: Design Record

## What was implemented

`POST /api/v1/auth/sign-up`: atomic Tenant + Owner creation, idempotent,
rate-limited, GST format validation with a pluggable (currently no-op)
verification provider, audit trail, no password ever returned or logged.
Frontend: 4-step responsive Sign-Up flow (Organization → GST → Owner → Review),
wired to the real endpoint, retry-safe on failure.

## Conflicts / gaps found (flagged, not silently resolved)

1. **API Contract Specification v1.0 has no sign-up endpoint.** §5.3 lists only
   `/auth/login`, `/auth/logout`, `/auth/refresh`, `/auth/me`,
   `/auth/session-status`. Implemented `POST /api/v1/auth/sign-up` anyway per
   PROMPT-002's own explicit instruction and FRD §9.2's clear requirement —
   this needs to be formally added to the API Contract document.

2. **`tenant` table has no address columns.** Data Dictionary v3.0's tenant
   table is only `business_name`, `gstin`, `state_code` (+ audit/concurrency
   columns) — no address/city/pin_code. PROMPT-002 §7 explicitly requires
   capturing these at sign-up. Rather than silently collecting and discarding
   this data, added `address_line1`, `city`, `pin_code` as nullable columns via
   migration `0003_tenant_address_fields`. **Proposed change requiring
   Database Design v3.0 sign-off.**

3. **No `idempotency_key` table exists anywhere in the DB baseline**, despite
   API Contract §10.1 mandating idempotent-request storage. Added via
   migration `0002_idempotency_key`. Same proposed-change status as above.

## Open decisions (implemented configurably, not silently chosen)

- **Phone uniqueness scope** (API-OD-03, still open): `settings.phone_uniqueness_scope`
  (`tenant` | `platform`), defaults to `tenant` (least restrictive). At
  sign-up time specifically, `tenant` scope is a no-op by construction — there
  is no existing tenant yet to conflict with. This only becomes meaningful once
  PROMPT-003 (or a future user-invite flow) adds users to existing tenants.
- **Password complexity policy**: exact rules aren't specified in any document
  available to this codebase (the "legacy FRD Complete Edition v1.0" referenced
  elsewhere isn't present in `Document/`). `settings.password_min_length = 8`
  is a documented placeholder, not a final policy.
- **GST verification provider** (FRD OQ-003, still open): `GSTVerificationProvider`
  interface with `NullGSTProvider` as the only implementation — GSTIN is
  format-validated only; live lookup is a no-op until a real provider is
  configured. The frontend surfaces this honestly ("Live GSTIN verification
  isn't available yet") rather than pretending to verify.
- **Sign-up rate limit**: `settings.signup_rate_limit_per_ip_per_hour = 10`,
  an in-memory per-process placeholder (S21: "do not invent a specific rate
  limit without documenting it"). Known limitation: per-process only, not
  shared across multiple app instances — needs Redis or similar for a real
  multi-instance deployment.
- **role_permission rows**: deliberately NOT populated for the new OWNER role.
  The Role & Entitlement Matrix (FRD DEP-005) isn't an approved/available
  document — inventing permission grants would be inventing a business rule.
  The Owner role exists and is assigned, but carries zero explicit permissions
  until that matrix is defined.

## Known limitations

- Owner email is mandatory (not optional as PROMPT-002 §13's wording could be
  read) — reconciled against FRD FR-SU-04 ("Must"-priority) and the DB's
  `user.email NOT NULL`, both of which agree it's mandatory.
- Rate limiter is in-memory/per-process (see above).
- Idempotency-Key header is required (400 if missing) rather than optional —
  chosen because PROMPT-002 explicitly requires idempotent submission for
  every genuine attempt.
