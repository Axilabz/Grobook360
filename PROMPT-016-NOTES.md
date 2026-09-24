# PROMPT-016 — Sales Return Management — Implementation Notes

## 1. Summary

Sales Return Management is the fifth Sales document type, and the first
that **reverses** a prior transaction instead of extending one. It records
goods physically returned by a customer against a specific, already-
POSTED Sales Invoice, validates the return quantity against a live
"returnable quantity" (invoiced − previously returned), and on
confirmation creates exactly one **Stock IN** movement per line through
the existing `InventoryService.post_movement` primitive — the mirror
image of Delivery Challan/direct Sales Invoice's Stock OUT.

Sales Return is explicitly **not** a Credit Note. No credit-note table,
reference column, or automatic-creation logic exists in this prompt —
only two thin, additive integration-boundary methods
(`AccountingPostingService.post_sales_return`,
`GstReportingService.record_return_transaction`) that write an audit
trail and return an opaque reference string, exactly mirroring how
PROMPT-015 handled the same requirement for Sales Invoice.

## 2. Existing components reused (per §1's explicit instruction)

- Auth/tenant/RBAC (`app.core.deps`, `app.core.permissions`)
- `InventoryService.post_movement` (Stock IN, `source_type='SALES_RETURN'`,
  per-line `source_id`) and `InventoryService.get_active_product_locked`
- `DocumentNumberingService` (`document_type='SALES_RETURN'`, prefix `SR`
  — the constant was already reserved in `app.core.sales_constants`
  since PROMPT-011)
- `gst_calculation_service.calculate_line` / `calculate_document_totals`
  / `determine_gst_treatment` — no new tax logic invented
- `sales_validation_service.validate_customer_for_sale` /
  `validate_product_for_sale`
- `AuditService.record` — the only writer of `audit_log`
- `IdempotencyService` — create and confirm both require an
  `Idempotency-Key`
- `check_row_version` / optimistic concurrency on every mutation
- `AccountingPostingService` / `GstReportingService` — extended with new
  methods (`post_sales_return`, `record_return_transaction`), not
  duplicated
- `SalesInvoiceService` — extended with two public wrappers
  (`get_invoice_locked`, `get_lines`), the exact pattern
  `DeliveryChallanService` used for PROMPT-015

## 3. Database changes

Migration `0018_sales_return.py`:

- New tables `sales_return` / `sales_return_line`, reusing the Data
  Dictionary v3.0 baseline's exact minimal field set for both (id,
  tenant_id, return_number, customer_id, document_date, status, subtotal/
  discount_total/taxable_total/tax_total/grand_total, source_invoice_id
  at the header; id/tenant_id/sales_return_id/line_no/product_id/
  description/quantity/uom_id/unit_price/discount_amount/taxable_amount/
  gst_rate/cgst_amount/sgst_amount/igst_amount/cess_amount/line_total at
  the line — see the migration's own docstring for the full proposed-
  addition list, which includes `return_date` as this migration's naming
  for the baseline's `document_date`, `return_reason`/
  `reason_description`, header GST split (`cgst_total`/`sgst_total`/
  `igst_total`), `total_return_quantity`, `accounting_posting_reference`/
  `gst_transaction_reference`, and — critically —
  `sales_return_line.source_invoice_line_id` (NOT NULL FK), the field the
  entire Returnable Quantity calculation depends on).
- ALTER `sales_invoice_line` to add `returned_quantity` (NUMERIC(18,3),
  default 0, `CHECK (returned_quantity >= 0 AND returned_quantity <=
  quantity)`) — the running total only `SalesReturnService.confirm_return`
  writes, mirroring `delivery_challan_line.invoiced_quantity`'s identical
  pattern one level up the chain.
- Seeded `sales_return.*` permissions (view/create/edit/confirm/cancel).
- RLS enabled + tenant-isolation policy on both new tables, matching
  every prior Sales table.

## 4. Backend

- `app/models/sales_return.py`, `app/models/sales_return_line.py` (new)
- `app/models/sales_invoice_line.py` — added `returned_quantity`
- `app/schemas/sales_return.py` (new) — `ReturnLineInput`,
  `CreateSalesReturnRequest` (with a `model_validator` requiring
  `reason_description` when `return_reason == 'OTHER'`),
  `UpdateSalesReturnRequest`, `SalesReturnActionRequest`,
  `SalesReturnLineItem`/`ListItem`/`Detail`, `ReturnEligibilityLine`/
  `ReturnEligibility`
- `app/services/sales/sales_return_service.py` (new) — `SalesReturnService`
  with `get_return_eligibility`, `list_returns`, `get_return`,
  `create_return`, `update_return` (DRAFT only), `confirm_return` (the
  atomic core), `cancel_return` (DRAFT only)
