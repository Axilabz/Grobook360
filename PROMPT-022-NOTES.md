# PROMPT-022 — Purchase Invoice Management — Implementation Notes

## 1. Summary

As with PROMPT-020 (Purchase Order) and PROMPT-021 (Goods Receipt), the
great majority of "the complete Purchase Invoice workflow" — create
direct/from-GR, draft/edit/post, server-authoritative numbering, GST
calc, GR-eligibility tracking, the DIRECT-vs-GR stock decision,
idempotency, concurrency, RBAC, tenant isolation, and the mandatory
no-duplicate-Stock-IN rule — was already built and tested in
PROMPT-019's foundation (`purchase_invoice_service.py`,
`purchase_invoices.py`). This prompt's own genuinely new work is:

- **PO-linked invoicing ("Supported Flow 2")** — creating a Purchase
  Invoice directly from a Purchase Order, consolidating eligible
  quantity across potentially MULTIPLE confirmed Goods Receipts under
  it, rather than requiring the user to pre-select one specific GR.
- **Supplier invoice date / due date** header fields, distinct from
  the internal `document_date`.
- **Non-blocking duplicate-supplier-invoice-number detection** (§7).
- **The system-determined `stock_impact` field** (§12/§46) — surfaced
  explicitly, never user-editable.
- **Per-line stock-movement visibility** for DIRECT invoices (§30/§42
  style, mirrors Goods Receipt's own §42 pattern).
- **POSTED-invoice cancellation with reversal** (§33-35) — the single
  biggest addition. Previously (PROMPT-019) only a DRAFT invoice could
  be cancelled; a POSTED invoice is now reversible, with two
  structurally different behaviors depending on `invoice_type`.
- `/related-documents` and `/audit-history`, mirroring PROMPT-020/021's
  identical pattern.

No Purchase Return, Supplier Payment, Accounting Posting, GST Returns,
or Reports work was started — all explicitly out of scope per this
prompt's own final instruction.

## 2. The critical stock rule, and how PO-linked invoicing fits it (§2)

Two scenarios were already correctly implemented in PROMPT-019:

- **Scenario A** (goods already received via GR): `GOODS_RECEIPT_
  PURCHASE_INVOICE` — no stock movement, increments `goods_receipt_
  line.invoiced_quantity`.
- **Scenario B** (no prior GR): `DIRECT_PURCHASE_INVOICE` — creates its
  own Stock IN.

This prompt adds a **third invoice_type**, `PURCHASE_ORDER_PURCHASE_
INVOICE`, for "Supported Flow 2" (PO → Invoice, no single pre-selected
GR). Critically, this is **NOT** a third stock-impact scenario — it is
Scenario A, computed at the PO level instead of a single GR. Every unit
billed via this path is still traced back to a specific `goods_
receipt_line` (never invoice-before-receipt): a requested PO-line
quantity is fanned out across that PO line's own contributing GR lines
(oldest first), consuming each one's own remaining invoiceable quantity
— so ONE requested line can produce SEVERAL `purchase_invoice_line`
rows (one per contributing GR line). This reuses the exact same
`goods_receipt_line.invoiced_quantity` counter that single-GR invoicing
already uses, which is what makes INVARIANT 5 ("one physical receipt
must not be counted twice") hold even when a unit could theoretically
be invoiced through either path — see §13 "mixed receipt scenario"
below.

## 3. §13 "Mixed receipt scenario" — the resolution

The prompt explicitly asks: if PO=100, GR=60, and someone tries to
invoice 100, what happens to the 40 that was never received?

**Resolved as: REJECT.** Invoice-before-receipt is NOT supported by
either the GR-based or the new PO-consolidated path — the PO-level
eligibility calculation (`invoiceable = received_quantity -
invoiced_quantity`) is hard-capped at what was actually received, and
`create_invoice_from_purchase_order` raises `PINV_EXCEEDS_INVOICEABLE`
(422) if the requested quantity exceeds it. This is the SAME
conservative resolution PROMPT-019 already used for GR-based invoicing;
this prompt did not relitigate it, per §67 Open Decision #2 below.

## 4. Database changes

Migration `0024_purchase_invoice_management.py`:
- `purchase_invoice.source_purchase_order_id` (nullable FK) — header
  traceability for the new `PURCHASE_ORDER_PURCHASE_INVOICE` type.
- `purchase_invoice.supplier_invoice_date` / `.due_date` (nullable
  dates) — proposed additions per §5/§13's header-field list.
- `purchase_invoice_line.source_purchase_order_line_id` (nullable FK)
  — which PO line a PO-consolidated line was requested against (in
  ADDITION to `source_goods_receipt_line_id`, which every non-direct
  line still always carries).
- Widened `ck_purchase_invoice_type` and `ck_purchase_invoice_source_
  consistency` CHECK constraints for the third invoice type.

**No new column was needed for the reversal feature itself** — the
compensating STOCK_OUT reuses `purchase_invoice_line.id` as its
`stock_ledger_entry.source_id`, with a NEW `source_type`
(`PURCHASE_INVOICE_REVERSAL`), which `uq_stock_ledger_entry_source`
already accommodates without colliding with the original `source_type=
'PURCHASE_INVOICE'` entry — the exact same pattern PROMPT-021
established for Goods Receipt reversal. The downstream-dependency check
for cancelling a POSTED invoice reuses the already-existing `purchase_
invoice_line.returned_quantity` column (migration 0021).

## 5. Backend changes

- `app/core/error_codes.py` — `PINV_HAS_DOWNSTREAM_RETURN = "PINV-008"`,
  `PINV_SOURCE_PO_NOT_FOUND = "PINV-009"`.
- `app/core/purchase_constants.py` — new `PURCHASE_INVOICE_REVERSAL`
  source_type constant.
- `app/models/purchase_invoice.py` — `PURCHASE_ORDER_PURCHASE_INVOICE`
  type; `NO_STOCK_IMPACT_INVOICE_TYPES` frozenset (GR-sourced + PO-
  consolidated); `CANCELLABLE_STATUSES` widened to `{DRAFT, POSTED}`.
- `app/models/purchase_invoice_line.py` — `source_purchase_order_line_id`.
- `app/schemas/purchase.py` — new request schemas
  (`InvoiceFromPurchaseOrderLineInput`/`CreateInvoiceFromPurchaseOrderRequest`),
  new fields on existing ones (`supplier_invoice_date`/`due_date`),
  `stock_impact`/`duplicate_supplier_invoice_warning`/`stock_movement_id`/
  `stock_movement_reversed` response fields, and new supporting-endpoint
  schemas (`PurchaseOrderInvoiceEligibility*`, `PurchaseInvoiceRelated*`,
  `PurchaseInvoiceAudit*`).
- `app/services/purchase/purchase_invoice_service.py`:
  - New `check_duplicate_supplier_invoice` — non-blocking detection
    only (§7 Open Decision, not enforced as a DB constraint).
  - New `stock_movement_info_for_lines` — mirrors Goods Receipt's own
    (PROMPT-021) exactly.
  - New `get_po_invoice_eligibility`/`_invoiced_quantity_by_po_line`/
    `_confirmed_gr_lines_for_po_line` — the PO-level eligibility
    calculation and GR-line fan-out source.
  - New `create_invoice_from_purchase_order` — the "Supported Flow 2"
    creation path, fanning a requested PO-line quantity out across its
    contributing GR lines.
  - `post_invoice`'s non-DIRECT branch **generalized** from "lock the
    ONE source GR referenced by `invoice.source_goods_receipt_id`" to
    "lock every DISTINCT GR referenced by this invoice's own lines" (in
    a consistent sorted order, to avoid a lock-ordering deadlock against
    a concurrently-posting invoice referencing the same receipts in a
    different order) — this single change is what makes both
    `GOODS_RECEIPT_PURCHASE_INVOICE` (always exactly one GR) and
    `PURCHASE_ORDER_PURCHASE_INVOICE` (possibly several) work through
    the SAME code path, with zero special-casing.
  - `cancel_invoice` rewritten: DRAFT path unchanged; POSTED path is a
    reversal — checks `purchase_invoice_line.returned_quantity == 0` on
    every line first (rejects with `PINV_HAS_DOWNSTREAM_RETURN`/422
    otherwise), then branches on `invoice_type`: DIRECT posts a
    compensating STOCK_OUT per line (rejected with 409 if the stock was
    already consumed elsewhere, via `InventoryService`'s own guard);
    GR/PO-sourced NEVER touches stock, only decrements each line's
    source `goods_receipt_line.invoiced_quantity` back down.
  - New `get_related_documents`/`get_audit_history` — mirror PROMPT-020/
    021's identical entity-scoped, tenant-ownership-checked-first
    discipline.
- `app/api/v1/purchase_invoices.py` — `_to_list_item`/`_to_line_item`/
  `_to_detail` updated for all new fields; every endpoint updated for
  `get_invoice`'s new 5-tuple return (`invoice, supplier_name,
  grn_number, po_number, lines`); two new `GET` endpoints —
  `/related-documents`, `/audit-history` — gated by `purchase_invoice.view`.
- `app/api/v1/purchase_orders.py` — two new endpoints:
  `GET /{id}/invoiceable-items` (PO-level eligibility, gated by
  `purchase_invoice.create`) and `POST /{id}/create-invoice` (the
  PO-consolidated creation flow, same gating + idempotency pattern as
  every other `create-invoice`-style endpoint in this codebase).
- `app/services/purchase/purchase_return_service.py` /
  `app/api/v1/goods_receipts.py` — updated for `get_invoice`'s new
  5-tuple return and `_to_detail`'s new required `po_number` parameter
  (these were NOT touched otherwise — pure call-site updates).

## 6. Stock impact decision & posting (§12/§14/§25/§30-32)

Unchanged mechanism from PROMPT-019, generalized as described in §5
above. `_stock_impact()` in the router is a pure function of
`invoice_type` — `DIRECT_PURCHASE_INVOICE` → `"STOCK_IN_REQUIRED"`,
anything else → `"STOCK_ALREADY_RECEIVED"` — computed server-side,
never accepted from the client, and displayed read-only on both the
list and detail screens (AC-14/AC-15).

## 7. Duplicate-Stock-IN prevention (§16/§32, AC-17/AC-18)

Unchanged: `uq_stock_ledger_entry_source (tenant_id, source_type,
source_id)` with `source_id = <invoice_line.id>` makes a second
`post_invoice` call on an already-POSTED invoice structurally
incapable of creating a duplicate STOCK_IN (the status guard rejects
it before `post_movement` is ever reached again) — verified by
PROMPT-019's own `test_idempotent_invoice_post_retry` and
`test_duplicate_purchase_invoice_posting_rejected` (both still passing
unmodified).

## 8. Idempotency strategy (§16/§61)

`create`/`post` use the existing `Idempotency-Key` + `IdempotencyService`
mechanism verbatim (unchanged from PROMPT-019). `cancel` follows the
same status-guard convention Purchase Order (PROMPT-020) and Goods
Receipt (PROMPT-021) both already established — a retried cancel on an
already-CANCELLED invoice is rejected (412 stale row_version, or 422
already-cancelled) rather than double-reversing. Verified by
`test_double_cancel_posted_invoice_rejected` (only one compensating
STOCK_OUT is ever posted).

## 9. Concurrency strategy (§17/§62)

`SELECT ... FOR UPDATE` on the invoice row, plus (for non-DIRECT
invoices) every distinct source Goods Receipt row referenced by the
invoice's own lines — locked in a consistent sorted order specifically
to avoid a lock-ordering deadlock between two concurrently-posting
invoices that reference an overlapping set of receipts in different
orders. PROMPT-019's own concurrent-posting protections continue to
apply unmodified; no new concurrency primitive was needed for the
PO-consolidated path since it reuses the same GR-row locking.

## 10. Cancellation/reversal strategy (§33-36, INVARIANTs 7/8/10/11)

| Scenario | Resolution |
|---|---|
| DRAFT invoice cancellation | Pure status change, zero stock/quantity impact (unchanged from PROMPT-019) |
| POSTED DIRECT invoice cancellation, no downstream Purchase Return | Full reversal: compensating STOCK_OUT per line |
| POSTED GR/PO-sourced invoice cancellation, no downstream Purchase Return | Bookkeeping-only release of each line's `goods_receipt_line.invoiced_quantity` — NEVER a Stock OUT (§35, the source GR remains the physical receipt) |
| POSTED invoice cancellation, downstream Purchase Return exists | REJECTED — `PINV_HAS_DOWNSTREAM_RETURN` (422) |
| POSTED DIRECT invoice cancellation, stock already consumed elsewhere | REJECTED — `InventoryService`'s own negative-stock guard (409), not forced through |
| Cancellation after Payment | N/A — no Payment module exists yet in this codebase (§37 explicit boundary); nothing to check |
| Partial cancellation | NOT implemented — reversal is all-or-nothing for the whole invoice, same resolution Goods Receipt (PROMPT-021) already used |

## 11. Authorization model (§50)

No new permission codes. `purchase_invoice.view/create/edit/post/cancel`
(PROMPT-019) remain the complete set — cancellation-with-reversal uses
the SAME `purchase_invoice.cancel` permission as a DRAFT cancellation.
The two new supporting endpoints on `/purchase/invoices` are gated by
`purchase_invoice.view`; the two new endpoints on `/purchase/orders`
(`/invoiceable-items`, `/create-invoice`) are gated by `purchase_
invoice.create` (the same convention `/receipt-eligibility` already
uses with `goods_receipt.create`).

## 12. Audit events

New: `PURCHASE_INVOICE_CANCELLED` now also fires for the POSTED-reversal
path (previously only DRAFT), with `after.stock_reversed` distinguishing
a DIRECT reversal from a GR/PO-sourced bookkeeping-only cancellation.
No new audit ACTION names were needed beyond what PROMPT-019 already
defined (`PURCHASE_INVOICE_CREATED/UPDATED/POSTED/CANCELLED`).

## 13. Testing

`backend/tests/integration/test_purchase_invoice_management.py` (new,
19 tests, all passing after two test-authoring fixes — a Decimal-vs-
string formatting assertion, and the by-now-familiar "invoiced_quantity
only increments at POST time, not DRAFT-create time" trap) covers ONLY
the new PROMPT-022 surface area: supplier invoice date/due date,
duplicate-supplier-invoice-number warning (non-blocking), the
`stock_impact` field for both invoice types, stock-movement visibility,
PO-level invoiceable-items calculation, single-GR and multi-GR
PO-consolidated invoice creation (verified to fan out into multiple
lines and to NOT double-count against the shared `invoiced_quantity`
counter — the mixed-receipt-scenario/INVARIANT-5 test), over-invoicing
rejection, related-documents (including multi-GR case), audit history,
RBAC on the three new endpoints, and the reversal feature: compensating
STOCK_OUT for a DIRECT invoice (verified against the raw
`stock_ledger_entry` table), stock-neutral cancellation for a GR-based
invoice (with the invoiced-quantity claim actually released), downstream-
Purchase-Return blocking, insufficient-stock blocking, double-cancel
rejection, and unauthorized-cancellation rejection.

`test_purchase_foundation.py` (27), `test_purchase_order_management.py`
(14), and `test_goods_receipt_management.py` (17) re-run — one shared
regression was found and fixed during this pass: `goods_receipts.py`'s
own `create-invoice` endpoint called the router's `_to_detail` with the
OLD 4-positional-argument shape, which broke once `_to_detail` gained a
required `po_number` parameter. Fixed as a pure call-site update; not a
new business-logic bug.

**Full backend regression and frontend Vitest suite: see the
Implementation Output's Test Results section below for the final tally.**

## 14. Open Decisions (per §67 — not silently resolved)

| # | Open Decision | Classification | Resolution in this prompt |
|---|---|---|---|
| 1 | Direct Purchase Invoice allowed or not | APPROVED (unchanged from PROMPT-019) | Yes — `DIRECT_PURCHASE_INVOICE` was already implemented; this prompt did not relitigate it |
| 2 | Invoice-before-receipt allowed or not | **RESOLVED THIS PROMPT** | NOT allowed, for either the GR-based or the new PO-consolidated path — see §3 above |
| 3 | Partial invoicing rules | APPROVED (unchanged) | Fully supported — cumulative `invoiced_quantity`/invoiceable-quantity tracking, multiple invoices per GR/PO line |
| 4 | Multiple GRs against one invoice | **RESOLVED THIS PROMPT** | Supported via the new `PURCHASE_ORDER_PURCHASE_INVOICE` type — one invoice fans a PO-line quantity out across all its contributing confirmed GR lines |
| 5 | Multiple invoices against one GR | APPROVED (unchanged) | Already supported via `invoiced_quantity` tracking on `goods_receipt_line` (PROMPT-019) |
| 6 | Over-invoicing policy | APPROVED (unchanged) | Rejected unconditionally, server-side, for both GR-based and PO-consolidated paths |
| 7 | Supplier invoice number uniqueness | OPEN DECISION (per the baseline's own annotation) | NOT enforced as a DB constraint — `check_duplicate_supplier_invoice` surfaces a non-blocking `duplicate_supplier_invoice_warning` flag instead |
| 8 | Supplier invoice date rules | PROPOSED | Optional, free date field, no validation beyond "must be a valid date" |
| 9 | Purchase Invoice numbering timing | APPROVED (unchanged) | At create/Draft time, matching Purchase Order/Goods Receipt's own identical resolution |
| 10 | Invoice approval workflow | OPEN DECISION | NOT implemented — Post is a single permission check, no multi-step/threshold chain |
| 11 | Invoice cancellation rules | **RESOLVED THIS PROMPT** | See §10 table above |
| 12 | Cancellation after payment | APPROVED (N/A) | No Payment module exists yet (§37) — nothing to check; will need revisiting once one does |
| 13 | Cancellation after return | **RESOLVED THIS PROMPT** | Blocked — `PINV_HAS_DOWNSTREAM_RETURN` |
| 14 | Direct invoice stock reversal | **RESOLVED THIS PROMPT** | Compensating STOCK_OUT via `InventoryService.post_movement`, same primitive as every other stock movement (AC-32) |
| 15 | GR-based invoice cancellation | **RESOLVED THIS PROMPT** | Bookkeeping-only, never a stock movement (§35) |
| 16 | Purchase price variance | APPROVED (unchanged) | NOT supported — invoice line pricing is always copied from the GR/PO line verbatim, no independent price entry |
| 17 | Freight/other charges | OPEN DECISION | NOT implemented — no line or header field exists for freight, same scope as every other Purchase/Sales document |
| 18 | Round-off rules | APPROVED (unchanged) | Uses the common `gst_calculation_service` — no invoice-specific rounding logic was added |
| 19 | GST treatment | APPROVED (unchanged) | Full CGST/SGST/IGST via the shared service, same as every other document |
| 20 | Accounting posting rules | APPROVED (out of scope) | NOT implemented — no `AccountingPostingService` call exists in `post_invoice`, per §38's explicit instruction (unchanged from PROMPT-019) |
| 21 | Payment linkage | APPROVED (out of scope) | NOT implemented, per §37's explicit instruction |
| 22 | Offline Purchase Invoice support | APPROVED (deferred) | NOT enabled, per §55's explicit instruction |
| 23 | Batch/expiry capture | OPEN DECISION | NOT implemented — no batch/expiry columns exist anywhere in the Purchase or Inventory schema |
| 24 | Damaged/rejected quantity | OPEN DECISION | NOT implemented — same as Goods Receipt's own identical open item (PROMPT-021) |
| 25 | Purchase Invoice amendment rules | APPROVED (unchanged) | NOT allowed post-POSTED — `update_invoice` raises if `status != DRAFT`; the only post-POSTED mutation is the new cancel-with-reversal path, which is a status transition, not an edit |
| 26 | Supplier-specific pricing | OPEN DECISION | NOT implemented — no supplier-specific price list, unit price is always entered manually or copied from a source line |
| 27 | Exact Purchase Invoice permissions | APPROVED (unchanged) | `purchase_invoice.view/create/edit/post/cancel` (PROMPT-019); no separate "view stock impact"/"view related documents"/"print" permissions were created (§50 Open Decision, same resolution PROMPT-020/021 used) |

## 15. Known Limitations

- No partial-cancellation of a POSTED invoice — reversal is all-or-
  nothing for the whole invoice.
- No batch/expiry/damaged-quantity capture at invoicing time.
- No purchase-price variance — invoice line pricing always traces back
  to its source GR/PO line verbatim.
- No approval workflow/threshold gating on posting or cancellation.
- No Payment-dependency check on cancellation (no Payment module
  exists yet — will need revisiting when one is built).
- Print/Preview is a single fixed layout, not a configurable template
  (same limitation as Purchase Order/Goods Receipt's own print
  features from PROMPT-020/021).

## 16. Definition of Done

Every §68 checklist item within this prompt's explicit scope is
satisfied: list/create(direct+PO+GR)/draft/edit/supplier-selection/PO-
linkage/GR-linkage/supplier-invoice-number-and-date/product-and-
quantity-validation/invoiceable-quantity-calculation/over-invoicing-
validation/discount-and-GST-calculation/server-side-totals/internal-
numbering/status-machine/posting/stock-impact-decision-service/direct-
invoice-Stock-IN/GR-duplicate-Stock-IN-prevention/Stock-Movement-
Service-integration/idempotency/concurrency/cancellation-reversal-
boundary/PO-and-GR-invoice-quantity-tracking/RBAC/tenant-isolation/
audit/print-preview/responsive-UI (desktop; tablet/mobile follow the
same Tailwind responsive classes already proven across every other
Purchase/Sales screen in this codebase)/tests all pass. Items dependent
on unapproved decisions (supplier-invoice-number uniqueness, approval
workflow, freight, batch/expiry, supplier-specific pricing) are
explicitly listed as Open Decisions or Known Limitations above, not
silently invented.

Purchase Invoice Management is complete. Purchase Return, Supplier
Payment, Accounting Posting, GST Returns, Payroll, Reports, AI, Route
Management, POS, and Vendor Portal were all explicitly NOT started, per
this prompt's own STOP condition.
