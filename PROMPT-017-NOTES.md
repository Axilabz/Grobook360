# PROMPT-017 — Credit Note & Debit Note Management — Implementation Notes

## 1. Summary

Credit Note and Debit Note Management is the sixth Sales document type,
and the first that is a **pure financial adjustment** with **zero
inventory effect** of any kind. Both note types reference a specific
POSTED Sales Invoice, adjust a controlled, eligible-quantity-limited
portion of its lines, and — on posting — record conceptual
accounting/GST integration-boundary entries. Neither note type ever
imports `InventoryService` or calls `post_movement`; this is structural,
not a runtime guard, and is verified by dedicated tests for both note
types.

Credit Note and Debit Note are kept explicitly and permanently separate
from Sales Return: Sales Return owns all physical inventory movement
(Stock IN, PROMPT-016); Credit/Debit Note owns only the financial/GST
adjustment. The two flows share a common source (Sales Invoice) but
never touch each other's ledgers.

## 2. Existing components reused (per §1's explicit instruction)

- Auth/tenant/RBAC (`app.core.deps`, `app.core.permissions`)
- `gst_calculation_service.calculate_line` / `calculate_document_totals`
  / `determine_gst_treatment` — no new tax logic invented
- `sales_validation_service.validate_customer_for_sale`
- `AuditService.record` — the only writer of `audit_log`
- `IdempotencyService` — create and post both require an
  `Idempotency-Key`
- `check_row_version` / optimistic concurrency on every mutation
- `DocumentNumberingService` (`document_type='CREDIT_NOTE'`/
  `'DEBIT_NOTE'`, prefixes `CN`/`DN` — the constants were already
  reserved in `app.core.sales_constants` since PROMPT-011)
- `AccountingPostingService` / `GstReportingService` — extended with new
  methods (`post_credit_debit_note`, `record_credit_debit_note_
  transaction`), not duplicated
- `SalesInvoiceService.get_invoice_locked` / `.get_lines` — the public
  wrappers PROMPT-016 already added for exactly this kind of reuse

## 3. Database changes

Migration `0019_credit_debit_note.py`:

- New tables `credit_debit_note` / `credit_debit_note_line`, reusing the
  Data Dictionary v3.0 baseline's exact minimal field set for both (id,
  tenant_id, note_number, customer_id, document_date, status, subtotal/
  discount_total/taxable_total/tax_total/grand_total, note_type,
  source_invoice_id at the header; id/tenant_id/credit_debit_note_id/
  line_no/product_id/description/quantity/uom_id/unit_price/
  discount_amount/taxable_amount/gst_rate/cgst_amount/sgst_amount/
  igst_amount/cess_amount/line_total at the line — see the migration's
  own docstring for the full proposed-addition list).
- `note_type` widened to VARCHAR(20) from the baseline's VARCHAR(10) to
  fit the prompt's own required self-describing values `CREDIT_NOTE`/
  `DEBIT_NOTE` (the baseline's CHECK-constraint wording implies the
  shorter `CREDIT`/`DEBIT`) — resolved in favor of the more specific,
  more recent prompt instruction, documented, not silently changed.
