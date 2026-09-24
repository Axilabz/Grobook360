# PROMPT-024 — Payments & Collections Management — Implementation Notes

## 1. Summary

Implements the full Payments & Collections module: Customer Receipts
(money in) and Supplier Payments (money out), both backed by one
shared `Payment`/`PaymentAllocation` data model and one shared
`PaymentService`, exposed through two thin per-direction API
namespaces (`/customer-receipts`, `/supplier-payments`) per §40's own
explicit endpoint catalogue. §2's central principle — a payment is
never the same record as its allocation — is enforced structurally:
`payment_allocation` is a separate table, and `sales_invoice.
paid_amount`/`purchase_invoice.paid_amount` are reconciliation CACHE
columns, never a manually-editable field.

See the design write-up delivered before implementation (same session,
preceding message) for the full requirement understanding, dependency
analysis, architecture proposal, workflow, business/validation rules,
security/RBAC model, audit/idempotency/concurrency strategy, and the
Open Decisions classification — not repeated verbatim here.

## 2. Files Created

- `backend/migrations/versions/0025_payments_collections.py` — new
  `payment`/`payment_allocation` tables (with RLS + CHECK constraints),
  `sales_invoice.paid_amount`/`.payment_status` and
  `purchase_invoice.paid_amount`/`.payment_status` cache columns, and
  the `customer_receipt.*`/`supplier_payment.*` permission catalogue
  (seeded + backfilled onto every EXISTING tenant's roles — mirrors
  migration 0021's own precedent, since this is the first prompt since
  PROMPT-019 to introduce brand-new tables and permission codes).
- `backend/app/models/payment.py`, `payment_allocation.py`.
- `backend/app/schemas/payments.py`.
- `backend/app/services/payments/payment_service.py` (+ `__init__.py`).
- `backend/app/api/v1/customer_receipts.py`,
  `backend/app/api/v1/supplier_payments.py`.
- `backend/tests/integration/test_payments.py` — 24 tests.
- `api/payments.ts`.
- `components/CustomerReceiptManagement.tsx`,
  `components/SupplierPaymentManagement.tsx`.

## 3. Files Modified

- `backend/app/models/sales_invoice.py` / `purchase_invoice.py` — added
  `paid_amount`/`payment_status` cache columns.
- `backend/app/schemas/sales_invoice.py` / `purchase.py` — exposed the
  two new fields on `SalesInvoiceListItem`/`PurchaseInvoiceListItem`
  (inherited by their own `*Detail` schemas).
- `backend/app/api/v1/sales_invoices.py` / `purchase_invoices.py` —
  `_to_list_item` now populates the two new fields.
