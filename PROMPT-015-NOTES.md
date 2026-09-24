# PROMPT-015 — Sales Invoice Management: Design Record

## What was built

The fourth and final MVP Sales document type — the authoritative billing
transaction — built on PROMPT-011's foundation and reusing PROMPT-013's
Sales Order and PROMPT-014's Delivery Challan services directly.

### 1. Schema (migration `0017_sales_invoice.py`)

New `sales_invoice`/`sales_invoice_line` tables, mirroring Estimate/Sales
Order's financial shape (unlike Delivery Challan, an Invoice DOES carry
pricing/GST — it is the billing document). Proposed additions (same
"propose, document, implement" pattern): identity/address snapshots
(same principle as every prior Sales document); `customer_type`
('B2B'/'B2C', derived from GSTIN presence — the same rule
`ValidatedCustomer.is_b2b` already uses); `invoice_type`
('DIRECT_SALES_INVOICE'/'DELIVERY_CHALLAN_SALES_INVOICE'); `source_delivery_challan_id`/
`source_sales_order_id` (nullable, with a DB-level CHECK enforcing
`§2`'s consistency rule — a DIRECT invoice has no source DC, a DC-based
invoice MUST have one); `accounting_posting_reference`/
`gst_transaction_reference` (opaque integration-boundary strings, NOT
foreign keys — see §14/§15 below); `irn`/`ack_number`/`ack_date`/
`einvoice_status`/`qr_code_data` (e-Invoice boundary, §23, reserved for
PROMPT-018, never written to here).

This migration also extends **Delivery Challan** (from PROMPT-014), since
Sales Invoice cannot enforce §16's double-stock-deduction rule without
it: `delivery_challan_line.invoiced_quantity` (new column, default 0,
cumulative), with a `CHECK (invoiced_quantity <= current_delivery_quantity)`
DB-level backstop — the same class of constraint
`sales_order_line.delivered_quantity` already established in migration
0016.

### 2. §2/§16 — the double-stock-deduction rule, and how it's actually enforced

This is the single most safety-critical rule in this prompt. It is
enforced by **branching on `invoice_type` BEFORE any stock code runs**,
not by inspecting the ledger and guessing after the fact:

- `DIRECT_SALES_INVOICE` posting: `SalesInvoiceService.post_invoice`
  calls `InventoryService.post_movement(STOCK_OUT, source_type=
  'SALES_INVOICE', source_id=<the invoice line's id>)` for every line —
  the same per-line `source_id` pattern `DeliveryChallanService.confirm_challan`
  already established in PROMPT-014 (needed for the same
  `uq_stock_ledger_entry_source` reason).
- `DELIVERY_CHALLAN_SALES_INVOICE` posting: **`InventoryService` is never
  imported into the branch that handles this invoice type.** Instead,
  `delivery_challan_line.invoiced_quantity` is incremented — a pure
  bookkeeping column update, zero calls to any stock-movement primitive.
  There is no code path by which a DC-based invoice can ever call
  `post_movement`, so there is no double-deduction to prevent at
  runtime — it is prevented by the architecture itself.

Verified by the mandatory §47 test
(`test_mandatory_no_double_stock_deduction`): stock 100 → DC for 20 →
stock 80 → invoice the DC for 20 → stock **remains 80** → exactly ONE
`STOCK_OUT` ledger entry exists for the product (from the DC's own
confirm, not a second one from the invoice) — and a companion test
(`test_dc_based_invoice_creates_no_stock_ledger_entry_of_its_own`)
directly counts ledger rows before/after posting the DC-based invoice and
asserts zero new rows of ANY movement type.

### 3. Pricing for a DC-based invoice line — proration, not copying

A Delivery Challan line carries **no price/GST at all** (PROMPT-014 — a
pure dispatch record). A DC-based invoice line's pricing is derived from
the **originating Sales Order line** (via
`delivery_challan_line.source_sales_order_line_id`), proportionally
recomputed for the invoice quantity — which may be SMALLER than what was
delivered, since §24/§25 explicitly allow partial invoicing of a single
Delivery Challan across multiple invoices.