- `app/services/sales/sales_invoice_service.py` — added public
  `get_invoice_locked`/`get_lines` wrappers for `SalesReturnService`
- `app/services/accounting/accounting_posting_service.py` — added
  `post_sales_return`
- `app/services/sales/gst_reporting_service.py` — added
  `record_return_transaction`
- `app/api/v1/sales_returns.py` (new) — `/sales/returns` router:
  `GET ""`, `GET "/{id}"`, `POST ""`, `PATCH "/{id}"`,
  `POST "/{id}/confirm"`, `POST "/{id}/cancel"`
- `app/api/v1/sales_invoices.py` — added
  `GET /sales/invoices/{invoice_id}/return-eligibility` (gated by
  `sales_return.create`, same convention as PROMPT-015's own
  `invoice-eligibility` endpoint gated by `sales_invoice.create`)
- `app/api/v1/__init__.py` — registered the new router
- `app/core/error_codes.py` — `SR-001` through `SR-008`
- `app/core/permissions.py` — `sales_return.view/create/edit/confirm/
  cancel`; Owner/Manager full, Salesperson everything except `confirm`

## 5. Return quantity / pricing logic

`Returnable Quantity = invoice_line.quantity - invoice_line.returned_quantity`
(§7), checked twice: once softly at DRAFT create/update time, and again
authoritatively under a `SELECT ... FOR UPDATE` lock on the source
invoice at confirm time (§18's mandatory concurrency requirement).

A return line's price/discount/GST are **derived from the originating
Sales Invoice line**, never accepted from the client (§15/§16 resolved as
YES/YES): the invoice line's absolute `discount_amount` (computed for its
full invoiced quantity) is converted to an equivalent discount
**percentage** before calling `calculate_line` with the return's own
(possibly smaller) quantity — identical proration technique to
PROMPT-015's Delivery-Challan-to-Invoice pricing, for the identical
reason (a copied absolute discount would not scale correctly for a
partial return).

## 6. Atomicity / concurrency / idempotency

`confirm_return` is one database transaction: lock the Sales Return row →
lock the source Sales Invoice row → re-validate live returnable quantity
per line → post Stock IN per line → increment
`invoice_line.returned_quantity` → record accounting/GST integration
entries → mark CONFIRMED → audit. Any failure anywhere rolls back
everything — §16's explicit requirement (never CONFIRMED without Stock
IN, never Stock IN without CONFIRMED) is satisfied by this being a single
`async def` with no intermediate commit.

Locking the source invoice row is what serializes two concurrent Sales
Returns against the SAME invoice — the same pattern
`DeliveryChallanService.confirm_challan` uses against Sales Order, and
`SalesInvoiceService.post_invoice` uses against a source Delivery
Challan. Confirm and create both require an `Idempotency-Key` header,
reusing the existing `IdempotencyService`.

## 7. Testing

`tests/integration/test_sales_returns.py` — 26 tests, **all passed on the
first full run** (no implementation bugs found), covering: valid draft
creation, invalid/cross-tenant/ineligible source invoice, invalid
quantity, exceeds-returnable rejection, invalid/OTHER-without-description
reason validation, return eligibility, partial/full return, the mandatory
§42 stock test (exact numbers: 140 seeded → 100 invoiced → 40 available →
20 returned → 60 available, exactly one Stock IN entry), the mandatory
§43 multiple-return test (100 → 20 → 30 → 50 returned across three
separate returns, then a 4th of even 1 unit correctly rejected), duplicate
confirmation rejection, idempotent confirm retry, the mandatory §44
concurrency test (60 previously returned + concurrent 30/20 attempts
against a 40 remaining — total confirmed return never exceeds 100),
immutability after confirmation, edit-draft, cancel-draft,
cannot-cancel-confirmed, row-version conflict, tenant isolation,
Salesperson cannot confirm / can create+edit, audit generation (all four
actions: `SALES_RETURN_CREATED`, `SALES_RETURN_CONFIRMED`,
`ACCOUNTING_POSTED`, `GST_TRANSACTION_CREATED`), and list/search/filter.

`tests/integration/test_rbac.py` — updated the Manager/Salesperson
permission-set assertions to include the five new `sales_return.*` codes.

## 8. Frontend

- `api/salesInvoices.ts` — added `ReturnEligibility`/`ReturnEligibilityLine`
  types and `getReturnEligibility`
- `api/salesReturns.ts` (new) — full CRUD client + `RETURN_REASONS` (the
  proposed taxonomy, exposed as `{value, label}` pairs for the UI)
