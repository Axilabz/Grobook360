# PROMPT-019 — Purchase Management Foundation — Implementation Notes

## 1. Summary

This prompt establishes the FOUNDATION for the procurement lifecycle:
Supplier → Purchase Order → Goods Receipt → Purchase Invoice → Payment,
plus Purchase Invoice → Purchase Return → Supplier Adjustment. The
prompt's own instruction explicitly forbade building the complete,
production-grade PO/GR/PI/PR workflow, reporting, Payments, Accounting,
GST Returns, or Payroll in this pass — yet its own 26 mandatory test
cases require genuinely working create/confirm/post/cancel/receive/
return operations with real stock effects, idempotency, and concurrency
protection. This was resolved by mirroring the already-proven Sales
document chain (Estimate → Sales Order → Delivery Challan → Sales
Invoice → Sales Return, PROMPT-012 through PROMPT-016) architecture
exactly, scoped appropriately for a foundation rather than either
inert placeholders or full production polish.

Four concrete document types were built:
- **Purchase Order** (mirrors Sales Order — never touches inventory)
- **Goods Receipt** (mirrors Delivery Challan — first to move stock,
  creates STOCK_IN)
- **Purchase Invoice** (mirrors Sales Invoice — DIRECT vs
  GOODS_RECEIPT-based branching; only the DIRECT branch moves stock)
- **Purchase Return** (mirrors Sales Return — creates STOCK_OUT,
  requires a source POSTED Purchase Invoice)

## 2. Existing components reused

- Auth/tenant/RBAC (`app.core.deps`, `app.core.permissions`)
- `AuditService.record` — the only writer of `audit_log`
- `IdempotencyService` — the HTTP-level replay guard, reused verbatim
  via the established `_idempotent_post` router helper pattern
- `check_row_version` / optimistic concurrency (`If-Match`/
  `expected_row_version`)
- `InventoryService.post_movement` — the SOLE stock-mutation primitive
  (PROMPT-010). No second inventory/stock-calculation engine was built.
- `app.services.sales.gst_calculation_service` (`determine_gst_treatment`,
  `calculate_line`, `calculate_document_totals`) — reused verbatim, no
  new tax logic invented for Purchase.
- `app.services.sales.document_numbering_service` — reused for
  `PO-{FY}-0001`/`GRN-{FY}-0001`/`PINV-{FY}-0001`/`PRET-{FY}-0001`
  numbering.
- `SupplierService.get_supplier` / `ProductService.get_product` — reused
  by the new `purchase_validation_service.py` rather than re-querying
  those tables directly.
- Row-level locking pattern (`SELECT ... FOR UPDATE`) from
  `SalesOrderService.get_order_locked`/`DeliveryChallanService`/
  `SalesInvoiceService` — reused identically for
  `PurchaseOrderService.get_order_locked`/`GoodsReceiptService.
  get_receipt_locked`/`PurchaseInvoiceService.get_invoice_locked`.

## 3. Database changes

Migration `0021_purchase_foundation.py` — 8 new tables, all "propose,
document, implement" additions on top of the approved Data Dictionary
baseline (which specifies these documents but not every column used
here):