The Sales Order line's `discount_amount` was computed for its full
ordered quantity; copying it verbatim onto a smaller invoice quantity
would overstate the discount. Instead it is converted to an equivalent
discount PERCENTAGE (`discount_amount / (quantity * unit_price) * 100`)
and `gst_calculation_service.calculate_line` is called with the
invoice's own (possibly smaller) quantity — the percentage naturally
scales; a copied absolute amount would not. This is a resolved design
decision (not silently invented pricing behavir — see Open Decisions
below for what WAS left genuinely open).

GST treatment (intra/inter-state) is recomputed fresh via
`determine_gst_treatment` using the invoice's own customer/place-of-
supply snapshot (copied from the Delivery Challan, which itself copied it
from the Sales Order) — this is a property of tenant+customer location,
not of quantity, so recomputing it is no different from what a manual/
direct invoice already does at its own creation time.

### 4. Accounting integration boundary (§21)

`app/services/accounting/accounting_posting_service.py` — a NEW package,
since no Accounting module exists yet. **This is explicitly NOT a real
double-entry ledger.** No Accounting Posting Matrix is approved (Open
Decision #18), so no real GL account codes are hard-coded anywhere. The
service's one method, `post_sales_invoice`, records the CONCEPTUAL
entries §21 itself describes (Debit Accounts Receivable, Credit Sales
Revenue, Credit Output CGST/SGST/IGST) as an audit-log entry using
plain-English account names and the invoice's own already-calculated
totals, then returns an opaque reference string
(`ACCPOST-<invoice-id>`) stored on `sales_invoice.accounting_posting_reference` —
not a foreign key, because no ledger table exists to point at. A future
Accounting module can implement this method fully (query the approved
Posting Matrix, create real journal entries) without any Sales Invoice
code needing to change — that is the "clean integration contract" §21
asks for.

### 5. GST reporting integration boundary (§22)

`app/services/sales/gst_reporting_service.py` — similarly, NOT a
GSTR-1/GSTR-3B submission (explicitly out of scope). §22 itself says the
invoice's own fields ARE the authoritative GST transaction data; this
service's `record_invoice_transaction` method records an audit-log entry
capturing that snapshot (GSTIN, invoice number/date, taxable value,
CGST/SGST/IGST, customer type, place of supply) and returns an opaque
reference string (`GSTTXN-<invoice-id>`) stored on
`sales_invoice.gst_transaction_reference`. A future GST module can read
either this reference trail or the invoice table directly — both are
valid, since the invoice table is the true source and this is just a
recognized-transaction marker.

### 6. Atomic posting (§20) — mirrors Delivery Challan's confirm pattern exactly

`SalesInvoiceService.post_invoice` is one database transaction end-to-end
(single commit at the router layer): lock invoice → branch on
`invoice_type` → (direct: lock+post stock per line) OR (DC-based: lock
source DC, re-validate LIVE invoiceable quantity, increment
`invoiced_quantity`) → call the two integration-boundary services → mark
POSTED → audit. Any failure anywhere rolls back everything — the same
"no new transaction-wrapping code needed" reasoning documented in
PROMPT-013/014's own NOTES (the session-per-request pattern already
guarantees this).

### 7. Concurrency (§38) — reused locks, not new ones

- Two draft invoices racing to post against the SAME Delivery Challan:
  `DeliveryChallanService.get_challan_locked` (a new public method,
  mirroring `SalesOrderService.get_order_locked`'s identical PROMPT-014
  addition) locks the DC row, so the second transaction blocks until the
  first commits, then re-reads live `invoiced_quantity` and correctly
  rejects if it would now exceed the invoiceable amount.
- Two users racing to post the SAME invoice: the invoice's own row lock
  (`_get_invoice_locked`) plus `check_row_version` — identical pattern to
  every prior document type's own confirm/post.

Verified by `test_concurrent_posting_only_one_succeeds` (same invoice)
and `test_concurrent_invoicing_against_same_dc` (two different invoices
against the same DC).

### 8. Cancellation — resolved conservatively (§35/§52 open decisions #4-7), mirroring Delivery Challan exactly

Only DRAFT invoices can be cancelled (`CANCELLABLE_STATUSES = {DRAFT}` in
`app/models/sales_invoice.py`). §35 explicitly permits this: "If
cancellation rules are not fully defined: flag Open Decision. Do not
implement unsafe automatic reversals." No approved source defines stock
reversal (for a Direct invoice), accounting reversal, or GST cancellation
treatment — inventing any of them would be exactly the "unsafe automatic
reversal" the prompt forbids.