- `components/SalesReturnManagement.tsx` (new) — list/search/filter,
  a self-contained Invoice-picker + eligibility-table create flow
  (mirrors `DeliveryChallanManagement.tsx`'s Sales-Order-picker exactly),
  detail view with confirm/cancel, confirmation dialog stating "This
  action will add the returned quantity back to inventory" per §32
- `components/SalesInvoiceManagement.tsx` — added a "Create Sales Return"
  button on a POSTED invoice's detail view (gated by
  `sales_return.create`) and a `CreateReturnFromInvoiceModal`, the same
  invoice-initiated-return entry point structure PROMPT-015 used for
  DC-initiated invoice creation
- `components/Sidebar.tsx`, `App.tsx` — wired "Sales Returns" under Sales

## 9. Open Decisions (per §47 — not silently resolved)

| # | Open Decision | Business Impact | Recommended Option | Decision Needed From |
|---|---|---|---|---|
| 1 | Exact status lifecycle | Affects reporting/automation expecting specific states | Adopted prompt's own baseline verbatim: DRAFT → CONFIRMED → CANCELLED (named CONFIRMED, not POSTED, since Return is inventory-only like Delivery Challan) | Product Owner |
| 2 | Return reason master | A hard-coded taxonomy may not match the eventual approved list | Adopted the prompt's own suggested 6 values (DAMAGED/WRONG_PRODUCT/EXCESS_QUANTITY/QUALITY_ISSUE/CUSTOMER_REJECTION/OTHER) as a proposed, non-final CHECK constraint | Product Owner / Business Analyst |
| 3 | Return without a Sales Invoice | Ad-hoc returns (e.g. no traceable sale) are unsupported | Answered by the Data Dictionary's own NOT NULL `source_invoice_id` — resolved as NO | Already resolved by approved schema |
| 4 | Multiple returns per invoice | If disallowed, current design over-permits | Allowed (no unique constraint blocks it; §19 explicitly asks for it); tracked via `sales_invoice_line.returned_quantity` running total | Product Owner |
| 5 | Partial returns | If disallowed, current design over-permits | Allowed — quantity need only satisfy `0 < qty <= returnable` | Product Owner |
| 6 | Negative stock relevance | N/A for Stock IN, but flagged for completeness | Not applicable — a return only ever increases stock | — |
| 7 | Returned goods always saleable? | No condition-based routing to quarantine/damaged stock exists | Not implemented — every return goes straight back into sellable `stock_qty_cache` regardless of `return_reason` (even DAMAGED) | Product Owner / Inventory Analyst |
| 8 | Damaged/rejected inventory handling | No separate quarantine location/status | Not implemented (§23 explicit permission to flag, not build, unless approved) | Product Owner |
| 9 | Cancellation of a CONFIRMED return | No reversal path if a mistaken CONFIRM needs undoing | Not implemented — `CANCELLABLE_STATUSES = {DRAFT}` only, mirrors Delivery Challan/Sales Invoice's identical resolution | Product Owner |
| 10 | Stock reversal on cancellation | Same as #9 | Not implemented — no compensating Stock OUT exists; would need a `SALES_RETURN_REVERSAL` source_type if approved later | Product Owner |
| 11 | Accounting treatment / exact GL mapping | No real ledger postings occur | Conceptual-only stub (`AccountingPostingService.post_sales_return`), same discipline as Sales Invoice's own stub | Accounting module owner, once an Accounting Posting Matrix is approved |
| 12 | GST treatment / real GSTR reporting | No real GST filing occurs | Conceptual-only stub (`GstReportingService.record_return_transaction`) | GST module owner |
| 13 | Is a Credit Note mandatory after every return? | Affects whether Sales Return alone is a complete financial record | Not decided here — explicitly deferred to PROMPT-017 | Product Owner |
| 14 | Does Sales Return auto-create a Credit Note? | Automatic creation would remove a manual control point | Resolved as NO per §22's explicit, non-negotiable boundary | Already resolved by this prompt's own instruction |
| 15 | Does return value use the original invoice price? | If NO, a separate re-pricing rule would be needed | Resolved as YES — price/GST always derived from the source invoice line | Product Owner (if a future re-pricing need arises) |
| 16 | Must original discount be preserved? | Affects refund/credit accuracy on partial returns | Resolved as YES, via percentage-proration (see §5 above) | Product Owner |
| 17 | Return tax calculation | A wrong formula would misstate GST liability | Reused `gst_calculation_service` verbatim — no new rule invented | — |
| 18 | Can a Salesperson confirm a return? | Affects who can trigger the stock-IN-impacting action | Resolved by mirroring the established 4-for-4 pattern (Owner/Manager only) for consistency, but explicitly flagged as a WEAKER signal this time — this prompt's own User Stories say "authorized user", not "Owner/Manager" | Product Owner — please confirm or override |
| 19 | Manager approval requirements | An approval workflow before confirm is unimplemented | Not implemented — no approved source defines thresholds/approvers (that's FR-CDN-02's territory for Credit Notes, not Sales Return) | Product Owner |
| 20 | Exact numbering format | Cosmetic only | Reused `DocumentNumberingService`, prefix `SR`, format `SR-{FY}-0001` | — |
| 21 | Offline Sales Return capability | Field-sales offline recording unsupported | Not implemented — no approved PRD offline-write matrix for ANY Sales document type exists yet | Product Owner |
| 22 | Offline stock conflict handling | Same as #21 | Not applicable until #21 is approved | Product Owner |
| 23 | Decimal quantity support | Affects fractional-unit products | Supported — NUMERIC(18,3) throughout, consistent with every prior Sales document | — |
| 24 | UOM conversion | Affects returning in a different unit than invoiced | Not separately implemented — the return line reuses the invoice line's own `uom_id` verbatim (no cross-UOM return path) | Product Owner, if cross-UOM returns are required |
| 25 | Multiple warehouse/location | Affects multi-location distributors | Not applicable — single "MAIN" location only, consistent with PROMPT-010's own scope | Product Owner |