- `purchase_order` / `purchase_order_line` — header GST split
  (subtotal/discount_total/taxable_total/cgst_total/sgst_total/
  igst_total/tax_total/grand_total), supplier identity snapshot fields
  (`supplier_gstin`), `billing_address` (the TENANT's own address — the
  buyer, inverted from a Sales document's billing_address which is the
  customer's), `shipping_address`, `place_of_supply_state_code`.
  Line-level proposed addition: `received_quantity` (cumulative,
  written only by `PurchaseOrderService.apply_receipt`).
- `goods_receipt` / `goods_receipt_line` — `source_purchase_order_id`
  nullable per the baseline (ad-hoc GR without a PO is NOT exercised by
  any service method in this foundation — see Open Decisions). Line
  snapshot fields (`ordered_quantity`, `previously_received_quantity`,
  `quantity`, `remaining_quantity`, refreshed at CONFIRM time, mirrors
  `delivery_challan_line`). Proposed addition: `invoiced_quantity`
  (mirrors `delivery_challan_line.invoiced_quantity`).
- `purchase_invoice` / `purchase_invoice_line` — `invoice_type` CHECK
  constraint (`ck_purchase_invoice_source_consistency`, mirrors Sales
  Invoice's identical constraint) enforcing DIRECT_PURCHASE_INVOICE has
  no source GR and GOODS_RECEIPT_PURCHASE_INVOICE always has one.
  `source_goods_receipt_id` nullable; NO `source_purchase_order_id`
  column exists (the baseline doesn't support a direct PO reference —
  see Open Decisions). `supplier_invoice_number` nullable, NOT
  unique-enforced (baseline's own "Duplicate policy to confirm"
  annotation — see Open Decisions). Proposed line addition:
  `source_goods_receipt_line_id` (nullable, links a GR-based line back
  to its source GR line) and `returned_quantity` (mirrors
  `sales_invoice_line.returned_quantity`).
- `purchase_return` / `purchase_return_line` — `source_purchase_invoice_id`
  NOT NULL (the baseline itself only supports Purchase-Return-from-
  Invoice, resolving that Open Decision definitively). Proposed
  `return_reason` taxonomy (`DAMAGED`/`WRONG_PRODUCT`/`EXCESS_QUANTITY`/
  `QUALITY_ISSUE`/`PRICE_DISPUTE`/`OTHER`), mirrors Sales Return's
  identical resolution pattern (PROMPT-016).

All 8 tables carry `id, tenant_id, created_by, created_at, updated_by,
updated_at, row_version` per the codebase's standard mutable-table
mixins, RLS policies (`tenant_isolation_<table>`), status CHECK
constraints, and per-header line-number uniqueness constraints.

Also seeds 20 new permission codes and their OWNER/MANAGER role
defaults (see §7 below).

## 4. Backend

- `app/core/purchase_constants.py` (new) — document-type constants,
  `STOCK_EFFECT_BY_DOCUMENT_TYPE` documentation dict.
- `app/models/purchase_order.py`, `purchase_order_line.py`,
  `goods_receipt.py`, `goods_receipt_line.py`, `purchase_invoice.py`,
  `purchase_invoice_line.py`, `purchase_return.py`,
  `purchase_return_line.py` (new)
- `app/services/purchase/` (new package):
  - `purchase_validation_service.py` — supplier/product validation for
    Purchase, reusing `SupplierService`/`ProductService`
  - `purchase_order_service.py` — `PurchaseOrderService`
    (create/update/confirm/cancel/list/get, plus the public
    `apply_receipt`/`get_order_locked`/`get_lines` entrypoints
    `GoodsReceiptService` calls into)
  - `goods_receipt_service.py` — `GoodsReceiptService`
    (create/update/confirm/cancel/list/get/get_receipt_eligibility,
    plus public `get_receipt_locked`/`get_lines` for
    `PurchaseInvoiceService`)
  - `purchase_invoice_service.py` — `PurchaseInvoiceService`
    (create_direct_invoice/create_invoice_from_receipt/update/post/
    cancel/list/get/get_invoice_eligibility, plus public
    `get_invoice_locked`/`get_lines` for `PurchaseReturnService`)
  - `purchase_return_service.py` — `PurchaseReturnService`
    (create/update/confirm/cancel/list/get/get_return_eligibility)
- `app/schemas/purchase.py` (new, consolidated) — all 4 document types'
  request/response schemas in one file, appropriate for a foundation
  prompt.
- `app/api/v1/purchase_orders.py`, `goods_receipts.py`,
  `purchase_invoices.py`, `purchase_returns.py` (new routers)
- `app/api/v1/__init__.py` — registered all 4 new routers
- `app/core/error_codes.py` — `PURCH-001..004`, `PO-001..004`,
  `GR-001..006`, `PINV-001..007`, `PRET-001..008`
- `app/core/permissions.py` — 20 new permission codes (§7)

## 5. Stock integration behavior (§4/§10, the mandatory rule)

- **Purchase Order NEVER moves stock** — `purchase_order_service.py`
  has no import of `InventoryService`/`post_movement` anywhere in the
  file. Verified by `test_po_creation_does_not_change_stock` and
  `test_po_confirmation_does_not_change_stock`.
- **Goods Receipt confirmation creates STOCK_IN** — one movement per
  LINE (`source_type=GOODS_RECEIPT, source_id=<gr_line.id>`), reusing
  the `uq_stock_ledger_entry_source` constraint for duplicate
  protection, identical to Delivery Challan's pattern.
- **Purchase Invoice**: DIRECT_PURCHASE_INVOICE calls `post_movement`
  per line (STOCK_IN); GOODS_RECEIPT_PURCHASE_INVOICE's branch NEVER
  calls `post_movement` at all — this file structurally cannot
  double-deduct, mirroring PROMPT-015's Sales Invoice DC-branch
  discipline exactly. Verified by
  `test_mandatory_no_duplicate_stock_in_from_gr_invoice` (stock stays
  at 20 after both the GR confirm AND the subsequent GR-based invoice
  post, never doubling to 40).
- **Purchase Return confirmation creates STOCK_OUT** — one movement per
  line, mirrors Sales Return exactly.

## 6. Idempotency strategy

Same as every prior module: `Idempotency-Key` header required on every
document-creating and status-transitioning `POST` (create/confirm/post/
cancel), checked via the existing `IdempotencyService` before executing,
stored after. Verified with dedicated retry tests for GR confirm,
Purchase Invoice post, and Purchase Return confirm — each shows the
second call with the same key returns the identical response body and
that only ONE stock movement was ever applied.

## 7. Concurrency strategy

- Optimistic concurrency (`row_version`/`expected_row_version`) on
  every mutating endpoint — a stale `expected_row_version` returns 412.
- Row-level locking (`SELECT ... FOR UPDATE`) on the "source" document
  before re-validating a live remaining/invoiceable/returnable quantity:
  `PurchaseOrderService.get_order_locked` (called from
  `GoodsReceiptService.confirm_receipt`), `GoodsReceiptService.
  get_receipt_locked` (called from `PurchaseInvoiceService.post_invoice`
  for the GR-based branch), `PurchaseInvoiceService.get_invoice_locked`
  (called from `PurchaseReturnService.confirm_return`).
- Verified by `test_concurrent_receipt_only_one_succeeds` — two
  concurrent Goods Receipt confirmations against the same 50-unit-
  remaining Purchase Order line for 40 units each: exactly one succeeds
  (200), the other is rejected (422, exceeds the now-10-remaining
  quantity) — no overselling/over-receiving under a race.

## 8. Authorization model (§4 of CLAUDE.md's "Known Open Decisions" —
NOT a weak-signal judgment call)

FRD Table 7 (Role & Screen matrix) explicitly lists Purchase Orders/
Goods Receipt/Purchase Invoice as **"Owner, Manager"** with **NO
Salesperson entry at all** — unlike every Sales-document row, which
always names Salesperson too (sometimes as "Limited"). This is a direct
reading of the approved matrix, not a judgment call:

| Permission group | Owner | Manager | Salesperson |
|---|---|---|---|
| `purchase_order.*` (view/create/edit/confirm/cancel) | ✅ | ✅ | ❌ |
| `goods_receipt.*` (view/create/edit/confirm/cancel) | ✅ | ✅ | ❌ |
| `purchase_invoice.*` (view/create/edit/post/cancel) | ✅ | ✅ | ❌ |
| `purchase_return.*` (view/create/edit/confirm/cancel) | ✅ | ✅ | ❌ |

Verified by `test_salesperson_cannot_view_purchase_orders` and the
existing RBAC test suite's Manager-full-permission-set assertions
(updated to include all 20 new codes).

## 9. Audit events

`AuditService.record()` calls for: `PURCHASE_ORDER_CREATED/UPDATED/
CONFIRMED/CANCELLED/RECEIPT_UPDATED`, `GOODS_RECEIPT_CREATED/UPDATED/
CONFIRMED/CANCELLED`, `PURCHASE_INVOICE_CREATED/UPDATED/POSTED/
CANCELLED`, `PURCHASE_RETURN_CREATED/UPDATED/CONFIRMED/CANCELLED`.
Verified by `test_audit_events_recorded`.

## 10. Frontend

- `api/purchaseOrders.ts`, `api/goodsReceipts.ts`,
  `api/purchaseInvoices.ts`, `api/purchaseReturns.ts` (new) — mirror
  the shape of `api/salesOrders.ts`/`api/deliveryChallans.ts`/
  `api/salesInvoices.ts`/`api/salesReturns.ts` exactly.
- `shared/SupplierSelector.tsx` (new) — Purchase's counterpart to
  `shared/CustomerSelector.tsx`, reused by Purchase Order and direct
  Purchase Invoice creation.
- `components/PurchaseOrderManagement.tsx`,
  `GoodsReceiptManagement.tsx`, `PurchaseInvoiceManagement.tsx`,
  `PurchaseReturnManagement.tsx` (new) — mirror the exact structure of
  `SalesOrderManagement.tsx`/`DeliveryChallanManagement.tsx`/
  `SalesInvoiceManagement.tsx`/`SalesReturnManagement.tsx`, reusing the
  existing `shared/ProductLineSelector.tsx` for line entry. No
  e-Invoice/e-Way Bill panel or accounting-reference display exists on
  Purchase Invoice (§14 below).
- `components/Sidebar.tsx` — "Purchase" menu now lists Suppliers,
  Purchase Orders, Goods Receipts, Purchase Invoices, Purchase Returns,
  each gated by its own `*.view` permission (UX-only — backend
  independently re-checks every one).
- `App.tsx` — wired `dashboardView` routing for all 4 new screens.

## 11. Testing

`backend/tests/integration/test_purchase_foundation.py` (new, 27 tests,
all passing on first full run) covers: PO create/confirm/no-stock-
change, cross-tenant access, Salesperson RBAC denial, GR confirm →
STOCK_IN, partial/cumulative receiving, full-receipt PO status
transition, over-receipt prevention, duplicate GR confirmation
rejection, idempotent GR confirm retry, concurrent receipt protection
(only one of two racing confirms succeeds), direct Purchase Invoice →
STOCK_IN, **the mandatory no-duplicate-stock-in-from-GR-invoice test**,
invoice-from-unconfirmed-GR rejection, duplicate invoice posting
rejection, idempotent invoice post retry, Purchase Return → STOCK_OUT,
excess-return prevention, duplicate return confirmation rejection,
idempotent return confirm retry, POSTED-invoice immutability, DRAFT PO
cancellation, row-version conflict (412), audit event verification,
list/search/filter, and server-authoritative GST calculation (client
tampering with `grand_total` is ignored).

`backend/tests/integration/test_rbac.py` was updated to include the 20
new permission codes in both Manager-full-permission-set assertions
(16 tests, still all passing).

**Full backend regression suite: 502 tests (475 pre-existing + 27 new),
all passing.** Frontend TypeScript compiles cleanly for every new file
(pre-existing, unrelated `ErrorBoundary.tsx` errors are untouched by
this prompt).

## 12. Open Decisions (per §46 — not silently resolved)

| # | Open Decision | Resolution in this prompt |
|---|---|---|
| 1 | Ad-hoc Goods Receipt without a source Purchase Order | `source_purchase_order_id` is nullable per the baseline, but NO service method in this foundation creates one without a PO — unexercised, flagged for a future prompt |
| 2 | Purchase Invoice directly from a Purchase Order (no GR) | NOT implemented — no `source_purchase_order_id` column exists on `purchase_invoice` at all (the baseline only supports GR-based or fully direct) |
| 3 | Purchase Return against a Goods Receipt or other source | NOT implemented — `source_purchase_invoice_id` is NOT NULL; invoice-only, per the baseline schema itself |
| 4 | `supplier_invoice_number` uniqueness | NOT enforced — baseline's own "Duplicate policy to confirm" annotation; left as a free, non-unique text field |
| 5 | Purchase Order cancellation after partial receipt | Allowed (`CANCELLABLE_STATUSES` includes `PARTIALLY_RECEIVED`) — already-received quantity is unaffected, no reversal |
| 6 | Goods Receipt / Purchase Invoice / Purchase Return cancellation after confirmation/posting | NOT allowed — `CANCELLABLE_STATUSES = {DRAFT}` for all three, mirrors Delivery Challan/Sales Invoice/Sales Return's identical resolution |
| 7 | GR-based Purchase Invoice line discount proration | NOT needed in this foundation — `goods_receipt_line.discount_amount` is always 0 (no receipt-time discount input path exists), so GR-based invoice lines copy the GR line's price/GST directly rather than prorating |
| 8 | Accounting integration boundary for Purchase Invoice | Explicitly OUT OF SCOPE per this prompt's own §14 instruction — `post_invoice` has no `AccountingPostingService` call at all (unlike Sales Invoice in PROMPT-015) |
| 9 | GST reporting integration boundary for Purchase Invoice | Same as #8 — not implemented, no call site exists |
| 10 | `purchase_return.return_reason` taxonomy | Proposed, non-final (`DAMAGED`/`WRONG_PRODUCT`/`EXCESS_QUANTITY`/`QUALITY_ISSUE`/`PRICE_DISPUTE`/`OTHER`) — mirrors Sales Return's identical resolution pattern, needs Product Owner sign-off |
| 11 | Salesperson's exact Purchase permissions | Resolved as a DIRECT reading of FRD Table 7 (Owner/Manager only, no Salesperson row) — not a judgment call, unlike several prior Sales-module RBAC decisions |
| 12 | Purchase Order UOM conversion at receipt time | NOT implemented — `goods_receipt_line.quantity` is captured in the PO line's own UOM only; no conversion UI/logic exists |
| 13 | Multi-location receiving | NOT implemented — reuses `InventoryService.ensure_default_location()`'s single lazily-provisioned "MAIN" location per tenant (PROMPT-010's existing scope, unchanged) |
| 14 | Supplier payable balance / Payment tracking | NOT implemented — `supplier.balance` is not written to by any Purchase document in this foundation; Payment is a future prompt |
| 15 | Detailed Purchase reports (aging, GRN register, etc.) | NOT implemented — explicitly out of scope per this prompt's own instruction |

