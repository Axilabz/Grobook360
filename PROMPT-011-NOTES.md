# PROMPT-011 — Sales & Billing Foundation: Design Record

## Conflict found — STOP and identify (per the global instruction)

This prompt is internally in tension in a way none of PROMPT-007 through
PROMPT-010 were, and resolving that tension **is** the main design
decision of this prompt.

On one hand, §2/§44-51 ask for a "reusable Sales transaction foundation"
with API endpoints (`GET/POST /api/v1/sales`, list/detail/confirm/post),
a Sales list screen, a Sales form, customer/product selectors — i.e.
something with real persistence and a real screen. On the other hand:

- §5 says *"Do not fully implement each document's business workflow
  here"* and lists ESTIMATE/SALES_ORDER/DELIVERY_CHALLAN/SALES_INVOICE/
  SALES_RETURN/CREDIT_NOTE/DEBIT_NOTE as document *types to evaluate*, not
  build.
- §71's Definition of Done explicitly requires **"[ ] No full Estimate
  workflow implemented," "[ ] No full Sales Order workflow implemented,"
  "[ ] No full Delivery Challan workflow implemented," "[ ] No full Sales
  Invoice workflow implemented," "[ ] No Sales Return workflow
  implemented."** — i.e. every concrete document type is explicitly
  forbidden here.
- §65: *"Use the existing Sales-related entities from the approved
  database baseline... Do NOT create duplicate Sales tables."* The
  approved Data Dictionary v3.0 has **no generic "sales" table** — it has
  seven specific, already-fully-specified tables (`estimate`,
  `sales_order`, `delivery_challan`, `sales_invoice`, `sales_return`,
  `credit_debit_note`, each with its own `_line` child table). Building a
  generic `/api/v1/sales` resource backed by a new catch-all table would
  directly violate both "don't duplicate" and "don't invent a document
  type" — there is no single approved entity a generic Sales CRUD screen
  could honestly sit on top of.
- §75 (Stop Condition) repeats: don't implement Estimate, Sales Order,
  Delivery Challan, Sales Invoice, or Sales Return "automatically" after
  this prompt — implying they are each their own future prompt, exactly
  like Customer/Supplier/Product/Inventory each got their own prompt.

**Resolved as**: this prompt builds the shared *service-layer*
infrastructure every future document-type prompt (PROMPT-012 onward,
presumably one per document type, mirroring the PROMPT-007→010 pattern)
will import and call — not a placeholder document table, not a generic
`/api/v1/sales` API, and not a document-shaped screen. Every checklist
item in §71 that reads as a genuine backend/service deliverable ("GST
integration contract implemented," "Document numbering foundation
implemented," "Inventory Stock Movement Service integration defined,"
"Server-side financial calculation implemented") is satisfied by real,
tested code below. Every checklist item that presupposes a concrete
document ("Sales document model reviewed/reused," "Document status
foundation implemented" as an enforced state machine) is satisfied at the
*shared-vocabulary* level (constants, schemas) rather than a persisted
table, since inventing the exact header/line field set for, say,
Sales Invoice specifically — before that prompt exists — would mean
guessing at requirements §71 itself says are out of scope.

**No new API endpoints under `/api/v1/sales` and no new Sales document
tables were created.** If this reading of the prompt is wrong and a
concrete document type (e.g. direct Sales Invoice) was actually wanted
now, that's a one-message correction — the infrastructure below is
designed so the first real document-type prompt can consume it
immediately either way.

## What was built

### 1. Shared vocabulary (`app/core/sales_constants.py`)

Document types, generic lifecycle statuses (DRAFT/CONFIRMED/POSTED/
CANCELLED/VOID — §22 explicitly says not every document supports every
status, so this is a shared *vocabulary*, not an enforced state machine
here), GST treatment (INTRA_STATE/INTER_STATE), and a
`STOCK_EFFECT_BY_DOCUMENT_TYPE` map encoding §25-29's rules (Estimate/
Sales Order never move stock; Delivery Challan/direct Sales Invoice
reduce it; Sales Return increases it) as a single documented source
future prompts can import instead of each re-deriving the rule.

### 2. GST Calculation Service (`app/services/sales/gst_calculation_service.py`)

