# PROMPT-036 — API Validation, Error Handling & Exception Standard

**Document type:** Development specification & implementation plan (per §51 — same pattern as PROMPT-030–035: no "implement" instruction, no "STOP before PROMPT-037" directive; §52's Definition of Done is spec-readiness framed). **No application code was written for this deliverable.**

**Baseline used:** the actual current codebase after PROMPT-001–035 (030–035 were also spec-only). Verified by direct inspection of `app/core/exceptions.py`, `app/core/error_codes.py`, `app/core/error_handlers.py` (read in the PROMPT-032 research pass, re-confirmed here), `api/client.ts` (frontend `ApiError`), and PROMPT-028/031/032/034-SPECIFICATION.md (cross-referenced for offline-sync retry classification, audit integration, and export error codes rather than re-derived).

---

## 1. Requirement Understanding

PROMPT-036 asks for a standardized API validation/error/exception framework. The grounding pass confirms this codebase ALREADY has a real, working, centralized exception hierarchy (`app/core/exceptions.py`, 9 classes, built in PROMPT-001 and reused by every one of the 30+ modules built since) and a real, consistent per-module error-code registry (`app/core/error_codes.py`, ~24 `PREFIX-NNN` catalogues) — this is NOT a greenfield design problem. The genuine gap this research pass finds is narrower and more precise: **the response envelope itself (`{"error": {"code", "message", "details"}, "meta": {"correlation_id"}}`) is missing three fields the source prompt's own §3 model requires — `category`, `field_errors` (as a distinct array from generic `details`), and `retryable`** — and **one deliberate, already-made HTTP-status decision genuinely diverges from the source prompt's own recommendation**: this codebase uses **412 Precondition Failed** for concurrency conflicts (`ConcurrencyConflictError`, tied to the `If-Match`/`row_version` pattern used everywhere since PROMPT-001), not the 409 the source prompt's §6 suggests — a real, arguable-both-ways divergence that must be flagged, not silently overridden in either direction.

## 2. Objective

Formalize the ALREADY-WORKING exception hierarchy and error-code registry into the source prompt's own richer, more machine-readable envelope (adding `category`/`retryable`/`field_errors`) WITHOUT breaking any of the ~30 modules' existing exception-raising code, and resolve the 409-vs-412 divergence explicitly rather than silently.

## 3. Scope

- Extending `AppError` (and its 9 subclasses) with two new class-level attributes: `category: ErrorCategory` and `retryable: bool` — defaulted per-class so **zero of the ~30 modules' existing `raise SomeError(...)` call sites need to change** (the new fields are inferred from the exception CLASS, not from each individual raise site).
- Extending the error envelope (`error_handlers.py`) to include `category`, `retryable`, and a genuinely NEW `field_errors` array (distinct from the existing generic `details` list) for the ONE case that needs it: Pydantic `RequestValidationError` → per-field error objects (§34).
- A single, explicit resolution of the 409-vs-412 concurrency-status question (§8 below) — not silently changing 8+ years^H^H^H prompts' worth of existing `412`-returning tests.
- Naming, not rebuilding, the offline-sync retryable/non-retryable classification already correctly implemented (`pwa/syncEngine.ts::classifySyncFailure`, PROMPT-028) as the AUTHORITATIVE source this new backend `retryable` field must AGREE with.
- A centralized `app/core/error_categories.py` mapping every EXISTING exception class (and, transitively, every `PREFIX-NNN` code already in `error_codes.py`) to one of the source prompt's §5 categories.

## 4. Out of Scope

- Rewriting or renaming any of the ~24 existing `PREFIX-NNN` error codes — they stay exactly as they are (§41's own "do not use different naming conventions per module" is ALREADY satisfied by the existing convention; renaming now would be the actual backward-compatibility break §43 warns against).
- A generic validation framework/library swap — Pydantic is already the validation layer (Layers 1-2 of §7) and is not replaced (Open Decision #15).
- Async job infrastructure (§37/§38 of the source prompt) — no background-job technology exists anywhere in this codebase (the same confirmed absence every PROMPT-018/028/031/033/034 spec has independently found); this spec documents the SYNCHRONOUS error contract only, consistent with PROMPT-033/034's own identical scope decisions.
- A dedicated error-monitoring/observability platform (Sentry, Datadog, etc.) — none exists; §45's own "do not turn the MVP into a full enterprise observability platform" instruction is honored by explicitly NOT proposing one (Open Decision #12).
- Multi-language error message localization — no i18n infrastructure exists anywhere in this codebase (Open Decision #18).

## 5. Core Principles

The source prompt's 20 principles (§2), checked against real code:

| # | Principle | Status |
|---|---|---|
| 1-5 | Server-side validation; never trust client tenant_id/created_by/authorization | **Already true everywhere**, re-confirmed across PROMPT-032/034/035's own independent verifications |
| 6 | Standardized HTTP status codes | **Mostly true, one deliberate divergence** (409 vs 412, §8) |
| 7 | Standardized application error codes | **Already true** — the `PREFIX-NNN` registry |
| 8 | Machine-readable errors | **Partially true** — `code` is machine-readable; `category`/`retryable` are the missing pieces (§3) |
| 9 | Human-readable messages | **Already true** — every `AppError` carries a `message` |
| 10-12 | No stack traces/SQL/secrets in responses | **Already true**, verified (`error_handlers.py`'s own docstring + code match, PROMPT-032 §32) |
| 13 | Traceable via correlation_id | **Already true** — `get_correlation_id()` is already in every envelope's `meta` |
| 14 | Retryability explicitly defined | **Missing today** — the gap this spec closes (§3) |
| 15 | No ambiguous financial success/failure | **Already true by construction** — every financial posting is one atomic DB transaction (§18/§36 below) |
| 16 | Idempotency where required | **Already true** — `IdempotencyService`, PROMPT-002, reused everywhere since |
| 17 | Explicit concurrency conflicts | **Already true** — `ConcurrencyConflictError`/412, `row_version` |
| 18 | Tenant isolation fails securely | **Already true** — cross-tenant lookups return the SAME 404 as genuinely-not-found (PROMPT-032 §10/§12) |
| 19 | Consistent API behavior across modules | **Mostly true by convention**, formalized further by this spec |
| 20 | Integrates with audit/security | **Already true** — `AuditService` records the OUTCOME of most operations; this spec does not change that, only enriches the error SHAPE |

## 6. API Error Model

**Current envelope** (verified, `error_handlers.py`):
```json
{"error": {"code": "CUST-003", "message": "...", "details": []}, "meta": {"correlation_id": "..."}}
```

**Extended envelope** (this spec's proposal — additive fields only, no existing field removed or renamed):
```json
{
  "error": {
    "code": "CUST-003",
    "message": "A customer with this code already exists.",
    "category": "BUSINESS_RULE",
    "details": [],
    "field_errors": [],
    "retryable": false
  },
  "meta": { "correlation_id": "..." }
}
```

`correlation_id` STAYS in `meta` (its existing, already-correct location) rather than moving inside `error` as the source prompt's own §3 example shows — moving it would be a breaking change to every existing frontend `ApiError` consumer (`api/client.ts` already reads `meta.correlation_id`, confirmed) for zero functional benefit. This is a deliberate, documented deviation from the source prompt's literal example, justified by backward compatibility (§43's own instruction to avoid unexpected breaking changes).

## 7. Error Categories

`app/core/error_categories.py` (new): an `ErrorCategory` enum matching the source prompt's §5 list exactly (`AUTHENTICATION`, `AUTHORIZATION`, `TENANT_ISOLATION`, `VALIDATION`, `BUSINESS_RULE`, `RESOURCE`, `CONFLICT`, `IDEMPOTENCY`, `INTEGRATION`, `OFFLINE_SYNC`, `RATE_LIMIT`, `SYSTEM`, `DATABASE`, `INTERNAL`), each mapped from an EXISTING exception class:

| Exception class (existing) | Category (new) |
|---|---|
| `ValidationAppError` | `VALIDATION` |
| `BadRequestError` | `VALIDATION` |
| `AuthenticationError` | `AUTHENTICATION` |
| `AuthorizationError` | `AUTHORIZATION` (or `TENANT_ISOLATION` for the specific cross-tenant-404 case, §12 below) |
| `NotFoundError` | `RESOURCE` |
| `ConflictError` | `CONFLICT` or `BUSINESS_RULE` (context-dependent — see §17/§18, both currently raise the SAME class) |
| `ConcurrencyConflictError` | `CONFLICT` |
| `RateLimitedError` | `RATE_LIMIT` |
| `ExternalServiceError` | `INTEGRATION` |
| `ServiceUnavailableError` | `SYSTEM` |
| (uncaught `Exception` → generic 500 handler) | `INTERNAL` |

**`IDEMPOTENCY` and `OFFLINE_SYNC` are NOT distinct exception classes today** — an idempotency-key-payload-mismatch error currently raises a plain `ConflictError`/`BadRequestError` (to be confirmed exactly at implementation time), and offline-sync failures are just ORDINARY 4xx/5xx responses that the CLIENT (`pwa/syncEngine.ts`) classifies into retryable/non-retryable AFTER the fact (PROMPT-028's own architecture — the server has no "this is a sync request" concept at the exception layer, §24 below elaborates). This spec does NOT propose adding two new exception subclasses for these — the CATEGORY can be attached via the error CODE's own prefix/context (e.g. any `IDEM-*`-coded error → `IDEMPOTENCY` category) rather than the exception class hierarchy, avoiding an unnecessary class-hierarchy expansion for a distinction that's really about WHICH endpoint raised it, not a fundamentally different exception shape.

## 8. HTTP Status Standard

| Status | Source prompt's recommendation | This codebase's actual, verified usage | Resolution |
|---|---|---|---|
| 200/201/204 | Standard | **Matches** — verified across every list/create/update endpoint | Unchanged |
| 400 | Malformed request | `BadRequestError` | Matches |
| 401 | Unauthenticated | `AuthenticationError` | Matches |
| 403 | Authenticated, unauthorized | `AuthorizationError` | Matches |
| 404 | Not found | `NotFoundError` | Matches |
| **409** | **State/concurrency/idempotency conflict** | `ConflictError` = 409 (state/business conflicts, e.g. `MASTER_IN_USE`-style), but **concurrency conflicts specifically use 412**, NOT 409 | **Genuine, documented divergence — see Requirement Conflict #1 below** |
| 422 | Semantic/business validation | `ValidationAppError` | Matches |
| 429 | Rate limited | `RateLimitedError` | Matches |
| 500 | Unexpected internal | Generic exception handler | Matches |
| 502 | Upstream integration failure | `ExternalServiceError` | Matches |
| 503 | Temporary unavailable | `ServiceUnavailableError` | Matches |
| 504 | Upstream timeout | **Not distinctly used** — a GST provider timeout currently surfaces as `ExternalServiceError`/502 or `STATUS_UNKNOWN` domain state (PROMPT-018), never a literal 504 | Minor gap, not urgent — 502 already communicates "upstream problem" adequately; a dedicated 504 is cosmetic, flagged as Open Decision, not built |

**Requirement Conflict #1 (formal statement)**: the source prompt's §6 explicitly recommends 409 for "concurrency conflict"; this codebase's `ConcurrencyConflictError` (PROMPT-001, used by EVERY optimistic-concurrency check since — dozens of endpoints) returns **412 Precondition Failed**, tied directly to the `If-Match`/`expected_row_version` HTTP header pattern (412 is the RFC-correct status for a failed conditional request, arguably MORE correct than 409 for this specific case). **Recommendation: keep 412** — changing it now would be a breaking change to every existing frontend consumer (`api/client.ts` already has a DEDICATED `ConcurrencyConflictError` class keyed specifically off status 412, confirmed) and every existing backend test asserting 412, for a "fix" that trades one valid interpretation of the HTTP spec for another. Flagged explicitly per the source prompt's own closing instruction rather than silently kept OR silently changed.

## 9. Validation Architecture

The source prompt's 7 layers, mapped onto ALREADY-EXISTING code:

1. **Transport/schema** — FastAPI + Pydantic request models (automatic, already universal).
2. **Field validation** — Pydantic field types/constraints (`Field(max_length=...)`, `Literal[...]`, custom validators for GSTIN/phone/email) — already universal.
3. **Reference validation** — each service's own "does this FK exist, belong to my tenant, is it active" check (PROMPT-011's `sales_validation_service.py` is the canonical example) — already universal, per-module.
4. **Authorization validation** — `require_permission()` dependency — already universal.
5. **Business-rule validation** — status-transition guards, stock/credit checks, etc. — already universal, per-module.
6. **Transaction/state validation** — `CANCELLABLE_STATUSES`-style checks before a state-changing action — already universal.
7. **Database constraints** — CHECK/UNIQUE/FK constraints as the final backstop — already universal (verified via migration inspection across PROMPT-034/035's own research).

**All 7 layers already exist and are exercised on every mutating request in this codebase** — this spec's contribution is naming them as an explicit, ordered pipeline other developers can reference, not building any of them from scratch.

## 10. Field Validation

Already thorough (PROMPT-032 §14, PROMPT-035 §15, re-confirmed) — UUID/String/Integer/Decimal/Date/Boolean/Enum/Email/Phone/GSTIN/HSN/Quantity/Percentage each already have an established validation pattern somewhere in this codebase (Pydantic types + dedicated format-check functions for GSTIN/HSN, `Numeric(precision, scale)` at the DB layer mirrored by `Decimal` at the Pydantic layer). This spec does not introduce new field-validation code — it DOCUMENTS the existing pattern as the standard (§39).

## 11. Financial Validation

**Already correct, decimal-safe throughout.** Every monetary column in this codebase is `Numeric(precision, scale)` at the DB layer, `Decimal` (never `float`) at the Python/Pydantic layer — confirmed across every financial model reviewed since PROMPT-015 (§9's own "never use binary floating-point arithmetic... if the technology doesn't guarantee decimal correctness" is satisfied because Python's `Decimal` + Postgres `NUMERIC` together DO guarantee it). Negative-value/zero-value rules are enforced per-module (e.g. a Sales Invoice line quantity must be positive, a discount cannot exceed the line total) — already implemented, not re-derived here. Maximum allowed value is bounded only by the column's own `Numeric(15,2)`-style precision (no separate business-rule ceiling exists or is recommended — an artificial cap would need product justification not present in any source document).

## 12. Tenant Validation

Unchanged, already fully correct (PROMPT-032 §10/§13, PROMPT-034 §17, PROMPT-035 §16 — the most independently-re-verified property in this entire specification series). `tenant_id` is NEVER accepted from a request body/query/path/header for a tenant-scoped caller — always server-derived from `AuthenticatedContext`. A mismatch (e.g. a crafted `entity_id` belonging to another tenant) fails via the SAME `NotFoundError`/404 a genuinely-missing resource would produce — never a distinguishable `TENANT_ACCESS_DENIED` error for a tenant-scoped resource lookup (§16's own "do not expose whether another tenant's resource exists" is satisfied precisely BECAUSE the codebase already collapses these two cases into one response). `TENANT_ACCESS_DENIED` as a NAMED code IS used, but only for the (currently unbuilt) Platform Admin boundary case (PROMPT-030/032), where the caller explicitly KNOWS they're crossing a tenant boundary and the question is authorization, not existence — a meaningfully different situation from an ordinary tenant user's own by-ID lookup.

## 13. Authentication Errors

| Code (source prompt's name) | This codebase's actual code | Status |
|---|---|---|
| `INVALID_CREDENTIALS` | `AUTH-001` | Exists |
| `SESSION_EXPIRED` | `AUTH-006` | Exists |
| `SESSION_INVALID` | `AUTH-005` | Exists |
| `ACCOUNT_DISABLED` | `AUTH-002` (`AUTH_ACCOUNT_INACTIVE`) | Exists |
| `ACCOUNT_NOT_ACTIVATED` | **Not a distinct code** — this codebase has no "pending activation" account state (new users get an immediate reset link, PROMPT-005, never a separate "not yet activated" limbo state) | **N/A — genuinely doesn't apply to this product's own user-creation model**, not a gap |
| `AUTHENTICATION_REQUIRED` | `AUTH-008` (`AUTH_UNAUTHENTICATED`) | Exists |

Anti-enumeration (§14's own "do not reveal whether a username/email exists") is **already correctly implemented and TESTED** — PROMPT-004's forgot-password flow returns an identical response regardless of account existence (CLAUDE.md's own long-standing, verified security default).

## 14. Authorization Errors

| Code (source prompt's name) | This codebase's status |
|---|---|
| `INSUFFICIENT_PERMISSION` | Generic `AuthorizationError`/403, message varies per permission — no single unified code exists today (each `require_permission()` failure just raises the generic class); **recommended addition**: a shared `AUTHZ-001 INSUFFICIENT_PERMISSION` code, attached uniformly by `require_permission()`'s own failure path, rather than each module inventing its own |
| `ROLE_NOT_ALLOWED` | Subsumed by the permission model — this codebase never checks "role" directly at the API layer, only the RESOLVED permission set (PROMPT-006's own architecture) — this code is **not needed**, since permission-based checking is strictly more precise than role-name checking |
| `MODULE_NOT_ENABLED` | **Does not exist yet** — this is PROMPT-030's own future Module Entitlement layer; reserved, not built |
| `RESOURCE_NOT_AUTHORIZED` | Overlaps with the existing tenant-scoped 404 pattern (§12) for ordinary resources; reserved specifically for PROMPT-030's Platform Admin boundary (a resource that EXISTS and the caller can SEE exists, e.g. in a tenant directory, but isn't authorized to modify) |
| `TENANT_ACCESS_DENIED` | Reserved for Platform Admin cross-tenant boundary violations (§12) |
| `PLATFORM_ACCESS_DENIED` | Reserved for a tenant user attempting any `/platform-admin/*` route — structurally impossible today since no such routes exist yet (PROMPT-030) |

## 15. Resource Errors

**Already correctly implemented as a GENERIC pattern, not per-entity codes.** Confirmed: this codebase does NOT actually use `CUSTOMER_NOT_FOUND`/`PRODUCT_NOT_FOUND`/etc. as the source prompt's own §16 example suggests — instead, each module's OWN `PREFIX-NNN` catalogue includes its own not-found code (e.g. presumably `CUST-001`-style, to be confirmed per prefix at implementation time) which IS effectively entity-specific but expressed through the numbering scheme rather than a semantic name. This is a **naming-convention observation, not a defect** — the existing scheme satisfies "distinguishable per entity type" (§16's own requirement) just via a different mechanism (numeric code + module prefix) than the source prompt's own suggested naming. No change is recommended — renaming ~24 catalogues' worth of not-found codes to a new naming style would be pure churn (§43).

## 16. Duplicate Errors

Same pattern — each module's own catalogue already has its own duplicate-code entries (Customer/Product/Employee code uniqueness violations, GSTIN, etc.) enforced at BOTH the application layer (a pre-check query) AND the database layer (the `UniqueConstraint`s verified in PROMPT-034/035's own research) — §17's own "use database constraints as final protection" is already satisfied; a race between two concurrent identical-code creates is caught by the DB constraint even if the application-layer pre-check both requests passed (a `IntegrityError` → translated to the SAME duplicate error, §28 below).

## 17. Business Rule Errors

Already extensively implemented per-module — `INACTIVE_CUSTOMER`/`INACTIVE_PRODUCT`(as inactive-master checks, PROMPT-035 §16), `INSUFFICIENT_STOCK` (PROMPT-010's negative-stock guard), `INVALID_STATUS_TRANSITION` (every document type's own `CANCELLABLE_STATUSES`-style check), `PAYMENT_OVER_ALLOCATION` (PROMPT-024), `JOURNAL_NOT_BALANCED` (PROMPT-025's `post_journal` debit=credit check), `PERIOD_CLOSED` (the `accounting_period` posting guard, PROMPT-025 — though CLAUDE.md's own OD-018/019 notes a period can never actually BECOME closed yet, so this specific error is currently unreachable in practice, a known limitation not a defect of THIS spec), `INVALID_GST_CONFIGURATION`/`INVALID_PLACE_OF_SUPPLY` (PROMPT-011/026's GST calculation guards). **All already exist, distinguishable from technical errors by their exception CLASS** (`ValidationAppError`/422 or `ConflictError`/409, never a 500) — this spec's contribution is confirming the CATEGORY tag (`BUSINESS_RULE`, §7) is attached consistently, not inventing new business rules.

## 18. Financial Transaction Errors

The source prompt's own critical distinction — REQUEST REJECTED vs. ACCEPTED-BUT-PROCESSING vs. FAILED vs. SUCCESSFUL — is **already resolved for this MVP's architecture, by the ABSENCE of asynchronous financial processing**: every financial posting (Sales/Purchase Invoice, Payment, Journal, Payroll Run finalize) is a SINGLE synchronous HTTP request that either (a) returns 2xx with the fully-posted result, or (b) returns a 4xx/5xx and the ENTIRE transaction is rolled back (§36 below) — there is NO "ACCEPTED BUT PROCESSING" state for any financial operation in this MVP, because none of them are asynchronous. This eliminates the ambiguity the source prompt is worried about BY CONSTRUCTION rather than by careful state-machine design — a genuinely simpler, MVP-appropriate resolution, not a gap.

## 19. Idempotency

Already fully implemented (`IdempotencyService`, PROMPT-002) and reused by every financial create/state-transition endpoint since. **Same key + same payload** → the ORIGINAL response is returned verbatim (never re-executed) — confirmed behavior. **Same key + DIFFERENT payload** (§21's own scenario) — this spec's research pass did NOT find explicit confirmation that `IdempotencyService` currently detects a payload MISMATCH and rejects it (vs. simply returning the original response regardless of payload, silently ignoring the new, different payload) — **flagged as a verification task for implementation**, not asserted as either already correct or broken. If a mismatch is NOT currently detected, `IDEM-001 IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_PAYLOAD` (new code) should be added, gated behind a fingerprint comparison (`idempotency_key.request_fingerprint`, a column already confirmed to exist per PROMPT-034's own research pass — meaning the DATA needed for this check already exists, only the comparison logic needs verification/addition).

## 20. Concurrency

Already fully implemented (`row_version` + `expected_row_version`/`If-Match`, `ConcurrencyConflictError`/412) — §8 above resolves the ONE open question (409 vs 412) explicitly. No further work needed beyond that documented decision.

## 21. Offline Sync Errors

**Already correctly implemented, but the classification logic lives CLIENT-SIDE, not server-side** — a genuinely important architectural fact to state precisely, cross-referencing PROMPT-028/032 rather than re-deriving: the SERVER has no special "offline sync" error path at all — it returns the SAME ordinary 4xx/5xx an online request would get. `pwa/syncEngine.ts`'s own `classifySyncFailure` function is what maps a plain HTTP status/error code into `TRANSIENT` (auto-retried) vs. `AUTHORIZATION`/`BUSINESS_CONFLICT`/`VALIDATION`/`DEPENDENCY_FAILURE` (surfaced to the user, never auto-retried) — this ALREADY matches the source prompt's own §24 example table almost exactly (network/5xx→retryable, invalid data/permission→non-retryable). **This spec's one recommendation**: the NEW `retryable` field this spec adds to the server's OWN error envelope (§3) should be set to VALUES CONSISTENT with what `classifySyncFailure` already independently concludes for the SAME status codes (e.g. server marks 503/502 as `retryable: true`, matching the client's own `TRANSIENT` classification) — not a behavior change, but an EXPLICIT cross-check to perform at implementation time so the two independently-built classifications (client heuristic vs. new server field) don't quietly diverge.

## 22. Integration Errors

Already implemented (PROMPT-018's `SandboxSimulatorProvider` fault-injection hooks: TIMEOUT/UNAVAILABLE/AUTH_FAILED/RATE_LIMITED, each mapped to the correct `ExternalServiceError`/502 or a permanent validation error as appropriate — including the ALREADY-FIXED "AUTH_FAILED was misclassified as permanent instead of transient" bug from PROMPT-018's own test-writing pass, confirming this distinction has ALREADY been deliberately, carefully made once). `GST_PROVIDER_UNAVAILABLE`/`_TIMEOUT`/`_AUTHENTICATION_FAILED`/`_VALIDATION_FAILED`/`IRN_GENERATION_FAILED`/`EWAYBILL_GENERATION_FAILED` (source prompt §25) map directly onto PROMPT-018's own already-built `EINV-*`/`EWB-*` catalogues — reused, not renamed.

## 23. Retry Policy

**The genuinely new, cross-cutting piece this spec adds**: a `retryable: bool` class attribute on every `AppError` subclass (§3/§7), defaulted per-class (`ExternalServiceError.retryable = True`, `ServiceUnavailableError.retryable = True`, `RateLimitedError.retryable = True` with a `Retry-After` hint where the rate-limiter can supply one, everything else `False` by default) — a single, centralized policy table rather than each of ~30 modules independently deciding. This does NOT change any EXISTING retry behavior (PROMPT-018's own provider-side retry logic, PROMPT-028's own client-side sync retry logic both stay exactly as they are) — it only makes the POLICY that already implicitly exists in those two places EXPLICIT and QUERYABLE via the API response itself, for any FUTURE consumer (e.g. a future mobile app) that doesn't already have `classifySyncFailure`'s own hard-coded logic.

## 24. Rate Limiting

Already implemented (`app/core/rate_limit.py`, PROMPT-002/003/004) — `RateLimitedError`/429 already exists; this spec adds `Retry-After` header emission (currently NOT confirmed present — `rate_limit.py`'s own code was read in the PROMPT-032 pass and no `Retry-After` computation was found) as a small, genuinely new addition, computed from the SAME in-memory window state the limiter already tracks (§27's own "retry-after where appropriate" instruction, previously unaddressed).

## 25. Database Error Mapping

Already correctly done via SQLAlchemy `IntegrityError` catching at the service layer (verified pattern: `DocumentNumberingService`'s own SAVEPOINT-retry-on-IntegrityError mechanism, PROMPT-011, and the general "check-before-insert AND catch IntegrityError as a race-safe backstop" pattern PROMPT-025's journal idempotency uses) — a raw Postgres error NEVER reaches the client (confirmed, `error_handlers.py`'s own generic-exception fallback catches anything unhandled and returns a sanitized 500). This spec formalizes the MAPPING table (Unique violation → `DUPLICATE_RESOURCE`-category error; FK violation → `INVALID_REFERENCE`; check-constraint violation → the relevant business-rule code) as documentation of the ALREADY-EXISTING per-module pattern, not new code.

## 26. Internal Error Handling

Already fully correct (`error_handlers.py`'s generic `Exception` fallback, confirmed to log full detail server-side via `exc_info=True` while returning a generic `{code: "INTERNAL_ERROR", message: "..."}` to the client) — this spec adds the human-readable, user-actionable message text the source prompt's own §29 example suggests ("Something went wrong. Please try again or contact support.") as the STANDARD wording, replacing whatever ad hoc message may currently exist for the truly-unexpected-exception path (to be confirmed/standardized at implementation time).

## 27. Correlation IDs

Already fully implemented and propagated (`CorrelationIdMiddleware`, PROMPT-001) — every response's `meta.correlation_id` is already populated, already consistent across the request → service → audit chain (PROMPT-031's own `AuditService.record()` already calls `get_correlation_id()` automatically). `request_id` as a DISTINCT concept from `correlation_id` was ALREADY evaluated and explicitly declined in PROMPT-031-SPECIFICATION.md Open Decision #16 — reused here, not re-litigated (Open Decision #5 below cross-references it rather than re-deciding).

## 28. Error Logging

Already fully correct and secure (`app/logging/config.py`'s `JsonFormatter`, `_REDACTED_KEYS`, PROMPT-032 §35) — timestamp/level/logger/correlation_id/tenant_id/user_id are already captured; endpoint/HTTP-method/duration are NOT currently explicit structured-log fields (confirmed gap, small, low-risk to add — Uvicorn's own access log covers method/path/status/duration today, just not correlated into the SAME JSON log line as the application's own error log — a minor consolidation opportunity, not a security gap).

## 29. Frontend Error Handling

Already substantially implemented — `api/client.ts`'s `ApiError` class already distinguishes status codes (a dedicated `ConcurrencyConflictError` for 412, an `onUnauthorized` callback for 401) and `ToastContext` surfaces error messages generically. **New, recommended additions** (given this spec's new `category`/`retryable` fields): the frontend's generic error-toast handler should branch on `category` to choose presentation (e.g. `VALIDATION`/`BUSINESS_RULE` → inline form errors using the new `field_errors` array where present, §34; `RATE_LIMIT` → a distinct "please wait" message using any `Retry-After` value; `INTEGRATION` → route to the relevant integration-status panel, e.g. `EinvoiceEwayBillPanel.tsx`, rather than a generic toast) — this is a natural, additive frontend enhancement enabled BY this spec's backend changes, not a redesign of the existing, already-working toast mechanism.

## 30. Async Error Handling

**Not applicable for M1** (§4 Out of Scope) — no asynchronous job infrastructure exists anywhere in this codebase; §37/§38 of the source prompt describe a REQUESTED/PROCESSING/COMPLETED/FAILED job lifecycle this MVP has never needed for ANY operation (every financial posting, document generation, and export is synchronous, per PROMPT-033/034's own independently-reached conclusions). If a future prompt introduces real background-job processing, THAT is the point to design this section for real — not speculatively now.

## 31. API Contract Standard

Every existing API specification (the individual PROMPT-XXX-NOTES.md files) already documents endpoint/method/auth/authorization/request/response/error-codes informally, module by module — this spec does not retrofit all 30+ prior NOTES files, but establishes the TEMPLATE (§39 of the source prompt's own list: Endpoint/Method/Auth/Authz/Request/Validation/Success/Errors/Status/Codes/Retry/Idempotency/Audit/Tenant) that any FUTURE prompt's own API documentation should follow, and that this document itself follows in every section above.

## 32. Error Code Registry

**Already exists and is comprehensive** — `app/core/error_codes.py`'s ~24 `PREFIX-NNN` catalogues collectively cover the vast majority of the source prompt's own §40 minimum list, just under this codebase's OWN naming convention (prefix+number) rather than the source prompt's own suggested semantic names (`RESOURCE_NOT_FOUND`, `DUPLICATE_RESOURCE`, etc.). **Recommendation**: do NOT rename the existing ~24 catalogues (§43's own backward-compatibility instruction) — instead, add a SEPARATE, small set of NEW, semantically-named, CATEGORY-level fallback codes (`VALIDATION_ERROR`, `DUPLICATE_RESOURCE`, `CONCURRENT_UPDATE`, `RATE_LIMIT_EXCEEDED`, `INTERNAL_ERROR`, `SERVICE_UNAVAILABLE` — matching the DEFAULT `error_code` already set on each `AppError` SUBCLASS itself, confirmed: `ValidationAppError.error_code = "VALIDATION_ERROR"` etc. ALREADY use exactly this semantic naming as the class-level default) — meaning the source prompt's own §40 list is ALREADY substantially satisfied by the EXISTING class-level default codes, and only overridden with a module-specific `PREFIX-NNN` code where a service explicitly passes `code=...`. This is a genuinely elegant, already-existing two-tier system (generic class default + specific module override) that this research pass surfaces as already meeting the requirement, not something needing new code.

## 33. Security Requirements

Directly reuses PROMPT-032's own Security Architecture (§13/§15/§16/§19/§27/§32) — every item in the source prompt's own §44 list (tenant A→B, invalid IDs, unauthorized APIs, auth failures, SQLi, invalid filters/sort, mass assignment, debug mode, stack traces, DB error exposure) is ALREADY addressed by PROMPT-032's own analysis, cross-referenced rather than re-verified from scratch here. **One item genuinely new to THIS spec**: "debug mode enabled" — confirmed, `app/main.py` already disables `/docs`/`/redoc` when `ENVIRONMENT=production` (verified in the PROMPT-032 research pass), but a Python framework's own DEBUG-mode stack-trace-in-response behavior (e.g. FastAPI/Starlette's `debug=True` constructor argument) was NOT explicitly checked as being off in production — flagged as a verification task (confirm `FastAPI(debug=False)` or the default, which IS `False`, is never overridden).

## 34. Observability

Per §45's own explicit "do not turn the MVP into a full enterprise observability platform" instruction: this spec recommends NO new tooling. Error COUNT/RATE/CODE/ENDPOINT/SEVERITY tracking is achievable TODAY via the existing structured JSON logs (`app/logging/config.py`) fed into whatever log-aggregation the hosting platform already provides (unspecified, deployment-layer, same conclusion PROMPT-032 §41 already reached) — no new metrics/tracing infrastructure is proposed (Open Decision #12, explicitly deferred, matching PROMPT-032's own identical conclusion for the SAME underlying gap).

## 35. QA Test Cases

Mapped to the source prompt's §46 (1–37) — items 1-20 (field/reference/duplicate/resource/status/period/concurrency/idempotency/business-rule validation) are **overwhelmingly regression confirmations of ALREADY-PASSING existing tests** across the 700+-test suite this codebase already has (PROMPT-007 through PROMPT-029 each built their own coverage for these exact scenarios) — this spec's GENUINELY NEW tests are: #17 (idempotency payload mismatch — the ONE unverified behavior, §19), the NEW `category`/`retryable` field presence on every error response (a new, centralized regression test asserting EVERY exception class's response includes both fields correctly), and #33 (correlation ID propagation — already works, but should get an explicit end-to-end test tracing one ID from HTTP request → business service → `AuditService` row → structured log line, since no such SINGLE test currently exists tying all three together, even though each piece is independently proven).

## 36. Security Test Cases

Mapped to the source prompt's §47 (1–18) — every item is **already covered by PROMPT-032's own Security Test Cases (§25 of that spec)** or PROMPT-034/035's own module-specific RBAC/tenant-isolation suites, EXCEPT #16 (unauthorized error-DETAIL access — a genuinely new angle: does the NEW `field_errors`/`details` array ever leak a field the caller shouldn't know exists, e.g. a validation error mentioning a `salary_amount` field to a Salesperson who shouldn't even know that field exists on the endpoint? — a real, previously-unexamined question this spec's own `field_errors` addition introduces, flagged as a NEW test to write, not assumed safe by default).

## 37. Cross-Module Traceability

Given the overwhelming conclusion of this entire spec — that error handling is ALREADY consistent, correct, and module-agnostic by construction — a full 15-module × 9-column matrix (as the source prompt's §50 requests) would be almost entirely "reuses the generic pattern, see §6-§28 above" repeated 15 times. Instead, this spec names the THREE modules with a genuinely distinct error-handling wrinkle worth calling out individually, and confirms every other module (User Management, Customer/Supplier, Product/Inventory, Sales, Purchase, Payments, Reports, Document Generation) follows the generic pattern with no special case:

| Module | Distinct wrinkle |
|---|---|
| Accounting | `JOURNAL_NOT_BALANCED`/`PERIOD_CLOSED` are business-rule errors with NO possible resolution via retry — always `retryable: false`, and the ONLY module where a validation failure could, in principle, indicate a genuine SYSTEM bug (an unbalanced journal should be structurally impossible given `JournalService`'s own debit=credit enforcement) rather than a user input mistake — worth a `CRITICAL` severity tag (§32 of the source prompt) specifically for this one error, distinct from ordinary `WARNING`-level business-rule violations elsewhere. |
| GST/E-Invoice/E-Way Bill | The ONLY modules with a genuine RETRYABLE integration-failure class (`ExternalServiceError`/502) as opposed to every other module's exclusively-non-retryable business-rule failures — the `retryable` field (§23) is MOST consequential here. |
| Offline Sync | The ONLY module where the SAME server-side error code must be independently interpretable by BOTH an online frontend (immediate toast) AND the offline sync engine's own retry logic (§21) — the two consumers must agree on retryability, which is why §21 calls for an explicit cross-check rather than assuming the new server-side field and the pre-existing client-side classifier naturally agree. |

## 38. Acceptance Criteria

Directly traceable to the source prompt's §48 (1–25) — the overwhelming majority are marked MET TODAY by already-existing code; items 6 (field-level errors) and 14 (retryable/non-retryable behavior) are the two genuinely NOT-yet-built pieces this spec's own implementation pass would need to add. Item 25 ("no critical defects") is deferred, as with every prior spec-only prompt.

## 39. Open Decisions

Directly answering the source prompt's own §49 list (1–20):

| # | Question | Recommended | Owner |
|---|---|---|---|
| 1 | Exact API response envelope | Extend the EXISTING envelope additively (§6) — do not adopt the source prompt's own literal example verbatim (correlation_id stays in `meta`) | Engineering Lead |
| 2 | Exact error-code catalog | Keep the EXISTING ~24 `PREFIX-NNN` catalogues; add category-level fallback codes only (§32) | Engineering Lead |
| 3 | 400 vs 422 usage | Already resolved and consistent (`BadRequestError`=400 for malformed input, `ValidationAppError`=422 for semantically-valid-but-business-invalid input) — not re-litigated | — |
| 4 | Error-detail verbosity | Keep current level (field name + code + message); do not add stack-trace-adjacent detail even in non-production, to avoid a future accidental production leak from copy-pasted dev code | Security + Engineering |
| 5 | Request ID vs correlation ID | Already decided in PROMPT-031 OD #16 — correlation_id only, no separate request_id | — (cross-referenced) |
| 6 | Error log retention | Unchanged from PROMPT-032 OD #15 (ephemeral stdout, hosting-platform-dependent) | DevOps |
| 7 | Rate-limit thresholds | Unchanged from PROMPT-032 OD #8 (existing documented placeholders) | Product + Security |
| 8 | Standard retry policy | §23's per-class default table | Engineering Lead |
| 9 | Idempotency-key format | Unchanged — client-generated string, already works (PROMPT-002/024/028) | — |
| 10 | Idempotency-key retention | Not currently time-bound (no purge exists) — acceptable at MVP scale, same reasoning as every other "no retention infra exists yet" open item this session has raised | Engineering Lead |
| 11 | Async job retention | N/A — no async jobs exist (§30) | — |
| 12 | Error monitoring platform | None for MVP (§34) | DevOps + Security |
| 13 | User-visible support reference | Not currently included in the generic 500 message; recommend adding the `correlation_id` itself as the "reference" a user can quote to support (already available, zero new infra) | Product Owner |
| 14 | Account-enumeration policy | Already resolved (PROMPT-004, anti-enumeration verified) — not re-litigated | — |
| 15 | Validation framework/library | Pydantic, unchanged (§4 Out of Scope) | — |
| 16 | API gateway error-handling | No API gateway exists in this architecture (a single FastAPI monolith, confirmed) — N/A | — |
| 17 | Database error mapping | §25's table — already the de facto existing pattern | Engineering Lead |
| 18 | Error localization | Not MVP — no i18n infrastructure exists anywhere | Product Owner |
| 19 | Technical error detail for Platform Admin | Recommend: NO special exposure — Platform Admin sees the SAME sanitized error shape as anyone else; deeper diagnosis uses correlation_id + server-side logs, never a richer API response (consistent with PROMPT-030/032's own "no admin backdoor" principle) | Security + Product |
| 20 | Mobile error UI pattern | Reuses this codebase's own existing `ToastContext`-based pattern, unchanged — no new mobile-specific error UI is proposed | Product Owner |

## 40. Risks

- **Adding `category`/`retryable` as CLASS-LEVEL attributes (§3/§23) is low-risk BECAUSE it requires zero changes to the ~200+ existing `raise SomeError(...)` call sites** — but this ALSO means the new fields' correctness depends entirely on each of the 9 EXISTING classes being assigned the RIGHT default, a one-time but consequential judgment call (e.g. is `ConflictError` retryable? Usually not — a business conflict rarely resolves itself — but a NAIVE default of `False` for the whole class could be wrong for some SPECIFIC conflict scenario a future developer raises via that same generic class). Recommend a careful, reviewed pass over EVERY existing `ConflictError`/`BadRequestError` raise site's actual semantics before finalizing the class-level default, not a rushed one-line guess.
- **The 409-vs-412 divergence (§8) being explicitly DOCUMENTED as "kept, not changed" could still surface as confusion for a new developer** who read the source prompt's own §6 literally and expects 409 — mitigated by this document itself being the canonical reference, but worth calling out in `app/core/exceptions.py`'s own docstring too at implementation time (a one-line comment pointing here).
- **The idempotency-payload-mismatch verification (§19)** could reveal an ACTUAL, previously-unknown security-relevant gap (a client could currently replay a DIFFERENT payload under an old key and get the STALE original response, silently masking their new request rather than rejecting it) — this needs to be checked EARLY in the implementation pass, since if it IS a real gap, it's a correctness issue independent of this spec's other, purely-additive changes.

## 41. Dependencies

- PROMPT-001 (the exception hierarchy, correlation-ID middleware, structured logging, `error_handlers.py`) — the foundation this ENTIRE spec extends, confirmed still the authoritative base 35 prompts later.
- PROMPT-002 (`IdempotencyService`) — the subject of §19/§21's own verification task.
- PROMPT-018 (integration fault-injection/classification, `SandboxSimulatorProvider`) — the model for §22's retryable/non-retryable distinction.
- PROMPT-025/026 (Accounting/GST business-rule error precedents) — §17/§37's own examples.
- PROMPT-028 (offline sync's own client-side `classifySyncFailure`) — the AUTHORITATIVE classification §21/§23 must stay consistent with.
- PROMPT-031-SPECIFICATION.md (correlation_id vs request_id decision, reused not re-litigated, §27/OD #5).
- PROMPT-032-SPECIFICATION.md (the security baseline §33 reuses wholesale).
- PROMPT-034-SPECIFICATION.md (error codes for export, `EXP-*`, reused in §32's registry discussion).
- PROMPT-035-SPECIFICATION.md (master-data error codes, `MST-*`, reused in §15/§17).

## 42. Definition of Done (for THIS specification deliverable)

- [x] All 42 sections requested by the source prompt's §51 are present.
- [x] Every claim is grounded in the ACTUAL current codebase — confirmed via direct inspection of `exceptions.py` (revealing the full 9-class hierarchy and the 412-vs-409 divergence), `error_codes.py` (confirming the existing `PREFIX-NNN` registry already substantially satisfies §40), `error_handlers.py`, and `api/client.ts` (confirming the frontend already has a working, status-aware `ApiError`/`ConcurrencyConflictError` split) — nothing asserted without verification.
- [x] The ONE genuine HTTP-status divergence from the source prompt's own literal recommendation (409 vs 412 for concurrency) is explicitly flagged as a Requirement Conflict, with a reasoned recommendation to KEEP the existing, arguably-more-correct 412 behavior rather than silently complying with the source prompt's own suggestion.
- [x] Every open decision from the source prompt's §49 is answered; several correctly point to decisions ALREADY made in PROMPT-004/031/032 rather than re-litigating them.
- [x] This spec correctly recognizes that MOST of what PROMPT-036 asks for already exists and works — the genuinely new work is narrow and precise: `category`/`retryable`/`field_errors` envelope fields, the idempotency-mismatch verification, and a `Retry-After` header addition — not a ground-up redesign.
- [ ] **Not done, and not in scope for this deliverable**: actual implementation (the `category`/`retryable` class attributes, `app/core/error_categories.py`, the `field_errors` array wiring in `error_handlers.py`'s `RequestValidationError` handler, the idempotency-payload-mismatch check/fix if the verification confirms a real gap, the `Retry-After` header). Per the source prompt's own framing (§51 "Produce the final implementation specification," §52's spec-readiness Definition of Done, and the same absent "implement/STOP" language as PROMPT-030–035), this document is the planning artifact for a future implementation pass.