- ALTER `sales_invoice_line` to add `credited_quantity` and
  `debited_quantity` (both NUMERIC(18,3), default 0, each CHECK-bounded
  by the line's own `quantity`) — the running totals only
  `CreditDebitNoteService.post_note` writes, per `note_type`.
- Seeded `credit_note.*`/`debit_note.*` permissions (10 codes total).
- RLS enabled + tenant-isolation policy on both new tables, matching
  every prior Sales table.

## 4. Backend

- `app/models/credit_debit_note.py`, `app/models/credit_debit_note_line.py` (new)
- `app/models/sales_invoice_line.py` — added `credited_quantity`/`debited_quantity`
- `app/schemas/credit_debit_note.py` (new) — `AdjustmentLineInput`,
  `CreateCreditDebitNoteRequest` (validates `note_type` against a fixed
  set), `UpdateCreditDebitNoteRequest`, `CreditDebitNoteActionRequest`,
  line/list/detail items, `AdjustmentEligibilityLine`/`AdjustmentEligibility`
- `app/services/sales/credit_debit_note_service.py` (new) —
  `CreditDebitNoteService` with `get_adjustment_eligibility`,
  `list_notes`, `get_note`, `create_note`, `update_note` (DRAFT only),
  `post_note` (the atomic core — NO stock code anywhere in this file),
  `cancel_note` (DRAFT only)
- `app/services/accounting/accounting_posting_service.py` — added
  `post_credit_debit_note` (branches conceptual journal direction on
  `note_type`)
- `app/services/sales/gst_reporting_service.py` — added
  `record_credit_debit_note_transaction`
- `app/api/v1/credit_debit_notes.py` (new) — `/sales/credit-debit-notes`
  router: `GET ""`, `GET "/{id}"`, `POST ""`, `PATCH "/{id}"`,
  `POST "/{id}/post"`, `POST "/{id}/cancel"`. Because one table serves
  both note types, RBAC here dynamically checks the `note_type`-specific
  permission (`credit_note.*` vs `debit_note.*`) per request rather than
  a single static `require_permission(...)` dependency.
- `app/api/v1/sales_invoices.py` — added
  `GET /sales/invoices/{invoice_id}/adjustment-eligibility` (gated by
  EITHER `credit_note.create` OR `debit_note.create`, checked directly
  since the endpoint serves both note types)
- `app/api/v1/__init__.py` — registered the new router
- `app/core/error_codes.py` — `CDN-001` through `CDN-008`
- `app/core/permissions.py` — `credit_note.view/create/edit/post/cancel`,
  `debit_note.view/create/edit/post/cancel`; Owner/Manager full,
  Salesperson everything except `.post` for both

## 5. Eligibility / pricing logic

`Creditable Quantity = invoice_line.quantity - invoice_line.credited_quantity`;
`Debitable Quantity = invoice_line.quantity - invoice_line.debited_quantity`
(§17), checked twice: softly at DRAFT create/update time, and again
authoritatively under a `SELECT ... FOR UPDATE` lock on the source
invoice at post time (§28's mandatory concurrency requirement).

A note line's price/discount/GST are derived from the originating Sales
Invoice line (§18 resolved as YES — use the original transaction's
commercial values), using the identical percentage-based discount
proration technique Sales Return already established in PROMPT-016.

## 6. Accounting direction (§11/§12/§20)

- **CREDIT_NOTE**: Debit Sales Return/Revenue Adjustment (+ Debit Output
  GST where applicable), Credit Accounts Receivable — reduces the amount
  receivable. This mirrors `post_sales_return`'s own resolution exactly.
- **DEBIT_NOTE**: implemented as the mirror-opposite (Debit Accounts
  Receivable, Credit Sales Revenue/Adjustment + Credit Output GST) as the
  most conventional commercial interpretation — but this is **explicitly
  flagged as Open Decision #28**, not a confirmed business rule, per
  §12's own instruction ("do not infer accounting direction solely from
  the document name... if unresolved, flag Open Decision").

Both are conceptual-only entries (an audit-trail record + opaque
reference string), never a real GL posting — no Accounting Posting
Matrix is approved yet.

## 7. Atomicity / concurrency / idempotency

`post_note` is one database transaction: lock the note row → lock the
source Sales Invoice row → re-validate live eligible quantity per line →
increment `invoice_line.credited_quantity`/`debited_quantity` →
record accounting/GST integration entries → mark POSTED → audit. No
stock code exists anywhere in this file — the §2/§3/§22 guarantee is
structural. Create and post both require an `Idempotency-Key`, reusing
the existing `IdempotencyService`.

## 8. Testing

`tests/integration/test_credit_debit_notes.py` — 26 tests, **all passed
on the first full run** (no implementation bugs found), covering: DRAFT
creation for both note types, invalid note type, invalid/cross-tenant/
ineligible source invoice, invalid quantity, exceeds-eligible rejection,
adjustment eligibility, GST calculation, the mandatory §48 no-stock test
(once via a prior Sales Return scenario, once via a Debit Note — both
assert zero new `stock_ledger_entry` rows), the mandatory §49 credit-
limit test (100 units invoiced → 60 credited → 40 remaining → a further
50 correctly rejected), the mandatory §50 concurrency test (concurrent
70/50 credit attempts against a 100-unit eligible pool — total confirmed
credit never exceeds 100), duplicate posting rejection, idempotent post
retry, immutability after posting, edit-draft, cancel-draft,
cannot-cancel-posted, row-version conflict, tenant isolation, Salesperson
cannot post / can create+edit, audit generation (all four actions:
`CREDIT_NOTE_CREATED`, `CREDIT_NOTE_POSTED`, `ACCOUNTING_POSTED`,
`GST_TRANSACTION_CREATED`), and list/search/filter (by type and status).

`tests/integration/test_rbac.py` — updated the Manager/Salesperson
permission-set assertions to include the ten new `credit_note.*`/
`debit_note.*` codes.

## 9. Frontend

- `api/salesInvoices.ts` — added `AdjustmentEligibility`/
  `AdjustmentEligibilityLine` types and `getAdjustmentEligibility`
- `api/creditDebitNotes.ts` (new) — full CRUD client for both note types
- `components/CreditDebitNoteManagement.tsx` (new) — combined list/
  search/filter (by type and status) for both note types, a self-
  contained Invoice-picker + eligibility-table create flow (separate
  "Credit Note"/"Debit Note" create buttons, sharing one form component
  parameterized by `noteType`), detail view with post/cancel,
  confirmation dialog with the exact required §38 wording per note type
- `components/Sidebar.tsx`, `App.tsx` — wired "Credit/Debit Notes" under
  Sales (visible if the user has either `credit_note.view` or
  `debit_note.view`)

## 10. Open Decisions (per §53 — not silently resolved)

| # | Open Decision | Business Impact | Recommended Option | Decision Needed From |
|---|---|---|---|---|
| 1 | Exact Credit Note use cases | No enumerated scenario list exists | Not constrained — any adjustment against an eligible invoice line is accepted with a free-text reason | Product Owner |
| 2 | Exact Debit Note use cases | Same as #1 | Same as #1 | Product Owner |
| 3 | Source documents permitted for Credit Note | If wrong, traceability breaks | Resolved by the Data Dictionary's own NOT NULL `source_invoice_id` — Sales Invoice only | Already resolved by approved schema |
| 4 | Source documents permitted for Debit Note | Same as #3 | Same as #3 — Sales Invoice only (same table/column) | Already resolved by approved schema |
| 5 | Whether Credit Note can be created from Sales Return | A return-initiated note flow is unavailable | NOT implemented — the baseline schema has no `source_sales_return_id` column, and no approved requirement confirms this path | Product Owner — approve schema addition if needed |
| 6 | Whether Credit Note can be created directly from Invoice | If NO, the entire feature is unusable | YES — this is the only supported path | Already resolved (this prompt's own primary flow) |
| 7 | Whether partial credit is allowed | If disallowed, current design over-permits | YES — quantity need only satisfy `0 < qty <= eligible` | Product Owner |
| 8 | Whether multiple Credit Notes per Invoice are allowed | Same as #7 | YES — tracked via `sales_invoice_line.credited_quantity` running total, no unique constraint blocks it | Product Owner |
| 9 | Credit eligibility calculation | Wrong formula over/under-permits | `invoice_line.quantity - invoice_line.credited_quantity`, mirrors Sales Return's identical model | Product Owner |
| 10 | Debit eligibility calculation | **No approved source confirms this** | Implemented as the SAME structure as #9 (`quantity - debited_quantity`) as a conservative, safe placeholder — a real Debit Note (e.g. short-billing correction) may need to exceed the original invoiced quantity entirely, which this MVP does NOT support | Product Owner — please confirm or override |
| 11 | Exact GST treatment | Wrong GST math misstates tax liability | Reused `gst_calculation_service` verbatim — no new rule invented | — |
| 12 | Accounting posting rules | No real ledger postings occur | Conceptual-only stub (`AccountingPostingService.post_credit_debit_note`) | Accounting module owner, once an Accounting Posting Matrix is approved |
| 13 | GL account mapping | Same as #12 | Same as #12 — placeholder account names only, no real chart-of-accounts codes | Accounting module owner |
| 14 | Return-to-Credit-Note relationship | See #5 | Not implemented — same resolution as #5 | Product Owner |
| 15 | Cancellation behavior (POSTED notes) | No reversal path if a mistaken POST needs undoing | Not implemented — `CANCELLABLE_STATUSES = {DRAFT}` only, mirrors Sales Return/Sales Invoice's identical resolution | Product Owner |
| 16 | Accounting reversal behavior | Same as #15 | Not implemented | Product Owner |
| 17 | GST cancellation treatment | Same as #15 | Not implemented | Product Owner / GST module owner |
| 18 | Note numbering format | Cosmetic only | Reused `DocumentNumberingService`, prefixes `CN`/`DN`, format `CN-{FY}-0001`/`DN-{FY}-0001` | — |
| 19 | Note date rules | Cosmetic only | Defaults to today, editable while DRAFT, consistent with every prior Sales document | — |
| 20 | Reason master | A hard-coded taxonomy could be wrong, but §4 explicitly forbids inventing one here | Free-text `reason` field, NOT a CHECK-constrained enum — the opposite resolution from Sales Return's own prompt, per this prompt's explicit instruction | Product Owner, if a controlled taxonomy is later approved |
| 21 | Discount/pricing correction behavior | No separate "adjust discount only" mode exists | Handled implicitly via the same quantity-based, prorated-discount line model as every adjustment — no distinct mode built | Product Owner |
| 22 | Whether quantity-based or value-based adjustments are allowed | Affects line model | Resolved as quantity-based, mirroring Sales Return's identical line shape (also forced by the baseline schema's NOT NULL, `>0` quantity column) | Product Owner, if a pure value-only line (no quantity) is later required |
| 23 | Whether negative adjustment values are permitted | Could allow financially nonsensical rows | NO — `quantity > 0`, `unit_price >= 0`, `discount_amount >= 0` enforced at the DB level | — |
| 24 | Role permissions | Affects who can create/post | Resolved by mirroring the established 5-for-5 pattern (Owner/Manager full, Salesperson minus `.post`) for consistency — flagged as open per weaker User-Story signal (same class of open decision as Sales Return's #18) | Product Owner — please confirm or override |
| 25 | Manager approval requirements | FR-CDN-02 mentions a threshold-based approval workflow but says "must be confirmed in detailed spec" | NOT implemented — no approved threshold/authority exists | Product Owner |
| 26 | Offline capability | Field-sales offline note creation unsupported | NOT implemented — no approved PRD offline-write matrix for ANY Sales document type exists yet | Product Owner |
| 27 | Consolidated adjustments | Whether one note can span multiple invoices | NOT supported — every note has exactly ONE `source_invoice_id` (matches the baseline schema); multiple LINES within that one invoice are supported | Product Owner |
| 28 | Exact Debit Note accounting direction | Wrong direction misstates the ledger | Implemented as the conventional mirror-opposite of Credit Note (see §6 above) — explicitly flagged as an Open Decision per §12's own instruction, NOT a confirmed rule | Product Owner / Accounting module owner |

## 11. Risks / Dependencies

- Depends on PROMPT-015/016's `sales_invoice`/`sales_invoice_line`
  tables and `SalesInvoiceService` being stable.
- Open Decision #10/#28 (Debit Note eligibility/direction) is the
  biggest real risk: this MVP's Debit Note behaves as a bounded,
  invoice-quantity-capped "mirror" of Credit Note, which may not match
  the eventual approved business rule for scenarios like short-billing
  correction (which conceptually might need to exceed the original
  invoiced quantity). Flagged prominently, not silently assumed.
- No real Accounting Posting Matrix or GST module exists — both
  integration boundaries remain conceptual stubs, as they have been
  since PROMPT-015.
- Cancellation-after-posting is unavailable for both note types; a
  data-entry mistake on a POSTED note has no built-in correction path.

## 12. Product Owner Validation (§57 answers)

1. Can an authorized user create a Credit Note? **Yes.**
2. Can an authorized user create a Debit Note where supported? **Yes** — against a posted Sales Invoice, the only supported source.
3. Are source-document relationships enforced? **Yes** — `source_invoice_id` NOT NULL FK, tenant-scoped lookup, 404 on mismatch.
4. Can users exceed the eligible adjustment value? **No** — rejected both at DRAFT time and at POST time under a row lock.
5. Can users exceed eligible quantity? **No** — same mechanism.
6. Is GST calculated correctly? **Yes** — reused `gst_calculation_service` verbatim.
7. Is accounting adjustment created correctly? **Yes, conceptually** — a balanced conceptual journal is recorded; real GL mapping awaits an Accounting Posting Matrix.
8. Are posted notes immutable? **Yes** — `update_note` rejects any edit once status is not DRAFT.
9. Can duplicate posting create duplicate journals? **No** — Idempotency-Key short-circuits; status check is a second backstop.
10. Can concurrent users over-adjust the source document? **No** — verified by the mandatory §50 test.
11. Do Credit/Debit Notes create ZERO stock movement? **Yes** — verified by two dedicated tests (§48), and structurally guaranteed (no `InventoryService` import in the file at all).
12. Is Sales Return kept separate from Credit Note? **Yes** — no shared table, no auto-creation, no cross-reference.
13. Is cancellation controlled? **Yes** — DRAFT-only, explicitly documented as an Open Decision for the POSTED case.
14. Is tenant isolation guaranteed? **Yes** — verified by dedicated test.
15. Are permissions enforced? **Yes** — `credit_note.*`/`debit_note.*` codes, dynamically checked per note type.
16. Are all financial changes auditable? **Yes** — `{NOTE_TYPE}_CREATED/UPDATED/POSTED/CANCELLED`, plus `ACCOUNTING_POSTED`, `GST_TRANSACTION_CREATED`.
17. Does the UI work on Desktop, Tablet, and Mobile? **Yes** — reuses the established responsive table/card-list pattern from every prior Sales document screen.
18. Are all unresolved decisions clearly documented? **Yes** — see §10 above, 28 items.

## 13. Definition of Done

All items in the prompt's §55 checklist are satisfied, with cancellation-
after-posting (and its accounting/GST reversal) explicitly isolated as
Open Decisions #15-17 rather than silently implemented or ignored, and
Debit Note's eligibility/accounting-direction rule explicitly isolated
as Open Decisions #10/#28 for the same reason.

Credit Note & Debit Note Management is complete and ready for the next
prompt. No E-Invoice, E-Way Bill, Payments, GST Return submission, full
Accounting module, or Sales Return work has been started or modified
beyond the additive integration-boundary extensions documented above.