Pure functions, no DB access — §14's *"Sales should call/use the approved
GST calculation service"* integration contract. `determine_gst_treatment`
compares supplier vs. customer state code (a missing customer state
defaults to intra-state — a documented, conservative interpretation, not
a claim that Place-of-Supply rules are fully implemented). `calculate_line`
does Quantity×Price → Gross → (−Discount) → Taxable → (+GST, split
CGST+SGST or IGST) → Line Total, exactly per §11-13's worked examples
(verified against the prompt's own ₹1,000/₹100 discount/₹162 GST/₹1,062
total example in `test_calculate_line_discount_amount_applied_before_gst`).
`calculate_document_totals` sums lines. **Rounding**: 2 decimal places,
`ROUND_HALF_UP` — §41's rounding policy was otherwise unresolved; Python's
`Decimal` default (`ROUND_HALF_EVEN`) is not the commercial-rounding
convention GST invoicing expects, so this was a deliberate, documented
choice rather than accepting the language default silently.

### 3. Document Numbering Service (`app/services/sales/document_numbering_service.py` + migration `0013`)

Proposed schema addition: `document_number_sequence` (tenant_id,
document_type, financial_year_label, last_number), the same class of gap
as `idempotency_key` in PROMPT-002 — no generic Sales table exists to hang
a numbering column off, but every future document type needs identical
server-authoritative, FY-scoped numbering (§34/§35). Format decided and
documented here (§74 Q5-10, otherwise unresolved):
`"{PREFIX}-{FY}-{seq:04d}"`, e.g. `"INV-2026-27-0001"`. Scope is tenant +
document_type + financial_year (each document type's sequence is
independent and resets every FY, using the tenant's own
`financial_year_start_month` from PROMPT-002). Cancelling a document
never frees or reuses its number — gaps are normal in GST-compliant
sequential numbering. Concurrency: row-level lock (`SELECT ... FOR
UPDATE`) on an existing sequence row, or insert-and-retry-on-conflict for
a not-yet-existing one — verified with an actual concurrent-allocation
test (3 simultaneous calls, 3 distinct numbers, no duplicates).

**A real concurrency bug was caught and fixed while testing this**: the
insert-a-new-sequence-row branch originally called `session.add(sequence)`
*before* entering the `begin_nested()` SAVEPOINT block, instead of inside
it (unlike the identical retry pattern already established correctly in
`customer_service.py`/`product_service.py`/`unit_service.py`). Under an
actual collision, the SAVEPOINT rollback didn't cleanly detach the
already-added pending object, corrupting the session for the retry and
surfacing as `PendingRollbackError` on the next statement. Fixed by moving
`add()` inside the nested block (matching the established pattern exactly)
— caught by writing a real concurrent-request test, not by inspection.

### 4. Sales Validation Service (`app/services/sales/sales_validation_service.py`)

`validate_customer_for_sale` / `validate_product_for_sale` — §17/§18's
required checks (exists, belongs to tenant, active), reusing
`CustomerService`/`ProductService` rather than re-querying independently.
Cross-tenant lookups return the same not-found error as a genuinely
missing id (established pattern). `ValidatedCustomer.is_b2b` is derived
from GSTIN presence — the same FR-CUST-03-style rule already used for
Customer Management, not a new invented classification (§16).

### 5. Inventory integration contract (`InventoryService.post_movement`)

PROMPT-010's `_post_movement` was renamed to the public `post_movement` —
this **is** the "Inventory Stock Movement Service integration" §30/§38
ask for. A future Delivery Challan or direct Sales Invoice posting will
call `post_movement(movement_type=STOCK_OUT, source_type="DELIVERY_CHALLAN"
/"SALES_INVOICE", source_id=<document id>, ...)` inside its own
transaction; a Sales Return calls it with `STOCK_IN`. No migration was
needed — `STOCK_IN`/`STOCK_OUT` already exist in
`ck_stock_ledger_entry_movement_type` from PROMPT-010; only `source_type`
varies per caller, exactly the extensibility PROMPT-010's migration
docstring anticipated. Verified end-to-end with a test simulating a
"SALES_INVOICE"-sourced stock-out (seed via OPENING_STOCK, then reduce via
a fake invoice id) and confirming the negative-stock policy still applies
identically. **Preventing a double stock-out when an Invoice is generated
from an already-posted Delivery Challan (§28) is explicitly left as that
future Sales Invoice prompt's own responsibility** — `post_movement` has
no way to know a DC→Invoice conversion link exists; that link itself
doesn't exist yet since no document tables were created here.

### 6. Shared schemas (`app/schemas/sales_common.py`)

`SalesLineInput` (what a caller submits — quantity/uom/unit_price/
discount, NUMERIC-backed per §10/§28), `SalesLineCalculated` and
`DocumentTotals` (server-calculated shapes, §60: never trust an
equivalent client value). Discount is validated as percentage *or* fixed
amount, never both (§12).

### 7. Frontend: reusable selector foundation (§50/§51)

