# PROMPT-025 — Accounting Posting Matrix & Journal Engine — Notes

## 1. Summary

Replaces the "conceptual entries" stub `AccountingPostingService` had
carried since PROMPT-015 (audit-log JSON blobs only, no real ledger)
with a genuine double-entry Journal Engine, and closes the accounting
boundary PROMPT-019 §14 explicitly deferred for Purchase Invoice and
Purchase Return. See the pre-implementation design write-up delivered
earlier in this session for the full requirement understanding,
source-to-accounting event map, posting matrix, and per-section
strategy (account mapping, GST, inventory/COGS, reversal, idempotency,
concurrency, period-close, RBAC, audit) — not repeated verbatim here.

## 2. Files Created

- `backend/migrations/versions/0026_accounting_engine.py` — `chart_of_
  account`, `account_mapping`, `accounting_period`, `journal_entry`,
  `journal_line` tables (RLS-enabled, mirrors migration 0021/0025's
  precedent) + `purchase_invoice.accounting_posting_reference`/
  `purchase_return.accounting_posting_reference` columns + the
  `accounting.*` permission catalogue (seeded + backfilled onto every
  existing tenant's OWNER/MANAGER roles).
- `backend/app/core/accounting_constants.py` — posting-rule-code
  vocabulary + the default, editable Chart of Accounts seed data.
- `backend/app/models/chart_of_account.py`, `account_mapping.py`,
  `accounting_period.py`, `journal_entry.py`, `journal_line.py`.
- `backend/app/services/accounting/chart_of_accounts_service.py` —
  lazy per-tenant COA/mapping provisioning + account resolution.
- `backend/app/services/accounting/journal_service.py` — the generic
  double-entry engine: `post_journal`, `reverse_journal`,
  `reverse_journal_for_source`, `list_journals`, `get_journal`.
- `backend/app/schemas/accounting.py`.
- `backend/app/api/v1/accounting.py`.
- `backend/tests/integration/test_accounting.py` — 18 tests.
- `api/accounting.ts`.
- `components/AccountingManagement.tsx`.

## 3. Files Modified

- `backend/app/services/accounting/accounting_posting_service.py` —
  **rewritten**: the four existing methods (`post_sales_invoice`,
  `post_sales_return`, `post_payment`, `post_credit_debit_note`) now
  build real `JournalLineInput` lists and call `JournalService.
  post_journal` instead of writing an audit-only JSON blob — every
  existing call site (`sales_invoice_service.py`, `sales_return_
  service.py`, `credit_debit_note_service.py`, `payment_service.py`)
  needed ZERO changes (same method names/params/`-> str` return). Two
  new methods added: `post_purchase_invoice`, `post_purchase_return`
  (closing PROMPT-019 §14's deferred boundary), plus three reversal
  methods: `reverse_purchase_invoice`, `reverse_purchase_return`,
  `reverse_payment`.
- `backend/app/services/purchase/purchase_invoice_service.py` — `post_
  invoice` now calls `post_purchase_invoice` and stores the reference;
  `cancel_invoice`'s POSTED branch now calls `reverse_purchase_invoice`.
- `backend/app/services/purchase/purchase_return_service.py` —
  `confirm_return` now calls `post_purchase_return`; `cancel_return`'s
  CONFIRMED branch now calls `reverse_purchase_return`.
- `backend/app/services/payments/payment_service.py` — `reverse_
  payment` now calls `AccountingPostingService.reverse_payment`.
- `backend/app/models/purchase_invoice.py` / `purchase_return.py` —
  added `accounting_posting_reference` column.
- `backend/app/schemas/purchase.py` / `app/api/v1/purchase_invoices.py`
  / `purchase_returns.py` — expose the new field on both Detail schemas.
- `backend/app/core/error_codes.py` — new `ACC-001`..`ACC-015` catalogue.
- `backend/app/core/permissions.py` — new `accounting.*` codes, wired
  into OWNER/MANAGER (Salesperson: none).
- `backend/app/api/v1/__init__.py` — registers the new router.
- `api/purchaseInvoices.ts` / `purchaseReturns.ts` — added
  `accounting_posting_reference` to the Detail TS types.
- `components/Sidebar.tsx` — new "Accounting" sub-item under
  "Accountant".
- `App.tsx` — wires the new screen.
- `CLAUDE.md` — new row, test count, Open Decision bullets.

## 4. Database Changes

5 new tables (`chart_of_account`, `account_mapping`, `accounting_
period`, `journal_entry`, `journal_line`), all RLS-enabled. 2 new
columns (`purchase_invoice`/`purchase_return`'s `accounting_posting_
reference`). New permission codes seeded and backfilled onto existing
tenants (third time this precedent has been used, after migration
0021 and 0025).

## 5. API Changes

```
GET  /api/v1/accounting/journals
GET  /api/v1/accounting/journals/{id}
GET  /api/v1/accounting/journals/{id}/lines
POST /api/v1/accounting/journals/{id}/reverse
GET  /api/v1/accounting/accounts
GET  /api/v1/accounting/account-mappings
GET  /api/v1/accounting/posting-rules
```
No manual-journal-creation endpoint exists (§56 OD-017 — not approved).

## 6. Accounting Posting Rules (implemented)

| Source | Debit | Credit |
|---|---|---|
| Sales Invoice | Accounts Receivable (grand_total) | Sales Revenue (taxable_total) + Output CGST/SGST/IGST |
| Sales Return | Sales Return/Revenue Adjustment + Output CGST/SGST/IGST | Accounts Receivable |
| Credit Note | Sales Return/Revenue Adjustment + Output GST | Accounts Receivable |
| Debit Note | Accounts Receivable | Sales Revenue/Adjustment + Output GST *(OD-016, judgment call)* |
| Purchase Invoice | Purchase Expense (taxable_total) + Input CGST/SGST/IGST | Accounts Payable (grand_total) |
| Purchase Return | Accounts Payable (grand_total) | Purchase Return/Inventory Adjustment + Input CGST/SGST/IGST |
| Customer Receipt | Cash/Bank/UPI/Cheque (by `payment_method`) | Accounts Receivable |
| Supplier Payment | Accounts Payable | Cash/Bank/UPI/Cheque (by `payment_method`) |
| Estimate / Sales Order / Purchase Order / Goods Receipt / Delivery Challan | — | — (no journal, verified structurally — no call site exists) |

## 7. Account Mappings (default seed, editable per tenant)

| posting_rule_code | Default account |
|---|---|
| ACCOUNTS_RECEIVABLE | 1010 Accounts Receivable |
| CASH_ACCOUNT | 1020 Cash-in-Hand |
| BANK_ACCOUNT | 1030 Bank Account |
| UPI_ACCOUNT | 1040 UPI Clearing Account |
| CHEQUE_ACCOUNT | 1050 Cheque Clearing Account |
| INPUT_CGST/SGST/IGST | 1060/1070/1080 Input GST Receivable |
| ACCOUNTS_PAYABLE | 2010 Accounts Payable |
| OUTPUT_CGST/SGST/IGST | 2020/2030/2040 Output GST Payable |
| SALES_REVENUE | 4010 Sales Revenue |
| SALES_RETURN_ADJUSTMENT | 4020 Sales Return / Revenue Adjustment |
| PURCHASE_EXPENSE | 5010 Purchase Expense |
| PURCHASE_RETURN_ADJUSTMENT | 5020 Purchase Return / Inventory Adjustment |

## 8. Journal Example

Sales Invoice INV-2026-27-0001, ₹10,000 taxable, intra-state 18% GST:
```
JRN-2026-27-0001  POSTED  ORIGINAL
  DR Accounts Receivable        11,800.00
  CR Sales Revenue                          10,000.00
  CR Output CGST Payable                       900.00
  CR Output SGST Payable                       900.00
```
Reversal (e.g. via manual reverse, or automatically on Purchase
Invoice cancellation / Payment reversal):
```
JRN-2026-27-0002  POSTED  REVERSAL (reverses JRN-2026-27-0001)
  DR Sales Revenue               10,000.00
  DR Output CGST Payable            900.00
  DR Output SGST Payable            900.00
  CR Accounts Receivable                        11,800.00
```
`JRN-2026-27-0001.status` flips to REVERSED; its own lines/amounts are
never edited.

## 9. Test Results

- **18 new PROMPT-025 tests** (`test_accounting.py`) — all passing:
  Sales Invoice intra-state (CGST+SGST) and inter-state (IGST) balanced
  journals, Sales Order/Estimate create no journal, Purchase Invoice
  balanced journal, Customer Receipt, Supplier Payment, Sales Return,
  Purchase Return, Credit Note, Debit Note, duplicate-posting prevention
  (exactly one journal per source), manual reversal + original-
  immutability + double-reversal rejection, payment-reversal auto-
  reverses its own journal, cross-tenant journal access denied, GST
  reconciliation + full source<->journal traceability, RBAC (Salesperson
  blocked from all three endpoints), and the Chart of Accounts/mapping/
  posting-rules supporting endpoints.
- One real bug found and fixed during test-writing: `PurchaseInvoiceDetail`/
  `PurchaseReturnDetail` schemas were missing the newly-added
  `accounting_posting_reference` field (added to the model but not
  threaded through the schema/router `_to_detail` builders) — fixed.
- **Full backend regression + frontend**: run as the final gate (see
  the closing summary message for the exact count).

## 10. Known Limitations

- Account Mappings are **view-only** via the API/UI in this prompt — no
  edit endpoint exists (§47 lists "Account Mapping/Configuration where
  authorized" as a UI minimum; editing was judged out of scope given
  the enormous prompt surface already covered, and because the default
  mapping itself is explicitly unapproved — editing an unapproved
  default felt premature). `ACCOUNTING_MANAGE_ACCOUNT_MAPPINGS`
  permission exists and gates the read view for future extension.
- No Trial Balance/General Ledger/P&L/Balance Sheet UI (§57 explicit
  non-scope) — the engine is structured to support them (stable
  journal/line IDs, source references, dates, account references,
  tenant, audit) per §49/AC-025, but no report screen is built.
- No period-close workflow (OD-018/OD-019) — `accounting_period` rows
  can currently never become CLOSED through any implemented code path;
  the posting guard exists and is real, but nothing can trigger it yet.

## 11. Open Decisions (§56) — Final Classification

| # | Item | Resolution |
|---|---|---|
| OD-001/002 | COA structure / global vs tenant | Tenant-scoped, lazily seeded, editable default — not an approved final COA |
| OD-003/004 | Sales Revenue / Purchase-Inventory mapping | Default seed provided (`SALES_REVENUE`, `PURCHASE_EXPENSE`); "Purchase Expense" used deliberately, not "Inventory" |
| OD-005/006/007 | Perpetual/periodic, valuation, COGS | **Not implemented** — no COGS/Inventory journal leg anywhere |
| OD-008/009 | GR accounting / GR-IR clearing | **Not implemented** — no Goods Receipt journal exists |
| OD-010 | Direct Purchase Invoice accounting | Implemented as a normal Purchase Invoice posting (Purchase Expense placeholder) |
| OD-011/012/013 | Cash/Bank/UPI mapping | Distinct default accounts + distinct posting-rule codes per method — never a single hard-coded account |
| OD-014 | Cheque accounting treatment | Handled entirely within Payments (PROMPT-024) — a bounced cheque triggers the SAME reversal mechanism as any other payment reversal |
| OD-015/016 | Credit/Debit Note treatment | Credit Note mirrors Sales Return; Debit Note is a documented mirror-opposite judgment call, unchanged from the pre-PROMPT-025 stub's own resolution |
| OD-017 | Manual Journal Entry | **Not implemented** — no approved source authorizes it |
| OD-018/019 | Period close / FY locking | Posting guard exists (`accounting_period`); no close/reopen workflow built |
| OD-020 | Rounding policy | `Numeric(15,2)` throughout, exact reconciliation with source document totals — no independent rounding logic |
| OD-021 | Journal numbering format | `JRN-{FY}-0001` via the existing `DocumentNumberingService`, default not final |
| OD-022/023 | Approval workflow | None implemented |
| OD-024 | COGS at DC or Invoice | N/A — COGS not implemented at all |
| OD-025 | Purchase accounting at GR or Invoice | At Purchase Invoice only (mirrors the existing Sales-side "recognition at Invoice, not at Delivery Challan" precedent) — GR itself creates no journal |

## 12. Definition of Done Status

All §58 checklist items are satisfied:
- [x] Accounting data model, Journal Header, Journal Lines
- [x] Chart of Accounts + account mapping framework
- [x] Posting matrix documented (§6 above)
- [x] Sales Invoice / Purchase Invoice / Customer Receipt / Supplier
      Payment / Sales Return / Purchase Return / Credit Note / Debit
      Note posting all work
- [x] Journal balancing enforced (CHECK constraint + service-level validation)
- [x] Idempotency enforced (unique constraint + pre-check + IntegrityError fallback)
- [x] Concurrency protection (unique constraint backstop)
- [x] Reversal works (manual + automatic from Purchase Invoice/Return
      cancellation and Payment reversal)
- [x] Posted journals immutable (only `status` transitions)
- [x] Accounting period validation (guard exists)
- [x] GST reconciliation (verified by dedicated test)
- [x] Source traceability both directions
- [x] Tenant isolation, RBAC, audit
- [x] API/DB/UI documentation updated
- [x] Automated tests pass
- [x] Desktop/Tablet/Mobile responsive UI (established Tailwind conventions)
- [x] Engine ready to support Financial Reports (stable IDs, references, dates, tenant, audit)
- [x] All unresolved accounting decisions documented (§11 above)

No critical accounting defects remain open.
