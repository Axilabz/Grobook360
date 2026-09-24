# PROMPT-035 — Master Data & Configuration Framework

**Document type:** Development specification & implementation plan (per §48 — same pattern as PROMPT-030–034: no "implement" instruction, no "STOP before PROMPT-036" directive; §49's Definition of Done is spec-readiness framed). **No application code was written for this deliverable.**

**Baseline used:** the actual current codebase after PROMPT-001–034 (030–034 were also spec-only). Verified by direct inspection of `app/models/product_unit_conversion.py`, `app/models/tenant.py`, `app/services/accounting/chart_of_accounts_service.py`, migrations 0008/0010/0026 (uniqueness constraints), and PROMPT-025/026/029/031/032/034-SPECIFICATION.md (cross-referenced, not re-derived).

---

## 1. Requirement Understanding

PROMPT-035 asks for a governance FRAMEWORK over master/reference/configuration data spanning every module. The grounding pass confirms this codebase already has a STRONG, CONSISTENT-BY-CONVENTION master-data pattern (tenant-scoped `(tenant_id, code)` unique constraints at the DB layer — verified for Customer/Product/Chart-of-Accounts; ACTIVE/INACTIVE lifecycle preferred over deletion — verified across every module since PROMPT-007; server-side validation everywhere) — this spec's job, like PROMPT-034's, is to NAME and FORMALIZE that convention as an explicit governance model, and — critically — to surface the ONE genuinely significant gap this research pass found: **`product_unit_conversion` has NO effective-dating or versioning at all** (a single `conversion_factor` row per product/UOM pair, unique-constrained, meaning a conversion-factor CHANGE would require either editing the existing row in place — silently invalidating any historical calculation that used the old factor — or being blocked by the unique constraint entirely). This directly contradicts §9/§18/§19's own explicit "1 CARTON = 24 PCS must not become 1 CARTON = 30 PCS without explicit version/effective-date handling" example — a real, concrete Requirement Conflict, not a hypothetical.

## 2. Objective

Document the ALREADY-CONSISTENT master-data governance model this codebase has built incrementally (PROMPT-007 through PROMPT-029) as one explicit, cross-referenced framework — classifying every existing master by ownership/scope/lifecycle/deletion-policy (§34 Cross-Module Matrix), and specifically closing the UOM-conversion effective-dating gap this research pass found.

## 3. Scope

- A classification of every EXISTING master/reference/configuration entity into the source prompt's own 4 categories (§6), grounded in what's actually built, not aspirational.
- Formalizing the ACTIVE/INACTIVE lifecycle + deactivation-dependency-check pattern already used by Customer/Supplier/Product/Chart-of-Accounts/Employee into one named convention other modules can point to.
- Closing the UOM-conversion effective-dating gap (§1) via an additive `effective_from` column + historical-lookup change, mirroring `salary_structure`'s own already-proven effective-dated pattern (PROMPT-029).
- Cross-referencing (not redefining) PROMPT-031 (audit), PROMPT-032 (security), PROMPT-034 (search/filter/export) for every master screen.
- A minimal Global Configuration section, cross-referencing PROMPT-030's `platform_configuration` design rather than re-deriving it.

## 4. Out of Scope

- Bulk master import (CSV/Excel) — no such capability exists anywhere in this codebase today, and none is built here (Open Decision #13, explicitly marked out of scope per the source prompt's own §29 instruction).
- A generic master-data approval workflow — no approved source anywhere in this codebase's 34 prior prompts defines one; not invented here (Open Decision #21).
- Retroactively re-architecting any EXISTING master table's core fields (Customer/Supplier/Product's own already-approved shapes from PROMPT-007/008/009 are not redesigned) — this spec governs LIFECYCLE/GOVERNANCE, not business-field content (§6's own instruction: "do not redefine customer-specific business rules here").
- Global platform/reference-data tables (Country/State/Currency as separate tables) — checked and confirmed NOT to exist anywhere in this codebase (state/GSTIN validation is done via format-checking functions and a hard-coded state-code table reference in `gst_validation_service.py`, not a queryable `state` master table) — flagged as Open Decision #1/#6, not silently assumed to exist.

## 5. Core Principles

The source prompt's 15 principles (§2), checked against real code:

| # | Principle | Status |
|---|---|---|
| 1 | Tenant-owned master has `tenant_id` | **True everywhere** — every master table reviewed has it, NOT NULL, indexed |
| 2 | Global data not copied per-tenant unnecessarily | **True by omission** — no global reference table exists to copy in the first place (§4) |
| 3 | No cross-tenant access | **True** — RLS + app-level checks (PROMPT-032 §10) |
| 4 | Referenced masters not physically deleted | **True** — verified, no DELETE endpoint exists for Customer/Supplier/Product/Chart-of-Account/Employee anywhere |
| 5 | ACTIVE/INACTIVE preferred over deletion | **True**, the universal pattern |
| 6 | Historical transactions remain valid when masters change | **Mostly true, ONE gap** — UOM conversion (§1) |
| 7 | Transaction-time snapshotting where required | **True for prices/GST** (line-item `unit_price`/`gst_rate` snapshotted at posting, PROMPT-015) — **gap for buyer/seller identity** (already identified and being fixed per PROMPT-033-SPECIFICATION.md §9, cross-referenced not re-derived here) |
| 8-9 | Server-side validation mandatory, frontend supplementary | **True universally** (PROMPT-032 §14) |
| 10 | Uniqueness at DB + app level | **True** — verified `UniqueConstraint(tenant_id, code)` at the migration/DB layer for Customer/Product/COA |
| 11 | Master changes audited | **True** — `CUSTOMER_UPDATED`/`PRODUCT_UPDATED`/etc. all exist (PROMPT-007/008/009) |
| 12 | Effective-dated config doesn't rewrite history | **True where effective-dating exists** (Salary Structure, PROMPT-029) — **N/A/gap where it doesn't** (UOM conversion) |
| 13 | Transactions consume authoritative masters | **True** — every document service fetches the LIVE master at creation time, then snapshots what it needs (PROMPT-015 pattern) |
| 14 | Global masters not tenant-editable unless designed as overrides | **N/A** — no global master exists yet to test this against |
| 15 | Configuration doesn't silently change historical records | **True** — `accounting_period` posting guard, GST snapshot-per-transaction discipline (PROMPT-025/026) |

## 6. Master Classification

| Category | Definition | Members in THIS codebase |
|---|---|---|
| **A. Platform/Global Reference Data** | Shared across every tenant, not tenant-owned | **None currently exist as real tables** — state codes are validated via a hard-coded lookup in `gst_validation_service.py`, not a queryable master; no Country/Currency/District table exists. Flagged as Open Decision #1. |
| **B. Tenant Master Data** | Owned by one tenant, `tenant_id` NOT NULL | Customer, Supplier, Product, Unit of Measure, Location, Chart of Account, Employee, Salary Component |
| **C. Transaction Configuration** | Tenant-level settings shaping HOW transactions behave | Tenant's own `financial_year_start_month`, `phone_uniqueness_scope` (currently a GLOBAL app setting, not per-tenant — see §26), `integration_configuration` (PROMPT-018) |
| **D. System Configuration** | Platform-wide, Platform-Admin-controlled | Not yet built — this is exactly PROMPT-030's `platform_configuration` (spec only) |

## 7. Global Reference Data

**Genuinely, confirmed empty today.** State-code validity is checked via a fixed lookup table INSIDE `gst_validation_service.py` (a Python constant, not a DB table) — this satisfies GST validation's own narrow need without requiring a real `state` master. HSN reference data (a real master GST rate/classification table) does **not exist** — `product.hsn_code`/`product.gst_rate` are free-text/free-numeric fields (CLAUDE.md §4's own long-standing "blocked on ERD-DEC-05" open item, reused verbatim here, not re-litigated). **Recommendation**: keep it this way for M1 — introducing a real global State/Country/Currency/HSN master table would be pure infrastructure with no current consumer needing more than the existing lightweight validation functions already provide (Open Decision #1/#5).

## 8. Tenant Master Data

Every entity in Category B (§6) already follows the IDENTICAL governance shape, independently arrived at across 6 different prompts (007/008/009/010/025/029) — this is the strongest evidence this framework is describing a REAL, already-converged convention, not inventing one:

| Entity | Code field | Uniqueness (verified) | Lifecycle | Deletion |
|---|---|---|---|---|
| Customer | `customer_code` (system-generated) | `(tenant_id, customer_code)` UNIQUE (migration 0008) | ACTIVE/INACTIVE | None — deactivate only |
| Supplier | `supplier_code` (system-generated) | Same pattern | ACTIVE/INACTIVE | None |
| Product | `sku` (user-entered) | `(tenant_id, sku)` UNIQUE (migration 0010) | ACTIVE/INACTIVE | None |
| Unit of Measure | `code` | Tenant-scoped (per PROMPT-009) | ACTIVE (no deactivate UI built, per CLAUDE.md — confirmed minor gap, not addressed here) | None |
| Location | `location code` | Single lazily-provisioned "MAIN" per tenant (PROMPT-010 §8) | Always ACTIVE (no multi-location lifecycle exists) | None |
| Chart of Account | `code` | `(tenant_id, code)` UNIQUE (migration 0026) | `is_active` | None — verified, `ChartOfAccountsService` has no delete method |
| Employee | `employee_code` (system-generated via `next_number_no_fy`) | Tenant-scoped, permanent numbering (PROMPT-029) | ACTIVE/INACTIVE/ON_NOTICE/EXITED (a richer 4-state lifecycle, not just binary) | None |
| Salary Component | `code` | Tenant-scoped catalogue | `is_active` | None |

## 9. Master Lifecycle

**Standardized as: ACTIVE ⇄ INACTIVE, with DRAFT used ONLY where a specific master's own approved spec calls for it** (§15's own instruction). Confirmed: NONE of the tenant masters in §8 use DRAFT — DRAFT is exclusively a TRANSACTION-document concept (Sales Estimate/Order/Invoice etc.), never a master-data concept in this codebase. Employee's own richer 4-state lifecycle (`ACTIVE`/`INACTIVE`/`ON_NOTICE`/`ON_NOTICE`/`EXITED`, PROMPT-029) is a deliberate, approved EXTENSION of the binary pattern for that specific master's own business need (an employee's exit is a real HR event, not just "off") — not a template other masters should copy without their own justification.

## 10. Deletion Policy

**Confirmed, codebase-wide: NO tenant master supports hard deletion.** Every one of Customer/Supplier/Product/Chart-of-Account/Employee has ONLY create/update/activate/deactivate endpoints — no `DELETE` verb exists on any of their routers (verified). This satisfies §16 completely, by construction, not by a runtime check that could have a gap. **Whether an UNREFERENCED DRAFT master could ever be deleted is moot** — since no master uses DRAFT (§9), the question doesn't arise for any entity in this codebase today.

## 11. Historical Data Protection

Already strong for PRICE/GST fields (§5 principle #7 — `sales_invoice_line.unit_price`/`.gst_rate`/`.hsn_code` are frozen at posting time, PROMPT-015), and now further strengthened by PROMPT-033-SPECIFICATION.md's own recommended fix for buyer/seller NAME/ADDRESS snapshotting (cross-referenced, not re-derived here — that spec already owns the exact column-level design). **The ONE gap this spec's own research pass found and PROMPT-033 did not examine**: UOM conversion factors (§1/§12 below).

## 12. Effective Dating

| Master | Effective-dated today? | Assessment |
|---|---|---|
| Salary Structure | **Yes** — `effective_from`, no `effective_to` (applicable = latest `effective_from <= date`), PROMPT-029's own already-correct design | Model to replicate |
| GST rate (`product.gst_rate`) | **No** — a plain field, no history (CLAUDE.md's own long-standing "blocked on ERD-DEC-05" item) | Genuinely blocked on an upstream product-master decision, not addressed here |
| Product pricing (`selling_price`/`mrp`/`cost_price`) | **No** — plain fields on `product`, no effective-dating; a price CHANGE simply updates the row. Historical invoices are UNAFFECTED because `sales_invoice_line.unit_price` is its OWN snapshot (§11) — so the LACK of price effective-dating on the master itself is NOT actually a defect, since the consuming transaction never re-reads the master's current price for a historical document. Confirmed sufficient by this reasoning, not silently assumed. | No gap — snapshot-at-transaction-time already achieves the same protective outcome effective-dating would |
| UOM conversion factor | **No effective-dating, AND no snapshot at the consuming transaction either** — this is the genuine double-gap: `sales_order_line`/`sales_invoice_line`/`purchase_*_line` all store QUANTITY IN THE PRODUCT'S BASE UOM directly (confirmed by re-reading PROMPT-011's own `ProductLineSelector` design — the line item's own `quantity` field is always base-UOM, the CONVERSION happens only in the UI's OWN presentation layer, not persisted per-line) — meaning **the base-UOM quantity itself is protected** (a later conversion-factor change cannot retroactively alter an already-posted invoice's own stored base-UOM quantity), but the DISPLAY-time re-conversion (e.g. re-showing "2 CARTON" on a reprinted historical document) WOULD use today's live factor, not the one active at the time of entry. This is a narrower, real gap than initially feared — financial/stock correctness is NOT at risk (the persisted quantity is always base-UOM), only DISPLAY fidelity for a reprinted historical document is. | Real but narrow — flagged in Requirement Conflicts (§37), NOT elevated to a financial-integrity emergency |

**Recommendation**: add `effective_from` to `product_unit_conversion` (mirroring Salary Structure's own exact pattern — no `effective_to`, applicable = latest `effective_from <= date`) — closes the display-fidelity gap for a low implementation cost, reusing an already-proven pattern rather than inventing a new one.

## 13. Versioning

Per §19's own "do not introduce versioning for every simple master unnecessarily" instruction: versioning (in the sense of an immutable historical row per change, distinct from simple effective-dating) is used ONLY where §12's own analysis shows real risk — Salary Structure already IS this (each `effective_from` creates a new row, the old one is never edited, PROMPT-029). UOM conversion's recommended fix (§12) is the SAME shape — a new dated row per change, old rows retained. **No other master in this codebase needs full versioning** — Chart of Accounts/Customer/Supplier/Product changes are simple in-place updates (with `row_version` optimistic concurrency, §29, but not historical versioning) because none of them has a demonstrated "a later change would misrepresent an already-posted transaction" risk (§11 already established why price/GST are safe via line-item snapshotting).

## 14. Uniqueness

Confirmed pattern, consistent across every master: **`(tenant_id, code)` UNIQUE at the database layer** (migration-level `UniqueConstraint`, not just an application-level check) — Customer/Product/Chart-of-Account all verified. **GSTIN**: `tenant.gstin` is a plain nullable column with NO uniqueness constraint of any kind — satisfying "one GSTIN per tenant" trivially (one column, one value) but leaving CROSS-TENANT GSTIN uniqueness (can two different tenants register the same real-world business/GSTIN?) completely unenforced — a genuine, previously-unexamined gap, flagged as Open Decision #3, not silently assumed either way. **Phone uniqueness**: already a long-standing, explicitly-carried-forward open item since PROMPT-002 (`settings.phone_uniqueness_scope`, default `"tenant"`, unenforced at the DB level) — reused verbatim, not re-litigated (Open Decision #18, cross-referencing the ALREADY-EXISTING CLAUDE.md §4 item rather than inventing a new one).

## 15. Validation

Already thorough and server-side-only for every master (PROMPT-032 §14, unchanged) — required fields, length, type, format (GSTIN/phone/email), enum values, tenant ownership, and uniqueness are all validated in the service layer before any INSERT/UPDATE, verified across Customer/Supplier/Product/Employee. **Referenced-master existence + status validation** (§22's own additional items) is the one area worth naming explicitly as a per-module discipline to CONTINUE, not a gap: e.g. creating a Sales Invoice line already validates the referenced Product exists, belongs to the tenant, AND is ACTIVE (`sales_validation_service.py`, PROMPT-011) — this pattern must be followed by any NEW master-referencing relationship added in the future, not assumed automatic.

## 16. Referential Integrity

Already correct and consistently applied: every FK (Product→UOM, Employee→Salary Structure, Invoice→Customer, Invoice→Product, Journal→Account) is a real database foreign key (never an unconstrained UUID column), AND additionally re-validated at the application layer for tenant-ownership + active-status BEFORE use (double-enforced, matching PROMPT-032 §24's own "RLS + application layer, never one alone" discipline one level down). If a referenced master becomes INACTIVE, existing records remain valid by construction (the FK doesn't disappear, only future NEW references are blocked by the application-layer active-status check) — exactly per §23's own instruction.

## 17. Dependency Rules

| Master | Deactivation blocked by | Verified mechanism |
|---|---|---|
| Chart of Account | Active account mappings / posted journals referencing it | **Not fully verified as implemented** — `chart_of_accounts_service.py`'s own `deactivate` path was checked (line 67, `if not account.is_active`) but a dedicated "block deactivation if posted journal lines reference this account" guard was NOT confirmed present in this research pass — flagged as a verification task for implementation, not asserted as already done |
| Customer/Supplier | Existing transactions referencing it | **Not required to BLOCK deactivation** — per this codebase's own established pattern (Customer/Supplier deactivation has never been gated on existing-transaction-count anywhere since PROMPT-007), since deactivation only prevents FUTURE new transactions, never invalidates past ones (§17's own "however, whether deactivation should be blocked or merely prevent future use must be defined per master" — resolved here as "prevent future use only, no block" for Customer/Supplier/Product, matching the ALREADY-SHIPPED behavior) |
| UOM | Active products depending on it | **Not verified as implemented** — no dedicated dependency check found in `unit_of_measure`'s own (minimal) service layer; flagged as a genuine small gap for the implementation pass |
| Employee | N/A — Employee deactivation has no analogous "in use by a future transaction" concept; PROMPT-029's own status machine (ON_NOTICE/EXITED) already handles this domain-appropriately | — |

**This spec's recommendation, resolving §24's own explicit either/or question**: deactivation NEVER blocks on historical usage (the "prevent future use only" model, already the de facto behavior for Customer/Supplier/Product) — EXCEPT Chart of Account, where blocking IS recommended (an account with a non-zero balance or active mapping being deactivated could break future postings in a way ordinary master deactivation doesn't risk) — flagged as a decision needing explicit confirmation before implementation (Open Decision #11), not silently assumed either way.

## 18. Configuration Framework

Per §25's own instruction to keep Master Data / Configuration / Reference Data as DISTINCT concepts: this codebase already does NOT combine them into one generic table (confirmed — `tenant` holds configuration-ish fields like `financial_year_start_month` directly on the tenant row, `integration_configuration` is its own table, master entities are entirely separate tables) — no consolidation is needed or recommended. Global Configuration (Platform-Admin-controlled, §26) is entirely PROMPT-030's own scope (`platform_configuration`, spec only) — reused by reference, not redefined. Tenant Configuration (§27) — business profile, financial year, enabled modules once entitlements exist — is already Owner-editable via the (currently minimal) tenant-profile update path; PROMPT-030-SPECIFICATION.md §7.4's "Tenant Settings" screen is the recommended home for this, not a new screen invented here.

## 19. Master Import

**Explicitly out of scope** (§4) — no bulk import capability exists anywhere in this codebase, and building one is a substantial, independent feature (file upload — which PROMPT-032 §30 already confirmed doesn't exist anywhere — validation-preview UX, partial-failure handling) that no approved source requires for M1. Open Decision #13, resolved as "not MVP," not silently ignored.

## 20. Master Export

Reuses PROMPT-034's own `ExportService`/`columns`-allowlist design directly (§30's own "follow PROMPT-034, do not create a separate export framework" instruction, honored) — Customer/Supplier/Product/Employee/Chart-of-Accounts each get a `GET /{module}/export` endpoint per PROMPT-034-SPECIFICATION.md's §19 pattern, gated by a `<module>.export` permission (reusing PROMPT-034's own permission-naming convention). No new export mechanism is designed here.

## 21. Search/Filter Integration

Same — reuses PROMPT-034's `sortable()`/`apply_text_search`/`PageParams` directly (§31's own "do not implement independent pagination/filter/sort frameworks" instruction). Every master's own searchable/sortable field set is ALREADY documented in PROMPT-034-SPECIFICATION.md §7/§35 — not redefined here, only referenced.

## 22. Audit Integration

Reuses PROMPT-031's `AuditService` directly — every master's create/update/activate/deactivate ALREADY writes an audit event (verified: `CUSTOMER_CREATED`/`_UPDATED`/`_ACTIVATED`, `PRODUCT_CREATED`/etc.) — this spec adds NOTHING new here except naming the convention explicitly and confirming effective-dated changes (once UOM's fix, §12, lands) log OLD value/NEW value/effective date/actor, mirroring how `salary_structure` changes are ALREADY audited (PROMPT-029's own existing `before`/`after` snapshot discipline, PROMPT-031 §15).

## 23. Security

Reuses PROMPT-032 directly — every master already derives `tenant_id`/`created_by`/`updated_by` server-side, never from the client (verified across every `create_*` method reviewed — the Pydantic request schema never even HAS a `tenant_id`/`created_by` field for the client to attempt to set, making the "never trust these from the client" instruction structurally enforced, not just a runtime check). No new security concept is introduced.

## 24. Offline Master Data

Reuses PROMPT-028's own already-built `masterDataCache.ts` (Customer/Supplier/Product read-caches) directly. **§39's own critical question — "if a product became inactive after the offline cache was created, is the resulting offline transaction accepted/rejected/needs-resolution?" — is answered by PROMPT-032-SPECIFICATION.md §18's own already-established rule**: the server ALWAYS re-validates the referenced master's current tenant-ownership + active status at SYNC time (never trusts the client's cached "was active" belief), so an offline invoice referencing a since-deactivated product is REJECTED at sync (surfacing as a normal validation 422, classified by `classifySyncFailure` as `VALIDATION`→`REQUIRES_ACTION` in the existing Sync Center, PROMPT-028) — this is not a new behavior, it already falls out of the existing "server re-validates everything, offline data is never trusted" architecture; this spec simply confirms and names it for masters specifically.

## 25. API Specification

No new generic `/masters/*` endpoint family is introduced — each master keeps its OWN existing, module-specific router (`/customers`, `/products`, `/uom`, `/accounts`, `/employees`, etc.), following the identical CRUD+activate/deactivate verb shape the source prompt's own §40 example already matches (`GET`/`POST`/`GET {id}`/`PATCH {id}`/`POST {id}/activate`/`POST {id}/deactivate`) — **because every one of these endpoints already exists** (PROMPT-007/008/009/010/025/029). This spec's only API-level addition: confirming EVERY master's activate/deactivate endpoint accepts `expected_row_version` for optimistic concurrency (§29 below) — verified present for Customer/Product; to be confirmed for Chart-of-Account/UOM/Location at implementation time (flagged as a verification task, not asserted done).

## 26. Database Impact

**One small, additive migration**: `product_unit_conversion.effective_from` (Date, NOT NULL, default = the conversion's own `created_at::date` for existing rows via backfill) — mirroring `salary_structure.effective_from`'s exact type/semantics. The existing `UniqueConstraint(tenant_id, product_id, from_uom_id, to_uom_id)` would need to become `UniqueConstraint(tenant_id, product_id, from_uom_id, to_uom_id, effective_from)` (allowing multiple dated versions of the same conversion pair, exactly mirroring how `salary_structure`'s own `UniqueConstraint("tenant_id", "employee_id", "effective_from")` permits multiple structures per employee over time). **No other new tables or columns are required** — every other master's schema is already sufficient for this framework's governance model.

## 27. UI Standards

Already consistent by convention across every master screen (`CustomerManagement.tsx`/`SupplierManagement.tsx`/`ProductManagement.tsx`/`AccountingManagement.tsx`'s COA tab/`PayrollManagement.tsx`'s Employee tab) — Header/Search/Filters/Create button/List table/row-Actions/Pagination, and per-record View/Edit/Activate/Deactivate — this spec names the pattern explicitly (§34 of the source prompt) as the standard every FUTURE master screen must follow, rather than inventing a new layout.

## 28. Responsive UX

Reuses this codebase's own proven `hidden md:block`/`md:hidden` table-vs-card pattern, unchanged — no new responsive work, since every existing master screen already implements it.

## 29. Concurrency

**Already implemented everywhere** via `row_version` + `expected_row_version` (PROMPT-001's own `RowVersionMixin`, used by every mutable master table) — a stale-version update returns 409/412 with a clear conflict error, not a silent overwrite (verified pattern, `check_row_version()` helper). This spec adds nothing new here except, as noted in §25, confirming coverage is complete across ALL masters at implementation time.

## 30. Cache Invalidation

The ONLY master-data cache in this entire codebase is PROMPT-028's own client-side, OFFLINE-ONLY `masterDataCache.ts` — there is NO server-side application cache (no Redis, no in-process memoization of master rows) anywhere, confirmed by the absence of any caching library/decorator in the backend. This means §38's own concern ("stale master cache must not become the authoritative source for financial transactions") is **moot for the server** — every online request always reads the LIVE database row directly, no cache to go stale. It is a REAL concern ONLY for the offline cache, and §24 above already covers its resolution (server re-validates at sync, never trusts the cached snapshot's active-status).

## 31. Error Handling

New error codes (prefix `MST-`, confirmed no collision):

| Code | Meaning |
|---|---|
| `MST-001` | `MASTER_NOT_FOUND` |
| `MST-002` | `MASTER_INACTIVE` (referenced master exists but is inactive — blocks new transaction creation) |
| `MST-003` | `DUPLICATE_MASTER` (uniqueness violation — reuses each module's EXISTING specific code, e.g. `CUST-*`'s own duplicate-code error, where one already exists; `MST-003` is the fallback for any FUTURE master lacking its own) |
| `MST-004` | `INVALID_MASTER` |
| `MST-005` | `INVALID_REFERENCE` / `REFERENCE_NOT_FOUND` |
| `MST-006` | `REFERENCE_INACTIVE` |
| `MST-007` | `MASTER_IN_USE` / `MASTER_DEACTIVATION_BLOCKED` (Chart of Account's own recommended new guard, §17) |
| `MST-008` | `INVALID_EFFECTIVE_DATE` / `EFFECTIVE_DATE_CONFLICT` (the new UOM-conversion validation, §12/§26) |
| `MST-009` | `CONCURRENT_UPDATE` — **already exists** under each module's own row-version-conflict code (e.g. generic 409); `MST-009` is a shared fallback name, not a replacement |
| `MST-010` | `INVALID_CONFIGURATION` (reserved for PROMPT-030's own configuration endpoints once built) |

`TENANT_ACCESS_DENIED`/`INSUFFICIENT_PERMISSION` reuse existing generic codes, unchanged.

## 32. QA Test Cases

Mapped to the source prompt's §43 (1–30) — items 1-9 (create/view/update/activate/deactivate/duplicate/invalid/invalid-reference/inactive-reference) are **largely regression confirmations of ALREADY-PASSING existing tests** per module (Customer/Supplier/Product/Employee/Chart-of-Account each already have their own equivalent test coverage from PROMPT-007/008/009/025/029) — this spec's genuinely NEW tests are: #10 (master dependency — the Chart-of-Account deactivation-block guard, §17, once built), #13/#14 (effective-dated/versioned master — the UOM-conversion fix, §12/§26, with a test mirroring `salary_structure`'s own existing "later structure doesn't retroactively change an already-calculated payroll run" test pattern, PROMPT-029, applied to UOM conversion instead), #18/#19 (offline stale master — reuses PROMPT-028's own existing sync-rejection test pattern, confirmed already covers this need per §24). #11 (master deletion) is **N/A** — no deletion path exists to test (§10).

## 33. Security Test Cases

Mapped to the source prompt's §44 (1–15) — all 15 are **already covered by each master's own existing RBAC/tenant-isolation test suite** (PROMPT-007/008/009/025/029 each independently built these), EXCEPT #11 (sensitive master export — new, once PROMPT-034's export framework is wired to masters, §20) and #12/#13 (global configuration modification by a tenant user / Platform Admin boundary — both **N/A today**, since no global configuration exists yet; will be covered by PROMPT-030's own security test suite once built, not duplicated here).

## 34. Cross-Module Traceability

| Master | Owner | Scope | Lifecycle | Deletion | Effective-dated | Versioned | Uniqueness | Dependencies | Auth | Audit | Offline |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Customer | Owner/Manager (create/edit); Salesperson create/edit only | Tenant | ACTIVE/INACTIVE | Never | No | No | `(tenant_id, customer_code)` | Referenced by every Sales document | `customers.*` | Full | Read-cache + quick-add (PROMPT-028) |
| Supplier | Owner/Manager; Salesperson create/edit only | Tenant | ACTIVE/INACTIVE | Never | No | No | `(tenant_id, supplier_code)` | Referenced by every Purchase document | `suppliers.*` | Full | Read-cache + quick-add |
| Product | Owner/Manager full; Salesperson view-only | Tenant | ACTIVE/INACTIVE | Never | No (see §12 — snapshotting substitutes) | No | `(tenant_id, sku)` | Referenced by Sales/Purchase lines, Inventory | `products.*` | Full | Read-cache only |
| UOM | Owner/Manager | Tenant | ACTIVE (no deactivate UI) | Never | **Recommended: yes** (§12/§26, new) | **Recommended: yes** (mirrors Salary Structure) | Tenant-scoped code | Product's `base_uom_id` FK | Bundled under `products.*` | Partial (creation only) | None specifically cached |
| Location | System-provisioned | Tenant | Always ACTIVE | N/A | No | No | Single "MAIN" per tenant | Stock Ledger | N/A (no management UI) | Minimal | N/A |
| Chart of Account | Owner/Manager | Tenant | `is_active` | Never | No | No | `(tenant_id, code)` | Journal lines, Account Mappings — **deactivation-block recommended, not yet verified built** | `accounting.*` | Full | None |
| Employee | Owner/Manager | Tenant | ACTIVE/INACTIVE/ON_NOTICE/EXITED | Never | No | No | Permanent `employee_code` (`next_number_no_fy`) | Salary Structure, Attendance, Leave, Payroll Run | `employees.*` | Full | None (PROMPT-029 §61) |
| Salary Component | Owner/Manager | Tenant | `is_active` | Never | No | No | Tenant-scoped code | Salary Structure Lines | Bundled under `salary.*` | Full | None |
| GST Reference | **No real master exists** (§7) | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A |
| HSN | **No real master exists** (§7) | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A |
| Configuration (tenant) | Tenant Owner | Tenant | N/A | N/A | Some fields effectively immediate, some (e.g. GSTIN) recommended Platform-Admin-only per PROMPT-030 §7.4 | No | N/A | Affects every future GST/numbering calculation | `tenant.manage_settings` (PROMPT-030 §15, spec only) | Reserved (PROMPT-030) | N/A |
| Feature Entitlement | Platform Admin | Cross-tenant (target = one tenant) | Boolean per module | N/A | No | No | `(tenant_id, module_code)` (PROMPT-030 §16) | Gates every module's own endpoints | `platform.manage_entitlements` (spec only) | Reserved (PROMPT-030) | N/A |

## 35. Acceptance Criteria

Directly traceable to the source prompt's §45 (1–22) — nearly all are marked MET today by the ALREADY-EXISTING convergent convention this spec documents; items 6/7 (effective dating/versioning "where required") are met EXCEPT for the one identified UOM gap, honestly flagged rather than glossed over. Item 22 ("no critical defects") is deferred to the implementation pass that would build the UOM fix and the unverified Chart-of-Account dependency guard.

## 36. Open Decisions

Directly answering the source prompt's own §46 list (1–23):

| # | Question | Recommended | Owner |
|---|---|---|---|
| 1 | Exact global/reference masters | None needed for M1 (§7) — state validation stays a code-level lookup, not a DB table | Product + Engineering |
| 2 | Exact tenant masters | §8's table — already the complete, converged set | — |
| 3 | GST master ownership | No real GST rate/HSN master exists (§7); `product.gst_rate`/`.hsn_code` stay free-form, blocked on the pre-existing ERD-DEC-05 open item | Product Owner |
| 4 | GST rate versioning mechanism | N/A until #3 is resolved | Product Owner |
| 5 | HSN master ownership | Same as #3/#4 | Product Owner |
| 6 | UOM global vs tenant | Tenant-owned (already the case) | — |
| 7 | Exact location scope | Single-location remains MVP (PROMPT-010 §8, unchanged) — multi-location is a real future feature, not silently expanded here | Product Owner |
| 8 | Product deletion policy | Never delete, deactivate only (already the case) | — |
| 9 | Customer deletion policy | Same | — |
| 10 | Supplier deletion policy | Same | — |
| 11 | Account deletion/deactivation policy | Deactivate only, BUT recommend adding the dependency-block guard (§17) before this can be considered fully safe | Product + Engineering |
| 12 | Employee deletion policy | Never delete — EXITED status is the terminal state (already the case, PROMPT-029) | — |
| 13 | Master import scope | Not MVP (§19) | Product Owner |
| 14 | Master export scope | All masters in §8's table, via PROMPT-034's framework (§20) | Product Owner |
| 15 | Saved master filters | Not MVP (mirrors PROMPT-034's own OD #13) | Product Owner |
| 16 | Effective dating per master | UOM conversion — yes (recommended, §12); everything else — no, snapshotting already substitutes | Engineering Lead |
| 17 | Versioning per master | Salary Structure (existing) + UOM conversion (recommended) only | Engineering Lead |
| 18 | Phone uniqueness | Unchanged existing open item (`phone_uniqueness_scope`, CLAUDE.md §4) | Product Owner |
| 19 | Exact configuration precedence | Deferred to PROMPT-030's own §15 (Global vs Tenant Configuration precedence) — not re-derived here | Product Owner (shared with PROMPT-030) |
| 20 | Offline stale-master behavior | Reject at sync, surfaced as `REQUIRES_ACTION` (§24, already the existing architecture's natural behavior) | — |
| 21 | Master approval workflow | Not MVP — no approved source requires one | Product Owner |
| 22 | Bulk update support | Not MVP — no bulk-update endpoint exists for any master today | Product Owner |
| 23 | Master change approval thresholds | N/A given #21's answer | — |

## 37. Risks

- **The UOM-conversion fix (§12/§26) changes an existing UNIQUE constraint** (`(tenant_id, product_id, from_uom_id, to_uom_id)` → adding `effective_from`) — a real, if small, migration risk touching PROMPT-009's already-shipped, already-tested table; must re-run PROMPT-009's own existing conversion tests after the change, not just add new ones.
- **The Chart-of-Account deactivation-block guard (§17) is RECOMMENDED but its current absence is unverified as a defect** — this research pass did not exhaustively confirm whether `chart_of_accounts_service.py` already has SOME form of this check elsewhere in the file; the implementation pass must first CONFIRM the gap actually exists before building a fix, to avoid duplicating an already-working control.
- **Cross-tenant GSTIN uniqueness (§14) being unenforced** is a genuine, newly-surfaced business-risk question (could two tenants legitimately claim the same real business/GSTIN?) — this is more a PRODUCT question than an engineering one, and resolving it wrong in either direction (enforcing global uniqueness incorrectly, or leaving a real duplicate-tenant-fraud vector open) has real consequences; flagged prominently, not buried.

## 38. Dependencies

- PROMPT-007/008/009/010 (Customer/Supplier/Product/Inventory — the master entities this framework classifies and governs).
- PROMPT-025 (Chart of Accounts — the lazy-seed + deactivation pattern).
- PROMPT-029 (Salary Structure's own effective-dating design — the exact model §12/§26's UOM fix replicates; Employee's own richer lifecycle).
- PROMPT-028 (offline master-data cache — §24's resolution point).
- PROMPT-030-SPECIFICATION.md (Global/Tenant Configuration precedence, Feature Entitlement — reused by reference, §18/§34).
- PROMPT-031-SPECIFICATION.md (audit integration, §22).
- PROMPT-032-SPECIFICATION.md (security model, §23; offline-revalidation rule, §24).
- PROMPT-034-SPECIFICATION.md (search/filter/export framework, §20/§21 — reused directly, not reimplemented).

## 39. Definition of Done (for THIS specification deliverable)

- [x] All 39 sections requested by the source prompt's §48 are present.
- [x] Every claim is grounded in the ACTUAL current codebase — confirmed via direct inspection of `product_unit_conversion.py` (revealing the effective-dating gap), `tenant.py` (revealing the GSTIN cross-tenant-uniqueness question), migration-level `UniqueConstraint` declarations, and `chart_of_accounts_service.py` — nothing asserted without verification, including honest flagging of what could NOT be fully confirmed (the Chart-of-Account dependency guard).
- [x] Every open decision from the source prompt's §46 is answered with Question/Recommended/Owner; several correctly cross-reference PROMPT-030/034 rather than re-deriving shared decisions.
- [x] One genuine, concrete finding (UOM conversion's missing effective-dating) is identified, precisely scoped (financial/stock correctness is NOT at risk — only display fidelity for reprinted historical documents), and given a low-cost fix reusing an already-proven pattern from this same codebase.
- [x] This spec correctly recognizes and DOCUMENTS an already-converged, consistent convention rather than inventing a new one where none was needed — the majority of this codebase's master-data governance was already correct BEFORE this prompt, verified rather than assumed.
- [ ] **Not done, and not in scope for this deliverable**: actual implementation (the `product_unit_conversion.effective_from` migration + lookup-logic change, the Chart-of-Account dependency-guard verification/build, wiring PROMPT-034's export framework onto every master). Per the source prompt's own framing (§48 "Produce the final implementation specification," §49's spec-readiness Definition of Done, and the same absent "implement/STOP" language as PROMPT-030–034), this document is the planning artifact for a future implementation pass.