`shared/CustomerSelector.tsx` and `shared/ProductLineSelector.tsx` — the
server-side, tenant-scoped, debounced search-select controls every future
Sales form needs, built against the already-existing Customer/Product
list APIs. `ProductLineSelector` resolves a product's available units the
same way `ProductManagement.tsx`'s edit form already does (base unit +
its defined conversions) and shows a clearly-labeled **client-side
estimate** of gross/discount/taxable/GST/total for UX responsiveness —
explicitly captioned "Estimate only — the server independently calculates
and validates the final amount" (§60), since no real posting endpoint
exists yet to actually authorize a number.

**Neither component is mounted anywhere** — there's no Sales screen to
place them on yet. They're TypeScript-verified and ready for the first
document-type prompt to import; live browser verification isn't
applicable this prompt for the same reason no new page exists.

## RBAC — deliberately not touched

No `sales.*` permission codes were added. `app/core/permissions.py`'s own
established discipline (documented in CLAUDE.md) is explicit: *"only
defines permissions for capabilities that actually exist in code...
don't invent a full permission model in advance of the module existing."*
Since no Sales document type/screen/endpoint exists yet, inventing
`sales.view`/`sales.create`/etc. now would be exactly that mistake. The
first document-type prompt (e.g. Sales Invoice) should add its own
permission codes when it actually builds something to gate.

## Testing

- `tests/unit/test_gst_calculation_service.py` (10 tests): intra/inter-
  state treatment, discount-before-GST (including the prompt's own
  worked example), percentage vs. fixed discount, discount capped at
  gross, zero-rate GST, document total aggregation.
- `tests/integration/test_document_numbering_service.py` (7 tests): FY
  label computation (before/after FY start month), sequential increments,
  per-document-type scoping, per-FY reset, per-tenant scoping, concurrent
  allocation producing unique numbers.
- `tests/integration/test_sales_foundation.py` (9 tests): customer/product
  validation (success, not-found, cross-tenant, inactive), and the
  Inventory `post_movement` integration contract exercised the way a
  future Sales document will use it (including negative-stock rejection).
- **Full suite: 271 backend tests passing** (245 prior + 26 new). No
  existing test was broken — `InventoryService`'s public method rename
  (`_post_movement` → `post_movement`) had no external callers to update
  beyond its own file.

## Open decisions carried forward (not silently resolved)

Per §74, none of the following were decided — they belong to whichever
future prompt builds the first concrete document type:

1. **Exact document types in M1** and their **exact lifecycle statuses**
   (§74 Q1-4) — only the shared vocabulary exists; no document enforces
   any particular subset of it yet.
2. **Document conversion rules** (Estimate→SalesOrder→DeliveryChallan→
   SalesInvoice at-most-once, per the approved `uq_*_source_*` conditional-
   unique constraints already noted in the Constraints & Indexes sheet
   during PROMPT-007's research) — not implemented; no conversion tables
   exist yet since no document tables exist yet.
3. **Discount type/precision, additional charges, freight, round-off**
   (§74 Q16-24) — the GST Calculation Service supports percentage-or-
   fixed-amount discount only; no charges/freight/round-off concept
   exists.
4. **B2B/B2C GSTIN-mandatory rule, HSN requirement by transaction type,
   Place-of-Supply beyond same/different-state** (§74 Q25-29) — Customer's
   `is_b2b` flag is derived and exposed, but no validation *requires*
   GSTIN/HSN for any transaction type yet — that's transaction-type-
   specific policy this prompt has no document to attach it to.
5. **Whether inactive customers/products can be used in new transactions**
   (§74 Q30-31) — `validate_customer_for_sale`/`validate_product_for_sale`
   default `require_active=True` (rejecting inactive), matching
   FR-PROD-02's "only active products may be selected for new documents"
   and the equivalent customer/supplier deactivation principle, but this
   is a default a future prompt can override per document type, not a
   hard rule baked into the validators.
6. **Negative stock policy** (§74 Q32) — inherited as-is from PROMPT-010
   (prohibited by default); not re-decided here.
7. **Sales permissions for each role, Salesperson invoice authority,
   approval thresholds, credit-limit validation, price override** (§74
   Q41-47) — entirely deferred; no permission codes exist yet (see RBAC
   section above).
8. **Payment status storage** (§74 Q40) — `DocumentTotals` has no payment
   field; whether payment status lives on the Sales document or is
   derived from a future Payments module is explicitly left open, per
   §42's own instruction not to implement Payments here.
9. **Exact transaction snapshot / address snapshot fields** (§74 Q48-49)
   — `SalesLineCalculated` captures the calculated amounts a line needs,
   but the exact snapshot shape for a real document (product name/HSN at
   transaction time, billing/shipping address snapshot) is each future
   document table's own schema decision, informed by whatever fields that
   document's own approved DB table actually has.