## 10. Risks / Dependencies

- Depends on PROMPT-015's `sales_invoice`/`sales_invoice_line` tables and
  `SalesInvoiceService` being stable — any future schema change to
  `sales_invoice_line.returned_quantity`'s semantics would need
  corresponding updates here.
- The "returned goods always go back into sellable stock" assumption
  (Open Decision #7) could be a real business risk if damaged-goods
  returns are common — currently no way to route them to a non-sellable
  bucket.
- Cancellation-after-confirmation is unavailable; a data-entry mistake on
  a CONFIRMED return currently has no built-in correction path other than
  a manual, out-of-band stock adjustment (an existing PROMPT-010
  capability, but not integrated with Sales Return's own audit trail).

## 11. Product Owner Validation (§51 answers)

1. Can an authorized user create a Sales Return? **Yes.**
2. Is the return linked to the original Sales Invoice? **Yes** (`source_invoice_id` NOT NULL FK, always populated).
3. Is returnable quantity calculated correctly? **Yes**, `invoiced - previously_returned`, verified live under lock at confirm time.
4. Can users over-return? **No** — rejected both at DRAFT time (soft check) and at CONFIRM time (authoritative, race-proof check under a row lock).
5. Are partial returns supported? **Yes.**
6. Are multiple returns handled correctly? **Yes** — verified by the mandatory §43 test (20 → 30 → 50 → then rejected).
7. Does confirmation create Stock IN? **Yes**, exactly one movement per line via `InventoryService.post_movement`.
8. Is Stock IN atomic with confirmation? **Yes** — one transaction, no intermediate commit.
9. Can retry create duplicate Stock IN? **No** — verified by the idempotent-retry test (Idempotency-Key short-circuits; the ledger's own `uq_stock_ledger_entry_source` constraint is a second backstop).
10. Can concurrent users exceed the returnable quantity? **No** — verified by the mandatory §44 test.
11. Is the confirmed return immutable? **Yes** — `update_return` rejects any edit once status is not DRAFT.
12. Is cancellation behavior clearly defined? **Yes** — DRAFT-only, explicitly documented as an Open Decision for the CONFIRMED case (no reversal built).
13. Is Credit Note kept separate? **Yes** — no Credit Note table, reference, or auto-creation exists.
14. Is accounting integration clearly separated? **Yes** — a stub service, conceptual entries only, no real GL.
15. Is GST information preserved? **Yes** — full CGST/SGST/IGST breakdown retained at both header and line level.
16. Is tenant isolation guaranteed? **Yes** — verified by dedicated test; cross-tenant invoice/return lookups return 404.
17. Are permissions enforced? **Yes** — `sales_return.*` codes, Owner/Manager full, Salesperson minus confirm (flagged as Open Decision #18 given weaker source signal).
18. Are stock changes auditable? **Yes** — `STOCK_IN_CREATED` (via `InventoryService`'s own audit call), plus `SALES_RETURN_CREATED`/`CONFIRMED`, `ACCOUNTING_POSTED`, `GST_TRANSACTION_CREATED`.
19. Does the UI work on Desktop, Tablet, and Mobile? **Yes** — reuses the established responsive table/card-list pattern from every prior Sales document screen (desktop table, mobile card list, responsive modals).
20. Are all unresolved decisions clearly documented? **Yes** — see §9 above, 25 items.

## 12. Definition of Done

All items in the prompt's §49 checklist are satisfied, with the two
explicitly-scoped-out exceptions called out in §9 above (Open Decisions
#9/#10, cancellation-after-confirmation and its stock reversal — isolated
as an Open Decision rather than silently implemented or silently
ignored, per the prompt's own instruction).

Sales Return is complete and ready for the next prompt (PROMPT-017 —
Credit/Debit Notes, per §22's own forward reference). No Credit Note,
Debit Note, Payment, Accounting module, GST Return submission, E-Invoice,
or E-Way Bill work has been started.
