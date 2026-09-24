# PROMPT-020 — Purchase Order Management — Implementation Notes

## 1. Summary

PROMPT-020 asked for the "complete Purchase Order workflow." The great
majority of that workflow — create/save-draft/edit-draft/confirm/cancel,
server-authoritative numbering and GST calculation, ordered/received/
remaining quantity tracking, partial receiving, over-receipt prevention,
row-version concurrency, RBAC, tenant isolation, and the mandatory
"PO never moves stock" rule — was already built and tested in
PROMPT-019's Purchase Management Foundation (`purchase_order_service.py`,
`purchase_orders.py`, `test_purchase_foundation.py`). This prompt's own
work is therefore the genuinely NEW surface area PROMPT-019 didn't cover:

- Four new header fields (`supplier_reference`, `expected_delivery_date`,
  `payment_terms`, `delivery_terms`) — §4/§48 Open Decisions #6-9.
- Ordered/received/remaining quantities now exposed on the LIST screen
  (not just detail) and at line level as an explicit `remaining_quantity`.
- Three new supporting endpoints: `GET .../related-documents`,
  `GET .../receiving-summary`, `GET .../audit-history` — §17/§24/§30/
  §34/§38.
- Print/Preview capability (§36) — entirely new, no print infrastructure
  existed anywhere in this codebase before this prompt.
- Explicit idempotent-duplicate-confirm/cancel test coverage (TC-027/
  028) confirming the existing status-guard + row-version behavior
  already satisfies AC-20 without needing new server logic.

No new document types, no Goods Receipt/Purchase Invoice/Purchase
Return workflow changes, no Payments/Accounting/GST Returns — all
explicitly out of scope per this prompt's own final instruction.

## 2. Existing components reused (unchanged from PROMPT-019)

- `app.services.sales.gst_calculation_service` / `document_numbering_service`
- `PurchaseValidationService` (supplier/product validation)
- `AuditService.record` — still the only writer of `audit_log`
- `check_row_version` / optimistic concurrency
- `InventoryService.post_movement` — still never imported by
  `purchase_order_service.py` (§16's mandatory "PO = NO STOCK MOVEMENT"
  rule, re-verified, not re-litigated)

## 3. Database changes

Migration `0022_purchase_order_management.py` adds 4 nullable columns to
`purchase_order`: `supplier_reference` (VARCHAR 100), `expected_delivery_date`
(DATE), `payment_terms` (VARCHAR 200), `delivery_terms` (VARCHAR 200).
All nullable — no existing row is broken, matching the "propose,
document, implement" pattern used for every prior Purchase/Sales column
addition.

**Deliberately NOT added** (see §12 Open Decisions below for the full
rationale): `location_id` (M1 has exactly one lazily-provisioned
location; a FK column would be dead weight until multi-location is
approved) and `currency` (this MVP is INR-only throughout — no other
Sales or Purchase document carries a currency column either).

## 4. Backend changes

- `app/models/purchase_order.py` — 4 new columns.
- `app/schemas/purchase.py` — `CreatePurchaseOrderRequest`/
  `UpdatePurchaseOrderRequest` accept the 4 new fields;
  `PurchaseOrderListItem` gained `supplier_reference`,
  `expected_delivery_date`, `total_ordered_quantity`,
  `total_received_quantity`, `total_remaining_quantity`;
  `PurchaseOrderDetail` gained `payment_terms`/`delivery_terms`;
  `PurchaseOrderLineItem` gained `remaining_quantity`. Five new schema
  classes for the three new endpoints:
  `PurchaseOrderRelatedGoodsReceipt`/`PurchaseOrderRelatedInvoice`/
  `PurchaseOrderRelatedDocuments`, `PurchaseOrderReceivingSummaryLine`/
  `PurchaseOrderReceivingSummary`, `PurchaseOrderAuditEvent`/
  `PurchaseOrderAuditHistory`.
