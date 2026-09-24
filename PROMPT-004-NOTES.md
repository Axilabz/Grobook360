# PROMPT-004 — Forgot Password & Reset: Design Record

## Conflict found — STOP and identify (per the global instruction)

**FRD v2.0 §9.1 FR-SI-07** ("Provide Forgot Password using **OTP-based reset** to
registered phone") is marked *Confirmed* — but PROMPT-004 §3 explicitly and
repeatedly forbids implementing any OTP mechanism for this feature. These two
approved instructions directly contradict each other for this exact
capability. **Resolved by treating PROMPT-004 — the more specific, most recent
instruction for this exact task — as authoritative for what was built.**
FR-SI-07 needs a formal update to stay consistent with the product baseline;
not silently ignored here.

## Recovery channel decision (S4)

- **Channel: email**, not phone. Since OTP-to-phone is forbidden and a link
  can't reach a phone without SMS, email is the only viable stored identifier
  for a link-based recovery flow.
- `user.email` is **not verified** (FR-SU-08's verification method is itself
  still open) — reset instructions go to whatever email was typed at sign-up.
  Documented limitation, not hidden.
- `user.email` has **no uniqueness constraint** (same open-decision pattern as
  phone in PROMPT-002/003). An email matching >1 active user is treated
  identically to "not found" — silently, which is actually *more* secure here.
- **No email delivery provider exists anywhere in this codebase.** Built a
  `PasswordRecoveryService` abstraction (S28) with only a
  `ConsolePasswordRecoveryProvider` dev/test stub — it never reaches a real
  user. `get_recovery_provider()` **raises at startup if `ENVIRONMENT=production`**
  with no real provider wired, rather than silently "delivering" nothing.
  **Selecting and integrating a real provider (SendGrid/SES/SMTP/etc.) is an
  OPEN DECISION requiring product/security sign-off — not invented here.**

## Token design (S10/S11)

- `secrets.token_urlsafe(32)` — 256-bit, cryptographically secure.
- Stored as a SHA-256 digest only (`password_reset_token.token_hash`), never
  the raw value. A fast hash is intentional here (unlike passwords): the
  token's security comes from its randomness, not hash slowness.
- Configurable expiry: `password_reset_token_expire_minutes = 30` (documented
  placeholder, not a specially-approved value — but this one is a pure
  security-engineering parameter, not a product decision like the FRD-tagged
  ones).
- Single-use via `consumed_at`; a second use returns `RESET-004`.
- **S19 (multiple requests)**: a new forgot-password request revokes all
  previous unconsumed tokens for that user first — an old leaked link can't
  remain valid indefinitely.

## Session invalidation (S17)

Successful reset revokes **every** existing `auth_session` row for that user
(reusing PROMPT-003's revocation mechanism directly) — the user must sign in
again everywhere. Verified live: a cookie from a pre-reset login session
returns 401 from `/auth/me` immediately after reset.

## Database changes

One proposed addition, same pattern as `idempotency_key` (PROMPT-002) and
`auth_session` (PROMPT-003): `password_reset_token` (migration `0005`).

## Anti-enumeration (S8) — verified, not just claimed

- `/auth/forgot-password` always returns the same generic message and 200,
  regardless of: unknown email, disabled account, ambiguous email match.
- Even the **rate-limit response** on this endpoint reuses the identical
  generic message (only the HTTP status changes to 429) — a differently-worded
  rate-limit message would itself be an enumeration signal.
- Tested explicitly (`test_auth_reset_api_002_003_unknown_identifier_same_generic_response`).

## Rate limiting (S20)

Two independent limiters on `/forgot-password` (per-IP and per-identifier) and
one on `/reset-password` (per-IP) — all documented configurable placeholders,
same pattern as PROMPT-002/003's rate limits.

## What was implemented

- `POST /auth/forgot-password`, `POST /auth/reset-password/validate`,
  `POST /auth/reset-password`
- `PasswordResetService` (token lifecycle), `PasswordRecoveryService`
  (delivery abstraction)
- Frontend: `ForgotPassword.tsx`, `ResetPassword.tsx`, deep-link handling in
  `App.tsx` for `?token=` reset links (works even if the browser already holds
  an unrelated authenticated session), wired the previously-disabled "Forget
  Password?" link on Sign In

## Known limitations

- No real email provider — see channel decision above.
- Rate limiter/lockout state is in-memory/per-process (same limitation carried
  from PROMPT-002/003).
- Reset-token cleanup (S36 — removing old consumed/expired rows) is not
  implemented as a scheduled job; rows accumulate until a future retention/cleanup
  task is built. Not a correctness issue (expired/consumed tokens are already
  rejected), only a storage-growth one.

## Open decisions

- Real password-recovery delivery provider selection (S4/S28).
- FR-SI-07 needs reconciling with the no-OTP constraint in a future FRD revision.
- Email verification at sign-up (FR-SU-08, carried forward from PROMPT-002) —
  would materially strengthen this feature once decided.
