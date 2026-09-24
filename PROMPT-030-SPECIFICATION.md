# PROMPT-030 — Platform Administration, Tenant Administration & Operational Controls

**Document type:** Development specification & implementation plan (per the prompt's own §37 instruction — this document does NOT implement code; it is the feature-by-feature blueprint a development team uses to implement PROMPT-030 in a future session).

**Baseline used:** the actual, current state of this codebase after PROMPT-001 through PROMPT-029 (verified by reading the real models/services/migrations, not assumed) — `CLAUDE.md`, `PROMPT-001` through `PROMPT-029-NOTES.md`, and direct inspection of `app/models/`, `app/core/permissions.py`, `app/core/deps.py`, `app/models/audit_log.py`, `app/models/role.py`, `app/models/integration_configuration.py`/`integration_operation.py`.

**Explicit non-negotiable per the prompt's own closing instruction:** any place this spec would conflict with an already-approved decision from a prior prompt is called out under §28 (Open Decisions) / §28A (Requirement Conflicts) rather than silently resolved.

---

## 1. Requirement Understanding

PROMPT-030 asks for a **Platform Administration** capability (operated by the SaaS vendor, not any tenant) layered on top of the **already-existing Tenant Administration** capability (Owner/Manager managing their own organization, built across PROMPT-005/006/007/etc.), plus a small number of **operational controls** (tenant lifecycle state, feature entitlements, integration/sync health monitoring, centralized audit visibility) that touch every tenant but must never let a platform operator become a backdoor business user of any tenant's financial/GST/payroll data.

Three things already exist and must be reused, not rebuilt:
1. **Tenant Administration** (Owner managing users/roles/permissions) — PROMPT-005/006, live today at `/api/v1/users`, `/api/v1/roles`, `/api/v1/permissions`.
2. **`tenant.status`** — the column already exists (`Tenant.status`, default `"ACTIVE"`, migration 0002-era) but **is not read or enforced anywhere in the codebase today** (confirmed by code search — no `tenant.status` check exists in `app/core/deps.py`, login, or anywhere else). PROMPT-030 is what gives this column real behavior for the first time.
3. **Integration monitoring data** — `integration_configuration`/`integration_operation` (PROMPT-018) already record GST/e-Invoice/e-Way Bill provider status, retry counts, and failure reasons per tenant. PROMPT-030's "Integration Monitoring" screen is a cross-tenant READ view over this existing data, not a new table.

Two things do **not** exist yet and are genuine, in-scope additions:
1. **A Platform Administrator identity** — no such role, permission, login path, or session mechanism exists anywhere in this codebase (confirmed: `CLAUDE.md` §4 already lists "Platform Administrator role" as an open decision carried since PROMPT-006, unresolved until now).
2. **Global (cross-tenant) configuration and feature entitlements** — no table or service for either exists.

## 2. Scope

In scope for the PROMPT-030 implementation this specification describes:

- Platform Administrator identity, authentication, and a dedicated, isolated authorization model.
- Tenant lifecycle state machine (`ACTIVE`/`SUSPENDED`/`DISABLED`) with real enforcement (the currently-dormant `tenant.status` column comes alive).
- Tenant directory (search/list/detail) for Platform Administrators — READ ONLY by default.
- Support access: a time-bound, audited, explicitly-authorized elevated-access session mechanism, off by default.
- Feature/module entitlement per tenant (module ON/OFF), enforced as a SECOND, independent gate alongside the existing permission system — never a replacement for it.
- Global configuration vs. tenant configuration, with a documented precedence and snapshot rule.
- Integration monitoring (reusing `integration_configuration`/`integration_operation`) and sync-health visibility (see §28A — this is where a real conflict with PROMPT-028's approved architecture is flagged).
- Centralized, cross-tenant audit log visibility for Platform Administrators.
- A minimal system health view (API/DB reachability, recent error counts) — MVP scope only, explicitly not a full observability platform.
- Full RBAC/audit/security model for every new capability above.
- Responsive UI (desktop/tablet/mobile) for both the Platform Administration area and the (already-partially-built) Tenant Administration area.

## 3. Out of Scope

Per the prompt's own §3 non-scope plus this codebase's own established restraint pattern (mirrors every prior prompt's "do not invent" discipline):

- Billing/subscription/metering (OD-11).
- Tenant self-service signup approval workflows beyond what PROMPT-002 already does.
- True full impersonation (silently acting as a tenant user with zero visual indicator) — explicitly forbidden by the source prompt itself (§9/§28).
- A generic "Admin Override" edit/delete button for any financial/GST/payroll record (§25, hard requirement, must never be built).
- A full enterprise observability/APM platform (§21).
- MFA implementation (flagged as an open decision, §36 item 12 — not built without a separate decision).
- Tenant data export/deletion tooling (§36 item 15/16 — open decision, not built).
- Any change to the existing Sales/Purchase/Inventory/Accounting/GST/Payroll business logic itself.
- Rebuilding `integration_operation`/`integration_configuration` (PROMPT-018) or the offline sync engine (PROMPT-028) — this module only ADDS a monitoring/read layer on top.

## 4. User Stories

**Platform Administrator**
- As a Platform Administrator, I can sign in through a dedicated platform-admin login, separate from any tenant's user base, so that my access is never confused with a tenant identity.
- As a Platform Administrator, I can search/browse the tenant directory so I can locate a tenant for support.
- As a Platform Administrator, I can view a tenant's operational metadata (status, plan/entitlements, user count, integration health) without seeing their financial transaction detail, so I can diagnose issues without exposure to sensitive business data by default.
- As a Platform Administrator, I can suspend or disable a tenant (e.g., for non-payment or abuse) and later reactivate a suspended tenant, with every transition audited.
- As a Platform Administrator, I can request time-bound elevated support access to a specific tenant, with a mandatory reason, so I can investigate an issue the tenant reported — and every action I take during that window is attributed to me AND the tenant.
- As a Platform Administrator, I can view integration and sync failure trends across tenants so I can proactively identify a provider outage.
- As a Platform Administrator, I can view the centralized audit log across tenants for security investigation.
- As a Platform Administrator, I CANNOT edit a posted Sales Invoice, journal entry, or payslip for any tenant, under any access level.

**Tenant Owner**
- As a Tenant Owner, I continue to manage my own organization's users/roles exactly as I do today (PROMPT-005/006) — nothing in this prompt changes that experience.
- As a Tenant Owner, I can view my tenant's own configuration (financial year, GSTIN, address) — some of it editable, some Platform-Admin-only (e.g., GSTIN change, since it affects every prior GST filing).
- As a Tenant Owner, I can see if my tenant is SUSPENDED and understand why (a visible banner, not a silent failure).
- As a Tenant Owner, I CANNOT create or assign a "Platform Administrator" role to anyone (§11, hard requirement — structurally impossible since Platform Administrator is not a row in the tenant's own `role` table at all, see §17).

**Tenant Manager**
- As a Tenant Manager, I only have the administrative permissions (e.g., `users.view`) my Owner has explicitly granted me — nothing changes from the existing PROMPT-006 permission model.

## 5. Personas

| Persona | Identity source | Typical session | Tenant-scoped? |
|---|---|---|---|
| Platform Administrator | New `platform_admin_user` table (see §17) | Platform-admin login, own JWT claim shape | No — spans all tenants by design, but every action against a SPECIFIC tenant's data still requires that tenant's id to be explicit and audited |
| Tenant Owner | Existing `user` + `role`="OWNER" | Existing tenant login (PROMPT-003) | Yes — exactly one tenant, enforced by existing RLS |
| Tenant Manager | Existing `user` + `role`="MANAGER" | Existing tenant login | Yes |
| Tenant Salesperson | Existing `user` + `role`="SALESPERSON" | Existing tenant login | Yes (no admin capability, unaffected by this prompt) |

## 6. Role & Permission Matrix

### 6.1 New platform-level permissions (NOT rows in the existing tenant-scoped `permission` table — see §17 for why)

| Permission code | Description | Default holder |
|---|---|---|
| `platform.view_dashboard` | View the Platform Admin dashboard | Platform Admin |
| `platform.view_tenants` | View the tenant directory and tenant detail (read-only) | Platform Admin |
| `platform.manage_tenant_status` | Change a tenant's lifecycle status | Platform Admin (senior — see OD table) |
| `platform.manage_entitlements` | Change a tenant's feature/module entitlements | Platform Admin (senior) |
| `platform.manage_global_config` | Change global/platform configuration | Platform Admin (senior) |
| `platform.view_integration_health` | View cross-tenant integration/sync monitoring | Platform Admin |
| `platform.view_audit_logs` | View the cross-tenant audit log | Platform Admin |
| `platform.request_support_access` | Request an elevated support-access session for a tenant | Platform Admin |
| `platform.approve_support_access` | Approve another admin's elevated support-access request (if approval workflow is adopted — OD item 4) | Senior Platform Admin |
| `platform.manage_platform_users` | Create/deactivate other Platform Administrator accounts | Super Admin only |

A **two-tier Platform Admin model** (`PLATFORM_SUPPORT` — read-only + monitoring; `PLATFORM_SUPER_ADMIN` — the above plus status/entitlement/config/user management) is **recommended** (see OD table) rather than a single undifferentiated "Platform Administrator" — this directly satisfies §2 principle 9 ("read-only support access is the default").

### 6.2 Existing tenant-scoped permissions (unchanged — reused verbatim)

`users.view/create/update/activate/deactivate`, `roles.view`, `permissions.view` (PROMPT-005/006) continue to govern Tenant Owner/Manager's own user administration exactly as today. **No new tenant-level permission is required for "Tenant Administration" as described in §10/§11 of the source prompt — it already exists.** The only tenant-facing addition is a **read-only "Tenant Settings" view** (financial year, GSTIN, status banner) — see §7.4.

### 6.3 Explicit exclusion

`ALL_PERMISSIONS`/`ROLE_DEFAULT_PERMISSIONS` in `app/core/permissions.py` (the tenant-scoped permission catalogue) **must never contain a `platform.*` code** — Platform permissions live in a structurally separate table/catalogue (§17) specifically so a tenant-side bug can never accidentally grant a tenant user a platform permission (defense in depth, directly satisfying §11's "do not allow a tenant Owner to assign Platform Administrator privileges" as a schema-level guarantee, not just an application check).

## 7. Functional Requirements

### 7.1 Platform Admin Dashboard
- Tenant counts by status (`ACTIVE`/`SUSPENDED`/`DISABLED`), total/active users, recent tenant registrations (last N days), recent integration failures (from `integration_operation` where `status='FAILED'` or `'UNKNOWN'`), recent administrative actions (last N platform audit events).
- Explicitly excludes any tenant financial figure (no aggregate revenue, no GST totals) — operational metrics only, per §5's own instruction.

### 7.2 Tenant Directory
- Paginated list: business name, GSTIN, owner name/email, status, created date, last activity (derived from `auth_session.last_seen_at` or equivalent — see §16 for the exact column to add if missing), entitlement summary (count of enabled modules).
- Filters: business name (ILIKE), GSTIN (exact), tenant ID (exact), owner (ILIKE on the owner user's name/email), status.
- Server-side pagination, capped page size (mirrors the `page_size <= 100/200` cap convention already used by every list endpoint in this codebase since PROMPT-007).

### 7.3 Tenant Detail (Platform Admin view)
- Organization details (business name, address, GSTIN, state, financial year start month), status + status history (last N transitions), owner identity, user count by role, entitlement summary, integration configuration status (provider environment, `einvoice_enabled`/`eway_bill_enabled` — never the encrypted credential itself), recent tenant-scoped audit events (last N, read-only).
- **Never** displays: password hashes, JWT secrets, `credentials_encrypted` blob contents, any individual transaction line.

### 7.4 Tenant Settings (Tenant Owner-facing, new)
- A new, minimal "Tenant Settings" screen (distinct from the existing "View Company" screen — see §28A for why these should probably be merged, flagged as an open decision) showing: business name, GSTIN, address, financial year start month, current tenant status (with a visible banner if `SUSPENDED`), enabled feature modules (read-only list — Owner sees what's enabled, cannot change it themselves per §13/§2 principle 6&7 unless a future decision changes this).
- GSTIN/financial-year-start-month are **Platform-Admin-only to change** in this spec's recommendation (changing either retroactively affects every historical GST filing and accounting period-label — too high-risk for tenant self-service in M1; flagged in OD table for confirmation).

### 7.5 Tenant Status Management
- Platform Admin action: `PATCH /platform-admin/tenants/{id}/status` with `{new_status, reason}`.
- Enforces the state machine in §9.
- Every transition writes a status-history row (new `tenant_status_history` table, §16) AND a `TENANT_SUSPENDED`/`TENANT_ACTIVATED`/`TENANT_DISABLED` audit event.

### 7.6 Support Access
- See §10 (dedicated workflow section) — full request/grant/use/expire/audit lifecycle.

### 7.7 Feature/Module Entitlements
- Platform Admin action: `PUT /platform-admin/tenants/{id}/entitlements` with the full desired set of enabled modules.
- New `feature_entitlement` table (tenant_id, module_code, is_enabled) — see §16.
- Enforced as `require_permission(...) AND require_entitlement(module_code)` — a NEW, second FastAPI dependency, composed alongside (never replacing) the existing `require_permission`.

### 7.8 Global Configuration
- New `platform_configuration` table: `key` (unique), `value` (JSONB), `description`, versioned via `row_version` + an append-only `platform_configuration_history` table (mirrors the `tenant_status_history` pattern).
- Examples from §14: supported document-type list, GST integration provider selection, system limits (e.g., max page size), feature flags.
- **Never** used to silently alter a historical transaction — see §15 precedence rule.

### 7.9 Integration Monitoring
- `GET /platform-admin/integrations/health` — aggregates `integration_operation` (PROMPT-018) across all tenants: status, tenant, integration type (`EINVOICE`/`EWAY_BILL`), error category, timestamp, retry count, correlation ID. **Reuses the existing table verbatim** — no new table (§23's own "do not introduce duplicate tables" instruction honored).

### 7.10 Sync Monitoring
- **See §28A — this requirement conflicts with PROMPT-028's approved architecture and cannot be implemented as literally specified without either a scope change to PROMPT-028 or an explicit, documented scope reduction here.** A best-effort MVP resolution is proposed in §28A.

### 7.11 Audit Log Monitoring
- `GET /platform-admin/audit-logs` — cross-tenant read over `audit_log`, filterable by tenant/actor/action/date range, paginated. Requires `audit_log.tenant_id` to become nullable (§16) so PLATFORM-level events (which have no single tenant subject, e.g. "global config changed") can be recorded at all.

### 7.12 System Health
- `GET /platform-admin/system-health` — DB connectivity check (`SELECT 1`), recent 5xx error rate (derived from existing correlation-ID-tagged structured logs, PROMPT-001), recent integration failure count. MVP-minimal per §21's own explicit restraint instruction.

## 8. Business Rules

1. `tenant_id` is server-derived from the authenticated session for every tenant-scoped call — NEVER from the request body/path for authorization purposes (the path `{tenantId}` in Platform Admin routes is the TARGET of an explicitly-authorized cross-tenant action, not a trust boundary bypass — see §19).
2. A Platform Administrator's own JWT/session NEVER carries a `tenant_id` claim in the sense the existing `AuthenticatedContext.tenant_id` does — accessing a specific tenant's data is always an explicit, audited, per-request action, never an ambient session attribute (this is what prevents "become an unrestricted business user of every tenant," §1 principle 4).
3. Posted financial/GST/payroll records remain reachable ONLY through their existing business-workflow endpoints (cancel/reverse/credit-note/debit-note) — no Platform Admin endpoint in this spec ever accepts a financial document ID for direct mutation.
4. Suspending or disabling a tenant NEVER deletes data (§7, hard requirement — enforced by construction: the status-change endpoint only ever writes to `tenant.status`, never issues a DELETE).
5. Feature entitlement is checked in ADDITION to permission — both must pass (§13's own `USER ACCESS = ... + Module Entitlement + ...` formula, implemented as two independent, both-required FastAPI dependencies).
6. Global configuration changes are versioned; a historical transaction/report reads its OWN posting-time snapshot, never a live join to current global config (§15 precedence rule, mirrors the exact "GST snapshot never recalculates" discipline PROMPT-026 already established one layer down).
7. Support access defaults to READ-ONLY; elevated (write) access requires a SEPARATE, explicitly time-bound grant (§9 principle 9/10).
8. Audit logs are immutable — no platform or tenant role can update/delete an audit_log row (already enforced today by the existing DB trigger, PROMPT-001/012 — this prompt extends the SAME table/trigger, inheriting the guarantee for free).

## 9. Tenant Lifecycle State Machine

```
                 ┌───────────┐
     ┌──────────▶│  ACTIVE   │◀──────────┐
     │           └─────┬─────┘           │
     │                 │                 │
     │        suspend  │                 │ reactivate
     │                 ▼                 │
     │           ┌───────────┐           │
     └───────────┤ SUSPENDED ├───────────┘
      reactivate  └─────┬─────┘
                        │ disable
                        ▼
                  ┌───────────┐
                  │ DISABLED  │
                  └─────┬─────┘
                        │
                        │  reactivate — OPEN DECISION, see OD #3
                        ▼
                  (ACTIVE, if OD #3 resolved "yes")
```

Allowed transitions (source prompt §31, explicitly NOT silently decided):
- `ACTIVE → SUSPENDED` ✅
- `ACTIVE → DISABLED` ✅
- `SUSPENDED → ACTIVE` ✅ (reactivate)
- `SUSPENDED → DISABLED` ✅
- `DISABLED → ACTIVE` ❓ **Open Decision #3** — recommended: **allowed**, but ONLY by a Super Admin tier (not a regular Platform Support admin), since a disabled tenant likely represents a more serious situation (e.g., contractual termination) than a suspension.
- Any other transition (e.g., `ACTIVE → ACTIVE`, same-state) → rejected with `INVALID_STATUS_TRANSITION`.

### Exact behavior per state (§7, resolved — not left ambiguous)

| Capability | ACTIVE | SUSPENDED | DISABLED |
|---|---|---|---|
| User sign-in (`POST /auth/login`) | ✅ | ✅ (succeeds — see rationale below) | ❌ (`TENANT_DISABLED`, 403) |
| Read-only data access (GET endpoints) | ✅ | ✅ | ❌ |
| New transaction creation (POST/PATCH/PUT on business data) | ✅ | ❌ (`TENANT_SUSPENDED`, 403) | ❌ (`TENANT_DISABLED`, 403) |
| Offline sync (client replaying queued creates, PROMPT-028) | ✅ | ❌ — the replayed `POST` hits the same guard as any other write, surfaces as `REQUIRES_ACTION` in the Sync Center (no special-casing needed in `pwa/syncEngine.ts`, since `classifySyncFailure` already maps a 403 to `AUTHORIZATION`/`REQUIRES_ACTION`) | ❌ (same mechanism) |
| Scheduled/background operations (none exist yet in this codebase — see CLAUDE.md's own "no background-worker technology exists" note, PROMPT-018) | N/A | N/A | N/A |
| Reports (read-only) | ✅ | ✅ | ❌ |

**Rationale for SUSPENDED allowing login + read**: a suspended tenant (e.g., for a billing issue) should be able to see their own data and understand WHY they're suspended (the UI shows a persistent banner) rather than being locked out entirely — this matches common SaaS practice and avoids the harsher, data-inaccessible experience of DISABLED. This is the specification's RECOMMENDATION — see OD table item 1/2 for why it is still marked open rather than assumed.

**Enforcement point**: `app/core/deps.py::get_current_user` — after resolving `AuthenticatedContext`, look up `tenant.status`; if `DISABLED`, raise `AuthenticationError`/403 immediately (blocks everything, including read). If `SUSPENDED`, attach `context.tenant_status = "SUSPENDED"` and let each WRITE endpoint's own permission-check layer additionally reject via a new `require_active_tenant()` dependency composed only onto mutating routes (GET routes stay unaffected). This is a **single, centralized change point** — confirmed by reading the actual `get_current_user` implementation (§1), not assumed.

## 10. Support Access Workflow

```
Platform Admin
     │  1. Request support access
     │     { tenant_id, reason, requested_duration_minutes, access_level: READ_ONLY | ELEVATED }
     ▼
support_access_session (status=PENDING or ACTIVE — see OD #4 re: approval)
     │  2a. (if approval required, OD #4) Senior Admin approves/rejects
     │  2b. (if no approval required) session activates immediately, READ_ONLY only without approval;
     │      ELEVATED always requires explicit senior approval regardless of OD #4's answer for READ_ONLY
     ▼
ACTIVE support session (start_time set, expires_at = start_time + duration, capped — see OD #7)
     │  3. Every subsequent Platform-Admin API call against this tenant_id
     │     carries the session_id; middleware validates it's ACTIVE + unexpired
     │     + matches the target tenant before allowing ANY tenant-scoped read
     │     (and, if ELEVATED, write within the still-forbidden-for-financial-data
     │     boundary of §25).
     │  4. UI shows a persistent "SUPPORT ACCESS — READ ONLY" or
     │     "SUPPORT ACCESS — ELEVATED" banner (§28) for the WHOLE duration.
     ▼
Session ends: (a) admin explicitly ends it, (b) expires_at reached, (c) senior admin revokes it
     │  5. status → ENDED/EXPIRED/REVOKED, end_time recorded
     ▼
SUPPORT_ACCESS_ENDED audit event, listing every resource touched during the session
     (derived from audit_log rows carrying this session_id in a new
     `support_access_session_id` column added to audit_log — §16)
```

**Key constraints** (directly answering §9's 10 numbered requirements):
1. Explicit authorization — session row must exist and be ACTIVE.
2. Attributable — `platform_admin_id` on the session row.
3. Reason captured — `reason` column, NOT NULL.
4. Start time captured — `start_time`.
5. End time captured — `end_time` (nullable until ended).
6. Every accessed/modified resource audited — every audit event written while a session is active carries `support_access_session_id`.
7. Limited to the requested tenant — middleware rejects any tenant_id other than `session.tenant_id`.
8. Limited to required permissions — `access_level` (`READ_ONLY`/`ELEVATED`) gates which operations are even attempted; ELEVATED still never bypasses §25's financial-data-immutability rule.
9. Financial/GST modification prohibited even under ELEVATED — enforced by the SAME rule as §25 (no endpoint exists to do it, regardless of access level — this is an architectural absence, not a runtime check that could have a bug).
10. No hidden impersonation — the UI banner (§28) is ALWAYS shown; there is no "silent" mode.

## 11. Tenant Administration Workflow

Unchanged from PROMPT-005/006 for the actual user/role/permission CRUD (Owner creates a user → assigns a role → the existing `/users`/`/roles`/`/permissions` endpoints handle everything). The ONLY new tenant-facing workflow is:

```
Tenant Owner logs in
     │
     ▼
Tenant Settings screen (NEW, §7.4)
     │  shows: business profile (some fields read-only), current status,
     │  enabled modules (read-only), financial year
     ▼
If SUSPENDED: persistent banner "Your account is suspended. Contact support." + all
     write actions across the ENTIRE app return TENANT_SUSPENDED (handled generically
     by the frontend's existing ApiError-driven toast mechanism — no per-screen change needed)
```

## 12. Platform Administration Workflow

```
Platform Admin logs in (dedicated login route, §17)
     │
     ▼
Platform Admin Dashboard (§7.1)
     │
     ├──▶ Tenant Directory → Tenant Detail → [Change Status | Request Support Access | View Entitlements]
     ├──▶ Feature Entitlements → per-tenant module toggle
     ├──▶ Global Configuration → key/value editor with version history
     ├──▶ Integration Monitoring → cross-tenant integration_operation view
     ├──▶ Sync Monitoring → best-effort view, see §28A
     ├──▶ Audit Logs → cross-tenant audit_log view
     └──▶ System Health → DB/API status
```

## 13. UI Screen Inventory

**New Platform Admin screens** (a new top-level area, NOT nested under the existing tenant `Sidebar.tsx` — a Platform Admin never sees the tenant business sidebar at all, since they're not logged into a tenant):
1. Platform Admin Login (separate route, e.g. `/platform-admin/login`)
2. Platform Admin Dashboard
3. Tenant Directory (list + search/filter)
4. Tenant Detail (tabs: Overview / Status History / Entitlements / Integration / Audit)
5. Support Access Request/Active-Session panel (likely a modal + persistent banner component, reusable across every Tenant Detail sub-view)
6. Feature Entitlements editor
7. Global Configuration editor (+ version history view)
8. Integration Monitoring (cross-tenant table)
9. Sync Monitoring (cross-tenant table — scope per §28A)
10. Audit Log viewer (cross-tenant, paginated, filterable)
11. System Health panel

**New tenant-facing screen:**
12. Tenant Settings (§7.4) — reachable from the existing tenant Sidebar, likely merged into the existing "View Company" screen (see §28A recommendation) rather than built as a wholly separate one.

**Modified existing screens:**
- `Header.tsx`/global app shell — a persistent "SUSPENDED" banner when `tenant.status !== 'ACTIVE'` (mirrors the existing `ConnectivityBadge` pattern from PROMPT-028 — a small, always-visible status indicator, not a blocking modal).
- Global API-error handling (already centralized in `api/client.ts`'s `ApiError`) — add `TENANT_SUSPENDED`/`TENANT_DISABLED` to the existing toast-driven error display, no new plumbing needed.

## 14. Responsive UX Requirements

Every new screen follows the EXACT Tailwind responsive pattern already established and proven across `AccountingManagement.tsx`/`GstManagement.tsx`/`ReportsManagement.tsx`/`PayrollManagement.tsx` (PROMPT-025/026/027/029) — table on desktop (`hidden md:block`), stacked cards on mobile (`md:hidden`), sticky filter/tab header, `overflow-x-auto` scoped to the table container only (never the page body), pagination controls sized for touch targets. No new responsive pattern needs to be invented; this is a direct reuse of proven, already-tested UI conventions from this same codebase.

## 15. API Contract

All new platform routes live under `/api/v1/platform-admin/*`; the one new tenant route lives under `/api/v1/tenant/*` (both namespaces match the source prompt's own §22 suggestion exactly).

| Method | Path | Auth | Authorization | Idempotency | Audit event |
|---|---|---|---|---|---|
| POST | `/platform-admin/auth/login` | Platform admin credentials | N/A (this IS the auth boundary) | N/A | `PLATFORM_ADMIN_LOGIN` |
| GET | `/platform-admin/dashboard` | Platform admin session | `platform.view_dashboard` | N/A | none (read) |
| GET | `/platform-admin/tenants` | Platform admin session | `platform.view_tenants` | N/A | none (read) |
| GET | `/platform-admin/tenants/{tenantId}` | Platform admin session | `platform.view_tenants` | N/A | none (read), UNLESS an active support-access session exists for this tenant, in which case every read is still logged against that session per §10 |
| PATCH | `/platform-admin/tenants/{tenantId}/status` | Platform admin session | `platform.manage_tenant_status` | `Idempotency-Key` required (mirrors every state-changing endpoint in this codebase since PROMPT-002) | `TENANT_SUSPENDED`/`TENANT_ACTIVATED`/`TENANT_DISABLED` |
| POST | `/platform-admin/tenants/{tenantId}/support-access` | Platform admin session | `platform.request_support_access` | `Idempotency-Key` required | `SUPPORT_ACCESS_STARTED` |
| POST | `/platform-admin/support-access/{sessionId}/end` | Platform admin session | owner of the session, or `platform.approve_support_access` for a senior override | N/A | `SUPPORT_ACCESS_ENDED` |
| GET | `/platform-admin/users` | Platform admin session | `platform.manage_platform_users` | N/A | none (read) |
| PUT | `/platform-admin/tenants/{tenantId}/entitlements` | Platform admin session | `platform.manage_entitlements` | `Idempotency-Key` recommended | `FEATURE_ENABLED`/`FEATURE_DISABLED` per changed module |
| GET | `/platform-admin/configuration` | Platform admin session | `platform.view_dashboard` (read tier) | N/A | none (read) |
| PUT | `/platform-admin/configuration/{key}` | Platform admin session | `platform.manage_global_config` | row_version (`If-Match`, mirrors every optimistic-concurrency endpoint in this codebase) | `CONFIG_CHANGED` |
| GET | `/platform-admin/integrations/health` | Platform admin session | `platform.view_integration_health` | N/A | none (read) |
| GET | `/platform-admin/sync/health` | Platform admin session | `platform.view_integration_health` | N/A | none (read) — scope per §28A |
| GET | `/platform-admin/audit-logs` | Platform admin session | `platform.view_audit_logs` | N/A | none (read) |
| GET | `/platform-admin/system-health` | Platform admin session | `platform.view_dashboard` | N/A | none (read) |
| GET | `/tenant/settings` | Existing tenant session | any authenticated tenant user (read own tenant only) | N/A | none (read) |
| PATCH | `/tenant/settings` | Existing tenant session | new `tenant.manage_settings` permission (Owner only by default) — only for the fields NOT reserved to Platform Admin (§7.4) | row_version | `TENANT_SETTINGS_UPDATED` |

All request/response schemas follow the existing `{"data": ..., "meta": {...}}` / `{"data": [...], "pagination": {...}, "meta": {...}}` envelope conventions (`app/schemas/envelopes.py`), unchanged.

**Error codes** (new prefix `PADM-`, following the codebase's established `PREFIX-NNN` convention — confirmed no existing prefix collision):

| Code | Meaning |
|---|---|
| `PADM-001` | `TENANT_NOT_FOUND` |
| `PADM-002` | `TENANT_ACCESS_DENIED` |
| `PADM-003` | `TENANT_SUSPENDED` |
| `PADM-004` | `TENANT_DISABLED` |
| `PADM-005` | `INSUFFICIENT_PERMISSION` (platform-side; distinct from the existing tenant-side `AUTH-*`/`USR-*` codes) |
| `PADM-006` | `FEATURE_NOT_ENABLED` |
| `PADM-007` | `SUPPORT_ACCESS_NOT_AUTHORIZED` |
| `PADM-008` | `SUPPORT_ACCESS_EXPIRED` |
| `PADM-009` | `INVALID_CONFIGURATION` |
| `PADM-010` | `CONFIGURATION_CONFLICT` (row_version mismatch) |
| `PADM-011` | `CROSS_TENANT_ACCESS_DENIED` |
| `PADM-012` | `INVALID_STATUS_TRANSITION` |
| `PADM-013` | `INTEGRATION_UNAVAILABLE` |

## 16. Database Impact

Per the prompt's own §23 instruction ("inspect the existing ERD/data dictionary; reuse existing structures; document any required schema extension"), here is the FULL reuse-vs-new analysis:

**Reused verbatim (no change):**
- `tenant` (the `status` column already exists — this prompt is the first to actually READ it).
- `integration_configuration`/`integration_operation` (PROMPT-018) — Integration Monitoring reads these directly.
- `audit_log`'s existing append-only trigger mechanism (PROMPT-001/012) — extended, not replaced (see below).

**Requires a schema extension (documented, not silent):**
- **`audit_log.tenant_id` must become NULLABLE.** Currently `NOT NULL` (confirmed by reading `app/models/audit_log.py`). A platform-level event with no single tenant subject (e.g., `CONFIG_CHANGED` on a global setting) cannot be recorded in the current schema at all. Add a nullable `actor_platform_admin_id` column (FK to the new `platform_admin_user` table) alongside the existing nullable `actor_user_id`, and a CHECK constraint that exactly one of `actor_user_id`/`actor_platform_admin_id` is set. Also add nullable `support_access_session_id` (FK) for §10's own requirement.
- **`tenant.status` needs no schema change** — column exists; only a CHECK constraint addition (`status IN ('ACTIVE','SUSPENDED','DISABLED')`) if one doesn't already exist (verify at implementation time — not confirmed by this research pass).

**New tables required** (none of these have an existing equivalent — confirmed against the full current schema):
1. `platform_admin_user` — id, email, password_hash, tier (`PLATFORM_SUPPORT`/`PLATFORM_SUPER_ADMIN`), is_active, created_at, row_version. **Deliberately NOT a row in the existing `user` table** — see §17 for the full rationale (the existing `user.tenant_id` is `NOT NULL`, structurally incompatible with a cross-tenant identity).
2. `platform_admin_session` — mirrors the existing `auth_session` table's own shape (jti, platform_admin_id, expires_at, revoked_at) — a parallel, separate session table, not a reuse of `auth_session` (which FKs to tenant-scoped `user.id`).
3. `tenant_status_history` — id, tenant_id, previous_status, new_status, changed_by_platform_admin_id, reason, changed_at.
4. `support_access_session` — id, platform_admin_id, tenant_id, access_level, reason, requested_duration_minutes, status (`PENDING`/`ACTIVE`/`ENDED`/`EXPIRED`/`REVOKED`), approved_by_platform_admin_id (nullable), start_time, expires_at, end_time, row_version.
5. `feature_entitlement` — id, tenant_id, module_code, is_enabled, updated_by_platform_admin_id, row_version. Unique `(tenant_id, module_code)`.
6. `platform_configuration` — id, key (unique), value (JSONB), description, row_version.
7. `platform_configuration_history` — id, platform_configuration_id, previous_value, new_value, changed_by_platform_admin_id, changed_at (append-only, mirrors `audit_log`'s own trigger-enforced immutability pattern).

**RLS note**: none of the 7 new tables above are tenant-owned in the usual sense (`platform_admin_user`/`_session`/`platform_configuration`/`_history` have no `tenant_id` at all; `tenant_status_history`/`support_access_session`/`feature_entitlement` DO carry `tenant_id` but are only ever written by a Platform Admin, whose session carries no tenant RLS context at all). **RLS as currently implemented (`current_setting('app.tenant_id')`) does not apply to Platform Admin sessions** — this is a deliberate, necessary architectural difference from every tenant-scoped table in this codebase, and the PRIMARY reason tenant isolation for Platform Admin actions must be enforced at the APPLICATION layer (explicit `tenant_id` path parameter + audit, never ambient session state) rather than the database layer. This must be called out prominently to implementers so nobody assumes RLS "automatically" protects these flows the way it does everywhere else.

## 17. Authorization Model

**Why Platform Administrator is a SEPARATE identity, not a Role row (a genuine architectural decision, justified by the actual current schema, not asserted):**

- `role.tenant_id` is `NOT NULL` (confirmed, §1). A role that isn't owned by any one tenant literally cannot be expressed in the current `role`/`role_permission`/`user_role` tables without either (a) relaxing that constraint platform-wide (high blast radius, touches every tenant-scoped permission check in the codebase) or (b) picking one arbitrary tenant to "own" the Platform Administrator role (violates tenant isolation conceptually even if technically possible).
- `user.tenant_id` is similarly `NOT NULL` (confirmed via the existing `User` model's established shape, consistent with every tenant-scoped table in this codebase).
- Therefore: **a new, parallel identity/session stack** (`platform_admin_user` + `platform_admin_session`, §16) is the only option consistent with "do not introduce duplicate tables" (§23) while ALSO satisfying "Platform Administrator must not become an unrestricted business user of every tenant" (§1 principle 4) — the separation is enforced by the TYPE SYSTEM itself (a `PlatformAdminContext` dataclass, structurally distinct from the existing `AuthenticatedContext`), not merely by a permission check that could have a bug.

**Effective access formula** (§13, implemented literally):
```
Tenant user's effective access =
    Authentication (existing JWT/session, PROMPT-003)
  + Tenant Membership (existing tenant_id claim)
  + Permission (existing require_permission(), PROMPT-006)
  + Module Entitlement (NEW require_entitlement(), this prompt)
  + Resource Authorization (existing per-service tenant_id filter on every query)

Platform Admin's effective access to a specific tenant's data =
    Platform Authentication (NEW platform_admin_session)
  + Platform Permission (NEW require_platform_permission())
  + Explicit target tenant_id (path parameter, never ambient)
  + (for anything beyond directory-level metadata) an ACTIVE support_access_session
    scoped to that exact tenant_id
```

**Critical rule enforcement (§24)**: "A Platform Administrator must NOT be able to bypass tenant isolation simply by changing tenant_id in an API request." Because a Platform Admin's session carries NO tenant_id claim at all (unlike a tenant user, where `tenant_id` comes from the JWT and is layered into RLS), every platform-admin endpoint that touches a specific tenant's data MUST explicitly validate that tenant exists AND (for anything beyond the read-only directory/detail views) that an ACTIVE, unexpired `support_access_session` naming that exact `tenant_id` belongs to the requesting admin. This is a request-time authorization check, structurally identical in spirit to the "cross-tenant lookup returns the same 404 as not-found" pattern already used everywhere else in this codebase (PROMPT-007 onward) — reused, not reinvented.

## 18. Audit Model

Extends the existing, proven `AuditService.record()` mechanism (PROMPT-001) — NOT a new audit pipeline. Two call sites:
1. **Tenant-scoped platform actions** (status change, entitlement change, support access against a specific tenant) — `AuditService.record(tenant_id=<target tenant>, actor_user_id=None, ...)` with the NEW `actor_platform_admin_id` populated instead (§16 schema extension).
2. **Platform-only actions with no tenant subject** (global config change, platform admin user created) — `AuditService.record(tenant_id=None, ...)` — requires the §16 nullable-`tenant_id` extension.

New audit actions (exact strings, matching the source prompt's §20 list verbatim): `TENANT_CREATED` (already fires today via `AuditService` at sign-up, PROMPT-002 — reused), `TENANT_SUSPENDED`, `TENANT_ACTIVATED`, `TENANT_DISABLED`, `USER_CREATED`/`USER_DEACTIVATED`/`ROLE_CHANGED`/`PERMISSION_CHANGED` (already fire today for tenant-side actions — reused, unchanged), `FEATURE_ENABLED`, `FEATURE_DISABLED`, `CONFIG_CHANGED`, `SUPPORT_ACCESS_STARTED`, `SUPPORT_ACCESS_ENDED`, `INTEGRATION_CONFIG_CHANGED`.

Immutability is INHERITED for free — the existing `trg_audit_log_immutable` BEFORE UPDATE/DELETE trigger (migration 0012) applies to every row in `audit_log` regardless of which actor type wrote it.

## 19. Security Model

- **IDOR prevention**: every `{tenantId}` path parameter is validated to exist server-side before any further processing; a nonexistent tenant returns `PADM-001` (404-equivalent), never a stack trace or a different error shape that would let an attacker distinguish "tenant exists but I lack access" from "tenant doesn't exist" (mirrors the exact anti-enumeration discipline PROMPT-004 established for password reset).
- **Tenant A cannot access Tenant B via the EXISTING tenant-scoped API** — unaffected by this prompt; RLS + the existing `AuthenticatedContext.tenant_id` derivation from the verified JWT (never the request) continues to guarantee this exactly as it has since PROMPT-003.
- **Platform Admin session security**: same JWT/httpOnly-cookie transport pattern as tenant sessions (PROMPT-003's own architecture decision, reused) — a SEPARATE cookie name (e.g., `platform_admin_session`) so a browser with both a tenant session and a platform-admin session open in different tabs never confuses the two.
- **Secrets**: `integration_configuration.credentials_encrypted` (PROMPT-018) is NEVER returned by any Platform Admin API response — the Integration Monitoring view shows status/metadata only, exactly as PROMPT-018 already established for the tenant-facing side.
- **MFA**: flagged, not built (OD item 12).

## 20. Integration Monitoring

See §7.9/§16 — a read-only aggregation over the existing `integration_operation` table, grouped/filterable by tenant, integration type, status, and date range. No new table.

## 21. Sync Monitoring

**See §28A immediately below — this is where the specification's honesty requirement (flag conflicts, don't silently resolve them) is most load-bearing.**

## 22. Error Handling

See §15's error code table. All errors follow the existing `ApiErrorEnvelope`/`ApiErrorBody` shape (`app/schemas/envelopes.py`, unchanged) — `{code, message, details}`. Never includes a stack trace, secret, or internal path (existing global exception handler behavior, PROMPT-001, reused verbatim).

## 23. Concurrency / Idempotency

- Tenant status change: `Idempotency-Key` header required (mirrors every state-changing tenant-business endpoint since PROMPT-002's own `IdempotencyService`) — two admins racing to suspend the same tenant twice with the same key get the same recorded result, not a duplicate audit event.
- Global configuration update: `row_version` optimistic concurrency (`If-Match` header), mirroring every other row_version-protected update in this codebase since PROMPT-001's own `RowVersionMixin`/`check_row_version()` helper.
- Feature entitlement update: transactional (all module toggles in one request commit atomically — §32's own "no partial entitlement updates" requirement), `row_version` protected.
- Support access grant: unique constraint preventing two simultaneously-ACTIVE sessions for the same `(platform_admin_id, tenant_id)` pair (avoids a confusing double-audit-trail for the same investigation).

## 24. QA Test Cases

Mapped 1:1 to the source prompt's §33 letter list (A–AA); each becomes a concrete `pytest` integration test in a future `test_platform_admin.py`, following this codebase's own established test-file conventions (helper functions for signup/login, `_idem()`, `_reset_state_between_tests` fixture — see any existing `test_*.py` for the exact pattern to replicate):

A. Platform Admin login succeeds with valid credentials, fails with invalid ones (rate-limited, mirrors existing `login_lockout` reuse).
B. Tenant directory returns paginated results.
C. Tenant search by business name/GSTIN/status filters correctly.
D. `ACTIVE → SUSPENDED` succeeds, writes `tenant_status_history` + audit event.
E. `DISABLED → SUSPENDED` is rejected with `PADM-012`.
F. Tenant detail shows expected fields, excludes secrets.
G. Platform Admin without an active support-access session cannot fetch a tenant's business transaction data (only directory-level metadata).
H. Existing Tenant Owner user-management flow (PROMPT-005/006) is completely unaffected — regression test.
I. Owner assigns a permission to a Manager — unaffected, regression test.
J. Platform Admin attempting a tenant-business-data write (e.g., posting a Sales Invoice) is rejected — no such endpoint exists for them to call in the first place (a structural test: assert the platform-admin router has zero routes touching `sales_invoice`/`journal_entry`/etc.).
K. Toggling a feature entitlement off blocks the corresponding tenant endpoint with `PADM-006`, even for a user who otherwise has full permission.
L. Global config change is versioned; old value recoverable from history.
M. Tenant settings update (the one tenant-editable field set) persists correctly.
N. Two concurrent global-config updates — second one with stale `row_version` gets `PADM-010`.
O. Support access grant → admin can then read the target tenant's directory-level detail; a DIFFERENT admin without a session cannot.
P. Support access past `expires_at` is rejected with `PADM-008`.
Q. Every action during an active support session carries the `support_access_session_id` in its audit row.
R. Integration Monitoring shows a seeded `FAILED` `integration_operation` row correctly.
S. Sync Monitoring — scope per §28A's resolution.
T. Audit log viewer returns tenant-scoped and platform-only events correctly filtered.
U. Attempting to UPDATE/DELETE an `audit_log` row via raw SQL as the app's own DB role still fails (regression test, already covered since PROMPT-012 — re-run, not re-written).
V. No endpoint exists to directly edit a posted Sales Invoice/journal/payslip from the platform-admin router (structural test, same technique as J).
W. Every platform-admin endpoint rejects a request with no/invalid platform-admin session.
X. A crafted request with a `tenantId` the admin has no support-access session for is rejected (`PADM-002`/`PADM-011`), even though the tenant exists.
Y/Z/AA. Mobile/Tablet/Desktop layout smoke tests (structural class-presence assertions, consistent with how this codebase has tested responsive layout in prior prompts — full browser-rendering verification is explicitly out of the automated suite per this codebase's own established, repeatedly-documented limitation).

## 25. Security Test Cases

Mapped 1:1 to the source prompt's §34 numbered list:
1. Tenant A's existing tenant-scoped session calling any `/platform-admin/*` route → 403 (no platform permission exists on a tenant JWT — structurally impossible to pass `require_platform_permission()`).
2. Tenant A Owner calling `/tenant/settings` for Tenant B — impossible, since `tenant_id` is derived from their OWN session, never a path parameter, for that specific endpoint (by design, §15's contract table).
3. Platform Admin attempting to call any endpoint that would mutate a posted financial/GST/payroll record — no such endpoint exists (structural, see QA test J/V).
4. Platform Admin crafting a request with a manipulated `tenant_id` — rejected per §19/§17 (no ambient tenant context to manipulate; explicit path tenant_id validated against an active support-access session for anything beyond directory metadata).
5. Tenant Owner attempting to create a "Platform Administrator" role via the existing `/roles`/`/users` endpoints — impossible, since `platform_admin_user` is a structurally separate table the tenant-side API has no code path to write to.
6. An EXPIRED support session's subsequent API calls — rejected `PADM-008` (test P, re-verified here as a security case).
7. A Platform Admin without `platform.request_support_access` attempting to start a session — 403.
8. Direct API access to a platform-admin write endpoint without ever having used the UI — succeeds/fails purely on the same server-side checks (proves authorization is never UI-only, consistent with this codebase's own "backend authorization is always authoritative" principle, CLAUDE.md §3).
9. A manipulated `tenant_id` in a PATCH body for an endpoint whose real target tenant comes from the PATH — the body value is ignored/validated-but-not-trusted (mirrors the existing "tenant_id never from body" rule enforced everywhere else in this codebase since PROMPT-001).
10. Attempting to UPDATE/DELETE an audit_log row directly (regression of the existing PROMPT-012 guarantee).
11. Calling a tenant-business endpoint for a module that's been disabled via entitlement, using a user who otherwise has full permission — `PADM-006`.
12. Any endpoint against a DISABLED tenant — 403 at the authentication layer itself (§9 table).
13. Any WRITE endpoint against a SUSPENDED tenant — 403 (§9 table); reads still succeed.
14. Any Platform Admin API response is inspected for `credentials_encrypted`/password hash/session secret leakage — asserted absent.

## 26. Acceptance Criteria

Directly traceable to the source prompt's §35 numbered list (1-20) — each AC maps to one or more QA/Security test cases above (§24/§25) and one or more Functional Requirements (§7). No AC is left without a corresponding test case in this specification.

## 27. Dependencies

- PROMPT-001 (audit_log, correlation IDs, exception hierarchy) — extended, not replaced.
- PROMPT-002/003 (tenant/user/session model, `IdempotencyService`) — reused for the tenant-status/entitlement/config endpoints' idempotency.
- PROMPT-005/006 (existing user/role/permission model) — the Tenant Administration baseline this prompt does NOT rebuild.
- PROMPT-018 (`integration_configuration`/`integration_operation`) — reused verbatim for Integration Monitoring.
- PROMPT-025 (Chart-of-Accounts-style "lazy per-tenant default seed" pattern) — reused as the STYLE reference for how `feature_entitlement` could seed sensible defaults per newly-created tenant (implementation detail, not a hard dependency).
- PROMPT-028 (offline sync architecture) — **the Sync Monitoring requirement (§21 above) depends on this and currently conflicts with it — see §28A.**

## 28. Open Decisions

Directly answering the source prompt's own §36 list (1-20), each with Question / Why it matters / Recommended option / Alternative / Impact / Decision owner:

| # | Question | Why it matters | Recommended | Alternative | Impact | Owner |
|---|---|---|---|---|---|---|
| 1 | Exact SUSPENDED behavior (login+read allowed? per §9 table) | Determines UX harshness and support-ticket volume | Login+read allowed, all writes blocked (as specified in §9) | Login blocked entirely (harsher) | Affects `deps.py` enforcement scope | Product Owner |
| 2 | Exact DISABLED behavior | Same as above, more severe | Everything blocked including login/read (§9 table) | Read-only forever (archival access) | Affects data-retention UX | Product Owner |
| 3 | Is `DISABLED → ACTIVE` allowed? | Determines if disabling is "soft" or "terminal" | Allowed, Super Admin tier only | Not allowed — disabling is permanent, requires a NEW tenant | Affects state machine + UI | Product Owner |
| 4 | Does support access require tenant-owner approval? | Balances support speed vs. tenant trust/consent | No approval required for READ_ONLY; senior-admin (not tenant) approval for ELEVATED | Tenant-owner approval required for any support access (higher trust, slower support) | Major UX/workflow impact | Product + Security |
| 5 | Is true impersonation required (acting AS a tenant user in their own UI)? | The source prompt explicitly discourages unrestricted impersonation | NOT implemented in M1 — support access is API/data-inspection only, never "log in as" | Implement a clearly-banner-labeled impersonation mode later if support volume demands it | Significant scope/security impact if "yes" | Product + Security |
| 6 | Must support access be visible to tenant users (not just the admin)? | Transparency vs. support friction | Not visible to tenant users in M1 (only audited) | Show a "Support is currently assisting your account" banner tenant-side | Trust/transparency tradeoff | Product Owner |
| 7 | Maximum support-access duration | Bounds the blast radius of a compromised/mistaken grant | 4 hours default, 24-hour hard cap | 30 minutes default (tighter) | Affects `support_access_session.expires_at` default/cap | Security |
| 8 | Can ELEVATED support access modify ANY tenant master data (not just view)? | Determines how "elevated" elevated really is | Elevated may modify NON-financial master data only (e.g., fix a typo'd customer address) — financial/GST/payroll remain forever off-limits per §25 | Elevated is read-only too; a THIRD tier would be needed for any write at all | Defines the ceiling of admin capability | Product + Security |
| 9 | Exact global master/reference data Platform Admin manages | Scope of `platform_configuration` | Document type list, GST provider selection, system limits, feature flags (§14's own examples) — nothing tenant-business-specific | Broader — could include a shared HSN/tax-rate reference master later | Schema/UI scope | Product Owner |
| 10 | Exact feature entitlement model (per-module boolean vs. tiered plans) | Determines `feature_entitlement` schema complexity | Simple per-module boolean (§7.7) — matches MVP's "one tenant, no subscription tiers yet" reality | Tiered plans with bundled module sets (adds a `plan` concept) | Schema complexity | Product Owner |
| 11 | Is subscription/billing entitlement part of MVP? | Determines if entitlement ties to a billing system | No — `feature_entitlement` is admin-toggled only, no billing integration in M1 | Yes — entitlement driven by a Stripe/billing webhook | Major scope addition if "yes" | Product Owner |
| 12 | Is MFA required for Platform Admin? | Platform Admin is the highest-privilege identity in the system | Strongly recommended but marked OPEN — not built without a follow-up prompt/decision | Deferred to a later security-hardening prompt | Security posture | Security |
| 13 | Exact platform health metrics | Scope of §7.12 | DB connectivity + recent 5xx rate + integration failure count (MVP-minimal, per §21's own restraint instruction) | Broader (queue depth, latency percentiles) — needs real infra to back it | Engineering effort | Engineering Lead |
| 14 | Branding/customization scope | Whether Platform Admin UI needs white-labeling | None in M1 — internal tool only | Tenant-facing branding customization (unrelated, would be a different prompt) | None if "none" | Product Owner |
| 15 | Tenant deletion/data-retention policy | Legal/compliance requirement, currently undefined anywhere in this codebase | Not implemented in M1 — DISABLED is the closest state, data retained indefinitely | Define a retention period + hard-delete job | Legal/compliance risk if undefined long-term | Legal + Product |
| 16 | Data export capability for disabled tenants | Fairness/compliance concern for an offboarded tenant | Not implemented in M1 | Add a CSV/JSON export endpoint scoped to DISABLED tenants only | Support burden if manual | Product Owner |
| 17 | Audit-log retention period | Storage growth + compliance | No change from the existing (undefined/indefinite) retention — flagged, not decided here | Define an explicit N-year retention + archive job | Storage cost over time | Product + Engineering |
| 18 | Can Platform Admin create tenant users directly? | Support convenience vs. tenant autonomy | No — Platform Admin can only view; user creation remains a Tenant Owner action (support can guide, not do it for them, except possibly under ELEVATED per OD #8) | Yes, under ELEVATED access only | Blast radius of elevated access | Product + Security |
| 19 | Can a Tenant Owner create multiple Managers? | Already effectively YES today (no limit exists in the current `users.create` flow, PROMPT-005) | No change — already unrestricted, confirm as expected behavior | Cap the number of Managers per tenant | None (already the status quo) | Product Owner (confirm only) |
| 20 | Do configuration changes require an approval workflow? | Consistency with support-access approval (OD #4) | No approval workflow for global config in M1 — single Super Admin action, versioned/audited | Add a two-person-review requirement for config changes | Workflow complexity | Product Owner |

### 28A. Requirement Conflicts (explicitly flagged, per the source prompt's own closing instruction — NOT silently resolved)

**Conflict 1 — Sync Monitoring (§19 of the source prompt) vs. PROMPT-028's approved offline-sync architecture.**
The source prompt's §19 assumes the SERVER can see "failed sync transactions, retry count, conflict state, last sync timestamp, client transaction ID, server transaction ID, error reason" as queryable state. **PROMPT-028's own approved architecture (confirmed: no `sync_queue`/`sync_log`-equivalent table exists anywhere in `app/models/`) deliberately keeps the entire sync queue and its state machine CLIENT-SIDE, in the browser's IndexedDB** — the server only ever sees ordinary, already-idempotent `POST /customers`/`POST /suppliers`/`POST /sales/invoices` requests, indistinguishable from a normal online request except by the presence of an `Idempotency-Key` header (which online requests ALSO send for financial creates, per PROMPT-015's own pre-existing requirement). **The server therefore has NO visibility into "this request was a retried offline sync," conflict state, or client-side retry counts — that information physically does not leave the device unless the device chooses to report it.**
- **Recommended resolution**: implement Sync Monitoring as a MUCH narrower proxy metric — surface `IdempotencyKey` replay counts (a request hitting the SAME idempotency key more than once IS server-visible, via the existing `idempotency_key` table) as a rough "possible retry/conflict" signal, clearly labeled as an approximation, NOT a faithful reconstruction of the client's own Sync Center state. A full solution would require PROMPT-028's architecture to change (e.g., an optional, privacy-conscious client-to-server sync-telemetry beacon) — **that is a scope change to an ALREADY-APPROVED prior prompt and must not be silently decided here.**
- **Decision owner**: Product Owner + the engineer who owns PROMPT-028, jointly — this is exactly the kind of cross-prompt conflict the source prompt's own closing paragraph anticipates.

**Conflict 2 — "Tenant Settings" (§7.4, new) vs. the existing "View Company" screen.**
`components/ViewCompany.tsx` already exists (PROMPT-002/003 era) and likely already shows a subset of the same organization/business data this prompt's §7.4 wants to add status/entitlement info to. Building a wholly separate "Tenant Settings" screen risks duplicating UI for the same underlying data.
- **Recommended resolution**: EXTEND `ViewCompany.tsx` with the new status banner + entitlement summary rather than building a parallel screen — but this requires reading `ViewCompany.tsx`'s actual current content at implementation time to confirm it's a safe merge (not done in this research pass, since it's a UI-detail decision appropriately deferred to implementation).
- **Decision owner**: Engineering Lead, at implementation time.

**Conflict 3 — `role.tenant_id`/`user.tenant_id`/`audit_log.tenant_id` NOT NULL constraints vs. a cross-tenant Platform Administrator identity.**
Already resolved as a RECOMMENDATION in §17/§16 (separate `platform_admin_user`/`platform_admin_session` tables, `audit_log.tenant_id` made nullable) rather than left open — but flagged here explicitly because it IS a schema change to tables that predate this prompt, and the prompt's own §23 says to "document any required schema extension" rather than treat it as a given. **This is the single highest-impact schema change in this specification and should be explicitly signed off before implementation begins**, since `audit_log` is read/written by every module in the entire codebase.

## 29. Risks

- **Schema change to `audit_log`** (nullable `tenant_id`) touches the single most widely-depended-on table in the codebase — requires careful migration (every existing `AuditService.record()` call site must continue working unchanged, since `tenant_id` stays required for all of them; only the NEW platform-only call sites use the nullable path).
- **A second, parallel identity/session stack** (`platform_admin_user`/`_session`) is more implementation effort than reusing the existing `user`/`auth_session` tables would have been — but the alternative (relaxing `NOT NULL` on `user.tenant_id`) is a far higher-risk change to the tenant-isolation guarantee this entire codebase depends on. This tradeoff is deliberate and should not be second-guessed without re-deriving the same conclusion in §17.
- **Sync Monitoring cannot be built as literally specified** without either a scope reduction (accepted here, §28A Conflict 1) or a cross-prompt architecture change to PROMPT-028 — if the business insists on the full literal requirement, PROMPT-028 itself needs revisiting, which is a materially larger effort than this prompt alone.
- **Support access is a high-trust, high-blast-radius feature** — the OD table (items 4/6/7/8) leaves several of its exact boundaries open; implementing before those are answered risks building the wrong trust model.

## 30. Definition of Done (for THIS specification deliverable)

- [x] All 30 sections requested by the source prompt's §37 are present.
- [x] Every recommendation is grounded in the ACTUAL current codebase (models/services read directly, not assumed) — confirmed via direct file inspection of `tenant.py`, `role.py`, `audit_log.py`, `deps.py`, `integration_configuration.py`/`integration_operation.py`, and `CLAUDE.md`'s own carried-forward open decisions.
- [x] Every open decision from the source prompt's §36 is answered with Question/Why/Recommended/Alternative/Impact/Owner, none silently resolved as code.
- [x] Two genuine requirement conflicts with prior-approved prompts (PROMPT-028's offline architecture; the existing `ViewCompany.tsx` screen) are explicitly flagged under §28A rather than silently decided.
- [x] A concrete, implementation-ready API contract, database impact analysis, and RBAC/audit/security model are provided — sufficient for a development team to begin implementation without further business clarification, per the source prompt's own closing requirement.
- [ ] **Not done, and not in scope for this deliverable**: actual code implementation. Per the source prompt's own framing ("Generate the complete development specification and implementation plan," §37's "Produce the implementation specification," and the explicit absence of the "implement the approved solution" / "STOP — do not move to PROMPT-031" instructions every PRIOR prompt in this sequence carried), this document is the planning artifact for a FUTURE implementation pass, not a request to write code in this turn.