### 9. RBAC

`sales_invoice.view/create/edit/post/cancel` mirror Sales Order/Delivery
Challan's shape exactly. Both direct-invoice creation
(`POST /sales/invoices`) and invoice-from-DC creation
(`POST /sales/delivery-challans/{id}/create-invoice`) are gated by the
SAME `sales_invoice.create` code — the DC-nested endpoint is a REST
convenience for accepting a source DC id, not a signal that a different
permission model applies (unlike Estimate→Sales Order conversion, which
reuses the Estimate's OWN permission because that endpoint mutates the
Estimate itself; here the source DC is only read at create time).
Salesperson gets everything except `.post` — User Story 3 once more
names "Owner/Manager" as the actor for whom posted invoices become
immutable, the third consecutive Sales document type resolved with this
exact shape.

### 10. API

`GET/POST /sales/invoices`, `GET/PATCH /sales/invoices/{id}`,
`POST .../post`, `POST .../cancel` — new router. The suggested
`POST /sales/delivery-challans/{id}/create-invoice` and an
`invoice-eligibility` companion GET were added to the EXISTING
`delivery_challans.py` router (which now imports `SalesInvoiceService`
and reuses `sales_invoices.py`'s own `_to_detail` converter) rather than
duplicated, per §36's "reuse existing endpoints" instruction. No
dedicated `GET /sales/invoices/{id}/audit` endpoint was built — no prior
Sales document prompt built one either, and audit records are inspected
directly via the `audit_log` table in every test suite so far; this is a
minor, consistent scope trim, not a gap unique to this prompt.

### 11. Frontend

`api/salesInvoices.ts` + `components/SalesInvoiceManagement.tsx`
(list/create-direct/detail/post/cancel, reusing `CustomerSelector`/
`ProductLineSelector` for the direct-invoice flow). The
Delivery-Challan-based creation flow lives as a "Create Sales Invoice"
button on `DeliveryChallanManagement.tsx`'s own detail view (shown only
when the challan is CONFIRMED) rather than a separate top-level flow —
this matches §13's own UX flow ("User opens confirmed Delivery Challan →
selects Create Sales Invoice") and avoids building a second Sales-Order-
picker-style component for what is fundamentally the same "search then
drill into a source document" interaction already established for
Delivery Challan's own creation from Sales Order. The post-confirmation
dialog text is invoice-type-aware, exactly matching §33's two required
messages ("This action will reduce inventory" for Direct; "Inventory was
already reduced... will not reduce inventory again" for DC-based).

## Testing

- `backend/tests/integration/test_sales_invoices.py` (27 tests): direct-
  invoice create validation (customer/product not-found/inactive,
  invalid quantity/discount), GST calculation, client-total-tampering
  ignored, the mandatory §48 direct-invoice scenario (stock 100 → post
  20 → stock 80, exactly one ledger entry, both integration-boundary
  references populated), duplicate-post rejection, idempotent retry,
  concurrent posting, DC-based invoice creation + eligibility, invoicing
  an unconfirmed DC rejected, the mandatory §47 double-stock-deduction
  test, a companion zero-new-ledger-rows test, the mandatory §49
  over-invoicing rejection, concurrent invoicing against the same DC,
  posted-invoice immutability, DRAFT edit, cancellation (DRAFT succeeds,
  POSTED rejected), tenant isolation, permission checks (Salesperson
  cannot post but can create/edit), audit trail (including
  `ACCOUNTING_POSTED`/`GST_TRANSACTION_CREATED` actions), row-version
  conflict, and list search/filter/pagination.
- `backend/tests/integration/test_delivery_challans.py`: unaffected — the
  Delivery Challan line's new `invoiced_quantity` column is additive, no
  existing assertion changed.
- `backend/tests/integration/test_rbac.py`: `sales_invoice.*` codes added
  to the Owner/Manager/Salesperson effective-permission-set assertions
  and the new-role-auto-seed assertion.
- **All 71 tests in the combined delivery-challan/rbac/sales-invoice run
  passed on the first attempt after the migration was applied** — no
  implementation bugs were found during testing this time (unlike
  PROMPT-012's discount-field bug or PROMPT-013's permission redesign),
  a reflection of how closely this prompt's design mirrors PROMPT-014's
  already-proven patterns rather than introducing new ones.
- Frontend: `npx tsc --noEmit` clean (pre-existing, unrelated
  `shared/ErrorBoundary.tsx` errors only).

## Open decisions carried forward (not silently resolved)

1. **Exact Accounting GL mapping** (§18/§52 #18) — NOT resolved. The
   conceptual entries recorded (Accounts Receivable / Sales Revenue /
   Output CGST-SGST-IGST) use plain-English account names, not real
   chart-of-accounts codes. **Business impact**: no invoice posting
   currently produces a real, bookkeeper-usable journal entry.
   **Recommended option**: once an Accounting Posting Matrix is approved,
   `AccountingPostingService.post_sales_invoice` is the ONLY place that
   needs to change — it can look up real GL codes and write to a real
   ledger table without any Sales Invoice code changing.
   **Decision needed from**: Product Owner / Accounting domain lead.
2. **Cancellation-after-posting, with stock/accounting/GST reversal**
   (§35/§52 #4-7) — NOT implemented, mirrors Delivery Challan's identical
   PROMPT-014 resolution. **Business impact**: a posted invoice can never
   be voided through this system yet; corrections require a future
   Credit Note/Debit Note module (explicitly out of scope here).
   **Recommended option**: build Credit Note as the correction mechanism
   §10 itself names, rather than inventing invoice-level reversal.
   **Decision needed from**: Product Owner.
3. **One DC → one Invoice vs. multi-DC consolidation** (§25/§52 #8) —
   resolved as one DC per invoice-from-challan creation call (matches
   `delivery_challan_id` being a single FK, not a list). **Business
   impact**: a customer with three separate deliveries needs three
   separate DC-based invoices (or a Direct invoice covering all of them
   manually, with no automatic linkage). **Recommended option**: if
   consolidation is needed, extend `create_invoice_from_challan` to
   accept multiple challan ids and validate all belong to the same
   customer — a backward-compatible additive change.
   **Decision needed from**: Product Owner.
4. **Partial invoicing of a DC IS allowed** (§52 #9) — resolved as yes:
   `invoiced_quantity` tracking explicitly supports invoicing less than
   the full delivered quantity, across multiple invoices, exactly per
   §24's own formula. Not an open item — restated here only because §52
   lists it as one to explicitly confirm, not leave ambiguous.
5. **Whether Sales Order can directly create an Invoice** (§52 #21) — NOT
   implemented. Only Direct (no source) and Delivery-Challan-sourced
   invoicing exist; a Sales Order's own confirmed-but-undelivered lines
   cannot be invoiced without first creating a Delivery Challan.
   **Business impact**: FMCG distributors who invoice before physically
   dispatching (common for advance billing) cannot do so via a Sales-
   Order-direct path yet — they must use a Direct Invoice instead,
   losing the Sales Order linkage. **Recommended option**: a future
   `create_invoice_from_order` method mirroring
   `create_invoice_from_challan`'s shape, with `source_sales_order_id`
   set and no DC.
6. **Round-off rules** (§17/§52 #17) — no column, no computation, same
   unresolved status as every prior Sales document.
7. **Offline invoice creation / offline numbering** (§44/§52 #11/#12) —
   explicitly NOT implemented per the prompt's own "STOP and flag" for
   this exact scenario. No approved Offline Sync Specification exists.
8. **Negative stock policy** (§52 #13) — inherited unchanged from
   PROMPT-010: prohibited by default, applies identically to a Direct
   Invoice's own Stock OUT call.
9. **Price override / discount permission / discount threshold**
   (§52 #14-16) — not implemented; any user who can create/edit a
   Direct Invoice can apply any discount within `SalesLineInput`'s
   existing validation range, same as every prior Sales document.
10. **Invoice date rules** (§52 #20) — no validation beyond "must be a
    valid date"; no rule constraining it relative to the source DC/Sales
    Order date was specified anywhere.
11. **Whether an invoice can be created without a Sales Order/DC at all**
    (§52 #22) — already answered by design: yes, that IS the Direct
    invoice path (§9's own two controlled types).
12. **No dedicated `GET /sales/invoices/{id}/audit` endpoint** — not
    itself in §52's numbered list, but noted here for completeness: audit
    records remain queryable only via direct DB access (as in every
    prior prompt's own test suite), not a REST endpoint.