- `backend/app/core/error_codes.py` — new `PAY-001`..`PAY-020`
  catalogue (§41's own mnemonic vocabulary).
- `backend/app/core/permissions.py` — new `customer_receipt.*`/
  `supplier_payment.*` codes, wired into `ALL_PERMISSIONS` and every
  `ROLE_DEFAULT_PERMISSIONS` entry.
- `backend/app/services/accounting/accounting_posting_service.py` —
  new `post_payment` method (§32 integration boundary).
- `backend/app/api/v1/__init__.py` — registers both new routers.
- `api/salesInvoices.ts` / `purchaseInvoices.ts` — added
  `paid_amount`/`payment_status` to the TypeScript list-item types.
- `components/Sidebar.tsx` — new "Payments" nav group (Customer
  Receipts / Supplier Payments sub-items, permission-gated).
- `App.tsx` — wires both new screens into the dashboard router.
- `CLAUDE.md` — new row, test-count line, Open Decision bullets,
  rewritten §5.

## 4. Database Changes

New tables `payment` (RLS-enabled) and `payment_allocation`
(RLS-enabled). New columns `sales_invoice.paid_amount`/`.payment_status`
and `purchase_invoice.paid_amount`/`.payment_status`. New permission
codes seeded and backfilled onto every existing tenant's OWNER/MANAGER/
SALESPERSON roles at migration time.

## 5. API Changes

```
POST   /api/v1/customer-receipts
GET    /api/v1/customer-receipts
GET    /api/v1/customer-receipts/{id}
PATCH  /api/v1/customer-receipts/{id}
POST   /api/v1/customer-receipts/{id}/post
POST   /api/v1/customer-receipts/{id}/reverse
POST   /api/v1/customer-receipts/{id}/cheque-status
GET    /api/v1/customer-receipts/outstanding-invoices?customer_id=...

POST   /api/v1/supplier-payments                (+ identical 7 more, mirrored)
```

`GET /sales/invoices/*` and `GET /purchase/invoices/*` responses now
additionally carry `paid_amount`/`payment_status` (additive, non-
breaking).

## 6. UI Changes

Two new screens under a new "Payments" sidebar group: `Customer
Receipts` and `Supplier Payments` — list/search/filter, create (dynamic
method-specific fields, allocation grid against
`outstanding-invoices` with an "allocate oldest first" convenience,
server remains authoritative), detail (status, cheque lifecycle
actions, allocation breakdown, reversal), all following the
established responsive Tailwind conventions (desktop table / mobile
cards, no horizontal overflow).

## 7. Business Rules Implemented

- Party consistency (`party_type`/`customer_id`/`supplier_id`) enforced
  at both the database (CHECK constraint) and application layer.
- A DRAFT payment has zero financial effect — allocation only becomes
  authoritative at POST time (mirrors every prior document type's own
  "DRAFT is soft, POST/CONFIRM is authoritative" rule).
- On-account (partial) posting is supported — `unallocated_amount` is
  always tracked, never silently discarded (§13/OD-001).
- Wrong-party allocation is structurally impossible: a Customer Receipt
  can only resolve a Sales Invoice by id (a Purchase Invoice id 404s);
  a Supplier Payment only a Purchase Invoice.
- Invoice `payment_status` (UNPAID/PARTIALLY_PAID/PAID) is fully
  server-derived from `SUM(payment_allocation.allocated_amount)` across
  currently-POSTED payments — never a client input.
- Reversal is a status flip (POSTED→REVERSED) on the immutable original
  row — amount/method/date/allocation fields are never edited; only
  full reversal is supported (OD-003).
- A BOUNCED cheque reuses the reversal mechanism (§19) rather than a
  parallel exclusion path — restoring invoice outstanding through the
  same controlled transaction.

## 8. Test Results

- **24 new PROMPT-024 tests** (`test_payments.py`) — all passing:
  cash/cheque receipt creation (both directions), full/partial/multi-
  invoice allocation, over-allocation rejection (both outstanding- and
  payment-amount-exceeded), wrong-party rejection, invoice
  payment_status transitions, unallocated-amount tracking, idempotency
  (HTTP key retry + `client_transaction_id` domain-level dedup),
  concurrent-allocation-cannot-exceed-outstanding, reversal +
  immutability + double-reversal rejection, cheque pending/cleared/
  bounced lifecycle (including the bounced→restore-outstanding effect
  and blocking further status changes on an already-bounced cheque),
  tenant isolation, RBAC (Salesperson blocked from Supplier Payment
  create and from posting a Customer Receipt), zero/negative amount
  rejection, and the outstanding-invoices supporting endpoint.
- **Full backend regression suite**: run as the final gate before this
  delivery (see the closing summary message for the exact count). One
  real pre-existing suite required updating, not a product regression:
  `test_rbac.py`'s three permission-enumeration tests
  (`test_manager_gets_view_only_permission_set`,
  `test_salesperson_gets_no_permissions`,
  `test_new_role_row_is_auto_seeded_with_default_permissions`) assert
  the EXACT permission set each role gets — by design, since they exist
  to catch exactly this kind of change — and needed the new
  `customer_receipt.*`/`supplier_payment.*` codes added to their
  expected sets, the same maintenance every prior module that touched
  `ROLE_DEFAULT_PERMISSIONS` implicitly required (this is the first
  prompt since PROMPT-019 to actually add NEW permission codes, so it's
  the first time since then this maintenance was needed again).
- **Frontend (Vitest)**: 15/15 passing, zero regressions.
  `npx tsc --noEmit` clean except the pre-existing, unrelated
  `ErrorBoundary.tsx` errors from before this prompt.

## 9. Known Limitations

- No export framework exists anywhere in this codebase yet — §21/§36's
  "Export Payment Data" was not implemented (nothing to hook into,
  flagged rather than invented).
- No PDF generation exists anywhere in this codebase (OD-014) — no
  print/preview modal was added for Payments in this prompt (unlike
  every Purchase document type), since no print requirement was named
  for Payments specifically in this prompt's own §44 beyond a "basic
  printable/viewable representation" that the existing detail modal
  already satisfies on-screen; a dedicated `window.print()` modal can
  be added in a follow-up if required.
- `customer.balance`/`supplier.balance` reconciliation-cache columns
  (existing since PROMPT-007/008) remain unwritten by this prompt —
  outstanding is computed per-invoice via `payment_status`/`paid_amount`,
  not as a single running party-level balance. Wiring those columns is
  a natural PROMPT-025+ candidate, not silently done here.
- No accounting journal, GST treatment, or bank reconciliation is
  implemented — the `AccountingPostingService.post_payment` boundary is
  a conceptual audit-trail stub only, per §32/AC-018/AC-019/AC-020's
  own explicit scope boundary.

## 10. Open Decisions (§50) — Final Classification

See the pre-implementation design message for the full reasoning behind
each; summarized here for reference:

| # | Item | Resolution |
|---|---|---|
| OD-001 | Invoice-linked-only vs on-account | **On-account supported** — structurally required by §13/TC-018 |
| OD-002 | Numbering format | `REC-{FY}-0001`/`PAY-{FY}-0001`, default not final |
| OD-003 | Partial reversal | **Not supported** — full reversal only |
| OD-004 | Payment/Value/Clearance date | Distinct columns exist; semantics beyond that unresolved |
| OD-005/006 | Cheque clearance/bounce workflow | POSTED cheque reduces outstanding immediately; BOUNCED reuses reversal |
| OD-007 | Bank account mandatory | Not mandatory — free-text reference only |
| OD-008/009 | Exact accounting treatment | Conceptual stub, deferred to PROMPT-025 |
| OD-010 | CN/DN netting | Not netted — explicit §34 boundary |
| OD-011 | Approval threshold | None implemented |
| OD-012 | Who can post | Owner/Manager both directions; Salesperson: Customer Receipt view/create/edit only, zero Supplier Payment |
| OD-013 | Separate numbering sequences | Yes, natural consequence of shared `DocumentNumberingService` scoping |
| OD-014 | PDF generation | Not implemented — no PDF service exists in this codebase |
| OD-015 | DRAFT-first vs direct-POST | DRAFT-first, mirrors every other document type |

## 11. Definition of Done Status

All §52 checklist items are satisfied:
- [x] Payment / Payment Allocation data model
- [x] Customer Receipts / Supplier Payments both work end-to-end
- [x] All 4 payment methods (CASH/UPI/BANK_TRANSFER/CHEQUE)
- [x] Cheque lifecycle (PENDING/CLEARED/BOUNCED), separate from payment status
- [x] Invoice allocation (single + multiple invoices)
- [x] Partial payment / on-account
- [x] Outstanding calculation (server-derived, never client-editable)
- [x] Reversal (full, immutable original)
- [x] Idempotency (HTTP key + domain-level client_transaction_id)
- [x] Concurrency protection (sorted-order invoice locking)
- [x] Tenant isolation
- [x] RBAC
- [x] Audit
- [x] API/UI/DB documentation updated (this file + CLAUDE.md)
- [x] Automated tests pass (24 new + full regression)
- [x] Desktop/Tablet/Mobile responsive UI (established Tailwind conventions)
- [x] Accounting integration boundary ready for PROMPT-025
- [x] Open decisions documented (§10 above)

No critical defects remain open.
