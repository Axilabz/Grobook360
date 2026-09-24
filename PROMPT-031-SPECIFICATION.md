# PROMPT-031 — Audit Trail & Compliance Specification

**Document type:** Development specification & implementation plan (per §34 — this is a planning/design deliverable, mirroring PROMPT-030's own framing: no "implement the approved solution" instruction and no "STOP before PROMPT-032" code directive appear anywhere in the source prompt; its own §35 Definition of Done is written in spec-readiness terms — "architecture is defined," "taxonomy is defined," "API contracts are documented" — not "tests pass"). **No application code was written for this deliverable.**

**Baseline used:** the actual current codebase after PROMPT-001–030 (PROMPT-030 itself was also a specification, no code landed from it). Every claim below was verified by direct inspection of `app/models/audit_log.py`, `app/services/audit/audit_service.py`, `app/core/correlation.py`, `app/logging/config.py`, `app/models/idempotency_key.py`, `app/models/payment.py`, `app/services/user_management/user_service.py`, `app/core/permissions.py`, `app/core/error_codes.py`, and the 62 existing `AuditService.record(...)` call sites across the codebase — not assumed or invented.

---

## 1. Requirement Understanding

PROMPT-031 asks for a **centralized** audit trail and compliance framework spanning every module built so far (PROMPT-001–030). The critical grounding fact, confirmed by reading the code rather than assumed: **this codebase already has a centralized audit mechanism, not a fragmented one.** `AuditService.record()` (`app/services/audit/audit_service.py`, built in PROMPT-001) is already the *sole* writer to the *one* `audit_log` table, called from 62 distinct sites across every business module (Sales, Purchase, Payments, Accounting, GST, Payroll, User Management, E-Invoice/E-Way Bill). There is no per-module duplicate logging mechanism to consolidate — §2 principle "the audit system must be centralized rather than each module implementing unrelated audit mechanisms" is **already satisfied by the existing architecture** and must be preserved, not replaced.

What PROMPT-031 genuinely adds, confirmed by gap analysis against the real schema and code:
1. **Schema extension** — `audit_log` currently has `tenant_id, actor_user_id, action, entity_type, entity_id, before_json, after_json, occurred_at, ip_address, device_info, correlation_id`. It is **missing** `actor_type`, `event_category`, `result`, `source`, `request_id`, `client_transaction_id`, `reason`, `metadata` — all required by §4's Audit Event Model.
2. **A formal, enumerated action taxonomy** — 62 call sites already use a consistent `<ENTITY>_<PAST_TENSE_VERB>` naming convention (e.g. `SALES_INVOICE_POSTED`, `PAYROLL_FINALIZED`), but it exists only implicitly as scattered string literals, not as a single controlled list a frontend/API layer can validate against (§6's "do not allow arbitrary free-text action names from frontend clients").
3. **A general-purpose, centralized query API** (`GET /api/v1/audit-events`) — today, audit READS exist only as four narrow, per-document-type endpoints (`GET /purchase/orders/{id}/audit-history` and its Goods Receipt/Purchase Invoice/Purchase Return siblings, PROMPT-020/021/022/023). No cross-entity, cross-module, filterable audit search exists anywhere (§14).
4. **Platform-level / Security / Support-Access audit categories** — these depend on constructs specified in PROMPT-030 (`platform_admin_user`, `support_access_session`) that do not exist in code yet; PROMPT-031 must define how audit accommodates them without assuming they're already built.
5. **A documented redaction/snapshot policy** — before/after snapshots are today built ad hoc, by hand, per call site (e.g. `user_service.py`'s `before = {"name": ..., "email": ..., "role": ...}`) — always an *allowlist* of named fields, never a blind `record.__dict__` dump. This is actually the right pattern (§9/§13's "never log secrets") but has never been written down as a rule, so nothing stops a future call site from doing it wrong.

## 2. Objective

Formalize, extend, and centralize the audit trail already embedded in this codebase's architecture into a single, queryable, compliance-grade framework — without duplicating the working `AuditService`/`audit_log` mechanism, and without breaking any of its 62 existing call sites.

## 3. Scope

- Extending `audit_log`'s schema (additive columns only) and `AuditService.record()`'s signature (additive, backward-compatible parameters).
- A formal, centralized action-name and event-category taxonomy (`app/core/audit_taxonomy.py`), covering both the ~90 action strings already in use and the new ones §6/§7 of the source prompt name that don't exist yet (`ROLE_CHANGED`, `PERMISSION_CHANGED`, `CONFIG_CHANGED`, `SUPPORT_ACCESS_STARTED/ENDED`, `AUDIT_LOG_EXPORTED`, etc.).
- A new centralized read API (`GET /api/v1/audit-events`, `GET /api/v1/audit-events/{id}`) with tenant-isolated, permission-gated, filtered, paginated access — while keeping the 4 existing narrow per-document endpoints working (as thin wrappers, §10 below).
- New `audit.view`/`audit.export` tenant permissions; alignment with PROMPT-030's `platform.view_audit_logs`/`platform.security_audit_view` for platform-level visibility.
- Offline-sync audit reconstruction (reusing `idempotency_key.idempotency_key` as the `client_transaction_id`, §8/§13 below — no new per-table column).
- Support-access audit hooks that plug into PROMPT-030's `support_access_session` design once that module is built.
- Redaction/snapshot policy, retention policy, export capability, and the full UI/API/security specification.

## 4. Out of Scope

- Rewriting or relaxing PROMPT-001/012's existing immutability trigger (`trg_audit_log_immutable`) — it already satisfies §11 completely; reused verbatim.
- A distributed tracing system (spans, trace propagation across services) — this MVP is a single FastAPI monolith; `correlation_id` already does the job §17 asks for. No OpenTelemetry/Jaeger-style infrastructure is introduced.
- Retroactively renaming any of the 62 existing action strings — they stay exactly as they are; the taxonomy formalizes them, it does not rename them (a rename would be a destructive historical-data change with no compliance benefit).
- A background-job-based async audit pipeline — no background-worker technology exists anywhere in this codebase (confirmed, carried forward from PROMPT-018/028's own identical finding); §24's "asynchronous mechanism […] for non-critical operational telemetry" is therefore explicitly NOT built in M1 (see §25/Requirement Conflicts).
- WORM (Write-Once-Read-Many) storage, log shipping to an external SIEM, or any production infrastructure change — flagged as Open Decision #15, not built.
- Actual implementation of PROMPT-030's Platform Administration module (`platform_admin_user`, `support_access_session`) — this spec only defines how audit *would* integrate with it once built.

## 5. Audit Principles

The source prompt's 15 principles (§2) are adopted verbatim, cross-referenced against what already holds true today:

| # | Principle | Current status |
|---|---|---|
| 1 | Append-only | **Already true** — `trg_audit_log_immutable` (migration 0012) |
| 2 | Normal users can't modify | **Already true** — no UPDATE endpoint exists on `audit_log` anywhere |
| 3 | No silent deletion | **Already true** — same trigger blocks DELETE too |
| 4 | Tenant-owned where applicable | **True today** (`tenant_id NOT NULL`) — must become nullable for platform events (schema extension, shared with PROMPT-030 §16) |
| 5 | Platform vs tenant events distinguishable | **New** — via `actor_type` + nullable `tenant_id` |
| 6 | Financial history traceable | **Mostly true** (see §11 Financial Audit Rules) |
| 7 | Administrative actions traceable | **Partially true** — `USER_CREATED`/`USER_UPDATED`/`USER_ACTIVATED`/`USER_DEACTIVATED` exist; `ROLE_CHANGED`/`PERMISSION_CHANGED` as *distinct* actions do not (see §9 Action Model gap below) |
| 8 | Security events traceable | **Partially true** — `LOGIN_SUCCESS`/`LOGIN_FAILED`/`AUTH_PASSWORD_RESET_*` exist; `LOGOUT`, session expiry, and unauthorized-access-attempt events do not |
| 9 | Offline transactions retain client_transaction_id | **New** — resolved via `idempotency_key.idempotency_key` reuse, §13 |
| 10 | UTC timestamps | **Already true** — `TIMESTAMPTZ` + `utcnow()` everywhere in this codebase |
| 11 | Server-generated timestamps authoritative | **Already true** — `occurred_at` is always `utcnow()`, never client-supplied |
| 12 | Never a tenant-isolation bypass mechanism | **Already true structurally** — `AuditService.record()` takes `tenant_id` as an explicit parameter, always server-derived from `AuthenticatedContext`, never from a request body |
| 13 | No secrets stored | **Already true by convention** (allowlist snapshot-building, §15) — never formally documented until now |
| 14 | No passwords/tokens/keys | Same as #13 |
| 15 | No material performance degradation | **Already true** — audit writes are `session.flush()` inside the SAME DB transaction as the business write, adding one INSERT to an already-open transaction, not a separate round-trip |

## 6. Audit Event Taxonomy (Event Categories, §3 of the source prompt)

The 19 categories (A–S) map directly onto this codebase's own module boundaries:

| Category | Existing module(s) | Status |
|---|---|---|
| A. AUTHENTICATION | `app/api/v1/auth.py` (PROMPT-003/004) | Partial coverage today |
| B. AUTHORIZATION | `app/core/deps.py`'s `require_permission()` | **Gap** — a 403 today raises `AuthorizationError` but writes NO audit event (see Requirement Conflict #3) |
| C. USER MANAGEMENT | `app/services/user_management/` (PROMPT-005/006) | Covered, taxonomy gap on ROLE_CHANGED |
| D. TENANT ADMINISTRATION | Does not exist yet — PROMPT-030's own scope | Defined here for when it lands |
| E. CONFIGURATION | Does not exist yet — PROMPT-030's `platform_configuration`/tenant settings | Defined here for when it lands |
| F. MASTER DATA | Customer/Supplier/Product (PROMPT-007/008/009) | Covered |
| G. SALES | PROMPT-011–017 | Covered, the deepest existing taxonomy |
| H. PURCHASE | PROMPT-019–023 | Covered |
| I. INVENTORY | PROMPT-010 (`stock_ledger_entry`) | **Gap** — stock movements are recorded in `stock_ledger_entry` itself (an append-only ledger) but NOT mirrored into `audit_log` as a `STOCK_MOVEMENT_CREATED` event (see Requirement Conflict #2) |
| J. PAYMENTS | PROMPT-024 | Covered |
| K. ACCOUNTING | PROMPT-025 | Covered |
| L. GST | PROMPT-026 | Covered |
| M. E-INVOICE | PROMPT-018 | Covered |
| N. E-WAY BILL | PROMPT-018 | Covered |
| O. PAYROLL | PROMPT-029 | Covered |
| P. OFFLINE SYNC | PROMPT-028 | **Gap** — client-side only today; §8/§13 below define server-side reconstruction |
| Q. PLATFORM ADMINISTRATION | PROMPT-030 (spec only) | Defined here for when it lands |
| R. SUPPORT ACCESS | PROMPT-030 (spec only) | Defined here for when it lands |
| S. SYSTEM / INTEGRATION | `integration_operation` (PROMPT-018) | Partially covered — `integration_operation` already tracks E-Invoice/E-Way Bill call attempts; not yet mirrored into `audit_log` |

`event_category` is stored as a new `String(30)` column on `audit_log`, always server-set from a fixed enum (`app/core/audit_taxonomy.py::EventCategory`), never client-supplied.

## 7. Actor Model

```python
class ActorType(str, Enum):
    TENANT_USER = "TENANT_USER"        # existing: actor_user_id set, tenant_id set
    PLATFORM_ADMIN = "PLATFORM_ADMIN"  # PROMPT-030: actor_platform_admin_id set, tenant_id often set (target)
    SUPPORT_ADMIN = "SUPPORT_ADMIN"    # PROMPT-030: platform admin acting under an active support_access_session
    SYSTEM = "SYSTEM"                  # server-internal, e.g. lazy seeding (ensure_default_location, COA seed)
    BACKGROUND_JOB = "BACKGROUND_JOB"  # reserved — no background-job infra exists yet (§4 Out of Scope)
    INTEGRATION = "INTEGRATION"        # e-Invoice/e-Way Bill provider callbacks, GST integration events
```

**Support-access actor resolution (§5 of the source prompt — "do not record only the impersonated user"):** when an action occurs during an active `support_access_session` (PROMPT-030), the audit event records THREE identities, not one:
- `actor_platform_admin_id` — the real actor (a new nullable column, alongside the existing `actor_user_id`)
- `tenant_id` — the target tenant whose data was touched
- `support_access_session_id` — a new nullable FK column, making the "effective user context" (§5) reconstructable by joining back to the session row, which itself records `access_level`/`reason`/`expires_at`

`actor_type` is set to `SUPPORT_ADMIN` (not `PLATFORM_ADMIN`) specifically for actions taken during such a session — this distinction is what lets a query separate "an admin looked at the tenant directory" from "an admin touched a specific tenant's data under an authorized, time-bound, audited grant."

## 8. Action Model

### 8.1 Formalizing what already exists

`app/core/audit_taxonomy.py` (new file) becomes the single source of truth, built by literally enumerating the 62 existing call sites' action strings (verified via `grep -rhoE 'action="[A-Z_]+"' app/services app/api`) — no action is renamed. Organized as:

```python
class AuditAction(str, Enum):
    # Generic (existing, used directly for simple CRUD where no domain-specific name exists)
    CREATE = "CREATE"
    # ... UPDATE, DELETE, POST, CANCEL, VOID, REVERSE, APPROVE, REJECT, SUBMIT,
    #     SYNC, RETRY, LOGIN_SUCCESS, LOGIN_FAILED, EXPORT ...

    # Domain-specific (existing, verbatim — a representative slice)
    SALES_INVOICE_CREATED = "SALES_INVOICE_CREATED"
    SALES_INVOICE_POSTED = "SALES_INVOICE_POSTED"
    SALES_INVOICE_CANCELLED = "SALES_INVOICE_CANCELLED"
    PAYMENT_CREATED = "PAYMENT_CREATED"
    PAYMENT_POSTED = "PAYMENT_POSTED"
    JOURNAL_REVERSED = "JOURNAL_REVERSED"
    EINVOICE_GENERATION_REQUESTED = "EINVOICE_GENERATION_REQUESTED"
    PAYROLL_FINALIZED = "PAYROLL_FINALIZED"
    # ... all ~90 existing strings, one per line, grouped by module ...

    # NEW — genuine gaps identified by this spec (§9 below)
    ROLE_CHANGED = "ROLE_CHANGED"
    PERMISSION_CHANGED = "PERMISSION_CHANGED"
    CONFIG_CHANGED = "CONFIG_CHANGED"
    STATUS_CHANGED = "STATUS_CHANGED"          # generic fallback for TENANT_STATUS_CHANGED-style events
    UNAUTHORIZED_ACCESS_ATTEMPT = "UNAUTHORIZED_ACCESS_ATTEMPT"
    LOGOUT = "LOGOUT"
    SESSION_EXPIRED = "SESSION_EXPIRED"
    STOCK_MOVEMENT_CREATED = "STOCK_MOVEMENT_CREATED"
    AUDIT_LOG_EXPORTED = "AUDIT_LOG_EXPORTED"
    # PROMPT-030-dependent (defined now, wired when that module is built)
    TENANT_CREATED = "TENANT_CREATED"          # already fires today via AuditService at sign-up — reused
    TENANT_STATUS_CHANGED = "TENANT_STATUS_CHANGED"
    FEATURE_ENABLED = "FEATURE_ENABLED"
    FEATURE_DISABLED = "FEATURE_DISABLED"
    SUPPORT_ACCESS_STARTED = "SUPPORT_ACCESS_STARTED"
    SUPPORT_ACCESS_ENDED = "SUPPORT_ACCESS_ENDED"
    PLATFORM_ADMIN_LOGIN = "PLATFORM_ADMIN_LOGIN"
```

### 8.2 Server-side validation, never free text (§6's own requirement)

`GET /api/v1/audit-events?action=...` validates the `action` query parameter against `AuditAction`'s own values (400 `AUDIT-002 INVALID_ACTION_FILTER` if not recognized) — the filter is constrained, not the WRITE path itself (a service can still, in principle, pass any string to `AuditService.record()`, exactly as today; §6's "do not allow arbitrary… action names" is interpreted as a client-facing API constraint, not a rewrite of every one of the 62 internal call sites to import an enum, which would be a large, risk-bearing refactor for zero compliance benefit — flagged as Open Decision #10 below, not silently assumed).

## 9. Audit Event Schema (§4 of the source prompt, mapped onto the real table)

`audit_log` schema extension (new Alembic migration, `0031_audit_taxonomy.py` — first PROMPT-031-owned migration number, since PROMPT-030 produced none):

| New column | Type | Nullable | Purpose |
|---|---|---|---|
| `actor_type` | `String(20)` | NOT NULL, default `'TENANT_USER'` (backfilled for all 62 call sites' historical rows) | §5 Actor Model |
| `actor_platform_admin_id` | `UUID` FK → `platform_admin_user.id` (PROMPT-030, added when that table exists) | NULL | Support/platform actor |
| `support_access_session_id` | `UUID` FK → `support_access_session.id` (PROMPT-030) | NULL | §5/§20 |
| `event_category` | `String(30)` | NOT NULL, backfilled by a one-time data migration mapping each existing `action` prefix to its category (e.g. `SALES_*` → `SALES`, `PAYROLL_*` → `PAYROLL`) | §6 |
| `result` | `String(20)` CHECK IN `('SUCCESS','FAILURE')` | NOT NULL, default `'SUCCESS'` (every existing call site only ever fires on the success path today — confirmed by reading all 62 sites, none are in an `except` block) | §4 |
| `source` | `String(20)` CHECK IN `('WEB','MOBILE_PWA','API','SYSTEM','OFFLINE_SYNC')` | NOT NULL, default `'WEB'` | §4 |
| `request_id` | `UUID` | NULL | See Open Decision #16 (below) — this codebase has never had a concept distinct from `correlation_id`; recommended to leave unused (`NULL`) rather than force a synthetic value |
| `client_transaction_id` | `String(100)` | NULL | §8/§9 — populated by copying `idempotency_key.idempotency_key` at write time for offline-originated creates (no new column needed on `sales_invoice`/`customer`/`supplier`) |
| `reason` | `Text` | NULL | Free text, used for cancellations/reversals/support-access requests where a reason is already collected (e.g. `sales_return.return_reason`, `support_access_session.reason`) |
| `metadata` | `JSONB` | NULL | Catch-all for category-specific structured extras (e.g. `{"provider": "SANDBOX", "irn": "..."}` for E-Invoice events) — **never** a dumping ground for `before`/`after`, which stay their own dedicated columns |

`tenant_id` becomes **nullable** (same change identified independently in PROMPT-030-SPECIFICATION.md §16 — this is now a SHARED schema dependency between the two specs, not a duplicate decision; whichever prompt implements first should own the migration, and the other should reuse it).

`AuditService.record()`'s signature gains matching **optional, keyword-only** parameters with safe defaults (`actor_type: ActorType = ActorType.TENANT_USER`, `result: str = "SUCCESS"`, `source: str = "WEB"`, etc.) — **every one of the 62 existing call sites compiles and behaves identically with zero changes**, the same "additive, zero-call-site-changes" discipline this codebase has used for every prior service extension (PROMPT-025's `AccountingPostingService`, PROMPT-026's `GstReportingService`).

## 10. Module-Level Audit Matrix (§33 of the source prompt)

| # | Module | Critical events (existing action, else *proposed*) | Actor | Entity | Required metadata | Related transaction | Security sensitivity |
|---|---|---|---|---|---|---|---|
| 00 | Platform Foundation | `LOGIN_SUCCESS`/`LOGIN_FAILED`/`AUTH_PASSWORD_RESET_REQUESTED`/`AUTH_PASSWORD_RESET_COMPLETED`, *`LOGOUT`*, *`SESSION_EXPIRED`* | TENANT_USER | `user` | ip_address, device_info | `auth_session` | High |
| 01 | User Management | `USER_CREATED`/`USER_UPDATED`/`USER_ACTIVATED`/`USER_DEACTIVATED`, *`ROLE_CHANGED`* | TENANT_USER (Owner) | `user` | before/after role | `user_role` | High |
| 02 | Customer/Supplier | `CUSTOMER_CREATED`/`_UPDATED`/`_ACTIVATED` (+ Supplier mirror) | TENANT_USER | `customer`/`supplier` | GSTIN change flagged | — | Medium |
| 03 | Product/Inventory | `PRODUCT_CREATED`/`_UPDATED`/`_ACTIVATED`, `OPENING_STOCK_CREATED`, *`STOCK_MOVEMENT_CREATED`* | TENANT_USER | `product`/`stock_ledger_entry` | qty, source_type | linked sales/purchase doc | Medium |
| 04 | Sales/Billing | `ESTIMATE_*`, `SALES_ORDER_*`, `DELIVERY_CHALLAN_*`, `SALES_INVOICE_*`, `SALES_RETURN_*`, `CDN`-prefixed Credit/Debit Note actions | TENANT_USER | each document type | grand_total, gst breakup | accounting_posting_reference, gst_transaction | High (financial) |
| 05 | Purchase | `PURCHASE_ORDER_*`, `GOODS_RECEIPT_*`, `PURCHASE_INVOICE_*`, `PURCHASE_RETURN_*` | TENANT_USER | each document type | same shape as Sales | same shape as Sales | High (financial) |
| 06 | Payments | `PAYMENT_CREATED`/`_POSTED`/`_UPDATED`, `PAYMENT_CHEQUE_STATUS_CHANGED`/`_BOUNCED` | TENANT_USER | `payment` | method, allocations | source invoice(s) | High (financial) |
| 07 | Accounting | `ACCOUNTING_POSTED`, `JOURNAL_REVERSED` | TENANT_USER (system-triggered by a posting document) | `journal_entry` | journal_number, debit=credit check | source document | High (financial) |
| 08 | GST | `GST_TRANSACTION_REVERSED` (+ existing creation is recorded under the SOURCE document's own action, e.g. `SALES_INVOICE_POSTED` — confirmed, `GstReportingService` writes its own `GST_TRANSACTION_CREATED` audit entry scoped to the source entity per the PROMPT-026 fix) | TENANT_USER / SYSTEM | `gst_transaction` | period, sign | source document | High (compliance) |
| 09 | E-Invoice/E-Way Bill | `EINVOICE_GENERATION_REQUESTED`/`_CANCELLATION_REQUESTED`/`_STATUS_RECONCILED` (+ EWB mirror) | TENANT_USER / INTEGRATION | `einvoice`/`eway_bill` | IRN/ack (never provider credentials) | sales_invoice | High (compliance + external) |
| 10 | Payroll | `EMPLOYEE_*`, `SALARY_STRUCTURE_CREATED`, `ATTENDANCE_UPDATED`, `LEAVE_*`, `PAYROLL_RUN_CREATED`/`_CALCULATED`/`_FINALIZED`/`_REVERSED` | TENANT_USER | `employee`/`payroll_run`/`payroll_record` | net_salary (never bank account number) | accounting journal | Very High (PII + financial) |
| 11 | Reports | *(none — deliberately unaudited, PROMPT-027's own explicit decision, reaffirmed here not overridden)* | — | — | — | — | Low (read-only) |
| 12 | PWA/Offline | *`SYNC`* (new, fired server-side on successful replay), existing `*_CREATED` action fires normally once synced | TENANT_USER, `source=OFFLINE_SYNC` | whichever entity synced | client_transaction_id, offline_created_at (client-supplied, informational only — see §13) | — | Medium |
| 13 | Platform Administration | *`TENANT_STATUS_CHANGED`*, *`FEATURE_ENABLED`/`_DISABLED`*, *`CONFIG_CHANGED`*, *`SUPPORT_ACCESS_STARTED`/`_ENDED`* — all defined in PROMPT-030-SPECIFICATION.md §18, reused verbatim here | PLATFORM_ADMIN / SUPPORT_ADMIN | `tenant`/`feature_entitlement`/`platform_configuration` | reason, approver (if any) | — | Very High |

*Italicized* actions are new (don't exist in code today); everything else is a verified, already-firing action string.

## 11. Financial Audit Rules

For Sales Invoice / Purchase Invoice / Payment / Journal / Credit Note / Debit Note / Sales Return / Purchase Return / Payroll posting, the source prompt's own question list is answered by tracing ACTUAL existing code, not asserted:

| Question | Answered by |
|---|---|
| WHO created it? | `audit_log.actor_user_id` on the `*_CREATED` event |
| WHEN created? | `audit_log.occurred_at` on that same event, OR the document's own `created_at` |
| WHO posted it? | `actor_user_id` on the `*_POSTED`/`*_CONFIRMED`/`*_FINALIZED` event — a SEPARATE audit row from creation, since posting is a distinct user action in every document service |
| WHEN posted? | that event's `occurred_at` |
| WHAT source transaction created it? | `entity_id` cross-referenced against the document's own `source_*_id` FK (e.g. `sales_invoice.source_delivery_challan_id`) — already present on every document model |
| WHAT accounting entry was generated? | `document.accounting_posting_reference` (now a real `journal_number`, PROMPT-025) → `GET /accounting/journals?journal_number=...` |
| WAS IT CANCELLED? | a `*_CANCELLED` audit event exists, or absent if never cancelled — status is ALSO independently visible on the document's own `status` column (both agree by construction, since cancellation always flips status AND writes the audit event in the same transaction) |
| WAS IT REVERSED? | `JOURNAL_REVERSED`/`GST_TRANSACTION_REVERSED`/`PAYROLL_REVERSED` events, cross-referenced via `reversal_of_journal_id`/`reversal_of_transaction_id`/`reversal_of_payroll_run_id` — all already exist as real FK columns (PROMPT-025/026/029) |
| WHAT REPLACED/CORRECTED IT? | Sales Return/Credit Note/Debit Note's own `source_invoice_id` — the CORRECTING document points back at what it corrects; there is no forward pointer on the original (by design, since one invoice can have MANY corrections) |

**This means full financial reconstruction is already ~90% possible today via a chain of existing FK lookups** — PROMPT-031's contribution is exposing it through ONE centralized, filterable API (§19) instead of requiring a developer to manually chain 4 different narrow per-document `/audit-history` endpoints plus direct DB queries.

## 12. Security Audit Rules

New events required that do NOT exist today (confirmed by grep — zero hits for `LOGOUT`, `SESSION_EXPIRED`, `UNAUTHORIZED_ACCESS_ATTEMPT` as action strings anywhere):

- `LOGOUT` — wire into `POST /auth/logout` (`app/api/v1/auth.py`), which today revokes the `auth_session` row but writes no audit event at all.
- `SESSION_EXPIRED` — **not** fired synchronously (no background job exists to detect expiry proactively); instead, fired lazily the next time an expired session is presented to `get_current_user()` and rejected — `result=FAILURE`.
- `UNAUTHORIZED_ACCESS_ATTEMPT` — wire into `require_permission()`'s own 403 path (`app/core/deps.py`) — **this is Requirement Conflict #3, see §31 — currently a 403 raises `AuthorizationError` and is returned to the client, but ZERO audit trail is written today.** This is a genuine, previously-unnoticed gap this spec surfaces, not a pre-existing feature being formalized.
- `PASSWORD_CHANGED`/`ROLE_CHANGED`/`PERMISSION_CHANGED`/`CONFIG_CHANGED` — `PASSWORD_CHANGED` already exists as `AUTH_PASSWORD_RESET_COMPLETED`; `ROLE_CHANGED` doesn't exist as a distinct action (see §8/§9 gap); `PERMISSION_CHANGED` cannot fire yet because no permission-EDITING endpoint exists anywhere in this codebase (`/permissions` is read-only per CLAUDE.md §2 PROMPT-006) — defined here for when such an endpoint is ever built, not retrofitted onto nothing.

**Visibility**: security events for a tenant's own users are visible to that tenant's Owner/Manager (gated by a new `audit.view_security` permission, stricter than plain `audit.view` — a Salesperson should not see other users' login-failure history even if `audit.view` were somehow granted). Platform-level security events (failed platform-admin logins, cross-tenant access attempts) are visible ONLY to Platform Admins via `platform.security_audit_view` (PROMPT-030 §6.1, cross-referenced).

## 13. Offline Sync Audit Rules

Grounded in PROMPT-028's actual, verified architecture (no server-side sync-queue table exists — confirmed again in this pass): an offline-originated write reaches the server as an ordinary `POST /customers`/`POST /suppliers`/`POST /sales/invoices` request carrying an `Idempotency-Key` header, which `IdempotencyService` already persists into `idempotency_key.idempotency_key`.

**Resolution**: `client_transaction_id` (the new `audit_log` column, §9) is populated by copying that SAME header value at the moment `AuditService.record()` is called for the resulting `*_CREATED` event — **no new column is added to `sales_invoice`/`customer`/`supplier`**, avoiding a schema change to three already-heavily-tested tables. `source` is set to `'OFFLINE_SYNC'` when the request carries an `X-Offline-Sync: true` header (a new, trivial, additive header PROMPT-028's `pwa/syncEngine.ts` already has full control to set, since it owns every outgoing sync request).

Lifecycle reconstruction (§8's own example diagram) becomes:

```
CLIENT_TRANSACTION_ID (= Idempotency-Key, generated client-side by pwa/offlineDb.ts)
        ↓
LOCAL CREATE          — client-only, IndexedDB, not server-visible (PROMPT-028's own design)
        ↓
SYNC SUBMITTED         — POST arrives at server (visible in access logs / correlation_id, not audit_log — see Requirement Conflict #1)
        ↓
SERVER ACCEPTED         — audit_log row: action=SALES_INVOICE_CREATED, source=OFFLINE_SYNC,
                           client_transaction_id=<the header value>, result=SUCCESS
        ↓
SERVER DOCUMENT NUMBER  — sales_invoice.invoice_number, visible via entity_id join
        ↓
POSTED                  — a LATER, SEPARATE, always-online user action (PROMPT-028 §32/§33's own
                           mandate — POST never happens during sync) → SALES_INVOICE_POSTED event
```

**This is a partial, not complete, reconstruction** — see Requirement Conflict #1 (§31): the "SYNC SUBMITTED" and "retry count"/"conflict status" states described in §8 of the source prompt live entirely client-side in `pwa/offlineDb.ts`'s `sync_queue` IndexedDB store today; the server only ever sees the FINAL successful (or final failed, surfaced as an ordinary 4xx/5xx) attempt. A `FAILURE`-result audit row is written for a rejected sync attempt (reusing the existing exception-handling middleware, extended to call `AuditService.record(result="FAILURE", ...)` on 4xx/5xx for offline-flagged requests specifically — NOT for every failed request generally, which would be excessive volume for zero compliance benefit) — but intermediate client-side retry counts are NOT mirrored server-side, matching the same conclusion PROMPT-030-SPECIFICATION.md §28A Conflict 1 already reached independently for Sync Monitoring.

## 14. Support Access Audit Rules

Fully specified in PROMPT-030-SPECIFICATION.md §10/§18/§20 — reused here verbatim rather than re-derived, since that document already worked out the exact `SUPPORT_ACCESS_STARTED`/`SUPPORT_ACCESS_ENDED` shape, the `support_access_session_id` join, and the three-identity actor model (§7 above). The ONE addition this spec makes: every audit event written *during* an active support session (not just the start/end pair) must carry `support_access_session_id` — already specified in PROMPT-030 §10 point 6, restated here because it's the mechanism that makes §20's "actions performed" list derivable (a `GET /audit-events?support_access_session_id=...` query IS that list — no separate "actions performed" array needs to be stored on the session row itself, avoiding a second source of truth).

## 15. Before/After Snapshot Rules

**Formalizing the existing convention, not inventing a new one.** Confirmed by reading `user_service.py`, `payroll_run_service.py`, and a dozen other call sites: every existing `before`/`after` dict is hand-built as an **explicit allowlist** of named fields (e.g. `{"name": user.name, "email": user.email, "role": current_role}`), never a serialization of the whole ORM row. This is exactly the discipline §9's "DO NOT store sensitive fields" requires, and it already works because a hand-picked dict can never accidentally include `password_hash`.

**New rule, made explicit for the first time**: a shared helper, `app/core/audit_snapshot.py::redact(d: dict) -> dict`, strips any key matching the SAME `_REDACTED_KEYS` set `app/logging/config.py`'s `JsonFormatter` already uses (`password`, `password_hash`, `token`, `access_token`, `secret`, `authorization`) as a **defense-in-depth backstop** — even though the allowlist convention should already prevent this, a second layer costs nothing and catches a future call site that copy-pastes `vars(model)` by mistake. This does not replace the allowlist discipline; it supplements it.

**Large-record policy (§9's "do not blindly duplicate the entire record")**: for multi-line documents (Sales Invoice, Purchase Order, Payroll Run), `before`/`after` capture HEADER-level fields only (status, grand_total, dates) — line-item-level changes are not diffed line-by-line into the snapshot (no existing call site does this, and retrofitting it is out of scope — flagged as Open Decision #4).

## 16. Immutability Rules

**Already fully satisfied, reused verbatim.** `trg_audit_log_immutable` (migration 0012) is a BEFORE UPDATE/DELETE trigger that unconditionally raises — it applies automatically to every new column this spec adds, since it fires on the table, not on specific columns. No new mechanism is needed for §11 of the source prompt. The "corrections must create additional audit events, never rewrite history" example diagram (Invoice Posted → Cancellation → Credit Note → Accounting Reversal) is exactly the existing pattern every document service already follows (verified: `cancel_invoice`/`reverse_payment`/`reverse_journal_for_source` all INSERT new rows, none contain an `UPDATE audit_log` or edit an existing journal/GST-transaction row — PROMPT-025/026's own "never edit the original" discipline, carried forward).

## 17. Retention Rules

No retention/archival/purge mechanism exists anywhere in this codebase today (confirmed — no background-job infrastructure, no cron, no scheduled task runner). **Recommendation for MVP: indefinite retention, no automated purge** (mirrors PROMPT-026 §17's own identical open item for `gst_transaction`, and PROMPT-030-SPECIFICATION.md's OD #17 for the same question one layer up) — see Open Decision #1. Legal hold and WORM-grade storage (§12's own "if applicable") are flagged as Open Decision #15, since no legal/compliance requirement document in `Document/` specifies either.

## 18. Tenant Isolation

Already structurally guaranteed for every EXISTING audit-reading endpoint (the 4 narrow `/audit-history` endpoints each confirm tenant ownership of the parent document FIRST, before returning anything — PROMPT-020's own established discipline, reused by 021/022/023). The NEW centralized `GET /audit-events` endpoint follows the identical rule: `tenant_id` is NEVER accepted as a query parameter for a tenant-scoped caller — it's always the server-derived `AuthenticatedContext.tenant_id`, exactly like every other list endpoint in this codebase since PROMPT-007. Row-Level Security (RLS) already applies to `audit_log` (it's tenant-owned like every other table) — reused, not re-implemented; a platform-admin query (nullable `tenant_id`, no RLS context) is the one deliberate, documented exception, identical to the exception PROMPT-030-SPECIFICATION.md §16 already carved out for its own new platform tables.

## 19. API Specification

| Method | Path | Auth | Permission | Notes |
|---|---|---|---|---|
| GET | `/api/v1/audit-events` | Tenant session | `audit.view` (security-category rows additionally require `audit.view_security`) | Filters: `date_from`, `date_to`, `event_category`, `action`, `actor_user_id`, `entity_type`, `entity_id`, `result`, `source`, `correlation_id`; paginated (`page`, `page_size`, capped at 100 — the existing codebase-wide convention), sorted by `occurred_at DESC` default |
| GET | `/api/v1/audit-events/{auditEventId}` | Tenant session | `audit.view` | Same tenant-ownership-check-first discipline as every other by-ID fetch in this codebase (404 for cross-tenant, never a distinguishable error) |
| GET | `/api/v1/audit-events/export` | Tenant session | `audit.export` | Respects the SAME filters as the list endpoint; itself writes an `AUDIT_LOG_EXPORTED` event (§21) |
| GET | `/api/v1/platform-admin/audit-events` | Platform admin session (PROMPT-030) | `platform.view_audit_logs` | Cross-tenant variant — same filter shape, plus optional `tenant_id` filter (meaningful here since the caller isn't tenant-scoped) |
| ~~POST /api/v1/internal/audit-events~~ | **NOT built** | — | — | The source prompt calls this "optional"; this spec declines it — every existing write path already goes through `AuditService.record()` called from WITHIN the same service method as the business write (§24/§25), so a separate HTTP endpoint for audit creation would be a second, parallel, weaker-guaranteed write path with no current caller that needs it. Revisit only if a genuine external-system-initiated audit need arises. |

Error codes (new prefix `AUDIT-`, following the established `PREFIX-NNN` convention — confirmed no collision against the existing `ACC/AUTH/CDN/CUST/DC/EINV/EST/EWB/GR/GST/INV/PAY/PINV/PO/PRET/PROD/PURCH/PYR/REG/REP/RESET/SALES/SI/SO/SR/SUPP/USR` prefixes):

| Code | Meaning |
|---|---|
| `AUDIT-001` | `AUDIT_EVENT_NOT_FOUND` |
| `AUDIT-002` | `INVALID_ACTION_FILTER` |
| `AUDIT-003` | `INVALID_DATE_RANGE` |
| `AUDIT-004` | `EXPORT_NOT_AUTHORIZED` |
| `AUDIT-005` | `CROSS_TENANT_ACCESS_DENIED` |

## 20. Database Impact

One migration, `0031_audit_taxonomy.py`:
- `ALTER TABLE audit_log ALTER COLUMN tenant_id DROP NOT NULL` (shared decision with PROMPT-030, §9 above).
- Add columns: `actor_type`, `actor_platform_admin_id` (FK, nullable — the referenced table doesn't exist until PROMPT-030 ships; the FK constraint itself is added in THAT migration once the table exists, this migration only adds the plain UUID column, matching the "additive, no forward dependency" discipline used throughout this codebase), `support_access_session_id` (same deferred-FK treatment), `event_category`, `result`, `source`, `request_id`, `client_transaction_id`, `reason`, `metadata`.
- Backfill: `actor_type = 'TENANT_USER'` for all existing rows (every historical row was written by a tenant user or the system on a tenant user's behalf); `result = 'SUCCESS'` for all (verified — no existing call site fires on a failure path); `event_category` backfilled via a `CASE` mapping each `action` value's prefix to its category (fully deterministic, since the existing naming convention already encodes the module).
- New indexes: `event_category`, `result`, `source`, `client_transaction_id`, `support_access_session_id` — added alongside the ALREADY-EXISTING indexes on `tenant_id`, `correlation_id` is NOT currently indexed (confirmed — `correlation_id` has no explicit index in `audit_log.py`); this migration adds one, since §17/§23 of the source prompt explicitly calls out `correlation_id` as a required index and cross-request tracing depends on it.
- **No new table is created** — `audit_event` (the source prompt's own suggested name, §23) is NOT a new table; it is `audit_log`, extended. Naming the API `/audit-events` while the underlying table stays `audit_log` is a deliberate, documented choice (renaming the table would touch 62 call sites' imports for zero behavioral benefit).

## 21. Index Strategy

| Column | Already indexed? | Action |
|---|---|---|
| `tenant_id` | Yes (`index=True` on the column) | Keep |
| `occurred_at` | **No** — confirmed by reading the model, only `tenant_id` has `index=True` | **Add** — every list query sorts/filters by this |
| `actor_user_id` | No | **Add** |
| `entity_type` + `entity_id` | No | **Add** (composite) — the single most common query shape (`/audit-history` per document) |
| `correlation_id` | No | **Add** |
| `action` | No | **Add** |
| `event_category` | New column | **Add** |
| `client_transaction_id` | New column | **Add** (partial index `WHERE client_transaction_id IS NOT NULL` — sparse column) |

## 22. UI Screen Inventory

- **`AuditLogManagement.tsx`** (new, wired into the sidebar under a new "Audit" item, gated by `audit.view`) — list view with the full filter panel (§14 of the source prompt), detail drawer (§15), reusing this codebase's own established `ReportsManagement.tsx`-style tab/filter/table responsive shell rather than inventing a new one.
- **Audit Detail view** — Event ID, Tenant (platform-admin view only), Actor + actor type, Action, Category, Entity (linked, where a detail screen for that entity type exists — e.g. clicking a `sales_invoice` entity_id navigates to `SalesInvoiceManagement`'s own detail modal, reusing existing navigation, not building a new universal entity viewer), Timestamp, Result, Source, Correlation ID, Client Transaction ID, Reason, before/after diff (rendered as a simple two-column key/value table, redacted fields shown as `[REDACTED]` rather than omitted, so the UI honestly signals something was withheld rather than looking incomplete).
- **Existing per-document `/audit-history` sections** (Purchase Order/Goods Receipt/Purchase Invoice/Purchase Return detail modals, PROMPT-020-023) are **kept as-is** — they become thin, unchanged consumers of the same underlying data, now ALSO reachable via the new centralized screen. No existing screen is removed or must be rebuilt.

## 23. Responsive UX

Follows the exact pattern already proven across `AccountingManagement.tsx`/`GstManagement.tsx`/`ReportsManagement.tsx`/`PayrollManagement.tsx` (table on desktop `hidden md:block`, stacked cards on mobile `md:hidden`, sticky filter header, `overflow-x-auto` scoped to the table only) — no new responsive pattern is invented, per this session's own repeatedly-stated discipline.

## 24. Export Specification

- **Format for M1: JSON and CSV only** — mirrors PROMPT-026/027's own identical "JSON first, no PDF/Excel in MVP" precedent (Excel/PDF flagged Open Decision #3, not built).
- Export respects every active filter (§21 of the source prompt) and the caller's own tenant/permission scope — it is literally the list endpoint's query re-executed with an unbounded page size (capped at a hard server-side maximum, e.g. 10,000 rows per export, to bound memory) rather than a separate code path.
- Export itself writes `AUDIT_LOG_EXPORTED` (actor, filter parameters used, row count — never the exported rows themselves duplicated into the event's own `metadata`, which would bloat `audit_log` pointlessly).

## 25. Failure Handling

**Critical financial/administrative audit events are already atomic with their business transaction — verified, not proposed.** Every one of the 62 existing `AuditService.record()` calls sits inside the SAME service method, using the SAME `AsyncSession`, as the business INSERT/UPDATE it documents (e.g. `sales_invoice_service.py::post_invoice` calls `AuditService(self._session).record(...)` before the method returns, all within one FastAPI request's one DB transaction). If the audit INSERT fails (e.g. a constraint violation), the exception propagates, the request handler's transaction rolls back, and the business write is undone too — **§25's own recommended principle ("critical compliance audit = transaction must not silently succeed without required audit") is already true by construction**, not something that needs new code. This spec's only addition: a code-review checklist item (documented here, enforced by convention, not by a runtime check — matching how every other cross-cutting discipline in this codebase, e.g. "always derive tenant_id server-side," is enforced) confirming any FUTURE service method's audit call is not accidentally placed after a `commit()`.

Non-critical/read-only events (report views, audit-log views themselves) are explicitly NOT audited (§26 below) — there is no "async audit pipeline" to fail, since none is built (§4 Out of Scope), so §24's "asynchronous mechanism for non-critical telemetry" question is moot for M1.

## 26. Audit vs. Application Logs

Already cleanly separated in this codebase, confirmed by reading both mechanisms side by side:

| | AUDIT LOG | APPLICATION LOG | METRICS | TRACE |
|---|---|---|---|---|
| Mechanism | `audit_log` table (Postgres, durable, immutable) | `app/logging/config.py`'s `JsonFormatter` (stdout JSON lines) | **Not built** | **Not built** |
| Purpose | Business/security accountability | Technical debugging | — | — |
| Retention | Indefinite (DB) | Ephemeral (stdout, whatever the hosting platform captures) | — | — |
| Redaction | Allowlist snapshot + `redact()` backstop (§15) | `_REDACTED_KEYS` set (already exists) | — | — |

Metrics and distributed tracing infrastructure do not exist anywhere in this codebase (confirmed, carried forward from PROMPT-027's own System Health restraint) — out of scope here too (§4), not silently built under the audit umbrella.

## 27. Security Model

- Every `GET /audit-events*` endpoint requires `require_permission("audit.view")` (or `"platform.view_audit_logs"` for the platform variant) — backend-authoritative, matching this codebase's universal rule (frontend hiding is UX only).
- IDOR prevention on `entity_id` filtering (Security Test Case #12): filtering `GET /audit-events?entity_type=sales_invoice&entity_id=<some other tenant's invoice id>` returns an EMPTY result set for a tenant-scoped caller, not an error and not another tenant's row — the underlying query always ANDs in the caller's own `tenant_id`, so a guessed `entity_id` belonging to another tenant simply matches nothing (same anti-enumeration shape used everywhere else in this codebase).
- SQL injection: all filters go through SQLAlchemy's parameterized query builder (the same pattern every other list endpoint in this codebase already uses) — no raw string interpolation into SQL anywhere in this framework, verified by construction (Security Test Case #15).
- Export data leakage: export inherits the exact same tenant/permission scoping as the list endpoint — no separate, weaker-checked code path (Security Test Case #14).

## 28. QA Test Cases

Directly mapped to the source prompt's §29 numbered list (1–31); each becomes a `pytest` integration test in a future `test_audit_events.py`, following this codebase's own established fixture/helper conventions:

1–7. Audit event created on: creation, posting, cancellation, reversal, config change, role change, permission change — each verified by asserting a new `audit_log` row with the expected `action`/`event_category` appears after calling the corresponding EXISTING service method (most of these are regression confirmations of already-working behavior, not new implementation, per §10's Module Matrix); role/permission change tests are NEW since those actions don't exist yet.
8–9. Support access / offline sync events — depend on PROMPT-030 (support access) and the new `source=OFFLINE_SYNC` header wiring (offline sync) respectively; written against those once built.
10–11. `client_transaction_id`/`correlation_id` present — asserted directly on the new columns.
12–13. Audit record cannot be edited/deleted — **already covered by existing tests** (PROMPT-012's own trigger tests) — re-run, not re-written, confirming the new columns don't weaken the trigger (it fires on the table, unconditionally, regardless of column set).
14. Tenant A cannot see Tenant B's audit logs — new test against the new centralized endpoint, same shape as every other cross-tenant isolation test in this codebase.
15. Unauthorized user cannot access audit API — permission-denial test, standard shape.
16. Sensitive information not logged — a NEW, dedicated test that triggers a password-reset flow and asserts no `audit_log` row's `before_json`/`after_json`/`metadata` contains a password hash substring, anywhere.
17. Export creates an audit event — new test.
18–21. Pagination/filters/sorting/detail view — standard list-endpoint test shape, mirrors every other paginated endpoint's own test suite in this codebase.
22. Before/after values correct — new test per representative module (Sales Invoice price change, User role change).
23. Financial transaction history reconstructable — an END-TO-END test: create → post → cancel → return → credit note, then assert the FULL chain is walkable via `GET /audit-events?entity_type=sales_invoice&entity_id=...` plus the cross-referenced FK chain (§11).
24. Cancel/reversal generates additional events, never edits — regression-style, reusing PROMPT-025/026's own existing reversal tests as the base.
25–26. Support access start/end + expired-session rejection — depend on PROMPT-030.
27–28. API failure behavior / DB rollback — a dedicated test that forces an audit INSERT to fail (e.g. a mocked constraint violation) mid-transaction and asserts the business row is ALSO rolled back (proves §25's atomicity claim, doesn't just assert it).
29–31. Mobile/Tablet/Desktop UI — structural class-presence smoke tests, same limitation this codebase has consistently documented (no full browser-rendering verification in the automated suite).

## 29. Security Test Cases

Mapped to the source prompt's §30 list (1–16), each following the exact technique used in PROMPT-030-SPECIFICATION.md §25 (same numbering discipline, reused rather than reinvented):
1. Cross-tenant audit access — empty result, not an error (§27).
2. Manipulated `tenant_id` — ignored; server-derived only, never accepted from a request body/query param for a tenant-scoped caller.
3. Direct audit API access without a valid session — 401.
4/5. Modification/deletion attempts (even via raw SQL as the app's own DB role) — rejected by the existing trigger, regression-tested.
6. Unauthorized export — 403 without `audit.export`.
7. Sensitive information leakage — QA test #16 doubles as this security test.
8. Password/token logging — same as #7, explicitly scoped to the redaction backstop (§15).
9. Privilege escalation — a Salesperson (no `audit.view`) cannot read another user's audit trail even by guessing an `entity_id`.
10. Support-access abuse — depends on PROMPT-030's session expiry/scope enforcement, cross-referenced.
11. Platform Admin boundary violation — a platform session cannot read a SPECIFIC tenant's audit detail without an active support-access session (PROMPT-030 §17's own rule, reused).
12. IDOR through `entity_id` — QA test #14/security test #1 cover this from two angles (empty result, not an error).
13. Audit pagination data leakage — a capped page size (100 max) prevents a single request from exfiltrating the whole table; still tenant-scoped regardless of page size.
14. Export data leakage — §27.
15. SQL injection through filters — §27.
16. Unauthorized before/after snapshot access — same `audit.view` gate as the rest of the record; no separate, weaker-checked path exists for snapshot fields specifically.

## 30. Acceptance Criteria

Directly traceable to the source prompt's §31 (1–20) — each AC maps to a QA/Security test case above and a section of this spec; no AC is left without a corresponding verification path. Item 20 ("no critical or unresolved major defects") is necessarily deferred to the actual implementation pass, since no code exists yet for this prompt.

## 31. Open Decisions

Directly answering the source prompt's own §32 list (1–15), in the same Question/Why/Recommended/Alternative/Impact/Owner shape used by PROMPT-030-SPECIFICATION.md:

| # | Question | Why it matters | Recommended | Alternative | Impact | Owner |
|---|---|---|---|---|---|---|
| 1 | Exact audit retention period | Compliance/legal exposure vs. storage growth | Indefinite for MVP (no purge mechanism exists to enforce a shorter one anyway) | A fixed N-year retention + archive job once background-job infra exists | None immediate; revisit when storage becomes a real constraint | Legal + Product |
| 2 | Are audit exports in MVP scope? | Determines whether §21/§24 ship now or later | Yes — JSON/CSV only, no new infra required (§24) | Defer entirely to a later prompt | Small, additive if yes | Product Owner |
| 3 | Is PDF export required? | PDF needs a rendering library not currently in this stack | No — not required for MVP | Add if a specific compliance/audit-handoff need arises | New dependency if yes | Product Owner |
| 4 | Exact before/after snapshot policy for large multi-line documents | Line-item-level diffing is a real engineering cost | Header-level only (§15), matches every existing call site | Full line-item diff for financial documents specifically | Moderate engineering cost if full diff required | Product + Engineering |
| 5 | Exact security-event visibility for Tenant Owner | Balances transparency vs. exposing other users' security data broadly | Owner/Manager see their OWN tenant's security events only, gated by `audit.view_security` (stricter than plain `audit.view`) | Owner sees everything including other tenants' events (never — would violate tenant isolation) is not a real alternative; the real alternative is Owner-only (excluding Manager) | Minor RBAC scope decision | Product Owner |
| 6 | Exact Platform Admin audit visibility | Same tradeoff one layer up | Per PROMPT-030-SPECIFICATION.md §6.1/§18 — `platform.view_audit_logs` for cross-tenant read, support-access-scoped for tenant-specific detail | Broader unrestricted platform access | Security posture | Security (shared with PROMPT-030) |
| 7 | Does `audit_log` need DB-level immutability controls beyond the existing trigger? | The trigger already exists and is proven (PROMPT-012) | No — reuse it, sufficient (§16) | A separate WORM-grade storage engine | None if "no"; infra project if "yes" | Security + Engineering |
| 8 | Are audit records archived? | Tied to #1 | Not in MVP — no archival infra exists | Build a cold-storage export job later | None immediate | Engineering Lead |
| 9 | Is tenant deletion ever allowed? | Determines whether `audit_log.tenant_id` FK needs `ON DELETE` behavior considered | No tenant-deletion capability exists anywhere in this codebase (confirmed) — moot for now | If ever built, audit rows for a deleted tenant should be RETAINED (compliance requirement typically outlives the tenant), not cascade-deleted | Would need explicit `ON DELETE RESTRICT` or a soft-delete pattern | Legal + Product |
| 10 | Should the 62 existing action strings be forced through the new `AuditAction` enum at every call site (not just at the read/filter layer)? | A full refactor touches every service file with zero user-visible benefit | No — enum used for taxonomy documentation + read-side filter validation only (§8.2); write-side call sites keep passing plain strings, exactly as today | Full refactor for stricter type safety | Refactor risk/cost vs. marginal benefit | Engineering Lead |
| 11 | Does audit failure block EVERY critical transaction, or only some? | Already answered structurally (§25) — every existing critical call site is same-transaction by construction | Yes for all currently-audited critical actions (financial posting, admin privilege changes) — because it already is, not a new policy choice | Selectively async for specific high-volume, lower-stakes events (e.g. login success) | None if the current shape is kept | Engineering Lead |
| 12 | Exact support-access disclosure policy (should the TENANT see that support accessed their data)? | Same open question raised independently in PROMPT-030-SPECIFICATION.md OD #6 | Not visible to tenant users in M1 (only audited server-side) | Show a "support assisted your account" banner | Trust/transparency tradeoff | Product Owner (shared with PROMPT-030) |
| 13 | Exact `metadata` JSONB retention/size policy | An unbounded JSONB column could grow large per row | Cap `metadata` at a small, documented set of known keys per category (e.g. E-Invoice: `{provider, irn}` only) — never a full response dump | No cap, log whatever is convenient | Storage growth risk if uncapped | Engineering Lead |
| 14 | Is IP/device information stored? | Privacy vs. security-investigation utility | Yes — `ip_address`/`device_info` already exist and are already populated on every login/user-management event; keep as-is, extend to the new categories | Stop collecting it | Minor privacy posture change if "no" | Security + Legal |
| 15 | Does production require WORM/separate-storage architecture? | No such infra exists; a real compliance requirement could mandate it | Not for MVP — the existing DB trigger is the control; flagged for revisit before a real production/compliance audit | Add a dedicated append-only storage tier (e.g. object storage with retention lock) | Infra project, out of MVP budget | Security + Legal + Engineering Leadership |
| 16 | (New, raised by this spec, not in the source list) Is a distinct `request_id` ever needed separate from `correlation_id`? | The source schema (§4) names both; this codebase has only ever needed one | No — leave `request_id` unused/NULL; `correlation_id` already serves this role end-to-end | Add real per-request IDs if a future need for multiple requests under one correlation_id arises (e.g. batch operations) | None now | Engineering Lead |

## 32. Requirement Conflicts

Per the source prompt's own closing instruction — flagged explicitly, not silently resolved:

**Conflict 1 — Offline Sync Audit (§8) assumes server-visible retry-count/conflict-state; PROMPT-028's approved architecture keeps that state 100% client-side.** Identical root cause to the conflict already identified in PROMPT-030-SPECIFICATION.md §28A Conflict 1 (Sync Monitoring) — this is the SAME underlying architectural fact surfacing in a second prompt. **This spec does not re-litigate it**: the resolution is the same narrowed scope (§13 above — server records only the final accepted/rejected state via `client_transaction_id`/`result`, not the full client-side retry timeline). If a future decision changes PROMPT-028's architecture (e.g. adds a server-side sync-telemetry beacon), BOTH this spec's §13 and PROMPT-030's §28A Conflict 1 would need to be revisited together, since they share the same root cause.

**Conflict 2 — Stock Ledger movements (§7 "Inventory" implicitly, via Category I) are not mirrored into `audit_log` today.** `stock_ledger_entry` (PROMPT-010) is ITSELF already an append-only, trigger-free-but-structurally-immutable ledger (no UPDATE/DELETE code path exists, though it lacks `audit_log`'s explicit DB trigger) — it already answers "what stock movements occurred," just not through `audit_log`. Recommendation: add `STOCK_MOVEMENT_CREATED` as a genuinely NEW audit event (§10 Module Matrix, Category I) fired alongside every `InventoryService.post_movement` call, rather than treating `stock_ledger_entry` as a silent second audit mechanism — this directly serves §2 principle "centralized… rather than each module implementing unrelated audit mechanisms," since today Inventory IS such an unrelated mechanism (correct data, wrong system of record for audit purposes). Flagged as new scope, not a defect in PROMPT-010 — that prompt was never asked to write to `audit_log`.

**Conflict 3 — Authorization audit (Category B) does not exist at all today.** `require_permission()`'s 403 path (`app/core/deps.py`) writes NO audit trail currently — this is a genuine, previously-unflagged gap (not carried forward from any prior prompt's own documented Open Decision), surfaced for the first time by this spec's own gap analysis against §3 Category B / §19 Security Auditing. Recommended fix: wire `UNAUTHORIZED_ACCESS_ATTEMPT` into the dependency's exception-raising path — low-risk, additive, touches one file.

## 33. Risks

- **Backfilling `event_category` for ~90 distinct historical action strings** requires a correct, exhaustive `CASE` mapping in the migration — a missed action string would backfill to some default/unknown category, degrading (not breaking) historical searchability. Mitigate by generating the mapping programmatically from the SAME `grep` output this spec's own research pass used, not by hand-transcribing it.
- **`tenant_id` becoming nullable** touches the single most widely-depended-on table in the codebase (61 other call sites besides PROMPT-030's own use) — same risk already flagged in PROMPT-030-SPECIFICATION.md §29, now doubly relevant since BOTH specs need this exact change; whichever implementation lands first should be the one that actually writes this migration, and the second should detect and reuse it rather than writing a conflicting second migration.
- **Wiring `UNAUTHORIZED_ACCESS_ATTEMPT` into `require_permission()`** (Conflict 3) touches the single most frequently-executed dependency in the entire API surface — every protected endpoint calls it. A performance regression here would be felt everywhere; must be verified as truly negligible (one conditional INSERT only on the FAILURE path, never on the success path, so normal-traffic overhead is exactly zero).
- **Centralizing audit reads through one endpoint** creates a single point that must get tenant-isolation exactly right — a single filter-construction bug here has broader blast radius than a bug in one of the 4 existing narrow endpoints, precisely because it's now the ONE place instead of four. Mitigate with the same defense already used everywhere else (server-derived tenant_id, never client-supplied) plus dedicated cross-tenant test coverage before this ships.

## 34. Dependencies

- PROMPT-001 (`audit_log`, `AuditService`, correlation-ID middleware, structured JSON logging) — the foundation this entire spec extends, not replaces.
- PROMPT-002 (`IdempotencyService`/`idempotency_key`) — reused verbatim for `client_transaction_id` (§13).
- PROMPT-006 (RBAC/`require_permission`) — extended with new `audit.*` permissions; also the exact integration point for Conflict 3.
- PROMPT-012 (the immutability trigger) — reused verbatim, unmodified (§16).
- PROMPT-010 (`stock_ledger_entry`) — the subject of Conflict 2.
- PROMPT-018 (`integration_operation`) — a natural future mirror-into-`audit_log` candidate for Category S, not built in this pass (flagged, not silently expanded into scope).
- PROMPT-020/021/022/023 (the 4 existing narrow `/audit-history` endpoints) — kept working unchanged; the new centralized API is additive.
- PROMPT-025/026/029 (Accounting/GST/Payroll reversal patterns) — the exact "new row, never edit the original" discipline this spec's §16 extends to `audit_log` broadly.
- PROMPT-028 (offline sync architecture) — the subject of Conflict 1, shared with PROMPT-030.
- **PROMPT-030-SPECIFICATION.md** — a genuine document-level dependency: this spec explicitly reuses PROMPT-030's `platform_admin_user`/`support_access_session` design (§7/§10/§14), and both specs independently arrived at the identical `audit_log.tenant_id` nullable requirement (§9/§20) — implementation of either should account for the other.

## 35. Definition of Done (for THIS specification deliverable)

- [x] All 33 sections requested by the source prompt's §34 are present.
- [x] Every recommendation is grounded in the ACTUAL current codebase — confirmed via direct inspection of `audit_log.py`, `audit_service.py`, `correlation.py`, `logging/config.py`, `idempotency_key.py`, `payment.py`, `user_service.py`, `permissions.py`, `error_codes.py`, and all 62 existing `AuditService.record()` call sites (via `grep`), not assumed.
- [x] Every open decision from the source prompt's §32 is answered with Question/Why/Recommended/Alternative/Impact/Owner (plus one new item this spec's own gap analysis surfaced), none silently resolved as code.
- [x] Three genuine requirement conflicts are explicitly flagged under §32 rather than silently decided — including one (Conflict 1) that is the SAME underlying architectural fact as an already-documented conflict in PROMPT-030-SPECIFICATION.md, correctly cross-referenced rather than re-derived independently.
- [x] A concrete, implementation-ready API contract, database impact analysis (one migration, fully additive, zero call-site breakage across 62 existing sites), and security/QA test case mapping are provided.
- [ ] **Not done, and not in scope for this deliverable**: actual code implementation (the migration, `AuditService` signature extension, `audit_taxonomy.py`, the new API router, `AuditLogManagement.tsx`). Per the source prompt's own framing ("Generate the complete development specification and implementation plan," §34's "Produce the final implementation specification," and the explicit absence of any "implement the approved solution" / "STOP before PROMPT-032" instruction — the same pattern PROMPT-030 established), this document is the planning artifact for a future implementation pass, not a request to write code in this turn.