- `app/services/purchase/purchase_order_service.py`:
  - `create_order`/`update_order` accept and persist the 4 new fields;
    `_snapshot` (audit before/after) includes them.
  - New `QuantityTotals` dataclass and `totals_from_lines` static
    helper (pure, computed from an already-fetched line list — no
    extra query) reused by `get_order`/`get_receiving_summary`/the
    router's create/update responses.
  - New `_quantity_totals_for_orders` (ONE aggregate query per page,
    never N+1) used only by `list_orders`, so the list screen's new
    ordered/received/remaining columns don't cost a query per row.
  - New `get_related_documents` — Goods Receipts sourced from this PO,
    plus (transitively, via those Goods Receipts'
    `source_goods_receipt_id`) any Purchase Invoices linked to them. A
    Purchase Invoice has no direct PO reference of its own (PROMPT-019
    Open Decision #2), so this is the only way to reach it from a PO.
  - New `get_receiving_summary` — the authoritative ordered/received/
    remaining view at header + line level, computed via
    `totals_from_lines`.
  - New `get_audit_history` — the FIRST audit-log READ path anywhere
    in this codebase (`audit_log` has been write-only through every
    prior prompt). Deliberately narrow: PO-scoped only, not a general
    audit-log browsing API — confirms tenant ownership first (same
    404-for-cross-tenant discipline as everywhere else in this
    codebase) before querying.
- `app/api/v1/purchase_orders.py`: `_to_list_item`/`_to_detail` updated
  for the new fields/totals; `create_order`/`update_order`/`confirm_order`/
  `cancel_order` updated for `get_order`'s new 4-tuple return
  (`order, supplier_name, lines, totals`); three new `GET` endpoints —
  `/related-documents`, `/receiving-summary`, `/audit-history` — all
  gated by `purchase_order.view` (§37 Open Decision: the entitlement
  matrix defines no separate "view related documents"/"view audit"
  permission, so these piggyback on the parent document's own view
  permission, the same resolution every other supporting/eligibility
  endpoint in this codebase already uses).
- `app/services/purchase/goods_receipt_service.py` — 3 call sites
  updated for `PurchaseOrderService.get_order`'s new 4-tuple return
  (received-quantity/status logic itself is unchanged).

## 5. Stock impact confirmation (§16, re-verified not re-litigated)

`purchase_order_service.py` still has zero `InventoryService`/
`post_movement` imports or calls anywhere in the file. Every
PROMPT-019 stock-impact test (`test_po_creation_does_not_change_stock`,
`test_po_confirmation_does_not_change_stock`) still passes unmodified.

## 6. Quantity calculation logic (§18/§19/§21)

Unchanged from PROMPT-019: `received_quantity` is only ever incremented
by `PurchaseOrderService.apply_receipt`, called exclusively from
`GoodsReceiptService.confirm_receipt` inside the same transaction as
the Stock IN movement(s). `remaining_quantity` is always
`ordered - received`, computed server-side (`totals_from_lines`/
`_quantity_totals_for_orders`), never accepted from a client, and now
surfaced explicitly on every line item and at header level on both the
list and detail screens.

## 7. Idempotency strategy (§29, AC-20)

No new server-side idempotency mechanism was added for `confirm`/
`cancel` — the existing status-guard (`if order.status != DRAFT: raise
...`) plus row-version check already guarantees no duplicate PO number,
no duplicate CONFIRMED/CANCELLED transition, and no duplicate audit
event on a retried request; the second call is safely rejected (412 on
a stale row_version, or 422 if somehow retried with a fresh version
against an already-transitioned order) rather than silently repeating
the side effect. This matches Sales Order's own established convention
(PROMPT-013) — confirm/cancel were never wrapped in the `Idempotency-Key`
replay-guard pattern used for document-creating/side-effect-bearing
POSTs, because a status-transition guard is itself sufficient here.
Verified explicitly by two new tests (`test_duplicate_confirmation_
request_rejected_no_duplicate_state`, `test_duplicate_cancellation_
request_rejected_no_duplicate_state`) asserting exactly one audit event
of each type exists after the duplicate attempt.

## 8. Concurrency strategy (§28)

Unchanged: `SELECT ... FOR UPDATE` row-level locking on the Purchase
Order (`get_order_locked`), reused by `GoodsReceiptService.confirm_receipt`
before re-validating live remaining quantity — PROMPT-019's own
`test_concurrent_receipt_only_one_succeeds` (two racing 40-unit receipts
against a 50-unit-remaining line; exactly one succeeds) still passes
unmodified and continues to be the concurrency proof for this prompt too.

## 9. Authorization model (§37)

No new permission codes were added. `purchase_order.view/create/edit/
confirm/cancel` (PROMPT-019) remain the complete set; the three new
supporting endpoints are gated by `purchase_order.view`. Flagged as an
explicit Open Decision (§12 #4 below) rather than silently inventing
separate "print"/"view related documents" permission codes the
entitlement matrix doesn't define.

## 10. Audit events

No new audit ACTIONS were introduced — `PURCHASE_ORDER_CREATED/UPDATED/
CONFIRMED/CANCELLED/RECEIPT_UPDATED` (all from PROMPT-019) are the
complete set, now readable via the new `/audit-history` endpoint and
displayed on the PO detail screen.

## 11. Frontend

- `api/purchaseOrders.ts` — new fields on existing types; three new
  client functions (`getRelatedDocuments`/`getReceivingSummary`/
  `getAuditHistory`) with their response types.
- `components/PurchaseOrderManagement.tsx`:
  - Create form gained Supplier Reference / Expected Delivery Date /
    Payment Terms / Delivery Terms inputs (all optional).
  - List screen gained an "Expected Delivery" column and a compact
    "Qty (Ord / Rcv / Rem)" column.
  - Detail modal gained a Related Documents section (Goods Receipts +
    Purchase Invoices, each with status badge), an Audit History
    section (chronological, human-readable action labels), a line-level
    Remaining column, and Payment/Delivery Terms display.
  - New `PrintPreviewModal` — a full-page, print-stylesheet-driven
    (`@media print`) preview triggered by a new Printer-icon button in
    the detail modal's header, invoking the browser's own
    `window.print()`. Heading explicitly reads "PURCHASE ORDER" (never
    "Invoice"), with a footer disclaimer "Not a tax invoice" per §36's
    own instruction.

## 12. Open Decisions (per §48 — not silently resolved)

| # | Open Decision | Classification | Resolution in this prompt |
|---|---|---|---|
| 1 | Exact PO status names | APPROVED | DRAFT/CONFIRMED/PARTIALLY_RECEIVED/FULLY_RECEIVED/CANCELLED — adopted verbatim from PROMPT-019, matches this prompt's own §13 baseline exactly |
| 2 | PO number generated at Draft or Confirm | APPROVED | At Draft/create time (PROMPT-019's established convention) — per this prompt's own §12 instruction to follow the existing project convention rather than introduce a conflicting one |
| 3 | PO amendment rules after confirmation | APPROVED | No amendment mechanism — confirmed POs cannot be edited at all (`update_order` raises if `status != DRAFT`), matching Sales Order/every other confirmed-document's identical resolution |
| 4 | Print/Related-documents/Audit-history permission | OPEN DECISION | No separate permission codes exist for these; all three new endpoints are gated by the existing `purchase_order.view` — needs Product Owner confirmation on whether finer-grained permissions are ever required |
| 5 | Over-receipt policy | APPROVED | Rejected unconditionally (PROMPT-019, unchanged) — no "explicitly approved" override path exists |
| 6 | Over-invoicing policy | OPEN DECISION (unchanged from PROMPT-019) | Purchase Invoice's own eligibility-quantity guard (built in PROMPT-019) is the only protection; not revisited by this prompt |
| 7 | Expected delivery date mandatory vs optional | PROPOSED | Optional — added as a nullable column with no validation requiring it |
| 8 | Supplier reference mandatory vs optional | PROPOSED | Optional — same resolution as #7 |
| 9 | Payment terms | PROPOSED | Free text, optional, no controlled taxonomy (no approved terms list exists) |
| 10 | Delivery terms | PROPOSED | Free text, optional, same resolution as #9 |
| 11 | Currency support | OPEN DECISION | NOT implemented — no `currency` column added; this MVP is assumed INR-only throughout (Indian GST product, no other document carries currency either) |
| 12 | Freight/other charges | OPEN DECISION | NOT implemented — no line or header field exists for freight; PO totals are product-line GST/discount only, same scope as every other Purchase/Sales document in this codebase |
| 13 | Purchase discount model | APPROVED | Per-line percentage-or-amount discount before GST (PROMPT-019, unchanged) |
| 14 | GST applicability on PO | APPROVED | Full CGST/SGST/IGST calculation via the shared `gst_calculation_service`, same as every other document (PROMPT-019, unchanged) |
| 15 | PO tax-inclusive vs tax-exclusive pricing | APPROVED | Tax-exclusive — `unit_price` is the pre-GST rate, GST added on top (same convention as every Sales/Purchase document) |
| 16 | PO approval workflow | OPEN DECISION | NOT implemented — "Confirm" is a single-step action by anyone with `purchase_order.confirm`; no multi-step/threshold-based approval chain exists |
| 17 | Approval thresholds | OPEN DECISION | NOT implemented — no amount-based gating exists on confirmation |
| 18 | Who can confirm PO | APPROVED | Owner/Manager only (`purchase_order.confirm`, PROMPT-019's FRD Table 7 reading — Salesperson gets zero Purchase permissions) |
| 19 | Who can cancel PO | APPROVED | Owner/Manager only (`purchase_order.cancel`), same resolution as #18 |
| 20 | Cancellation after partial receipt | APPROVED | Allowed (`CANCELLABLE_STATUSES` includes `PARTIALLY_RECEIVED`, PROMPT-019, unchanged) — already-received quantity is unaffected, no reversal |
| 21 | Cancellation after invoice | OPEN DECISION | Not specifically guarded — a PO with a linked GR/Invoice can still be cancelled if its own status is cancellable; the linked GR/Invoice documents themselves are untouched (they have their own independent lifecycle). No cross-document cancellation-blocking rule was added, since no approved source specifies one |
| 22 | PO expiry/validity | OPEN DECISION | NOT implemented — no expiry date or validity-window concept exists on Purchase Order |
| 23 | Offline PO creation | APPROVED (deferred) | NOT enabled in this MVP, per §44's own explicit instruction; the model already uses UUID PKs + Idempotency-Key + server-authoritative numbering, so future offline support is architecturally possible without redesign |
| 24 | Supplier-specific purchase pricing | OPEN DECISION | NOT implemented — no supplier-specific price list exists; `unit_price` is entered manually per line (mirrors PROMPT-019, unchanged) |
| 25 | PO revision/versioning | OPEN DECISION | NOT implemented — `row_version` is optimistic-concurrency only, not a user-facing revision history; no amendment/versioning UI exists (see #3) |
| 26 | Return linkage | APPROVED | Out of scope for PO itself — Purchase Return links to a Purchase Invoice (PROMPT-019), never directly to a Purchase Order |
| 27 | Document print template | PROPOSED | A single, minimal print layout implemented this prompt (`PrintPreviewModal`) — not a themeable/configurable template system; needs Product Owner sign-off if a formal branded template is required |
| 28 | Exact reporting fields | APPROVED | §45's own list (po number/supplier/date/status/ordered/received/remaining/taxable/GST/total/expected delivery date) is fully exposed via the existing detail/list/receiving-summary endpoints — no separate reporting module was built, per this prompt's own scope boundary |
| 29 | Location | OPEN DECISION | NOT implemented as a PO field — M1 (PROMPT-010) supports exactly one lazily-provisioned "MAIN" location per tenant with no management UI; a location_id FK was deliberately withheld until multi-location is approved (see migration 0022's own docstring) |

## 13. Testing

`backend/tests/integration/test_purchase_order_management.py` (new, 14
tests, all passing on first run) — covers ONLY the new surface area:
header-field create/optional/update, list+detail quantity totals,
related-documents (empty/with-GRs/with-transitive-invoice), receiving
summary, audit history (lifecycle + cross-tenant 404), duplicate
confirm/cancel rejection with no duplicate audit event, RBAC on the
three new endpoints, and a fully-received-PO-rejects-further-receipt
regression guard.

`backend/tests/integration/test_purchase_foundation.py` (PROMPT-019,
27 tests) re-run unmodified and still passes — confirms none of this
prompt's changes broke the existing PO/GR/PI/PR foundation.

**Full backend regression suite: 516 tests (502 pre-existing, which
already includes PROMPT-019's 27 `test_purchase_foundation.py` tests,
plus 14 new this prompt), all passing.**

## 14. Known Limitations

- No PO approval workflow/threshold gating exists — confirmation is a
  single permission check, not a multi-step approval chain.
- No freight/landed-cost or currency support.
- No PO revision/versioning history beyond optimistic-concurrency
  row_version.
- Print/Preview is a single fixed layout, not a configurable template.
- No supplier-specific price list — unit price is always entered
  manually.
- No cross-document cancellation guard (a PO can still be cancelled
  even if a linked GR/Invoice exists, though this itself is rare given
  cancellable statuses already require the PO to not be FULLY_RECEIVED).

## 15. Definition of Done

Every §49 checklist item that falls within this prompt's explicit scope
is satisfied: list/create/draft/edit/confirm/cancel/validation/GST/
totals/numbering/status-machine/GR relationship/PI relationship
foundation/ordered-received-remaining/partial-receiving/over-receipt
validation/no-stock-movement/idempotency/concurrency/RBAC/tenant
isolation/audit/print-preview/responsive UI (desktop — Tablet/Mobile
follow the same Tailwind responsive classes already proven across every
other Purchase/Sales screen in this codebase, no device-specific logic
was needed)/tests all pass. Items dependent on unapproved decisions
(approval workflow, currency, freight, PO versioning, finer-grained
print/audit permissions) are explicitly listed as Open Decisions or
Known Limitations above, not silently invented.

Purchase Order Management is complete. Goods Receipt detailed workflow,
Purchase Invoice detailed workflow, Purchase Return detailed workflow,
Payments, Accounting posting, GST Returns, Payroll, Reports, AI, Route
Management, POS, and Vendor Portal were all explicitly NOT started, per
this prompt's own STOP condition.