## 13. Known Limitations

- No Purchase Order → direct Purchase Invoice path exists (only via a
  Goods Receipt, or a fully independent Direct Purchase Invoice) — see
  Open Decision #2.
- No ad-hoc (PO-less) Goods Receipt creation path is exercised, even
  though the schema technically permits a null `source_purchase_order_id`.
- No accounting/GST integration boundary exists for Purchase Invoice —
  a deliberate, explicit scope exclusion (§14), not an oversight.
- No Payment/Receipt-against-invoice functionality — supplier payable
  balances are not tracked or updated anywhere in this foundation.
- No detailed Purchase reports (aging, GRN register, PO status report)
  — explicitly deferred.
- Print/preview integration for any of the 4 new document types is not
  wired up.

## 14. Definition of Done

All items in §47's checklist are satisfied for the foundation scope
explicitly implemented — 4 working document types with real stock
effects, idempotency, concurrency protection, and RBAC, all covered by
27 new passing tests plus a clean 502-test full regression run — with
items dependent on unapproved decisions (PO→direct-invoice path, ad-hoc
GR, accounting/GST integration, Payments, detailed reports) explicitly
called out above as Open Decisions or Known Limitations rather than
silently skipped or silently invented.

Purchase Management Foundation is complete and ready for the next
prompt. Detailed PO/GR/PI/PR workflow deepening, Payments, a real
Accounting module, GST Return filing, Payroll, and detailed Reports
were all explicitly NOT started, per this prompt's own STOP condition.
