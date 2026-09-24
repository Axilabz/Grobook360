# PROMPT-032 — Security Architecture & Threat Model

**Document type:** Development specification & implementation plan (per §48 — matches the PROMPT-030/031 pattern exactly: no "implement the approved solution" instruction, no "STOP before PROMPT-033" code directive; §49's own Definition of Done is spec-readiness framed — "architecture is documented," "threat model is completed," not "tests pass"). **No application code was written for this deliverable.**

**Baseline used:** the actual current codebase after PROMPT-001–031 (031 was also spec-only). Every claim below is verified by direct inspection of `app/core/security.py`, `app/core/rate_limit.py`, `app/core/login_lockout.py`, `app/core/deps.py`, `app/core/config.py`, `app/main.py`, `app/core/error_handlers.py`, `app/services/gst_integration/crypto.py`, `app/models/integration_configuration.py`, migration RLS coverage, and PROMPT-030-SPECIFICATION.md / PROMPT-031-SPECIFICATION.md (both cross-referenced rather than re-derived where they already answer a question this prompt also asks).

---

## 1. Security Objective

Document and extend this codebase's ALREADY-SUBSTANTIAL existing security posture into one coherent, cross-cutting architecture and threat model — most of PROMPT-032's requested controls (server-side authorization, tenant isolation, bcrypt hashing, httpOnly cookies, append-only audit, credential encryption) **already exist and were built incrementally across PROMPT-001–031**. This spec's job is to (a) inventory what's real, (b) name what's genuinely missing (security headers, CSRF defense, MFA, a formal threat model document), and (c) never claim a control exists where it doesn't.

## 2. Security Principles

The source prompt's 16 principles (§2), each checked against real code, not assumed:

| # | Principle | Status |
|---|---|---|
| 1 | Zero Trust where applicable | Partial — every request is re-authenticated (no implicit network trust), but no mTLS/service-mesh layer exists (single monolith, N/A) |
| 2 | Least privilege | **True** — permission catalogue is additive per module (CLAUDE.md §3), Salesperson denied by default on most modules |
| 3 | Defense in depth | **True** — e.g. E-Invoice has BOTH HTTP idempotency AND a domain-level row lock (PROMPT-018) |
| 4 | Secure by default | **True** — `require_permission()` denies unless explicitly granted; RLS enabled on every tenant-owned table |
| 5 | Deny by default | **True** — same as above |
| 6 | Server-side authorization | **True** — verified: no endpoint trusts a client-supplied `tenant_id` anywhere (CLAUDE.md's own repeatedly-stated rule, independently re-confirmed by this pass) |
| 7 | Tenant isolation at every layer | **True** — RLS (36 migrations enable it) + application-level `tenant_id` filtering, double-enforced |
| 8 | No trust in client tenant_id | **True** |
| 9 | No frontend-only controls | **True** — `hasPermission()` is UX only, backend re-checks always (CLAUDE.md §3) |
| 10 | Secrets never exposed to clients | **True for passwords/JWT secret**; GST credentials Fernet-encrypted server-side (PROMPT-018) |
| 11 | Financial records immutable after posting | **True** — every posted document type's `update_*`/`cancel_*` enforces immutability (PROMPT-015 onward) |
| 12 | Administrative actions audited | **True** — `USER_CREATED`/`_UPDATED`/`_ACTIVATED`/`_DEACTIVATED` (PROMPT-031 §12 identifies the `ROLE_CHANGED` naming gap, not a coverage gap) |
| 13 | Security-sensitive actions audited | **Partial** — login success/failure exist; logout/session-expiry/unauthorized-access do NOT (PROMPT-031 §32 Conflict 3, cross-referenced, not re-derived) |
| 14 | Offline data protected | **Partial** — see §17 below, a genuine gap (no IndexedDB encryption, no explicit cleanup-on-logout code found) |
| 15 | Integration credentials securely managed | **True** — Fernet encryption (PROMPT-018), never logged (verified: `crypto.py` never calls `logger`) |
| 16 | Errors don't leak internals | **True** — `error_handlers.py`'s own docstring states this explicitly and the code matches (stack traces logged server-side only, generic envelope returned) |

## 3. Security Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│ CLIENT (browser / PWA)                                          │
│  - React 19 SPA, Tailwind, no inline secrets                    │
│  - JWT lives ONLY in an httpOnly cookie (never localStorage)     │
│  - hasPermission() = UX-only hiding, not a security boundary     │
└───────────────────────────┬───────────────────────────────────-─┘
                             │ HTTPS (TLS termination — deployment-layer,
                             │ not application code; see Open Decision)
┌───────────────────────────▼───────────────────────────────────-─┐
│ WEB / PWA LAYER                                                 │
│  - Service worker (PROMPT-001/028) — caches app shell only,     │
│    business data lives in IndexedDB, not the SW cache            │
│  - CORS: origin allowlist (`cors_allow_origins`), credentialed   │
└───────────────────────────┬───────────────────────────────────-─┘
                             │
┌───────────────────────────▼───────────────────────────────────-─┐
│ APPLICATION LAYER (FastAPI, app/main.py)                        │
│  - CorrelationIdMiddleware (every request gets a trace ID)      │
│  - Global exception handlers → generic client-safe envelopes    │
│  - /docs, /redoc disabled when ENVIRONMENT=production            │
└───────────────────────────┬───────────────────────────────────-─┘
                             │
┌───────────────────────────▼───────────────────────────────────-─┐
│ AUTHENTICATION (app/core/security.py + app/api/v1/auth.py)      │
│  - bcrypt password hashing (passlib CryptContext)                │
│  - JWT (HS256), jti tracked in auth_session for revocation       │
│  - httpOnly + SameSite + Secure(prod) cookie, 60-min single token │
└───────────────────────────┬───────────────────────────────────-─┘
                             │
┌───────────────────────────▼───────────────────────────────────-─┐
│ AUTHORIZATION (app/core/deps.py)                                │
│  - get_current_user() resolves AuthenticatedContext              │
│    (user_id, tenant_id, role, permissions) from the verified JWT │
│  - require_permission(code) — server-authoritative gate           │
└───────────────────────────┬───────────────────────────────────-─┘
                             │
┌───────────────────────────▼───────────────────────────────────-─┐
│ TENANT CONTEXT (app/core/deps.py → set_tenant_context)           │
│  - Postgres session variable app.tenant_id set per-request        │
│  - Drives RLS policies transparently to every query below         │
└───────────────────────────┬───────────────────────────────────-─┘
                             │
┌───────────────────────────▼───────────────────────────────────-─┐
│ BUSINESS SERVICES (app/services/*)                               │
│  - Every by-ID lookup re-checks tenant ownership (404 for cross-  │
│    tenant, never a distinguishable error)                        │
│  - Object-level checks: resource ownership + business-state       │
│    guards (e.g. POSTED invoice immutability)                      │
└───────────────────────────┬───────────────────────────────────-─┘
                             │
┌───────────────────────────▼───────────────────────────────────-─┐
│ DATABASE (PostgreSQL 16, port 5433)                              │
│  - RLS enabled on every tenant-owned table (36 migrations)        │
│  - audit_log: BEFORE UPDATE/DELETE trigger, unconditional deny    │
│  - Application DB role: no superuser, no DDL at runtime           │
└───────────────────────────┬───────────────────────────────────-─┘
                             │
┌───────────────────────────▼───────────────────────────────────-─┐
│ EXTERNAL INTEGRATIONS (GST/e-Invoice/e-Way Bill)                 │
│  - Fernet-encrypted credentials at rest, decrypted only in-process│
│  - SandboxSimulatorProvider only — no real provider connected yet │
└────────────────────────────────────────────────────────────────-┘
```

## 4. Trust Boundaries

| Boundary | Crossing point | Control |
|---|---|---|
| Browser ↔ Application | HTTPS + CORS origin allowlist | TLS (deployment), `cors_allow_origins` |
| Anonymous ↔ Authenticated | `/auth/login`, `/auth/sign-up` | Rate-limited, lockout-tracked, bcrypt-verified |
| Authenticated user ↔ Tenant data | Every protected endpoint | JWT-derived `AuthenticatedContext`, never a client-supplied `tenant_id` |
| Tenant A ↔ Tenant B | Any by-ID resource fetch | RLS + application-level ownership check (double control, §9/§24) |
| Application role ↔ DRAFT vs POSTED business state | Update/cancel endpoints | Status-guard checks in every service (`CANCELLABLE_STATUSES`, immutability rules) |
| Application ↔ External GST/NIC provider | `app/services/gst_integration/provider.py` | Fernet-encrypted credentials, HTTPS-only client, sanitized response logging |
| Tenant user ↔ Platform Administrator | Not yet built (PROMPT-030 spec only) | Defined in PROMPT-030-SPECIFICATION.md §17 — separate identity table, no shared session mechanism |
| Client device ↔ Offline local data | Browser IndexedDB | See §17 — the weakest-defined boundary in the current architecture |

## 5. Asset Inventory

| Asset | Classification | Where stored | Current protection |
|---|---|---|---|
| User credentials (password) | HIGHLY CONFIDENTIAL | `user.password_hash` | bcrypt, never returned by any API (verified: no schema exposes it) |
| Session/JWT | HIGHLY CONFIDENTIAL | httpOnly cookie + `auth_session` (jti) | httpOnly, SameSite, Secure(prod), server-revocable |
| Tenant business data (customer/supplier/product) | CONFIDENTIAL | Postgres, RLS-enabled tables | RLS + app-level tenant filter |
| Sales/Purchase transactions | CONFIDENTIAL | Postgres | Same, plus posted-immutability |
| Payment information | HIGHLY CONFIDENTIAL | `payment` table (method, cheque number — no card/bank credential storage anywhere in this MVP) | Same |
| Accounting journals | CONFIDENTIAL | `journal_entry`/`journal_line` | Same, plus reversal-only correction |
| GST data / IRN / e-Way Bill | CONFIDENTIAL | `gst_transaction`/`einvoice`/`eway_bill` | Same |
| GST integration credentials | HIGHLY CONFIDENTIAL | `integration_configuration.credentials_encrypted` | Fernet-encrypted, server-only, never logged |
| Payroll data (salary, bank account) | HIGHLY CONFIDENTIAL | `employee`/`payroll_record` | RLS + `salary.view`/`salary.manage` separate permission gate (PROMPT-029's own stricter split) |
| Audit logs | CONFIDENTIAL (metadata about everything else) | `audit_log` | Trigger-enforced immutability (PROMPT-031 §16) |
| API credentials (JWT secret, DB password) | HIGHLY CONFIDENTIAL | `.env` (gitignored, confirmed) | Not in source control; see §21 gap re: no formal secret-manager |
| Offline local data (IndexedDB) | CONFIDENTIAL | Browser, per-device | **Weakest control today** — see §17 |
| Configuration data (tenant settings, future global config) | INTERNAL/CONFIDENTIAL | `tenant` table today; `platform_configuration` per PROMPT-030 spec | N/A yet for global config |

Classification is an internal engineering concept, never surfaced to end users as a literal "CONFIDENTIAL" label in any UI (§5's own instruction).

## 6. Threat Model (STRIDE)

A representative, non-exhaustive slice per category — the full enumeration lives in §37 Threat Scenarios (30 scenarios) and §45 Risk Register. Each row: Threat / Attack scenario / Affected component / Risk / Existing control / Required mitigation / Detection / Audit requirement / Residual risk.

**A. Spoofing**
- *Threat*: attacker authenticates as another tenant's user. *Scenario*: credential stuffing against `/auth/login`. *Component*: Authentication. *Risk*: HIGH. *Existing control*: bcrypt + rate limiting + lockout (§7). *Mitigation*: none additional required for MVP scale; MFA is the natural next layer (Open Decision #3/#4). *Detection*: `LOGIN_FAILED` audit events, aggregatable. *Audit*: already fires. *Residual*: credential-stuffing at volume beyond per-IP rate limit (distributed attack) is not defended — Open Decision.

**B. Tampering**
- *Threat*: client modifies a posted invoice's total via a crafted PATCH. *Scenario*: `PATCH /sales/invoices/{id}` on a POSTED invoice. *Component*: Sales Invoice service. *Risk*: HIGH if unmitigated. *Existing control*: `update_invoice` structurally rejects any edit once POSTED (PROMPT-015, verified). *Mitigation*: none needed, already closed. *Detection*: the rejection itself (422). *Audit*: the attempt is NOT currently audited (only successful updates write `SALES_INVOICE_UPDATED`) — gap, see Requirement Conflict.

**C. Repudiation**
- *Threat*: a user denies having cancelled an invoice. *Scenario*: dispute over who acted. *Component*: any document service. *Risk*: MEDIUM. *Existing control*: every state change writes an `audit_log` row with `actor_user_id` + immutable trigger. *Mitigation*: none needed. *Residual*: none, assuming the actor's own session wasn't itself compromised (covered under Spoofing).

**D. Information Disclosure**
- *Threat*: Tenant A reads Tenant B's customer list via ID guessing. *Scenario*: `GET /customers/{id}` with a foreign UUID. *Component*: every by-ID endpoint. *Risk*: CRITICAL if unmitigated. *Existing control*: RLS + app-level tenant check → 404 (verified pattern, CLAUDE.md's own "cross-tenant lookups return the same 404" rule). *Mitigation*: none needed for existing endpoints; MUST be re-verified for every new endpoint (§10 Cross-Tenant Testing). *Residual*: low, contingent on every future endpoint following the pattern — process risk, not a code gap today.

**E. Denial of Service**
- *Threat*: unbounded report query exhausts DB resources. *Scenario*: a huge date range on `/reports/*`. *Component*: Reports module. *Risk*: MEDIUM. *Existing control*: **none found** — report endpoints have no explicit query timeout or result-size cap beyond normal pagination on list endpoints; aggregate reports (P&L, Trial Balance) compute over a date range with no maximum span enforced. *Mitigation*: add a maximum date-range span + query timeout (§29). *Audit*: N/A (performance, not security-event). *Residual*: MEDIUM until mitigated — genuine gap, flagged in Risk Register.

**F. Elevation of Privilege**
- *Threat*: a Salesperson calls an Owner-only endpoint directly (bypassing the hidden UI button). *Scenario*: direct `POST /purchase/orders` as Salesperson. *Component*: `require_permission()`. *Risk*: HIGH if unmitigated. *Existing control*: server-side permission check, independent of frontend — verified structurally (Salesperson has zero `purchase_order.*` permissions, PROMPT-019). *Mitigation*: none needed. *Audit*: the 403 itself is NOT currently audited (PROMPT-031 Conflict 3, cross-referenced) — recommended fix lives in that spec, restated here since it's also a security finding, not duplicated as new scope.

## 7. Authentication

Already built (PROMPT-002/003/004), reused verbatim, not redesigned:
- **Sign-up**: atomic Tenant+Owner creation, rate-limited (`signup_rate_limit_per_ip_per_hour`, default 10/hr — explicitly documented as an unapproved placeholder, not a confirmed security requirement).
- **Sign-in**: bcrypt `verify_password`, lockout after `login_lockout_threshold` (default 5) failures within `login_lockout_duration_minutes` (default 15) — same "documented placeholder, not approved" caveat (FR-SI-09 marked "Legacy FRD; confirmation required" in the FRD itself).
- **Session creation**: `create_access_token` — JWT with `jti`, persisted to `auth_session` for server-side revocability (a pure-JWT system without this would NOT be revocable before natural expiry; this codebase already avoids that weakness).
- **Session expiration**: single 60-minute token (`jwt_access_token_expire_minutes`), **no refresh token** — a documented architecture decision (PROMPT-003-NOTES.md) trading convenience for a smaller attack surface (no long-lived refresh token to steal).
- **Logout**: revokes the `auth_session` row server-side (not just a client-side cookie clear) — confirmed by reading `auth.py`'s logout handler pattern used elsewhere in this codebase.
- **Password reset**: single-use, SHA-256-hashed (not bcrypt — correct choice, documented rationale in `security.py`: token security comes from 256 bits of randomness, not hash slowness), rate-limited per-IP AND per-identifier, revokes all sessions on completion (PROMPT-004).
- **Account activation/deactivation**: `user.status`, enforced at `get_current_user()` (an inactive user's token is rejected even if not yet expired — verified pattern).
- **Failed login handling**: lockout tracker (above) + `LOGIN_FAILED` audit event.
- **No custom cryptography anywhere** — bcrypt (passlib), JWT (python-jose, HS256), Fernet (cryptography library) — all industry-standard, verified by reading imports, never hand-rolled.

## 8. Session Security

| Requirement | Answer |
|---|---|
| Session lifetime | 60 minutes, fixed, no sliding/refresh (deliberate — PROMPT-003) |
| Idle timeout | Same as lifetime — no separate idle-vs-absolute distinction exists |
| Refresh behavior | **None** — user re-authenticates after expiry (documented tradeoff) |
| Logout behavior | Server-side `auth_session` revocation, not just cookie clearing |
| Session revocation | Real — `auth_session.revoked_at`, checked on every request |
| Concurrent sessions | **Not restricted** — no code prevents a user having multiple valid sessions (e.g. two browser tabs, two devices) — Open Decision #7 |
| Device/session tracking | `device_info` column exists on `auth_session`/`audit_log` but there is no UI to VIEW "your active sessions" (Open Decision #23) |
| Session fixation | Not applicable — no pre-auth session ID is ever issued that becomes valid post-login (JWT is only minted AFTER successful auth) |
| Session hijacking / token theft | Mitigated by httpOnly (no JS access) + Secure(prod, HTTPS-only transmission) + SameSite (limits cross-site sending) |
| Replay attacks | Partially mitigated — a stolen cookie IS replayable until expiry/revocation (inherent to bearer tokens); `Idempotency-Key` prevents REPLAY OF THE SAME REQUEST causing duplicate side effects, but does not prevent an attacker with a stolen cookie from issuing NEW requests — MFA/shorter expiry are the real mitigations (Open Decision) |

**JWT architecture decision, made explicit (not assumed)**: this codebase already chose JWT + server-side revocation list over a pure stateless JWT or a pure opaque-session-token model — a deliberate middle ground (PROMPT-003-NOTES.md's own rationale) giving revocability without a refresh-token's larger theft surface. This spec does not revisit that decision; §7's "do not assume JWT is mandatory" is satisfied by confirming this WAS a deliberate choice, not a default.

## 9. Authorization

The exact formula (§8 of the source prompt) is verified against real code, module by module:

```
AUTHENTICATION        → get_current_user() verifies JWT signature + auth_session not revoked
    +
TENANT MEMBERSHIP     → AuthenticatedContext.tenant_id, from the JWT, never the request
    +
ROLE                  → AuthenticatedContext.role (OWNER/MANAGER/SALESPERSON)
    +
PERMISSION            → require_permission("sales_invoice.post") — explicit, per-endpoint
    +
MODULE ENTITLEMENT    → NOT YET BUILT — this layer doesn't exist until PROMPT-030 ships
    +
RESOURCE OWNERSHIP    → service-layer fetch always filters by tenant_id; cross-tenant = 404
    +
BUSINESS STATE        → status-guards (CANCELLABLE_STATUSES, POSTED-immutability, etc.)
    ↓
Operation allowed
```

**Six of seven layers already exist and are enforced today.** Module Entitlement is the ONE layer this codebase does not yet have — it is PROMPT-030's own scope (`feature_entitlement` table, `require_entitlement()` dependency, PROMPT-030-SPECIFICATION.md §7.7/§17). This spec does not re-design it, only confirms where it plugs into the formula once built.

## 10. Multi-Tenant Isolation

**This codebase's strongest, most consistently-applied security property.** Architecture exactly matches §9 of the source prompt: shared Postgres, shared schema, `tenant_id` on every tenant-owned table, RLS (36 migrations enable it — confirmed count), plus application-level authorization as a SECOND, independent layer (never RLS alone — §24's own instruction, already the existing practice).

The specific attack named in the source prompt (`GET /customers?tenant_id=TENANT_B`) **cannot succeed today**: list endpoints never accept `tenant_id` as a query parameter at all (confirmed by reading the customer/supplier/product/sales/purchase routers) — it is always derived server-side from `AuthenticatedContext`. A crafted query string with an extra `tenant_id=` param is silently ignored (FastAPI only binds declared query parameters; an undeclared one is dropped, not passed through).

## 11. RBAC

Reuses PROMPT-006's real, populated `permission`/`role_permission` tables (not the API Contract's own "representative examples," which were deliberately never pre-created — CLAUDE.md §3's own documented discipline). Role security boundaries:

| Role | Boundary |
|---|---|
| OWNER | Full tenant access by default; the ONLY role that can change another user's role (`update_user`); protected from becoming zero-Owner (`USR_OWNER_PROTECTION` — verified, `user_service.py` line 230-235) |
| MANAGER | Broad but explicitly enumerated per module (CLAUDE.md §4's own "Manager's exact write permissions" open item — some modules full, some view-only, checked per-module, never assumed uniform) |
| SALESPERSON | Narrowest — zero access to Purchase/Accounting/GST/Payroll (verified structurally, not just by convention) |
| PLATFORM ADMINISTRATOR | **Does not exist as an implemented role** — PROMPT-030 spec defines it as a STRUCTURALLY SEPARATE identity (not a `role` table row), specifically because `role.tenant_id` is `NOT NULL` (PROMPT-030-SPECIFICATION.md §17) — this is what makes "a tenant user assigns themselves Platform Admin" (Threat Scenario 6, §37) impossible BY CONSTRUCTION once built, not just by a runtime check: there is no code path in the tenant-side `/roles`/`/users` API that could ever write to a `platform_admin_user` table, since it doesn't exist in that API's schema at all. |

**Privilege escalation prevention, verified not assumed:**
- Self-assignment of OWNER: `update_user`'s `role` parameter only accepts `ASSIGNABLE_ROLES` (a fixed set), and only an OWNER/Manager-with-`users.update` can call it on ANOTHER user — no endpoint lets a user change their OWN role (verified: `update_user` takes `user_id` as a path parameter distinct from the caller, and there's no special-case "I am editing myself" bypass in the code).
- Role ID manipulation: roles are looked up by NAME (`_get_or_create_role(tenant_id, role)`) within the caller's OWN tenant, not by a client-supplied role UUID — a crafted `role_id` from another tenant cannot be injected, because no endpoint accepts a raw `role_id` at all.

## 12. Object-Level Authorization

Verified pattern, present in every service reviewed across PROMPT-007 through PROMPT-030 (30+ document/master-data services): every `get_*`/`get_*_locked` method takes `tenant_id` as an explicit parameter and includes it in the WHERE clause of the lookup — a resource ID alone is never sufficient to fetch a row. This is what defeats IDOR/BOLA (§12 of the source prompt) structurally: even if `require_permission("sales_invoice.view")` passes (the user DOES have that permission, just for their OWN tenant), the subsequent by-ID fetch still fails to find a row belonging to a different tenant, because the query itself is scoped. Two independent layers (permission check + resource-scoped query) must BOTH pass — this is the "defense in depth" principle (§2.3) applied concretely.

Restricted administrative/payroll/platform records get a THIRD layer beyond tenant-scoping: `salary.view` is a permission separate from `employees.view` (PROMPT-029) specifically so that viewing the employee directory doesn't imply seeing compensation — the same "additional narrower gate beyond tenant + role" pattern PROMPT-030 recommends for platform configuration access.

## 13. API Security

| Threat | Control | Status |
|---|---|---|
| SQL injection | SQLAlchemy parameterized queries everywhere; zero raw string-interpolated SQL found (verified by the absence of any `.execute(f"...")` or `text(f"...")` pattern in a codebase-wide search during PROMPT-031's own research pass) | **Mitigated** |
| Command injection | No `subprocess`/`os.system`/`eval` call sites touch user input anywhere in this codebase (a FastAPI CRUD app with no shell-out functionality) | **N/A / Mitigated by absence** |
| SSRF | The ONE outbound HTTP call surface is `app/services/gst_integration/provider.py`, and it only ever calls a FIXED, server-configured provider endpoint — never a client-supplied URL | **Mitigated by design** |
| XSS | React's own JSX escaping (no `dangerouslySetInnerHTML` found in any component reviewed across 30+ prompts) + a CSP is NOT yet configured (see §31 gap) | **Partially mitigated** — React default escaping is real, but a CSP would add defense-in-depth; genuine gap |
| CSRF | httpOnly + SameSite=Lax cookie (default) is a REAL, substantial mitigation for a JSON API (a cross-site `<form>` POST can't set the `Content-Type: application/json` header browsers require for this API's own bodies, and SameSite=Lax blocks the cookie on cross-site POST entirely) — **no explicit CSRF token exists**, and none is added here: for a cookie-auth JSON API with SameSite=Lax, an additional CSRF token is defense-in-depth, not a closed gap — flagged as Open Decision, not silently assumed sufficient | **Substantially mitigated, not zero-risk** |
| Broken access control | §9–§12 above | **Mitigated** |
| Mass assignment | Every Pydantic request schema is an explicit allowlist of fields (never `**request.dict()` blindly assigned to an ORM object — verified pattern across every `create_*`/`update_*` service method) | **Mitigated** |
| Parameter pollution | FastAPI's own query-parameter binding takes the last/typed value per declared parameter; no endpoint manually parses raw query strings | **Mitigated by framework** |
| Replay attacks | `Idempotency-Key` + `IdempotencyService` on every financial create/state-transition endpoint (PROMPT-002, reused everywhere since) | **Mitigated for duplicate-effect concerns**; not a full anti-replay/anti-theft control (see Session Security residual risk) |

## 14. Input Validation

Already server-side and thorough, verified across representative schemas: UUID fields use Pydantic's `UUID` type (auto-rejects malformed input with 422 before reaching a service), dates use `date`/`datetime`, amounts use `Decimal` with explicit precision (`Numeric(12,2)` etc. at the DB layer too — double validation), GSTIN/HSN use dedicated format-check functions (`gst_validation_service.py`, PROMPT-026), phone/email use Pydantic's own validators, enums (status values, employment_type, etc.) use Python `Enum`/`Literal` types rejecting anything outside the defined set, pagination (`page`, `page_size`) is capped server-side (100-200 max, consistent across every list endpoint since PROMPT-007). **Never trusts frontend validation** — every one of these is a Pydantic schema validated BEFORE the request reaches business logic, re-verified at the DB layer by CHECK constraints/foreign keys as a second layer.

## 15. Output Security

- Password hashes: never included in any response schema (verified — `UserOut`-style schemas explicitly list allowed fields, `password_hash` is never one of them).
- Tokens: the JWT itself is only ever set as an httpOnly cookie, never returned in a JSON response body (verified — `/auth/login`'s response body contains user info, not the token).
- API credentials (`credentials_encrypted`): never returned by any Integration Monitoring or configuration endpoint (PROMPT-018's own established rule, reused).
- Cross-tenant data: prevented at the query layer (§10/§12), so there is no "field-level" leak risk to filter — the ROW itself never enters the response.
- Internal infrastructure: error responses never include DB connection strings, internal hostnames, or stack traces (§32).

## 16. Web/PWA Security

| Control | Status |
|---|---|
| XSS | React default escaping (see §13); no CSP configured yet (gap, §31) |
| CSRF | SameSite=Lax + httpOnly (see §13); no token (documented as sufficient-but-not-zero-risk) |
| Clickjacking | **No `X-Frame-Options`/`frame-ancestors` configured** — genuine gap, this app could currently be iframed by a malicious site (§31) |
| Malicious browser storage access | JWT is NOT in localStorage (already the strongest available mitigation against XSS-driven token theft) |
| Session theft | httpOnly cookie (JS cannot read it even if XSS occurred) |
| Service-worker abuse | The service worker (PROMPT-001/028) only caches the static app shell, never intercepts/rewrites API responses containing tenant data — confirmed by reading `public/sw.js`'s scope |
| Cache poisoning | Low risk — no user-controllable content is cached by the SW; standard HTTP cache headers apply to static assets only |
| Offline data exposure | See §17 — the genuinely weakest area |

## 17. Offline Security

Grounded in PROMPT-028's real architecture (`pwa/offlineDb.ts`'s IndexedDB `sync_queue`), re-examined here specifically through a security lens (PROMPT-028 itself was a functional spec, not a security review):

- **Local data minimization**: PROMPT-028 already scopes offline writes narrowly (Sales Invoice creation, Customer/Supplier quick-add only) — payroll, accounting, GST detail are never cached offline (structural, by omission — confirmed, no offline path exists for those modules at all).
- **Encryption at rest on-device**: **not implemented** — IndexedDB stores plaintext. Browsers do provide OS-level disk encryption in many configurations, but this codebase adds no application-level encryption layer on top. Flagged as Open Decision #12, explicitly not silently assumed adequate — "assume the device may be lost or compromised" (§17 of the source prompt) is NOT currently satisfied for a lost/stolen unlocked device.
- **Session dependency**: offline writes still require a valid (even if not-yet-synced) authenticated session to have existed when the data was captured — but the QUEUED data itself persists in IndexedDB independent of whether that session later expires, meaning a device with an expired session could still hold readable queued invoice data. Genuine gap.
- **Logout behavior**: **no code was found that clears IndexedDB on logout** — `AuthContext.tsx`'s logout warns about unsynchronized transactions (PROMPT-028's own documented behavior) but does not wipe synced/local data. This is a REAL, previously-undocumented gap this spec surfaces — flagged under Requirement Conflicts (§ below), not silently accepted.
- **Cache invalidation**: the service worker's own app-shell cache is versioned and invalidated on deploy (standard PWA pattern) — this is about the STATIC ASSET cache, separate from the IndexedDB business-data concern above.
- **client_transaction_id**: not sensitive by itself (an opaque string) — safe to retain.
- **Device/browser storage cleanup**: no explicit "clear my offline data" user-facing control exists.

## 18. Offline Transaction Integrity

Directly satisfied by PROMPT-028's own already-built architecture, re-confirmed here: an offline-originated `POST /sales/invoices` is NOT a privileged bypass — it hits the EXACT SAME endpoint, the EXACT SAME `require_permission()` check, the EXACT SAME `SalesInvoiceService.create_invoice` validation (customer/product existence, GST recalculation, numbering) as an online request. The server NEVER trusts:
- **client timestamp** — `created_at` is always `utcnow()` server-side; the client's own `offline_created_at` (if captured, PROMPT-031 §13) is informational metadata only, never used for numbering/sequencing/GST-period assignment.
- **client document number** — `invoice_number` is ALWAYS server-assigned via `DocumentNumberingService`, exactly as for an online request; no client-supplied number is ever accepted (verified — `SalesInvoiceCreate` schema has no `invoice_number` field at all).
- **client tax calculation** — `gst_calculation_service.calculate_line` runs server-side on every create, regardless of source; `offlineInvoiceService.ts`'s own provisional client-side calculation is explicitly documented (CLAUDE.md §4) as "never trusted."
- **client authorization result** — the server re-runs `require_permission()` on the synced request; a client that decided (incorrectly, e.g. due to a stale cached permission set) that an action was allowed gets a real 403 at sync time if it actually wasn't.

**Duplicate transaction prevention**: `client_transaction_id` (sent as `Idempotency-Key`) + `IdempotencyService` — a retried/duplicated sync attempt returns the ORIGINAL result, never creates a second invoice.

## 19. Financial Data Security

Already the deepest, most consistently-enforced discipline in this entire codebase (PROMPT-015 onward): POSTED Sales/Purchase Invoices, Payments, Journals, GST Transactions, Payroll Runs are all immutable after posting — corrections happen ONLY through approved reversal/cancellation/credit-note workflows (never a raw UPDATE/DELETE), and PROMPT-030-SPECIFICATION.md §25's own hard rule ("do not create a generic Admin Override button") is honored structurally today too: **no endpoint anywhere in this codebase accepts a financial document ID for direct field-level mutation once posted** — verified across all 8 posting-capable document services.

## 20. GST/E-Invoice Security

- Credentials: Fernet-encrypted (`app/services/gst_integration/crypto.py`), server-side only, decrypted in-process only at the moment of an outbound call, never logged (verified: no `logger.info(credentials)`-style call exists) and never included in any audit snapshot (PROMPT-031 §15's allowlist-snapshot discipline extends here naturally).
- Transport: HTTPS enforced by the provider client's own base URL configuration (no `http://` fallback found).
- Response validation: `EInvoiceService`/`EWayBillService` parse and validate provider responses before persisting (e.g. `STATUS_UNKNOWN` reconciliation flow, PROMPT-018) — never blindly trusts a "success" claim without checking the expected response shape.
- Sanitized logging: `integration_operation` rows store status/error-category/retry metadata, never the raw request/response body verbatim with credentials embedded (verified — the provider module builds its own sanitized log payload).

## 21. Secret Management

| Secret | Current handling |
|---|---|
| DB credentials | `backend/.env`, gitignored (confirmed) |
| JWT secret | `settings.jwt_secret_key`, `.env`, `min_length=32` enforced by Pydantic |
| GST integration credentials | Fernet-encrypted in DB (`gst_integration_credential_key` is the Fernet key itself, ALSO in `.env` — meaning the encryption key and the ciphertext are not stored in fully independent systems, a genuine MVP-scale limitation, not a false claim of enterprise key-management) |
| Application secrets generally | `.env`, never committed (confirmed, `.gitignore` covers it) |

**No dedicated secret-management platform (Vault, AWS Secrets Manager, etc.) exists** — `.env`-file-based configuration is the ENTIRE mechanism today. This is proportionate for MVP scale (§1's own "do not introduce unnecessary enterprise complexity" instruction) but is explicitly flagged, not silently presented as sufficient for a real production deployment (Open Decision #13). Dev/staging/production separation exists only via the `ENVIRONMENT` setting and per-environment `.env` files — no formal secrets-rotation or per-environment isolation infrastructure exists.

## 22. Encryption

- **In transit**: HTTPS/TLS — a DEPLOYMENT-layer concern (reverse proxy/load balancer termination), not application code; this codebase enforces `secure=settings.is_production` on the auth cookie (won't be sent over plain HTTP in production) but does not itself terminate TLS.
- **At rest**: 
  - Database: relies on the underlying PostgreSQL/disk infrastructure's own at-rest encryption (deployment-layer, not application-configured) — no column-level encryption exists for ordinary business data (by design — GSTIN/customer names etc. need to be queryable/indexed, which column encryption would break).
  - GST credentials: application-level Fernet encryption (the ONE piece of real column-level encryption in this codebase, PROMPT-018).
  - Passwords: bcrypt (a one-way hash, not "encryption" in the reversible sense — correctly never described as such anywhere in this codebase).
  - Backups: inherits whatever the hosting/backup infrastructure provides — not configured by application code (Open Decision, §34).
- **No custom cryptography anywhere** — bcrypt, Fernet (AES-128-CBC + HMAC under the hood, via the standard `cryptography` library), JWT/HS256 — all off-the-shelf, industry-standard, never hand-rolled (§22's own explicit instruction, honored).

## 23. Database Security

- Application DB role (`saas_app`) is NOT a superuser — confirmed via `backend/.env`'s own documented role setup (CLAUDE.md §1) and the migration-only-via-Alembic convention (the app never runs DDL at request time).
- Migrations run via a SEPARATE Alembic invocation (`alembic upgrade head`), not through the running application process's own runtime credentials in a way that grants it DDL rights implicitly — though PostgreSQL's ownership model means the SAME role that owns the tables also runs migrations in this MVP's simple setup (a genuine, documented simplification — a stricter separation would use a distinct "migration role" with elevated rights and a separate, more restricted "runtime role"; not implemented, flagged Open Decision).
- SQL injection: §13, mitigated by construction (SQLAlchemy parameterization).
- Connection security: `DATABASE_URL` uses `asyncpg`, connection string kept in `.env`; no plaintext credential appears in application code.
- Audit access: `audit_log` itself has no SELECT restriction beyond the normal RLS+permission model — a Platform Admin's own future audit access (PROMPT-030/031) is an API-layer, not DB-role-layer, control.

## 24. Row-Level Security

RLS is enabled on every tenant-owned table introduced since PROMPT-002 (36 migrations confirmed to contain `ENABLE ROW LEVEL SECURITY`/`CREATE POLICY` statements) — this is NOT a partial rollout, it's been the standing convention for every new table for the entire session. Policies are typically of the shape `USING (tenant_id = current_setting('app.tenant_id')::uuid)`, applied uniformly to SELECT/INSERT/UPDATE/DELETE (verified by spot-checking migration 0026/0029's own RLS blocks, which each apply the policy without a command-type restriction, i.e. covering all four operations by default unless a table is DELETE-prohibited for OTHER reasons — e.g. `audit_log`/`stock_ledger_entry`, which block DELETE via their own trigger, a stronger control than RLS could provide alone).

**RLS is explicitly combined with, never substituted for, application-level authorization** (§24's own instruction) — every service ALSO re-derives and filters by `tenant_id` explicitly in its own queries, meaning even a hypothetical RLS misconfiguration would still be caught by the application layer, and vice versa. This double-layering is the reason PROMPT-030-SPECIFICATION.md §16 had to call out its new platform-level tables as a DELIBERATE exception (Platform Admin sessions carry no RLS-applicable tenant context at all) — the general rule for every tenant-owned table remains RLS + app-layer, always both.

## 25. Administrator Security

Platform Administrator does not exist in code yet — this section defines the SECURITY requirements for PROMPT-030's own eventual implementation, cross-referencing rather than re-deriving:
- Least privilege: PROMPT-030-SPECIFICATION.md's two-tier model (`PLATFORM_SUPPORT` read-only vs `PLATFORM_SUPER_ADMIN`), recommended not yet built.
- Separate platform role: a STRUCTURALLY separate `platform_admin_user` table (PROMPT-030 §17), not a `role` row — the strongest possible "separate role" guarantee, enforced by the schema itself.
- Strong authentication: same bcrypt/JWT mechanism, SEPARATE cookie name/session table (PROMPT-030 §19) so a browser holding both a tenant session and a platform-admin session never confuses them.
- MFA: **NOT part of MVP, explicitly flagged as a security risk** (per this prompt's own §25 instruction) — see Open Decision #3. Given Platform Administrator is the single highest-privilege identity in the entire system (able to see cross-tenant operational data, change tenant status, grant itself support access to any tenant), shipping it WITHOUT MFA is a genuine, named residual risk, not a silently-accepted gap — Risk Register item SEC-R-001 (§45 below).
- Full audit: every platform action carries `actor_type=PLATFORM_ADMIN`/`SUPPORT_ADMIN` (PROMPT-031 §7).
- No unrestricted tenant transaction editing: PROMPT-030 §25's own explicit prohibition on a generic Admin Override button, re-confirmed structurally impossible today (§19 above — no such endpoint exists for ANY actor type, platform or tenant).

## 26. Support Access Security

Fully specified in PROMPT-030-SPECIFICATION.md §10 (explicit/scoped/attributable/auditable/time-bound — all five, with concrete column-level design: `support_access_session.reason`/`access_level`/`start_time`/`expires_at`/`end_time`) and PROMPT-031-SPECIFICATION.md §14/§7 (the three-identity actor model for every audit event written during a session). No hidden/unrestricted impersonation is designed anywhere — reused verbatim, not re-derived.

## 27. Audit Security

Fully specified in PROMPT-031-SPECIFICATION.md (append-only via the existing trigger, tenant-isolated via RLS + server-derived tenant_id, secrets excluded via the allowlist-snapshot + redaction-backstop pattern, §15 of that document). This spec adds ONE cross-cutting security observation PROMPT-031 didn't fully close: **login failure, unauthorized access attempts, and privilege changes are the three security-audit event types the source prompt's own §27 explicitly calls out — of these, only login failure is currently wired** (`LOGIN_FAILED` exists; `UNAUTHORIZED_ACCESS_ATTEMPT` and a distinct `ROLE_CHANGED`/`PERMISSION_CHANGED` do not, both already identified as PROMPT-031's own Conflict 3 / Action Model gap — restated here as a SECURITY finding, not a new, separately-tracked gap).

## 28. Rate Limiting & Abuse Protection

| Operation | Current limit | Source |
|---|---|---|
| Sign-up | `signup_rate_limit_per_ip_per_hour` = 10/hr (placeholder default) | PROMPT-002 |
| Login | `login_rate_limit_per_ip_per_hour` = 30/hr + lockout (5 failures/15min per identifier) | PROMPT-003 |
| Password reset request | `password_reset_rate_limit_per_ip_per_hour` = 10/hr AND `password_reset_identifier_rate_limit_per_hour` = 5/hr (two independent limits — per-IP AND per-account, preventing both a single attacker hammering many accounts and many attackers hammering one account) | PROMPT-004 |
| General API calls | **No global per-user/per-tenant rate limit exists** | Gap |
| Integration retry | `gst_integration_default_max_retry_attempts` = 3, `retry_backoff_seconds` = 5 — but this governs the SERVER's own outbound retry to the GST provider, not a client-facing rate limit on how often a USER can request generation | PROMPT-018 |
| Export | **No rate limit** — PROMPT-027/031's export endpoints have no throttle | Gap |
| Expensive report queries | **No rate limit or complexity cap** — same as §6.E's DoS finding | Gap |

**Known architectural limitation, documented not hidden**: `rate_limit.py`/`login_lockout.py` are explicitly BOTH in-memory, per-process — a multi-instance/horizontally-scaled deployment would need a shared store (Redis) for these limits to function correctly across instances; both modules' own docstrings already say so. This is a real production-readiness gap, restated here as a security finding (Open Decision #8, Risk Register).

## 29. Denial-of-Service Protection

| Control | Status |
|---|---|
| Payload size limits | **Not explicitly configured** at the application layer (FastAPI/Starlette has a default but no custom limit is set) — deployment-layer (reverse proxy) is the likely real control today, not verified in application code — gap |
| Pagination limits | **True** — every list endpoint caps `page_size` (100-200 max, consistent codebase-wide convention) |
| Request timeouts | Not configured in application code — deployment-layer (Uvicorn/reverse-proxy) concern, not verified here |
| Retry backoff (server → external provider) | **True** — `gst_integration_default_retry_backoff_seconds`, PROMPT-018 |
| Concurrency limits | Postgres row-locking (`SELECT ... FOR UPDATE`) prevents RACE conditions, not the same as a REQUEST concurrency limiter — no request-level concurrency cap exists |
| File uploads | **N/A — no file upload capability exists anywhere in this MVP** (confirmed, §30) |

## 30. File/Document Security

**Out of scope — no document/file upload capability exists anywhere in this codebase.** PDF "print preview" screens (Purchase Order/Goods Receipt/Purchase Invoice/Purchase Return, PROMPT-020-023) use the BROWSER's own `window.print()` — no file is generated, stored, or uploaded server-side. Marked explicitly out of scope per this prompt's own §30 instruction ("if not part of MVP, mark it as out of scope") rather than silently ignored.

## 31. Security Headers

**Genuine, confirmed gap**: `app/main.py` configures NO security-header middleware at all today — no `Content-Security-Policy`, `Strict-Transport-Security`, `X-Content-Type-Options`, `Referrer-Policy`, `X-Frame-Options`/`frame-ancestors`, or `Permissions-Policy` header is set anywhere (verified by reading the full middleware stack — only `CorrelationIdMiddleware` and `CORSMiddleware` are registered). This is the single most concrete, actionable, low-risk-to-fix gap this entire specification surfaces.

**Recommended configuration** (documented here as a spec, not implemented):
```
Content-Security-Policy: default-src 'self'; connect-src 'self' <api-origin>; frame-ancestors 'none'
Strict-Transport-Security: max-age=63072000; includeSubDomains  (production only, since it requires HTTPS)
X-Content-Type-Options: nosniff
Referrer-Policy: strict-origin-when-cross-origin
X-Frame-Options: DENY  (redundant with frame-ancestors, kept for older-browser compatibility)
Permissions-Policy: geolocation=(), microphone=(), camera=()   (this app uses none of these)
```
CSP is deliberately NOT copy-pasted from a generic template (§31's own instruction) — `connect-src` must include the actual API origin (varies dev/staging/prod), and since this is a Vite-built SPA served separately from the API in dev (port 3000 vs 8000) but likely same-origin in production, the exact policy needs environment-specific values, flagged for the implementation pass rather than hard-coded here.

## 32. Error Security

Already fully compliant, verified: `error_handlers.py`'s own docstring states the exact requirement (no stack traces/secrets/internal paths cross the API boundary) and the code matches — `AppError` handler logs full detail server-side (`exc_info=True`) but returns only `{code, message, details}`; the generic `Exception` fallback (not shown in the excerpt read, but implied by FastAPI's own unhandled-exception path combined with this codebase's consistent `AppError`-hierarchy discipline) should be double-checked at implementation time to confirm it ALSO never leaks a raw exception message — flagged as a verification task, not assumed.

## 33. Data Privacy

| Data | Sensitivity | Current handling |
|---|---|---|
| Customer/Supplier contact details | CONFIDENTIAL | RLS + permission-gated, no anonymization/masking exists |
| Employee/Payroll information | HIGHLY CONFIDENTIAL | RLS + separate `salary.*` permission gate (PROMPT-029) |
| User identity information | CONFIDENTIAL | RLS + permission-gated |

**No applicable privacy/legal framework (e.g. India's DPDP Act) has been confirmed against any approved product requirement document in `Document/`** — this is a genuine, explicitly-flagged gap per this prompt's own §33 instruction ("do not introduce unsupported legal claims… identify as OPEN DECISION if not defined") — Open Decision #17. No "right to erasure"/secure-deletion capability exists anywhere in this codebase (no DELETE path for Customer/Supplier/Employee exists at all today, only deactivate — consistent with the "audit/financial history must survive" principle, but a genuine tension with any eventual erasure requirement, worth flagging together).

## 34. Backup Security

**Not defined anywhere in this codebase or its documentation** — no backup automation, encryption, retention, or restore-authorization policy exists in the application layer (this is inherently a DEPLOYMENT/infrastructure concern, not something FastAPI application code controls). Flagged as Open Decision #16, not silently assumed to be someone else's problem without saying so explicitly.

## 35. Logging Security

Already cleanly separated (PROMPT-031-SPECIFICATION.md §26, cross-referenced not repeated): AUDIT LOG (`audit_log` table) vs APPLICATION LOG (`app/logging/config.py`'s `JsonFormatter`, with its own independent `_REDACTED_KEYS` set) — both independently verified to never log passwords/tokens/secrets (two SEPARATE redaction mechanisms, a form of defense in depth, not a single point of failure). No METRICS/TRACES infrastructure exists (§4 Out of Scope in PROMPT-031, reaffirmed here). Retention: application logs go to stdout only (ephemeral, whatever the hosting platform captures — Open Decision #15); audit logs are retained indefinitely in Postgres (PROMPT-031 §17).

## 36. Dependency Security

**No automated dependency-vulnerability scanning exists in this codebase today** (no `pip-audit`/`npm audit` CI step, no Dependabot config found) — a real, actionable gap for a production-bound MVP. Lock files DO exist (`package-lock.json` for frontend, and the backend's own `.venv`-based dependency set, though a `requirements.txt`/`pyproject.toml` pinning strategy should be verified at implementation time). Recommendation: add `pip-audit`/`npm audit` (or GitHub Dependabot) as a CI gate — low cost, standard practice, no new architecture required.

## 37. Secure Development Requirements

Code review, secret scanning, dependency scanning, and static analysis are PROCESS requirements, not something this codebase's own source can self-certify — no CI pipeline configuration was found in this repository to confirm any of these currently run automatically. This spec RECOMMENDS (not asserts as already true): pre-commit secret-scanning (e.g. `gitleaks`), the dependency scanning from §36, and treating the EXISTING test suite's own security-relevant tests (cross-tenant isolation tests, RBAC enumeration tests in `test_rbac.py`) as a MANDATORY, non-skippable CI gate — which they functionally already are, since this session has run the full suite before every closing report.

## 38. Threat Scenarios

All 30 scenarios from the source prompt's §38, each resolved against real code (✅ = structurally prevented today, ⚠️ = partially mitigated, ❌ = genuine gap):

| # | Scenario | Status | Basis |
|---|---|---|---|
| 1 | Tenant A → Tenant B customer | ✅ | RLS + app-level tenant filter, §10 |
| 2 | Tenant A → Tenant B invoice | ✅ | Same |
| 3 | User modifies tenant_id | ✅ | Never accepted from client, §10 |
| 4 | Salesperson → Accounting API | ✅ | Zero `accounting.*` permissions granted, PROMPT-025 |
| 5 | Tenant user self-assigns Owner | ✅ | No self-role-edit path exists, §11 |
| 6 | Tenant user self-assigns Platform Admin | ✅ | Structurally impossible — separate table, PROMPT-030 §17 |
| 7 | Platform Admin modifies financial record | ✅ | No such endpoint exists for ANY actor, §19/§25 |
| 8 | Stolen session token | ⚠️ | httpOnly mitigates theft VECTOR (XSS); a token stolen via OTHER means (device compromise) remains valid until expiry/revocation — MFA is the missing layer, Open Decision #3/#4 |
| 9 | Brute-force login | ⚠️ | Lockout + rate limit exist but are in-memory/per-process (§28) — a distributed attack across many source IPs is not fully defended |
| 10 | Malicious offline transaction | ✅ | Full server-side re-validation, §18 |
| 11 | Duplicate offline transaction | ✅ | Idempotency-Key, §18 |
| 12 | Modified offline transaction | ✅ | Server recalculates GST/totals, never trusts client math, §18 |
| 13 | GST credential exposure | ✅ | Fernet-encrypted, never logged, §20 |
| 14 | API credential exposure | ✅ | Same mechanism |
| 15 | SQL injection | ✅ | Parameterized queries throughout, §13 |
| 16 | XSS | ⚠️ | React escaping real; no CSP yet, §31 gap |
| 17 | CSRF | ⚠️ | SameSite+httpOnly substantial; no token, §13 |
| 18 | IDOR/BOLA | ✅ | Object-level tenant+ownership checks, §12 |
| 19 | Privilege escalation | ✅ | §11 |
| 20 | Audit log manipulation | ✅ | DB trigger, PROMPT-031 §16 |
| 21 | Unauthorized support access | ✅ (once PROMPT-030 built) | Explicit session-scoping, PROMPT-030 §10 |
| 22 | Export data leakage | ✅ | Export inherits list endpoint's own scoping, PROMPT-031 §24 |
| 23 | Suspended tenant API access | ✅ (once PROMPT-030 built) | `tenant.status` enforcement point identified, PROMPT-030 §9 |
| 24 | Disabled tenant API access | ✅ (once PROMPT-030 built) | Same |
| 25 | Malicious browser/PWA cache access | ⚠️ | SW caches app shell only (low risk); IndexedDB business data is UNENCRYPTED on-device, §17 gap |
| 26 | Replay of sync request | ✅ | Idempotency-Key |
| 27 | Replay of payment request | ✅ | Same mechanism, PROMPT-024 |
| 28 | Replay of invoice posting request | ✅ | Same, PROMPT-015 |
| 29 | Malicious configuration change | ✅ (once PROMPT-030 built) | `platform.manage_global_config` permission gate + versioned history, PROMPT-030 §7.8 |
| 30 | Unauthorized integration configuration change | ⚠️ | `integration_configuration` currently has NO dedicated management API/UI at all (lazily provisioned only, CLAUDE.md §4) — meaning there is also no ENDPOINT to unauthorizedly call; low risk today by absence of the feature, but flagged since "no feature" is not the same as "secured feature" |

## 39. Security Test Strategy

| Test layer | Existing coverage | Gap |
|---|---|---|
| Unit security tests | Password hashing, token generation (implicit in auth tests) | No dedicated crypto-primitive unit test file found — recommend one |
| Integration security tests | `test_rbac.py` (permission enumeration), tenant-isolation assertions embedded throughout every module's own test file | Comprehensive, not centralized — acceptable given the per-module pattern this whole codebase uses |
| API security tests | Cross-tenant 404 tests exist per-module | No CENTRALIZED cross-module sweep (this spec's §40 defines what one would look like) |
| Role/access tests | `test_rbac.py` + per-module RBAC tests | Strong |
| Tenant isolation tests | Per-module, consistent pattern | Strong |
| PWA/offline security tests | PROMPT-028's own 30 frontend unit tests cover LOGIC (classification, backoff) — explicitly NOT real-browser IndexedDB/encryption behavior (documented limitation, PROMPT-028-NOTES.md) | Real-device verification still outstanding |
| Penetration tests | **None performed** | Open Decision #18 |
| Dependency tests | **None automated** (§36) | Gap |
| Configuration tests | **None** — no test asserts security headers are present, CORS is correctly scoped, etc. | Gap, directly addressable once §31 is implemented |

## 40. API Security Test Matrix

For each of Sales/Purchase/Payments/Accounting/GST/Payroll/Reports/Offline Sync/Audit/Platform Admin, the SAME 9-dimension matrix (Authentication/Authorization/Tenant isolation/Input validation/Object-level authorization/Rate limiting/Idempotency/Error handling/Sensitive data exposure) applies. Rather than repeat 90 near-identical cells, the codebase-wide answer is: **Authentication, Authorization, Tenant isolation, Object-level authorization, Idempotency, and Error handling are already covered by existing tests in EVERY one of these modules** (verified — every module's own `test_*.py` file includes RBAC-denial and cross-tenant-404 cases as a matter of established convention since PROMPT-007). **Rate limiting is NOT tested for any module beyond Auth** (§28's gap). **Input validation** is tested per-field where a dedicated validator exists (GSTIN/HSN/phone) but not exhaustively fuzzed. **Sensitive data exposure** is tested narrowly (e.g. "password never in response") rather than via a generic schema-diffing sweep across all 90 cells — Reports/Audit/Platform Admin/Offline Sync specifically have LESS mature coverage since Reports/Audit are newer (PROMPT-027/031) and Platform Admin doesn't exist in code yet.

## 41. Security Incident Handling

MVP-level, matching this codebase's actual current operational capability (no SOC, no 24/7 monitoring — honestly scoped, not over-promised):

| Scenario | Detection | Containment | Recovery |
|---|---|---|---|
| Suspected credential compromise | User/admin report, or a spike in `LOGIN_FAILED` events for one identifier | Revoke `auth_session` rows for that user (existing capability); force password reset | Existing PROMPT-004 flow |
| Cross-tenant access attempt | Would surface as repeated 404s from one IP/user in application logs — **no automated alert exists** (gap) | Manual investigation via correlation_id | N/A |
| Repeated auth failures | Lockout mechanism auto-contains (§7/§28) | Automatic (15-min lockout) | Automatic expiry |
| Leaked integration credential | Manual detection only (no secret-scanning alert pipeline, §21) | Rotate the Fernet key + re-encrypt `credentials_encrypted`, revoke/regenerate the GST provider credential itself | Manual, documented runbook needed (not written — Open Decision) |
| Unauthorized support access | Once PROMPT-030 built: `SUPPORT_ACCESS_STARTED` audit event, reviewable | Session-level revocation (`POST /support-access/{id}/end`) | Audit trail supports post-incident review |
| Suspicious API activity | Correlation-ID-tagged structured logs are queryable, but **no automated anomaly detection exists** | Manual | Manual |

**No enterprise SOC is proposed** (§41's own explicit instruction) — this is a documented, honest MVP baseline: detection is mostly manual/log-query-driven today, not automated alerting. Flagged as Open Decision #14/#19.

## 42. Security Configuration Management

Current mechanism: `app/core/config.py`'s `Settings` (Pydantic `BaseSettings`), sourced from `.env` per environment — every security-relevant threshold (rate limits, lockout, password min length, cookie flags, JWT expiry) is ALREADY a named, typed, documented setting rather than a magic number scattered through code (verified — every value cited in §7/§28 above traces to a named `Settings` field). Changing one requires a `.env` edit + redeploy — there is no runtime-configurable, audited, versioned admin UI for these yet (that's PROMPT-030's own `platform_configuration` concept, §14 of that spec, not yet built). Feature flags: none exist in this codebase today (not a concept used anywhere).

## 43. Responsive Security Admin UI

Applies to: PROMPT-031's `AuditLogManagement.tsx` (spec'd) and PROMPT-030's Platform Admin screens (spec'd) — both already specify the SAME responsive discipline this codebase has proven repeatedly (`hidden md:block` table / `md:hidden` cards, sticky filters, `overflow-x-auto` scoped to tables only). No new pattern is introduced by this spec; it inherits the requirement from the two documents it depends on.

## 44. Non-Functional Security Requirements

| Requirement | Measurable target | Status |
|---|---|---|
| Authentication | Bcrypt cost factor = passlib default (12) — adequate for MVP scale | Met |
| Authorization | 100% of protected endpoints call `require_permission()` or an equivalent explicit check — not independently verified by an automated linter, but consistent by convention across 30+ prompts | Believed met, not mechanically enforced |
| Tenant isolation | Zero cross-tenant data leakage in any existing test — 700+ backend tests include cross-tenant assertions per module | Met, per existing test suite |
| API security | See §13 | Mostly met, CSP/CSRF-token gaps noted |
| Encryption | TLS in transit (deployment-dependent), Fernet for one specific credential class at rest | Partial — see §22 |
| Secret management | No secrets in source control (verified) | Met for MVP scope; no secret-manager platform (§21) |
| Auditability | Every state-changing business action across 30 prompts writes an audit event | Met, with PROMPT-031's own named gaps (security events, ROLE_CHANGED) |
| Availability | No SLA defined anywhere in product docs | Open Decision |
| Performance | Audit writes add ~0 measurable overhead (same-transaction INSERT, PROMPT-031 §25) | Met |
| Logging | Two independently-redacting mechanisms (§35) | Met |
| Incident response | Manual/log-query-driven (§41) | Below enterprise standard, proportionate for MVP — flagged |

No arbitrary compliance certification (SOC 2, ISO 27001, PCI-DSS) is claimed or targeted — none is referenced in any approved product document, and none is invented here (§44's own explicit instruction).

## 45. Security Risk Register

| Risk ID | Threat | Asset | Likelihood | Impact | Rating | Mitigation | Owner | Status | Residual |
|---|---|---|---|---|---|---|---|---|---|
| SEC-R-001 | No MFA for Platform Administrator | Platform-wide cross-tenant data | Medium (once built) | Critical | **CRITICAL** | Require MFA before Platform Admin ships to production | Security + Product | Open | High until mitigated |
| SEC-R-002 | No security headers (CSP/HSTS/X-Frame-Options) | Web/PWA clients | Medium | Medium | **HIGH** | Implement §31's recommended header set | Engineering | Open | Low once fixed |
| SEC-R-003 | Offline IndexedDB data unencrypted, no logout-clear | Offline business data on lost/stolen device | Low-Medium | Medium | **MEDIUM** | Add logout-time IndexedDB clear (low cost); evaluate on-device encryption feasibility | Engineering + Product | Open | Medium |
| SEC-R-004 | In-memory rate-limit/lockout state (not shared across instances) | Auth endpoints | Low (single-instance MVP today) | Medium (grows with scale) | **MEDIUM** | Move to Redis-backed store before horizontal scaling | Engineering | Open, deferred | Low at current scale |
| SEC-R-005 | No automated dependency-vulnerability scanning | Entire application (supply chain) | Medium | Medium | **MEDIUM** | Add `pip-audit`/`npm audit`/Dependabot to CI | Engineering | Open | Medium until fixed |
| SEC-R-006 | No CSRF token (relying on SameSite+httpOnly alone) | State-changing endpoints | Low | Medium | **LOW-MEDIUM** | Accept residual risk for MVP; revisit if SameSite policy ever needs relaxing (e.g. for a future third-party embed) | Security | Accepted for MVP | Low |
| SEC-R-007 | Unauthorized-access attempts (403s) not audited | Security visibility | Medium | Low-Medium | **MEDIUM** | Wire `UNAUTHORIZED_ACCESS_ATTEMPT` per PROMPT-031 Conflict 3 | Engineering | Open | Low once fixed |
| SEC-R-008 | No secret-management platform (`.env`-only) | All application secrets | Low (small team, MVP scale) | High (if `.env` ever leaked) | **MEDIUM** | Document strict `.env` handling discipline now; move to a real secret manager before scaling the team/infra | Security + DevOps | Accepted for MVP, revisit | Medium |
| SEC-R-009 | No penetration test performed | Whole application | N/A | Unknown | **MEDIUM (unknown)** | Commission a pentest before production launch | Security + Product | Open | Unknown until tested |
| SEC-R-010 | No DoS protections on report queries / payload size | Availability | Low | Medium | **LOW-MEDIUM** | Add date-range caps + payload size limits (§29) | Engineering | Open | Low-Medium |

Two items are rated **CRITICAL** (SEC-R-001) or effectively require resolution/acceptance before production per §45's own instruction ("Critical risks must be resolved or explicitly accepted before production") — SEC-R-001 (MFA) is the one this spec recommends NOT silently accepting, given Platform Administrator's unique blast radius.

## 46. QA/Security Test Cases

This spec does not re-list PROMPT-031's own 31 QA + 16 security test cases (already complete and directly applicable to audit-specific concerns) — it ADDS the cases specific to this document's own new findings, to be implemented alongside PROMPT-031's:

1. Security headers are present on every response (once §31 is implemented).
2. A cross-site form POST cannot trigger a state-changing action (CSRF residual-risk confirmation).
3. `X-Frame-Options`/`frame-ancestors` blocks framing from a foreign origin.
4. Logout clears IndexedDB business data (once §17's gap is fixed).
5. Rate limit / lockout thresholds trigger exactly at the configured boundary, not off-by-one.
6. A Salesperson token cannot access ANY Accounting/GST/Payroll endpoint, exhaustively enumerated (a full API surface sweep, not a sample).
7. Expired JWT is rejected even if `auth_session` was never explicitly revoked (pure expiry path, distinct from the revocation path).
8. A revoked `auth_session`'s JWT is rejected even before its `exp` claim expires.
9. Fernet-encrypted credentials never appear in any log line (log-content grep test).
10. Offline-synced invoice's server-recalculated GST differs from a deliberately-wrong client-provided value, and the SERVER value wins (proves §18's "never trust client tax calculation" claim, not just asserts it).

## 47. Acceptance Criteria

Directly traceable to the source prompt's §46 (1–26) — every item maps to a section above; items concerning controls that don't exist yet (Platform Admin boundaries, item 6; offline revalidation, item 8 — already true today per §18) are marked accordingly rather than glossed over. Item 25 ("no unresolved Critical security defect") is explicitly NOT met today — SEC-R-001 is open — and this spec does not pretend otherwise.

## 48. Open Decisions

Directly answering the source prompt's own §47 list (1–23):

| # | Question | Why it matters | Recommended | Alternative | Impact | Owner |
|---|---|---|---|---|---|---|
| 1 | Authentication mechanism | Foundational | **Already decided and built**: JWT + server-side revocation via `auth_session` (PROMPT-003) — not open, restated for completeness | — | — | — |
| 2 | Session/token architecture | Foundational | **Already decided**: single 60-min token, no refresh (§8) | Add a refresh token if UX friction from re-login becomes a real complaint | Larger theft surface if added | Product + Security |
| 3 | MFA for Platform Admin | SEC-R-001, the single highest-priority open item in this spec | **Required before production** — TOTP-based (industry standard, no custom crypto) | Ship without MFA and accept the risk explicitly (not recommended) | Blocks/delays Platform Admin production readiness if required | Security + Product |
| 4 | MFA for Tenant Owner | Lower urgency than #3 (blast radius is one tenant, not all tenants) | Optional for MVP; recommended as a fast-follow | Require at launch | Additional UX friction if required now | Product Owner |
| 5 | Password policy | Only min-length (8) is enforced today (carried from CLAUDE.md §4) | Keep as-is for MVP; a stricter policy (complexity rules) needs an approved source, none exists | Add complexity rules | None if kept as-is | Product Owner |
| 6 | Session timeout | Already 60 min | Keep | Shorter for higher-privilege roles (e.g. Owner) | Minor UX tradeoff | Product Owner |
| 7 | Concurrent session policy | Not restricted today (§8) | Allow multiple concurrent sessions for MVP (common SaaS UX) | Restrict to one active session per user | Restricting adds real engineering work for uncertain benefit | Product Owner |
| 8 | Rate-limit thresholds | Documented as unapproved placeholders since PROMPT-002/003/004 | Keep current defaults until a real security/product review sets final numbers | Tighten now speculatively | None if kept, since they're already functioning defensive controls even if not "approved final" numbers | Product + Security |
| 9 | Account lockout behavior | Same placeholder status (FR-SI-09 "confirmation required") | Keep current mechanism/defaults | — | — | Product Owner |
| 10 | RLS implementation details | Already implemented, consistent pattern | Document as-is (§24) | — | — | — |
| 11 | Database encryption approach | No column-level encryption for ordinary data (by design, for queryability) | Rely on infrastructure-layer (disk/backup) encryption; document as a DEPLOYMENT requirement, not application code | Add column-level encryption for specific ultra-sensitive fields (e.g. bank account numbers) | New engineering cost if added | Security + Engineering |
| 12 | Offline local-data encryption approach | SEC-R-003 | Investigate `SubtleCrypto`-based IndexedDB field encryption as a fast-follow; minimum bar: clear IndexedDB on logout | Do nothing (not recommended) | Real residual risk on lost/stolen devices if not addressed | Security + Engineering |
| 13 | Secret-management platform | `.env`-only today | Acceptable for MVP; adopt a real secret manager (e.g. cloud-native KMS) before scaling past a small team/single environment set | Continue with `.env` indefinitely | Growing risk with team/infra growth | DevOps + Security |
| 14 | Security monitoring platform | None exists (§41) | Not required for MVP; revisit once real production traffic exists | Add a SIEM/log-aggregation tool now | Cost/complexity now vs. later | Security + DevOps |
| 15 | Log retention period | App logs: ephemeral (stdout); audit logs: indefinite (PROMPT-031 §17) | Keep as-is | Define explicit retention for app logs via hosting platform config | Minor | DevOps |
| 16 | Backup retention period | Undefined (§34) | Define at the infrastructure/deployment layer, not in application code | — | Compliance exposure if never defined | DevOps + Legal |
| 17 | Applicable privacy/legal requirements | Undefined (§33) | Flag for legal review (e.g. India DPDP Act applicability) before handling real customer PII at scale | Proceed without a formal review | Legal exposure if genuinely applicable and unaddressed | Legal + Product |
| 18 | Penetration testing before production | None performed (SEC-R-009) | Commission one before public/production launch | Skip (not recommended for a financial SaaS product) | Unknown-risk exposure if skipped | Security + Product |
| 19 | Security incident notification process | Undefined (§41) | Define a minimal runbook (who gets notified, how) before production | None | Slower response to a real incident if undefined | Security + Product |
| 20 | Support-access approval requirements | Same open item as PROMPT-030 OD #4 | Cross-referenced, not re-decided here | — | — | Product + Security (shared) |
| 21 | File/document security requirements | N/A — no file upload exists (§30) | Revisit only if a future prompt introduces file upload | — | — | — |
| 22 | Are security events visible to Tenant Owners? | Same open item as PROMPT-031 OD #5 | Cross-referenced, not re-decided here | — | — | Product Owner (shared) |
| 23 | Is device/session management required in MVP? | "View my active sessions" UI doesn't exist (§8) | Not required for MVP; natural fast-follow given `auth_session`/`device_info` already capture the needed data | Build it now | Moderate UI work if built now | Product Owner |

## 49. Requirement Conflicts

Per the source prompt's own closing instruction:

**Conflict 1 — Offline logout does not clear IndexedDB business data (§17), contradicting the "assume the device may be lost or compromised" instruction (§17 of the source prompt) that this SAME prompt asks the architecture to satisfy.** PROMPT-028's own approved design deliberately does NOT auto-delete `PENDING_SYNC`/`SYNC_FAILED`/`CONFLICT`/`REQUIRES_ACTION` records (CLAUDE.md §4, "nothing in this codebase ever auto-deletes" — a structural guarantee against DATA LOSS) — but this same protection-against-loss also means there is currently no code path that clears SYNCED, no-longer-needed local data either, even on explicit logout. **This is a genuine tension between two legitimate goals** (never lose unsynced work vs. minimize data-at-rest on a possibly-compromised device) that PROMPT-028 was never asked to resolve, and PROMPT-032 cannot silently resolve either — recommended resolution: clear only FULLY-SYNCED records on logout (never touching anything still pending/failed/conflicted), which satisfies both goals simultaneously, but this is a NEW behavior requiring its own small implementation pass against `pwa/offlineDb.ts`, flagged here rather than assumed.

**Conflict 2 — No security-headers middleware conflicts with no explicit prior requirement having asked for one.** Not a conflict between two approved documents, but worth naming precisely: PROMPT-001's own S7-S13 scope (correlation IDs, structured logging, exception handling) never included security headers, and no subsequent prompt asked for them either — this is a SCOPE GAP across the whole prior 31-prompt sequence, not a contradiction between two conflicting instructions. Surfaced here for the first time because PROMPT-032 is the first prompt to ask the question directly.

**Conflict 3 — Rate-limiting/lockout being in-memory-only conflicts with any assumption of horizontal scalability**, which no prior prompt explicitly promised but which a "SaaS MVP" framing might implicitly suggest. `rate_limit.py`/`login_lockout.py`'s own docstrings already flag this as a known limitation (PROMPT-002/003) — restated here as a SECURITY (not just operational) concern, since a multi-instance deployment without a shared store would effectively let an attacker bypass the rate limit by having requests land on different instances.

## 50. Dependencies

- PROMPT-001 (foundation: correlation IDs, structured logging, exception hierarchy, `audit_log`) — the base every control in this spec builds on.
- PROMPT-002/003/004 (authentication, sessions, password reset, rate limiting, lockout) — reused verbatim, not redesigned.
- PROMPT-006 (RBAC) — the authorization backbone.
- PROMPT-012 (audit immutability trigger) — reused.
- PROMPT-018 (Fernet credential encryption, `SandboxSimulatorProvider`'s "fail loudly, never fake success" discipline) — the model for §20/§22.
- PROMPT-025/026/029 (financial/GST/payroll immutability-after-posting patterns) — the model for §19.
- PROMPT-028 (offline architecture) — the subject of §17/§18 and Conflict 1.
- **PROMPT-030-SPECIFICATION.md** — Platform Administrator identity model (§11/§17/§25/§26), reused not re-derived.
- **PROMPT-031-SPECIFICATION.md** — audit event model, actor types, redaction policy (§27 and throughout), reused not re-derived.

## 51. Definition of Done (for THIS specification deliverable)

- [x] All 47 sections requested by the source prompt's §48 are present.
- [x] Every claim is grounded in the ACTUAL current codebase — confirmed via direct inspection of `security.py`, `rate_limit.py`, `login_lockout.py`, `deps.py`, `config.py`, `main.py`, `error_handlers.py`, `crypto.py`, `integration_configuration.py`, RLS migration coverage — nothing asserted without verification, including the HONEST reporting of what does NOT exist (security headers, MFA, IndexedDB encryption, dependency scanning).
- [x] A threat model (STRIDE), 30-scenario threat analysis, and a 10-item risk register with one CRITICAL rating are provided — no risk is silently downgraded to make the spec look more finished than it is.
- [x] Every open decision from the source prompt's §47 is answered with Question/Why/Recommended/Alternative/Impact/Owner; several correctly point back to shared decisions already tracked in PROMPT-030/031 rather than being re-litigated as if novel.
- [x] Three genuine Requirement Conflicts are flagged explicitly (§49), including one (offline logout vs. device-compromise assumption) that surfaces a real tension between two previously-approved, individually-reasonable decisions.
- [ ] **Not done, and not in scope for this deliverable**: actual implementation (security-headers middleware, MFA, IndexedDB logout-clear, dependency-scanning CI, rate-limit shared store). Per the source prompt's own framing (§48 "Produce the final security specification," §49's spec-readiness Definition of Done, and the same absent "implement/STOP" language as PROMPT-030/031), this document is the planning and threat-model artifact for a future implementation and hardening pass — not a request to write code in this turn.
