# PROMPT-034 — Search, Filter, Pagination, Sorting & Export Framework

**Document type:** Development specification & implementation plan (per §51 — same pattern as PROMPT-030–033: no "implement" instruction, no "STOP before PROMPT-035" directive; §52's Definition of Done is spec-readiness framed). **No application code was written for this deliverable.**

**Baseline used:** the actual current codebase after PROMPT-001–033 (030–033 were also spec-only). Verified by direct inspection of `app/api/v1/customers.py`, `app/services/customers/customer_service.py`, `app/services/sales/sales_invoice_service.py`, `app/schemas/envelopes.py`, a codebase-wide search for `sort_by`/`order_by`/`ilike`/`pg_trgm`, and PROMPT-026/027/031-SPECIFICATION.md (cross-referenced for GST/Reports/Audit export precedent).

---

## 1. Requirement Understanding

PROMPT-034 asks for a centralized search/filter/sort/pagination/export framework. The grounding pass reveals this codebase's list-endpoint behavior is **functional but ad hoc and duplicated, not centralized** — every one of the ~25 list endpoints built since PROMPT-007 hand-rolls its own `page`/`page_size` clamping, its own `search` ILIKE construction, and its own fixed default ordering, independently, with no shared dependency or base class. Two concrete, codebase-wide facts anchor this spec:

1. **Zero server-side sorting exists anywhere.** A codebase-wide search for `sort_by`/`sort_order` across all 30+ API routers returns nothing. Every list endpoint returns rows in ONE hard-coded order (verified: `Customer` list orders by `created_at.desc()`; `SalesInvoice` list also `created_at.desc()`) — a user cannot sort a customer list by name, a sales list by amount, or anything else, anywhere in this application today.
2. **Search uses unindexed leading-wildcard `ILIKE '%term%'`** (verified in `customer_service.py`: `Customer.name.ilike(f"%{search}%")`, OR'd across name/code/GSTIN/phone) with **no supporting index beyond `tenant_id`** — acceptable at current MVP per-tenant row counts (hundreds to low-thousands), but exactly the pattern §5 of the source prompt names as a performance risk at scale, and precisely the kind of finding this spec must document honestly rather than pretend is already optimized.

Everything else the framework needs (pagination shape, the `{data, pagination, meta}` envelope, per-endpoint `page_size` clamping to a 1-100 range, `tenant_id` always server-derived) already exists and is CONSISTENT across modules by convention, even though it's not literally shared code — this spec's job is to formalize that convention into real shared infrastructure (a dependency/base-query-builder), close the sorting gap, and define export (which barely exists at all — only Reports/GST have JSON export, PROMPT-026/027).

## 2. Objective

Extract the ALREADY-CONSISTENT-BY-CONVENTION list-query pattern into real, shared, reusable server-side infrastructure (`app/core/list_query.py`): a `ListQueryParams` dependency (pagination clamping + an allowlisted sort-field mechanism, closing the §1 gap), a generic `apply_search`/`apply_sort`/`paginate` helper set services opt into, and a companion `ExportService` that reuses each module's EXISTING list-query logic (never a parallel calculation) to produce CSV/JSON exports respecting the caller's own filters.

## 3. Scope

- A shared pagination/sort/search query-parameter contract (`app/core/list_query.py`), retrofitted onto EVERY existing list endpoint without changing their external API shape (same query param names, same response envelope — purely an internal refactor + the NEW addition of `sort_by`/`sort_order` support).
- A formal, per-module ALLOWLIST of searchable/sortable/filterable fields (documented in this spec's §7/§35 Cross-Module Matrix, implemented as a small per-module constant).
- CSV export (the only NEW format this spec adds broadly) for every list endpoint named in §6/§43, reusing that SAME endpoint's own query-building logic — never a separate export calculation.
- Extending PROMPT-026/027's existing JSON export pattern for GST/Reports, not replacing it.
- Basic date-range and financial-year filter helpers, reusing the ALREADY-EXISTING `financial_year_start_month` logic (`dashboard_service.py`/`document_numbering_service.py`), not reinventing it.
- Audit integration (`EXPORT_REQUESTED`/`_COMPLETED`/`_DOWNLOADED`) via PROMPT-031's existing `AuditService`.

## 4. Out of Scope

- Cursor-based pagination — offset/limit is retained for M1 across every module, including Audit (once PROMPT-031 is implemented) and Inventory movements; justified in §15 below, not silently assumed.
- Full-text search / search-relevance ranking / a dedicated search engine (Elasticsearch, Postgres `tsvector`) — out of scope for MVP row counts; `pg_trgm` GIN indexes are the recommended NEXT step if row counts grow, not built now (Open Decision #1/#24).
- Excel/PDF export for anything beyond what's individually justified per module in §43 — CSV is the default new format; Excel requires a new dependency, not added without approval (Open Decision #11).
- Saved filters, column selection, grouping — all explicitly optional per §3/§30 of the source prompt and not built for M1 (Open Decisions #13/#15).
- Asynchronous/job-based export — given this MVP's per-tenant data volumes (confirmed via every prior prompt's own scale assumptions — hundreds to low-thousands of rows per tenant, not millions), synchronous export is sufficient for M1 (Open Decision #7/#8, resolved not silently assumed).
- Real-time/live-updating lists (WebSocket push) — §40's "refresh behavior" is satisfied by a manual refresh action, not automatic push (no such infrastructure exists anywhere in this codebase).

## 5. Core Principles

The source prompt's 18 principles (§2), checked against real code:

| # | Principle | Status |
|---|---|---|
| 1-4 | Server-side search/filter/pagination/authorization | **Already true**, verified across every list endpoint reviewed |
| 5 | Tenant isolation on every query | **Already true** — RLS + explicit `tenant_id` filter, double-enforced (PROMPT-032 §10) |
| 6 | Never trust frontend tenant_id | **Already true** |
| 7 | Never return unauthorized records via search match | **Already true** — search is applied WITHIN the tenant-scoped, permission-gated query, never a separate unscoped search step |
| 8 | No unrestricted dataset exposure | **Already true** via `page_size` clamping |
| 9 | Max page-size limit | **Already true, but duplicated** — the SAME `min(max(page_size, 1), 100)` clamp is copy-pasted into ~25 router functions (verified) rather than shared |
| 10 | Export limits / async for large datasets | **N/A today** — almost no export exists yet to limit |
| 11 | Indexed fields for common searches | **Partial** — `tenant_id` indexed everywhere; name/code/GSTIN/phone search fields are NOT indexed (the §1 finding) |
| 12 | Avoid expensive unbounded queries | **Already true** — every list is paginated, no endpoint returns an unbounded result set |
| 13 | Consistent search/filter behavior across modules | **Consistent BY CONVENTION, not by shared code** — the exact gap this spec closes |
| 14 | Export uses same authoritative dataset/filter logic as UI | Will be true by construction once `ExportService` reuses each list endpoint's own query builder (§19) |
| 15 | Financial reports use authoritative calculations | **Already true** — PROMPT-027's own "never a second source of truth" discipline, unaffected by this spec |
| 16 | Sensitive fields excluded from unauthorized exports | Will be true by construction — export reuses the SAME field-serialization/permission gate as the list endpoint (§20) |
| 17 | Mobile UX usable | Addressed in §30, reusing this codebase's own proven responsive patterns |
| 18 | No duplicate calculations in export logic | Central design constraint of §19/§23 |

## 6. Search Architecture

`app/core/list_query.py` (new): a generic `apply_text_search(query, model, fields: list[InstrumentedAttribute], term: str)` helper that builds the SAME `or_(...).ilike(f"%{term}%")` pattern every module already hand-writes today — centralizing the PATTERN (so a future performance fix, e.g. switching to `pg_trgm`'s `%` similarity operator, is a ONE-PLACE change) without changing behavior yet. Each service continues to declare ITS OWN allowlisted field list (§7) — the helper takes an explicit list, it never introspects a model's columns automatically (§4's own "do not automatically search every database column" is a design constraint on the helper's own API, not just a policy).

## 7. Searchable Fields

Per the source prompt's §6, cross-referenced against what's ALREADY implemented vs. genuinely new:

| Module | Search fields (existing/verified or newly specified) | Match type |
|---|---|---|
| Customers | name, customer_code, GSTIN, phone | **Already implemented**, verbatim |
| Suppliers | name, supplier_code, GSTIN, phone | **Already implemented** (mirrors Customer) |
| Products | product name, SKU, HSN | *New* — not verified as implemented; specified here for the retrofit pass |
| Sales (per document type) | document number, customer name (join), reference | **Partially implemented** — `search` param exists on `SalesInvoice.list_invoices` (verified) but its exact field set needs confirmation at implementation time; specified here as the target |
| Purchase | document number, supplier name (join), reference | Same pattern |
| Payments | payment number, customer/supplier name (join), reference | *New* |
| Inventory | product name, SKU, stock reference | *New* |
| Accounting | journal number, account name, reference | *New* |
| GST | document number, GSTIN, transaction reference | *New* |
| Payroll | employee name, employee code | *New* |
| Audit (once PROMPT-031 ships) | entity_id, actor, correlation_id, action | Specified in PROMPT-031-SPECIFICATION.md §19 already — reused, not redefined |
| Platform Admin (once PROMPT-030 ships) | tenant id, business name, GSTIN, owner | Specified in PROMPT-030-SPECIFICATION.md §7.2 already — reused |

All matches are **case-insensitive partial (`ILIKE`)**, minimum 1 character (no artificial minimum-length gate exists today and none is recommended — Open Decision #2, resolved as "no minimum" given small per-tenant datasets make even a 1-character search cheap). Exact-match fields (GSTIN, employee code, document numbers when a FULL number is pasted) still go through the same `ILIKE` path for simplicity — a genuinely exact-match-only mode is not built (would need a second parameter to distinguish "search" from "exact lookup," not justified at MVP scale).

## 8. Filter Architecture

The filter TYPES the source prompt's §7 lists (Text/Number/Currency/Date/Date range/Enum/Status/Boolean/User/Customer/Supplier/Product/Location/Account/Employee) already exist IMPLICITLY as typed Pydantic query parameters on each router (e.g. `Customer`'s `status: str | None`, `gst_registered: bool | None`) — this spec does not invent a generic "filter DSL" (§11's own "do not allow arbitrary query expressions from frontend users" is exactly why: a named, typed, per-endpoint query parameter is inherently safer than a generic filter-expression parser, since there's no expression grammar to ever misuse). Each module's own filter set is documented in §35 (Cross-Module Matrix) as the concrete allowlist.

## 9. Filter Types

Each filter type maps to a plain, named FastAPI query parameter with its own Pydantic type (already the established pattern) — never a generic `filters: dict` blob accepted from the client:
- Enum/Status → `Literal[...]` or validated against the module's own status constant set (e.g. `SALES_INVOICE_STATUSES`, already defined per PROMPT-015).
- Date/Date range → `date | None` pairs (`date_from`, `date_to`), validated `date_from <= date_to` server-side (400 `FLT-003 INVALID_DATE_RANGE` otherwise — new, not built anywhere today, since almost no module currently exposes a date-range filter at all).
- Entity references (Customer/Supplier/Product/Account/Employee filters) → a `UUID` query parameter, validated to belong to the SAME tenant before being used in the query (§12's own "referenced entity belongs to the same tenant" — closes a real, currently-untested gap: e.g. `GET /sales/invoices?customer_id=<another tenant's customer id>` today would likely just return zero rows because the JOIN's own tenant-scoping excludes it, which is SAFE but should be verified with a dedicated test, not just assumed).

## 10. Date Filtering

New shared helper, `app/core/date_ranges.py::resolve_named_range(name: Literal["today","yesterday","this_week","this_month","previous_month","this_fy","custom"], tenant_fy_start_month: int) -> tuple[date, date]` — reuses the tenant's OWN `financial_year_start_month` (already on the `tenant` model, already read by `dashboard_service.py`/`document_numbering_service.py`) rather than hard-coding April. **Authoritative date field is EXPLICITLY named per module, never assumed** (§8's own instruction): Sales Invoice filters by `invoice_date` (not `created_at`) by default, Payment by `payment_date`, Journal by `posting_date`/`entry_date` (whichever the actual column is named — to confirm at implementation time) — this spec requires each module's own date-filter parameter to be EXPLICITLY documented (§35) rather than silently defaulting to `created_at` everywhere, which would conflate "when the record was created in the system" with "the business date it represents" (a real distinction, e.g. an invoice dated for yesterday but entered today). All comparisons happen server-side against UTC-stored `TIMESTAMPTZ`/`DATE` columns — no client-side date math is trusted (§8's own instruction, already this codebase's universal practice per PROMPT-018's "never trust client timestamp" precedent, PROMPT-032 §18).

## 11. Status Filtering

No new status values are invented anywhere — every module's `status` filter parameter is validated against THAT module's own already-defined status constant set (`SALES_INVOICE_STATUSES`, `PAYMENT_STATUSES`, etc. — all already exist as Python `frozenset`s per module, PROMPT-015/024/etc.) — an invalid status value returns 400 `FLT-002 INVALID_FILTER_VALUE`, not a silent empty result. Tenant status (`ACTIVE`/`SUSPENDED`/`DISABLED`) and Document-generation status (`REQUESTED`/`PROCESSING`/`COMPLETED`/`FAILED`) are defined in PROMPT-030/033-SPECIFICATION.md respectively — reused here, not redefined, once those modules ship.

## 12. Sorting

**The genuinely new capability** (§1's central finding). New shared dependency:

```python
def sortable(allowed: dict[str, InstrumentedAttribute], default: str):
    def _dep(sort_by: str | None = None, sort_order: Literal["asc", "desc"] = "asc"):
        field = allowed.get(sort_by or default)
        if sort_by and sort_by not in allowed:
            raise ValidationError("Invalid sort field", code="SORT-001")
        return field, sort_order
    return _dep
```

`allowed` is an EXPLICIT per-module dict (e.g. `{"name": Customer.name, "created_at": Customer.created_at, "customer_code": Customer.customer_code}`) — **never** a raw client-supplied string concatenated into an `order_by()` call (§13's own explicit warning, and this design makes that mistake structurally impossible: the client's string is a DICTIONARY KEY lookup, never interpolated into SQL). An unrecognized `sort_by` value is a 400, not a silent fallback to default (clearer to the API consumer/frontend than silently ignoring their request).

## 13. Stable Sorting

Every sort ALWAYS appends `id` (or `created_at, id` where the primary sort isn't already `created_at`) as a deterministic tiebreaker — e.g. `order_by(Customer.name.asc(), Customer.id.asc())`, never `order_by(Customer.name.asc())` alone. This closes a genuine, currently-latent bug risk: today's hard-coded `order_by(created_at.desc())` on several tables has NO secondary sort either (verified: `SalesInvoice.list_invoices` line 240 is exactly `.order_by(SalesInvoice.created_at.desc())`, no id tiebreaker) — two invoices created in the same microsecond (unlikely but not impossible under concurrent posting) could theoretically page inconsistently. Flagged as a small, real defect worth fixing during the retrofit, not just a theoretical concern invented for this spec.

## 14. Pagination

Retains the EXISTING, already-consistent shape exactly: `page` (default 1), `page_size` (default 25, clamped `[1, 100]`) — centralized into ONE shared dependency (`PageParams`) instead of the ~25 duplicated inline `min(max(page_size, 1), 100)` clamps found today. No behavior change for existing API consumers (the frontend), purely a server-side de-duplication.

## 15. Cursor Pagination Evaluation

**Explicitly evaluated and rejected for M1, across every candidate the source prompt names** (Audit logs, Inventory movements, large transaction lists, integration logs): every one of these tables, even at this MVP's most audit-heavy tenant, is expected to hold at most tens of thousands of rows per tenant in year one (a wholesale distributor posting ~50-200 transactions/day → ~20-70k rows/year) — offset pagination's own known weakness (a large `OFFSET` value scanning-and-discarding preceding rows) only becomes materially slow at offsets in the hundreds of thousands to millions, well beyond this MVP's realistic per-tenant scale within its first several years. Cursor pagination adds real API-contract complexity (opaque cursor tokens, no "jump to page N," different response shape per §19) for a performance problem this MVP does not have yet. **Documented, not silently assumed** — Open Decision #5 names the exact row-count threshold (recommended: revisit if any single tenant's `audit_log` or `stock_ledger_entry` exceeds ~500,000 rows) at which cursor pagination should be reconsidered.

## 16. API Response Contract

Extends the EXISTING `ListResponse`/`Pagination` envelope (`app/schemas/envelopes.py`, unchanged shape: `{data, pagination: {page, page_size, total_items, total_pages}, meta}`) with two ADDITIVE, optional fields the source prompt's own §19 example includes but this codebase's current envelope lacks: `filters` (an echo of the resolved, validated filter values actually applied — useful for a frontend confirming what's active) and `sort` (`{sort_by, sort_order}` actually applied, including the resolved DEFAULT when the client didn't specify one). Both are OPTIONAL additions to `ListResponse` — no existing consumer breaks, since a new key appearing in a JSON response is backward-compatible by construction (no existing frontend code reads a field that would conflict). `has_next`/`has_previous`/`total_records` naming from the source prof's own example is NOT adopted verbatim — this codebase's EXISTING `total_items`/`total_pages` naming is kept (renaming would be a breaking change to ~25 already-shipped frontend consumers for zero functional benefit).

## 17. Tenant Isolation

Unchanged, already correct (PROMPT-032 §10) — every query built by the new shared helpers still takes `tenant_id` as an explicit, server-derived parameter, RLS remains the second independent layer. The framework does not introduce any new way to bypass this — `apply_text_search`/`sortable`/`PageParams` all operate on an ALREADY tenant-scoped base query, never construct their own.

## 18. Authorization

Unchanged — `require_permission()` remains the gate on every list endpoint, applied BEFORE any of this framework's helpers run (the existing dependency-injection order). Module Entitlement (PROMPT-030's future layer) and Object-Level checks (already covered per PROMPT-032 §12) compose the same way they already do; this spec adds no new authorization concept, only query-shaping helpers that run downstream of authorization, never in place of it.

## 19. Export Architecture

**The most substantively NEW capability besides sorting.** `app/services/shared/export_service.py::export_to_csv(query, columns: dict[str, Callable])` — takes the SAME SQLAlchemy query object a list endpoint's OWN service method already builds (after search/filter/sort are applied, WITHOUT the `.limit()`/`.offset()` pagination step) and streams it into CSV, with `columns` an explicit allowlist of `{header: extractor_function}` pairs (§16 of the source prompt — never a blind row-to-dict dump that could leak an unlisted sensitive column). This directly satisfies §14/§18/§23 of the source prompt: **export literally reuses the list endpoint's own query-building code path**, diverging only at the pagination step (export runs the query unpaginated, up to a row cap, §26) — there is no second, parallel calculation anywhere.

New endpoint shape (one per module, following the existing per-module router convention rather than a single generic `/export?entity=` endpoint, which would need its own permission-mapping logic and is a needless abstraction over ~12 already-distinct, already-permission-gated routers):

```
GET /api/v1/customers/export?search=...&status=...      (same query params as GET /customers)
GET /api/v1/sales/invoices/export?...
GET /api/v1/purchase/invoices/export?...
... one per module named in §43
```

## 20. Export Security

Export requires the SAME permission as the list endpoint it mirrors PLUS a new, distinct `<module>.export` permission (e.g. `customers.export`, `sales_invoice.export`) — a two-permission gate (view + export), matching PROMPT-030/031's own established "a narrower permission for a more sensitive action" pattern (e.g. `salary.view` vs `salary.manage`, PROMPT-029). **Payroll export requires `payroll.export`** (already exists as a defined-but-unused permission per PROMPT-029's own 16-code set — CONFIRMED reusable, not new) — closing the exact "payroll exports require appropriate permissions" requirement (§24) with an ALREADY-EXISTING permission rather than inventing one. Sensitive columns (bank account numbers, salary figures beyond what `payroll.export`'s own holder is authorized to see) are excluded from the `columns` allowlist by construction (§19's own design), not filtered post-hoc.

## 21. Large Export Processing

**Synchronous only for M1** (§4 Out of Scope, Open Decision #7/#8) — a hard row cap (recommended 10,000 rows, Open Decision #6) is enforced BEFORE the query even runs (a `COUNT(*)` check against the SAME filtered query; exceeding the cap returns 422 `EXP-002 EXPORT_TOO_LARGE` with a message asking the user to narrow their filters, rather than silently truncating or timing out mid-stream). The REQUESTED→PROCESSING→COMPLETED/FAILED/EXPIRED job lifecycle the source prompt's own §25 describes is **not built** — no background-job infrastructure exists anywhere in this codebase (the same confirmed absence every PROMPT-018/028/031/033 spec has independently found) — flagged, not silently assumed away.

## 22. Export Auditing

Reuses PROMPT-031's `AuditService` directly: `EXPORT_REQUESTED` is NOT separately audited (the request and its completion are the same synchronous HTTP call, §21 — there's no meaningful gap between "requested" and "completed" to log twice) — only `EXPORT_COMPLETED` (actor, tenant, module, applied filters as `metadata`, row count, timestamp) and `EXPORT_FAILED` (e.g. row-cap exceeded) are written, mirroring PROMPT-033 §18's own "audit the sensitive subset, not every read" reasoning. `EXPORT_DOWNLOADED` is not a separate event either — for a synchronous CSV response, the HTTP response body IS the download; there's no separate download step to distinguish from completion (unlike PROMPT-033's browser-print-then-separately-download flow, which genuinely has two distinct user actions).

## 23. Report Export

Unchanged from PROMPT-027's own already-correct design — GST/Financial report export continues to call the SAME `app/services/reports/*.py`/`GstrService` methods the on-screen report itself calls (verified, PROMPT-026/027's own "never a second calculation" discipline). This spec's `export_to_csv` helper is available to Reports too (e.g. a CSV variant of the currently-JSON-only Sales Register), but does NOT change how the underlying figures are computed.

## 24. Column Security

Every export's `columns` allowlist (§19) is a per-module, hand-authored mapping — the SAME discipline as PROMPT-031 §15's before/after snapshot allowlist ("never `record.__dict__`, always named fields"). A column existing in the database is NEVER sufficient for it to be exportable — it must be explicitly added to that module's `columns` dict, mirroring the exact reasoning PROMPT-029's `salary.view`/`employees.view` split already established for API responses generally.

## 25. Saved Filters

**Not built for M1** (Open Decision #13) — no product requirement document approves this, and the source prompt itself marks it optional (§30/§3). If approved later: ownership would default to per-USER (not per-tenant-shared), mirroring how `hasPermission()`-gated UI state is already user-scoped everywhere else in this codebase; a `saved_filter` table would need `tenant_id` + `user_id` + `module` + a JSONB `filter_state` column, RLS-enabled like every other tenant-owned table — sketched here for a future prompt, not built now.

## 26. URL Filter State

Frontend concern, not requiring new backend API — non-sensitive filters (status, date range, search term) already CAN be reflected in the URL query string using React Router/URLSearchParams (no framework change needed) as a frontend-only enhancement; **payroll-sensitive filters (e.g. an employee_id filter on a salary-figure list) must NOT go in the URL** (§31's own instruction) — recommended as a frontend convention (documented here, enforced by code review, not a runtime backend check, since the backend cannot see whether a value arrived via query-string or a POST body).

## 27. Database Query Strategy

Every new helper (`apply_text_search`, `sortable`, `PageParams`) builds exclusively through SQLAlchemy's query-builder API — no raw SQL string construction is introduced anywhere (preserving PROMPT-032 §13's own "zero raw string-interpolated SQL" verified property). The `sortable()` dependency's dictionary-lookup design (§12) is the SPECIFIC mechanism that prevents the "arbitrary column sorting"/"unrestricted joins" risks named in §33 — a client can only ever select from a finite, hand-authored set of `InstrumentedAttribute` objects, never name an arbitrary table/column string that reaches the query builder.

## 28. Index Strategy

New indexes, justified individually (per §44's own instruction — not blindly added to every field):

| Table.column | Query pattern it serves | Justification |
|---|---|---|
| `sales_invoice.invoice_date`, `purchase_invoice.invoice_date`, `payment.payment_date` | New date-range filters (§10) — none of these are currently indexed beyond `tenant_id` | Real new query shape this spec introduces; without an index, a date-range filter combined with a large `page_size`-1 export would force a sequential scan within the tenant partition |
| `customer.name`, `supplier.name`, `product.product_name` (plain B-tree) | Sorting by name (§12, a genuinely new capability) | A B-tree ASC index on the sort column directly serves `ORDER BY name` — cheap, standard, and ALSO the natural extension of the currently-nonexistent-but-implied need |
| **NOT added**: `pg_trgm` GIN indexes on the existing ILIKE search fields | Search performance (§5's own concern) | **Deliberately deferred** — current per-tenant row counts don't need it yet (§1); recommended as the trigger-point fix if/when a tenant's customer/product table exceeds ~10,000 rows (Open Decision #24), not added speculatively now (§44's own "do not add indexes to every searchable field automatically") |

Every new index's write-overhead is bounded — these are all single-column indexes on already-existing columns being written to at normal document-creation frequency (a handful of writes per index per transaction, not a composite/multi-column index with higher maintenance cost).

## 29. Offline Behavior

Per §41 of the source prompt, cross-referenced against PROMPT-028's real architecture: offline search/filter is **entirely client-side, against whatever `masterDataCache.ts` has cached** (Customer/Supplier/Product read-caches, PROMPT-028) — this is NOT the server-side framework this spec builds; it's a SEPARATE, already-existing, narrower client-side lookup used only within the offline invoice-capture flow. The UI must show "Offline — showing available local data" (verbatim, per §41) whenever a search/filter/list view is rendered from the offline cache rather than a live server response — this is a NEW, small UI addition (no such indicator currently exists on `OfflineInvoiceCapture.tsx`'s own customer-picker, confirmed not built) rather than a backend change.

## 30. Responsive UX

Reuses this codebase's own proven, repeatedly-applied responsive convention (Reports/Accounting/GST/Payroll/Purchase screens): desktop gets a full filter toolbar + data table (`hidden md:block`), mobile gets a search bar + a "Filters" button opening a bottom-drawer + applied-filter chips + a stacked card list (`md:hidden`) — exactly the layout the source prompt's own §34 ASCII example describes, and exactly what this codebase already does for every list screen built since PROMPT-025. **No new responsive pattern is introduced** — the NEW pieces (a sort control, export button, applied-filter chips reflecting the newly-added sort/date-range filters) slot into the EXISTING shell.

## 31. Accessibility

Sort-column headers become clickable buttons with `aria-sort` attributes (`ascending`/`descending`/`none`) — a genuinely new a11y consideration since sorting itself is new (§12); filter drawer/modal traps focus appropriately (standard modal a11y, already the pattern this codebase's existing modals use); "Clear Filters" and "Export" remain plain, labeled `<button>` elements consistent with PROMPT-032 §31's own accessibility baseline.

## 32. Error Handling

New error codes (prefixes `FLT-`/`SORT-`/`EXP-`, confirmed no collision against the existing prefix list):

| Code | Meaning |
|---|---|
| `FLT-001` | `INVALID_FILTER` (an unrecognized filter parameter for that module) |
| `FLT-002` | `INVALID_FILTER_VALUE` (e.g. an unrecognized status enum value) |
| `FLT-003` | `INVALID_DATE_RANGE` (`date_from > date_to`) |
| `SORT-001` | `INVALID_SORT_FIELD` |
| `SORT-002` | `INVALID_SORT_ORDER` (not `asc`/`desc`) |
| `PAGE-001` | `INVALID_PAGE_SIZE` (non-positive) — clamped, not rejected, per the EXISTING behavior (`min(max(...))`), so this code is defined for completeness but likely never actually raised, since the existing convention silently clamps rather than errors; flagged as a design choice to CONFIRM, not silently change (clamping vs. rejecting is itself a judgment call, and changing existing clamp-based endpoints to reject would be a breaking API change) |
| `EXP-001` | `EXPORT_NOT_ALLOWED` (missing `<module>.export` permission) |
| `EXP-002` | `EXPORT_TOO_LARGE` (row cap exceeded, §21) |
| `EXP-003` | `EXPORT_JOB_FAILED` — reserved for a future async implementation; not raised in M1's synchronous path (an export either completes or raises a normal 4xx/5xx, there's no distinct "job failed" state to report) |

`RESOURCE_NOT_AUTHORIZED`/`TENANT_ACCESS_DENIED`/`QUERY_TOO_COMPLEX`/`REQUEST_TIMEOUT` (from the source prompt's own §42 list) reuse EXISTING generic error codes (`AuthorizationError`, tenant-scoped 404, and — for `QUERY_TOO_COMPLEX`/`REQUEST_TIMEOUT` — **no query-complexity analyzer or request-timeout middleware exists anywhere in this codebase** (confirmed, the same gap PROMPT-032 §29 already flagged) — these two codes are DEFINED here for completeness but have no enforcement mechanism to raise them yet; listed as a genuine, named gap (Open Decision, cross-referenced to PROMPT-032's own DoS findings) rather than silently omitted.

## 33. Performance Requirements

No formal load-testing infrastructure exists in this codebase today (confirmed — no k6/Locust/JMeter config found anywhere) — §45's own 100/1,000/10,000/100,000-record benchmarks are **not currently executable** without first building that tooling, which is itself out of scope for a specification document. This spec RECOMMENDS (not asserts as done): a lightweight seed-script + `EXPLAIN ANALYZE` pass on the customer/sales-invoice list query at 1,000 and 10,000 rows per tenant BEFORE this framework ships, specifically to confirm whether the §28 index additions are sufficient or whether the `pg_trgm` deferral (§28) needs to be pulled forward. Flagged as a pre-implementation verification task, not a promise this document itself fulfills.

## 34. API Specification

Representative contract (identical shape repeats per module, per §43's own "reuse the common contract wherever possible" instruction):

```
GET /api/v1/customers
  ?search=...&status=...&state_code=...&gst_registered=...
  &sort_by=name&sort_order=asc            [NEW]
  &page=1&page_size=25

GET /api/v1/customers/export              [NEW]
  ?<same filter params as above>
  → 200, Content-Type: text/csv, Content-Disposition: attachment; filename="customers-<date>.csv"
  → 403 EXP-001 if caller lacks customers.export
  → 422 EXP-002 if the filtered row count exceeds the cap
```

Every module in §43's own list (Customer/Supplier/Product/Sales/Purchase/Payment/Inventory/Accounting/GST/Payroll/Audit/Tenant) gets the IDENTICAL query-parameter shape for pagination/sort (`page`, `page_size`, `sort_by`, `sort_order`) plus its OWN documented filter set (§35) — never a bespoke pagination/sort contract per module.

## 35. Database Impact

**No new tables** — this entire framework is query-shaping infrastructure (shared Python helpers) plus a small number of justified indexes (§28). The one exception: IF Saved Filters is ever approved (§25, not built now), that would be the only new table this framework family would ever need.

## 36. QA Test Cases

Mapped to the source prompt's §47 groups — SEARCH (exact/partial/case/special-char/Unicode/no-result/min-length/debounce — debounce is a FRONTEND concern, not tested server-side; min-length is N/A per §7's "no minimum" resolution), FILTER (single/multiple/date/date-range/status/numeric/invalid/clear — "clear filters" resets to page 1, a NEW assertion this spec introduces since it's the first time pagination-reset-on-filter-change (§39 of the source prompt) is being formally specified, though it's likely already the de facto frontend behavior), SORT (asc/desc/invalid-field/stable-sort — the NEW `id`-tiebreaker test, §13), PAGINATION (first/last/next/previous/page-size/page-size-limit/filter-while-on-later-page — a NEW test confirming applying a NEW filter while on page 8 correctly returns to page 1, not an empty page 8), EXPORT (CSV/filtered-export/unauthorized-export/large-export/secure-download — "secure download" reduces to "the export endpoint enforces the SAME permission+tenant checks as its sibling list endpoint," a regression-style test reusing each module's EXISTING RBAC test fixtures), RESPONSIVE (desktop/tablet/mobile, same documented smoke-test limitation as every prior spec in this session).

## 37. Security Test Cases

Mapped to the source prompt's §46 (1–16):
1-3 (cross-tenant search/filter/export) — **already prevented by construction** (tenant-scoped base query, §17), reused RBAC/tenant-isolation test fixtures apply directly, new export-specific variants added.
4-5 (unauthorized payroll export, unauthorized accounting search) — new tests confirming `payroll.export`/`accounting.view_journals` gates hold for the NEW export endpoints specifically (not just the existing list endpoints).
6-9 (sort-field injection, SQL injection via search/filter/sort) — **structurally prevented**: `sortable()`'s dictionary-lookup design (§12/§27) makes sort-field injection impossible by construction (there's no string concatenation path to inject into); search/filter already go through parameterized SQLAlchemy `ilike()`/comparison operators, unchanged by this spec.
10. Excessive page size — already clamped (§14), regression test.
11. Unbounded query — the NEW export row-cap (§21) is the specific new control to test here (the list endpoint was already bounded via pagination).
12. Unauthorized columns — the `columns` allowlist (§19/§24) is the control; test asserts a deliberately-sensitive field (e.g. `password_hash`, `bank_account_number`) is STRUCTURALLY ABSENT from every module's `columns` dict (a code-level assertion, not just a runtime test).
13. Sensitive fields in exports — same as #12, applied per-module (e.g. confirm the Payroll export never includes `bank_account_number` even though `salary.export` might exist).
14. Audit export access — confirms export of the audit list itself (once PROMPT-031 ships) is gated by `audit.export` (already specified in PROMPT-031-SPECIFICATION.md §19), not a new `<module>.export` permission separate from that spec's own design.
15. Cross-tenant saved filters — **N/A**, not built (§25).
16. Offline unauthorized cached data access — reuses PROMPT-028's own existing offline-scope tests; this spec adds no new offline data path.

## 38. Cross-Module Traceability

| Module | Search fields | Filter fields | Sort fields (NEW capability) | Default sort | Pagination | Export formats | Export permission | Sensitive fields excluded | Offline | Audit |
|---|---|---|---|---|---|---|---|---|---|---|
| Customer | name, code, GSTIN, phone | status, state_code, gst_registered | name, code, created_at | name ASC | Offset | CSV | `customers.export` (new) | — | Read-cache only | `EXPORT_COMPLETED` on export |
| Supplier | name, code, GSTIN, phone | status, state_code | name, code, created_at | name ASC | Offset | CSV | `suppliers.export` (new) | — | Read-cache only | Same |
| Product | name, SKU, HSN | status, category(if any) | name, SKU, created_at | product name ASC | Offset | CSV | `products.export` (new) | — | Read-cache only | Same |
| Inventory | product, SKU, stock reference | date range, location | product name, quantity, date | date DESC | Offset | CSV | `inventory.export` (new) | — | N/A | Same |
| Sales (each doc type) | doc number, customer, reference | status, date range, customer_id | invoice/doc date, doc number, grand_total, created_at | invoice date DESC | Offset | CSV | `sales_invoice.export` etc. (new, per doc type) | — | Sales Invoice creation only (PROMPT-028) | Same |
| Purchase (each doc type) | doc number, supplier, reference | status, date range, supplier_id | same shape as Sales | invoice date DESC | Offset | CSV | `purchase_invoice.export` etc. (new) | — | None | Same |
| Payments | payment number, party, reference | method, status, date range | payment date, amount, created_at | payment date DESC | Offset | CSV | `customer_receipt.export`/`supplier_payment.export` (new) | — | None | Same |
| Accounting | journal number, account name, reference | date range, account | posting date, journal number | journal date DESC | Offset | CSV | `accounting.export` (new) | — | None | Same |
| GST | doc number, GSTIN, txn reference | period, GSTIN | date | date DESC | Offset | JSON (existing) + CSV (new) | `gst.export` (existing, PROMPT-026) | — | None | Same |
| E-Invoice/E-Way Bill | IRN, doc reference | status, date range | generated_at | generated_at DESC | Offset | CSV (new) | `einvoice.export`/`eway_bill.export` (new) | — | None | Same |
| Payroll | employee name, employee code | period, status | employee name, net_salary, created_at | employee name ASC | Offset | CSV | `payroll.export` (**already exists**, PROMPT-029) | bank account number, PAN (if ever added) | None | `EXPORT_COMPLETED` written to real `audit_log` (sensitive) |
| Reports | N/A (aggregate, not row-list) | date range, FY | N/A | N/A | N/A | JSON (existing) + CSV (new, selected reports) | `reports.export` (**already exists but unused**, PROMPT-027 — now wired) | — | None | Existing PROMPT-027 non-audit decision unchanged |
| Audit (PROMPT-031) | entity_id, actor, correlation_id, action | category, date range, result | occurred_at | occurred_at DESC | Offset (PROMPT-031's own §15 evaluated cursor and offset was NOT the conclusion there — cross-reference: PROMPT-031-SPECIFICATION.md doesn't explicitly re-litigate cursor-vs-offset, so THIS spec's §15 evaluation is the authoritative one for Audit too) | CSV/JSON (PROMPT-031 §24) | `audit.export` (PROMPT-031 §19) | Redacted fields (PROMPT-031 §15) | N/A | Self-referential — export events are themselves audited |
| Platform Admin (PROMPT-030) | tenant id, business name, GSTIN, owner | status | business_name, created_at | created_at DESC | Offset | CSV (new) | `platform.view_tenants` + export | Tenant secrets | N/A | Platform-level audit |

## 39. Acceptance Criteria

Directly traceable to the source prompt's §48 (1–25) — every item maps to a section above. Item 19 ("performance is validated") is honestly marked as NOT YET DONE (§33 — no load-testing tooling exists to validate it), consistent with this document being a specification, not a completed implementation. Item 25 ("no critical defects") is deferred to the implementation pass.

## 40. Open Decisions

Directly answering the source prompt's own §49 list (1–24):

| # | Question | Recommended | Alternative | Owner |
|---|---|---|---|---|
| 1 | Search engine/strategy | Postgres `ILIKE`, unchanged (already proven at MVP scale) | `pg_trgm` GIN indexes, or a real search engine, if row counts grow | Engineering Lead |
| 2 | Minimum search characters | None (no minimum) | Require 2-3 chars to reduce query volume on very large tables | Product Owner |
| 3 | Default page size | 25 (already the existing convention) | — | — |
| 4 | Maximum page size | 100 (already existing) | Raise if a specific UX need (e.g. bulk print) justifies it | Product Owner |
| 5 | Offset vs cursor | Offset (§15) | Cursor, if any tenant's audit_log/stock_ledger_entry exceeds ~500k rows | Engineering Lead |
| 6 | Export row limits | 10,000 rows synchronous cap | Lower (5,000) for slower-rendering formats if Excel is ever added | Product + Engineering |
| 7 | Max synchronous export size | Same as #6 — no separate async tier built | Add async job processing if #6's cap proves too restrictive in practice | Engineering Lead |
| 8 | Async export threshold | N/A — not built (§21) | Revisit if #6/#7 change | — |
| 9 | Export retention period | N/A — exports are synchronous, nothing is retained server-side (the CSV is streamed directly to the client, never written to disk) | If async export is ever built, define retention then | — |
| 10 | PDF export scope | None beyond what PROMPT-033 already covers (document print views) | Add PDF report export as a fast-follow | Product Owner |
| 11 | Excel export scope | None for M1 (no dependency exists) | Add for GSTR-1/GSTR-3B specifically if requested (highest-value target) | Product Owner |
| 12 | CSV export scope | Every module in §38's matrix | Narrower initial rollout (e.g. Sales/Purchase/Payroll only) if implementation capacity is limited | Product Owner |
| 13 | Saved-filter support | Not built (§25) | Build if user feedback demands it post-launch | Product Owner |
| 14 | Saved-filter ownership | Per-user (if ever built) | Per-tenant-shared | Product Owner |
| 15 | Column customization | Not built | Add if requested | Product Owner |
| 16 | Multi-column sorting | Not built — single `sort_by`/`sort_order` only | Add a `sort_by=field1,field2` comma-list if genuinely needed | Product Owner |
| 17 | Advanced OR filtering | Not built — AND-only (§11, already the implicit existing behavior since every filter param is independently ANDed) | Add a structured OR-group syntax if a real use case emerges | Product Owner |
| 18 | Search relevance ranking | Not built (§4 Out of Scope) | Add with a real search engine | — |
| 19 | Full-text search requirement | Not required for MVP row counts | Revisit at scale | Engineering Lead |
| 20 | Report export formats | JSON (existing) + CSV (new, this spec) | Add Excel/PDF per #10/#11 | Product Owner |
| 21 | Offline search scope | Read-cache only (§29, already PROMPT-028's own scope) | Expand offline cache coverage | Product Owner |
| 22 | Export rate limits | None currently — flagged alongside PROMPT-032 §28's own existing rate-limiting gap | Add a per-user export rate limit if abuse is observed | Security + Engineering |
| 23 | Maximum date range for exports | None enforced explicitly — the row-cap (§21) implicitly bounds it | Add an explicit max-span check (e.g. 1 year) for defense-in-depth | Product Owner |
| 24 | Database indexing strategy | §28's table — new indexes on sort/date-filter columns only, `pg_trgm` deferred | Add `pg_trgm` proactively if #1 changes | Engineering Lead |

## 41. Risks

- **Retrofitting `sortable()`/`PageParams` onto ~25 EXISTING, already-tested list endpoints** risks a regression in already-shipped, already-verified behavior — must be done incrementally, one module at a time, with that module's existing test suite re-run after each change (same discipline PROMPT-033 §38 already recommended for its own shared-shell migration).
- **The unindexed `ILIKE '%term%'` search pattern (§1/§28) will eventually become a real performance problem** as tenants accumulate data — this spec deliberately defers the `pg_trgm` fix rather than over-engineering for a problem that doesn't exist yet, but this is a KNOWN, timed risk (Open Decision #1/#24), not a closed question — must be revisited, not forgotten.
- **A synchronous, unbounded-until-the-cap export** (§21) could still be a meaningful CPU/memory spike for a 10,000-row export with many columns — worth a dedicated performance check (§33) before shipping, not assumed fine by design alone.
- **Two-permission export gate (`view` + `export`)** adds real migration work across every module (new permission codes, backfilled onto existing tenants' roles, mirroring PROMPT-024/025's own precedent) — a non-trivial but well-understood, previously-executed-multiple-times migration pattern, not a novel risk.

## 42. Dependencies

- PROMPT-007/008/009 (Customer/Supplier/Product — the ALREADY-EXISTING search/pagination pattern this spec formalizes).
- PROMPT-015/019 (Sales/Purchase Invoice — the same pattern, one layer up).
- PROMPT-024/029 (Payments/Payroll — the source of the ALREADY-EXISTING `payroll.export` permission this spec reuses rather than re-inventing).
- PROMPT-026/027 (GST/Reports — the existing JSON-export precedent this spec's CSV addition extends, never replaces).
- PROMPT-028 (offline read-cache — the boundary for §29's offline search scope).
- PROMPT-030-SPECIFICATION.md (Platform Admin's own tenant-directory search, §7.2 — reused, not redefined).
- PROMPT-031-SPECIFICATION.md (Audit's own search/export design, §19/§24 — reused, not redefined; this spec's §15 cursor-vs-offset evaluation is the one that actually applies to Audit, since 031 didn't re-litigate it).
- PROMPT-032-SPECIFICATION.md (the existing input-validation/SQL-injection-prevention baseline this spec's `sortable()` design extends into a previously-unprotected surface — sort fields — that PROMPT-032 itself didn't specifically call out as already safe, since sorting didn't exist yet when that spec was written).
- PROMPT-033-SPECIFICATION.md (the export-security/audit-selectivity reasoning — "audit the sensitive subset, not every read" — reused verbatim for this spec's own export-auditing design, §22).

## 43. Definition of Done (for THIS specification deliverable)

- [x] All 43 sections requested by the source prompt's §51 are present.
- [x] Every claim is grounded in the ACTUAL current codebase — confirmed via direct inspection of `customers.py`/`customer_service.py`/`sales_invoice_service.py`/`envelopes.py` and a codebase-wide search proving ZERO server-side sorting exists anywhere — the central, most consequential finding of this document.
- [x] The proposed framework EXTENDS the already-consistent-by-convention existing pattern rather than replacing it — no existing API contract breaks, no existing frontend consumer needs to change for the pagination/search parts to keep working.
- [x] Every open decision from the source prompt's §49 is answered with Question/Recommended/Alternative/Owner; several correctly reuse decisions/permissions ALREADY established in prior prompts (`payroll.export`, `reports.export`) rather than inventing new ones.
- [x] No Requirement Conflict was found against any prior specification — this prompt's scope is additive infrastructure, not a redesign of anything previously approved (unlike PROMPT-033, which found a genuine historical-integrity bug, this spec's own gap — missing sorting — is a pure ADDITION, not a correction of something that was built wrong).
- [ ] **Not done, and not in scope for this deliverable**: actual implementation (`app/core/list_query.py`, `app/core/date_ranges.py`, `app/services/shared/export_service.py`, the retrofit of ~25 existing endpoints, the new `<module>.export` permissions and their migration, the `pg_trgm`-deferral performance verification). Per the source prompt's own framing (§51 "Produce the final implementation specification," §52's spec-readiness Definition of Done, and the same absent "implement/STOP" language as PROMPT-030–033), this document is the planning artifact for a future implementation pass.
