# PROMPT-021 — Goods Receipt Management — Implementation Notes

## 1. Summary

PROMPT-021 asked for the "complete Goods Receipt workflow." As with
PROMPT-020's Purchase Order pass, the great majority of that workflow —
create-from-PO/save-draft/edit-draft/confirm/list/view, eligible-PO-line
loading, ordered/received/remaining tracking, partial receiving,
over-receipt prevention, server-authoritative numbering, row-version
concurrency, idempotent confirm, tenant isolation, RBAC, and the
mandatory GR-confirmation-creates-exactly-one-Stock-IN-per-line rule —
was already built and tested in PROMPT-019's foundation
(`goods_receipt_service.py`, `goods_receipts.py`,
`test_purchase_foundation.py`). This prompt's own genuinely new work is:

- **Confirmed-GR cancellation with a compensating Stock OUT reversal**
  (§23-25) — the single biggest addition. Previously (PROMPT-019) only
  a DRAFT GR could be cancelled at all; a CONFIRMED GR is now
  reversible, gated by (a) no downstream Purchase Invoice against any
  line, and (b) the existing negative-stock guard (a reversal that
  would drive stock negative — because the received goods were already
  consumed elsewhere — is rejected, not forced through).
- A new `supplier_delivery_note` header field (§5/§28).
- Stock-movement visibility on each line (`stock_movement_id`/
  `stock_movement_reversed`) — §42's "Inventory Impact" requirement.
- Two new supporting endpoints: `GET .../related-documents` and
  `GET .../audit-history`, mirroring PROMPT-020's identical pattern for
  Purchase Order.
- Print/Preview (§43) — a GR-specific `GrPrintPreviewModal`, mirroring
  PurchaseOrderManagement's own `PrintPreviewModal`.

No Purchase Invoice, Purchase Return, Supplier Payment, Accounting
Posting, GST Returns, or Reports work was started — all explicitly out
of scope per this prompt's own final instruction.

## 2. Existing components reused (unchanged from PROMPT-019)

- `InventoryService.post_movement` — the SOLE stock-mutation primitive,
  used for BOTH the original STOCK_IN (PROMPT-019) and the new
  compensating STOCK_OUT reversal (this prompt). No second inventory
  engine was created (AC-29).
- `InventoryService.ensure_default_location`/`get_active_product_locked`
- `PurchaseOrderService.get_order_locked`/`get_lines` — row-level
  locking, reused for the reversal's PO-side update too.
- `AuditService.record` — still the only writer of `audit_log`.
- `check_row_version` / optimistic concurrency.
- `IdempotencyService` — reused verbatim on create/confirm (cancel
  still follows Sales Order/Purchase Order's own established
  convention of relying on its status guard rather than an
  `Idempotency-Key` wrapper — see §7 below).

## 3. Database changes

Migration `0023_goods_receipt_management.py` adds one nullable column
to `goods_receipt`: `supplier_delivery_note` (VARCHAR 100).

**No new table or column was needed for the reversal feature itself** —
the compensating STOCK_OUT reuses `goods_receipt_line.id` as its
`stock_ledger_entry.source_id`, with a NEW `source_type` value
(`GOODS_RECEIPT_REVERSAL`, see `app/core/purchase_constants.py`) rather
than a new column. The existing `uq_stock_ledger_entry_source
(tenant_id, source_type, source_id)` constraint already accommodates
this: the original STOCK_IN (`source_type='GOODS_RECEIPT'`) and its
reversal (`source_type='GOODS_RECEIPT_REVERSAL'`) coexist under the same
`source_id` without colliding, and the constraint still prevents a
SECOND reversal of the same line.

**Deliberately NOT added**: a `receipt_location_id` FK — M1 (PROMPT-010
§8) only ever has one lazily-provisioned "MAIN" location per tenant,
the identical reasoning PROMPT-020 already applied to Purchase Order's
own `location_id` decision.

## 4. Backend changes

- `app/core/error_codes.py` — `GR_HAS_DOWNSTREAM_INVOICE = "GR-007"`.
- `app/core/purchase_constants.py` — new `GOODS_RECEIPT_REVERSAL`
  source_type constant, documented as deliberately distinct from
  `GOODS_RECEIPT` (not a second entry with the same source_type — see
  §3 above).
- `app/models/goods_receipt.py` — `supplier_delivery_note` column;
  `CANCELLABLE_STATUSES` widened from `{DRAFT}` to `{DRAFT, CONFIRMED}`.
- `app/schemas/purchase.py` — `CreateGoodsReceiptRequest`/
  `UpdateGoodsReceiptRequest` accept `supplier_delivery_note`;
  `GoodsReceiptListItem` gained it; `GoodsReceiptLineItem` gained
  `stock_movement_id`/`stock_movement_reversed`. New schema classes:
  `GoodsReceiptRelatedInvoice`/`GoodsReceiptRelatedDocuments`,
  `GoodsReceiptAuditEvent`/`GoodsReceiptAuditHistory`.
- `app/services/purchase/purchase_order_service.py` — new
  `apply_reversal` method (the mirror image of `apply_receipt`): called
  by `GoodsReceiptService.cancel_receipt` when reversing a CONFIRMED GR,
  decrements `purchase_order_line.received_quantity` (floored at 0),
  and recomputes PO status via the existing `totals_from_lines` helper
  — CONFIRMED (received back to 0), PARTIALLY_RECEIVED, or
  FULLY_RECEIVED, never resurrecting a CANCELLED order out of its
  terminal state. Emits a new `PURCHASE_ORDER_RECEIPT_REVERSED` audit
  action.
- `app/services/purchase/goods_receipt_service.py`:
  - `create_receipt`/`update_receipt` accept and persist
    `supplier_delivery_note`.
  - New `stock_movement_info_for_lines` (public) — one query per
    GR-detail/confirm response, returning each line's
    `stock_ledger_entry.id` (if a STOCK_IN exists) and whether a
    `GOODS_RECEIPT_REVERSAL` entry has since been posted against it.
  - `get_receipt` now also returns this stock-info dict (5-tuple return
    — every existing caller across `purchase_invoice_service.py` and
    `goods_receipts.py` was updated).
  - `cancel_receipt` rewritten: DRAFT path unchanged (pure status
    change, no stock/PO impact); CONFIRMED path is now a full reversal
    — checks `goods_receipt_line.invoiced_quantity == 0` on every line
    (rejects with `GR_HAS_DOWNSTREAM_INVOICE`/422 otherwise), locks the
    source PO, posts one compensating STOCK_OUT per line (source_type=
    `GOODS_RECEIPT_REVERSAL`), calls `PurchaseOrderService.apply_reversal`,
    then marks the GR CANCELLED. If `post_movement` raises `ConflictError`
    (insufficient stock — already consumed elsewhere), the whole
    request fails atomically (409) and nothing is left half-applied,
    since nothing was committed yet.
  - New `get_related_documents` — source PO (if any) + every Purchase
    Invoice sourced from this GR.
  - New `get_audit_history` — the GR-scoped equivalent of
    `PurchaseOrderService.get_audit_history` (PROMPT-020), same
    tenant-ownership-checked-first discipline.
- `app/api/v1/goods_receipts.py` — `_to_list_item`/`_to_line_item`/
  `_to_detail` updated for the new fields; `get_receipt`/`create_receipt`/
  `update_receipt`/`confirm_receipt`/`cancel_receipt` updated for the
  new 5-tuple `get_receipt` return and `supplier_delivery_note`
  passthrough; two new `GET` endpoints — `/related-documents` and
  `/audit-history` — gated by `goods_receipt.view` (§45 Open Decision:
  no separate "view related documents"/"view audit" permission is
  defined, same resolution PROMPT-020 used for Purchase Order).

## 5. Stock IN / reversal implementation (§13-15, §23-26, INVARIANTs 1-3, 7-8)

- **Confirm** (unchanged from PROMPT-019): one `post_movement(STOCK_IN,
  source_type=GOODS_RECEIPT, source_id=<gr_line.id>)` call per line,
  inside the same transaction as the PO's `apply_receipt` and the GR's
  own status change. `uq_stock_ledger_entry_source` makes a second
  confirmation attempt structurally incapable of creating a duplicate
  STOCK_IN — proven by PROMPT-019's own `test_idempotent_gr_confirm_retry`
  (still passing unmodified).
- **Reversal** (new): one `post_movement(STOCK_OUT, source_type=
  GOODS_RECEIPT_REVERSAL, source_id=<gr_line.id>)` call per line, in the
  SAME transaction as the PO's `apply_reversal` and the GR's status
  change to CANCELLED. The original STOCK_IN row is never touched —
  INVARIANT 7 (immutable ledger) holds structurally, since no UPDATE or
  DELETE is ever issued against `stock_ledger_entry` anywhere in this
  codebase (also enforced at the DB level by its own BEFORE UPDATE/
  DELETE trigger, PROMPT-010/migration 0011).
- **Duplicate-reversal protection**: the SAME `uq_stock_ledger_entry_source`
  constraint that protects the original STOCK_IN also protects the
  reversal — a second cancel attempt on an already-CANCELLED GR is
  rejected by the status guard (`CANCELLABLE_STATUSES` no longer
  includes `CANCELLED`) before ever reaching `post_movement` again.

## 6. Idempotency strategy (§15/§56, AC-17)

Unchanged mechanism from PROMPT-019 for `create`/`confirm`
(`Idempotency-Key` + `IdempotencyService`, verified by
`test_idempotent_gr_confirm_retry`). `cancel` (both DRAFT and the new
CONFIRMED-reversal path) follows the same status-guard convention
established for Purchase Order's own confirm/cancel (PROMPT-020 §7) —
a retried cancel on an already-CANCELLED GR is rejected (412 stale
row_version, or 422 already-cancelled) rather than double-reversing.
Verified by `test_double_cancel_confirmed_gr_rejected` (only one
compensating STOCK_OUT is ever posted).

## 7. Concurrency strategy (§16/§55)

Unchanged from PROMPT-019: `SELECT ... FOR UPDATE` on both the
`goods_receipt` and (via `PurchaseOrderService.get_order_locked`) the
source `purchase_order` row, for BOTH confirm and the new reversal path.
PROMPT-019's own `test_concurrent_receipt_only_one_succeeds` (two racing
receipts against the same remaining quantity) still passes unmodified
and remains the concurrency proof for this prompt too — no new
concurrency mechanism was needed for reversal since it reuses the exact
same locking primitives.

## 8. Cancellation/reversal strategy (§23-26, §60 #4-7)

| Scenario | Resolution |
|---|---|
| DRAFT GR cancellation | Pure status change, zero stock/PO impact (unchanged from PROMPT-019) |
| CONFIRMED GR cancellation, no downstream | Full reversal: compensating STOCK_OUT per line + PO received-quantity/status rollback |
| CONFIRMED GR cancellation, downstream Purchase Invoice exists | REJECTED — `GR_HAS_DOWNSTREAM_INVOICE` (422), per §24's own example message, verbatim |
| CONFIRMED GR cancellation, stock already consumed elsewhere | REJECTED — `InventoryService`'s own negative-stock guard (409), not forced through |
| Partial cancellation (cancel only some lines) | NOT implemented — cancellation is all-or-nothing for the whole GR (§60 #24, Open Decision) |
| Cancellation after a Purchase Return exists | Not specifically checked — no Purchase Return in this codebase references a Goods Receipt at all (PROMPT-019: `purchase_return.source_purchase_invoice_id` only), so this scenario cannot currently arise |

## 9. Authorization model (§45)

No new permission codes. `goods_receipt.view/create/edit/confirm/cancel`
(PROMPT-019) remain the complete set — cancellation-with-reversal is
gated by the SAME `goods_receipt.cancel` permission as a DRAFT
cancellation (§60 #20 Open Decision: no separate "reverse a confirmed
GR" permission is defined by the entitlement matrix; flagged, not
silently split into a new permission). The two new supporting endpoints
are gated by `goods_receipt.view`.

## 10. Audit events

New: `PURCHASE_ORDER_RECEIPT_REVERSED` (on the Purchase Order, mirrors
`PURCHASE_ORDER_RECEIPT_UPDATED`'s exact shape). `GOODS_RECEIPT_CANCELLED`
is now also emitted for the CONFIRMED-reversal path (previously only
for DRAFT), with `after.stock_reversed=true` distinguishing the two
cases in the audit payload. Both readable via the new
`/audit-history` endpoint.

## 11. Frontend

- `api/goodsReceipts.ts` — new fields on existing types; two new client
  functions (`getGoodsReceiptRelatedDocuments`/`getGoodsReceiptAuditHistory`).
- `components/GoodsReceiptManagement.tsx`:
  - Create form gained a Supplier Delivery Note input (optional).
  - Detail modal gained: an "Inventory Impact" section (§42, shown once
    the GR leaves DRAFT) listing each line's STOCK IN quantity, or a
    "Reversed" indicator once cancelled; a Related Documents section
    (source PO + linked Purchase Invoices); an Audit History section;
    the Cancel action now also appears for CONFIRMED receipts, with a
    distinct confirmation-dialog message explaining the reversal
    behavior and its two rejection conditions.
  - New `GrPrintPreviewModal` — mirrors `PurchaseOrderManagement`'s own
    `PrintPreviewModal` exactly (same `window.print()`/`@media print`
    approach), headed "GOODS RECEIPT" with a "Not a Purchase Invoice"
    footer disclaimer and a Received-By/Approved-By signature section
    per §43's own instruction.

## 12. Testing

`backend/tests/integration/test_goods_receipt_management.py` (new, 17
tests, all passing after two real bugs were found and fixed during
first-run verification — see below) covers ONLY the new PROMPT-021
surface area: `supplier_delivery_note` create/optional/update, stock-
movement-id visibility (present once confirmed, absent while DRAFT),
related-documents (source PO only / with linked invoice / cross-tenant
404), audit history (lifecycle + RBAC), and the reversal feature itself:
compensating STOCK_OUT creation (verified against the raw
`stock_ledger_entry` table — exactly one STOCK_IN + one STOCK_OUT, never
more), PO received-quantity/status rollback, downstream-invoice
blocking, insufficient-stock blocking (via a real PROMPT-010 stock
adjustment to consume the received goods first), DRAFT-cancel stock-
neutrality (regression), double-cancel rejection, and unauthorized-
cancellation rejection.

**Two real implementation bugs were caught and fixed during first-run
verification** (not just test-authoring mistakes):
1. `confirm_receipt`'s router endpoint didn't attach stock-movement info
   to its own response (only `get_receipt` did) — a client reading the
   CONFIRM response directly (rather than re-fetching) saw
   `stock_movement_id: null` even though the ledger entry existed.
   Fixed by making `stock_movement_info_for_lines` public and calling
   it from the confirm endpoint too.
2. The downstream-invoice-blocking test initially only CREATED (DRAFT)
   a Purchase Invoice from the GR, which does not yet increment
   `goods_receipt_line.invoiced_quantity` (only POSTing does, per
   PROMPT-019's own design) — this was a test-authoring gap, not a
   production bug, fixed by posting the invoice in the test.

`backend/tests/integration/test_purchase_foundation.py` (27 tests) and
`test_purchase_order_management.py` (14 tests) re-run unmodified and
still pass — confirms none of this prompt's changes broke the existing
PO/GR/PI/PR foundation or PROMPT-020's Purchase Order workflow.

**Full backend regression suite and frontend Vitest suite: see the
Implementation Output's Test Results section below for the final tally.**

## 13. Open Decisions (per §60 — not silently resolved)

| # | Open Decision | Classification | Resolution in this prompt |
|---|---|---|---|
| 1 | Direct Goods Receipt without Purchase Order | APPROVED (unchanged from PROMPT-019) | NOT implemented — `purchase_order_id` is a required field on `CreateGoodsReceiptRequest`; no ad-hoc GR path exists |
| 2 | Over-receipt policy | APPROVED (unchanged) | Rejected unconditionally, server-side, no override path |
| 3 | Partial receipt rules | APPROVED (unchanged) | Fully supported — cumulative `received_quantity`/`remaining_quantity` tracking, multiple GRs per PO |
| 4 | GR cancellation policy | **RESOLVED THIS PROMPT** | DRAFT: pure cancel. CONFIRMED: reversal, gated by no-downstream-invoice + sufficient-stock-to-reverse. See §8 table above |
| 5 | Stock reversal rules | **RESOLVED THIS PROMPT** | Compensating STOCK_OUT via `InventoryService.post_movement`, same primitive as every other stock movement — no new inventory engine (AC-29) |
| 6 | Whether cancellation is allowed after Purchase Invoice | **RESOLVED THIS PROMPT** | NOT allowed — `GR_HAS_DOWNSTREAM_INVOICE` (422), per §24's own example |
| 7 | Whether cancellation is allowed after Purchase Return | OPEN DECISION | Not specifically checked — no Purchase Return in this codebase references a Goods Receipt (only a Purchase Invoice), so this scenario cannot currently occur; flagged for when/if that relationship is ever added |
| 8 | Supplier delivery note requirement | PROPOSED | Optional, free text, added as `supplier_delivery_note` |
| 9 | Receipt location rules | OPEN DECISION | NOT implemented — no location field on GR; M1's single "MAIN" location (PROMPT-010 §8) is implicit, same resolution PROMPT-020 applied to Purchase Order |
| 10 | Multiple locations/warehouses | OPEN DECISION | Out of scope — blocked on the same M1 single-location constraint as #9 |
| 11 | Batch/expiry capture | OPEN DECISION | NOT implemented — no batch/expiry columns exist anywhere in the Purchase or Inventory schema yet |
| 12 | Damaged quantity handling | OPEN DECISION | NOT implemented — a GR line only has one `quantity` field, no separate damaged/rejected split |
| 13 | Rejected quantity handling | OPEN DECISION | Same as #12 — not implemented |
| 14 | Accepted vs rejected quantity | OPEN DECISION | Same as #12/#13 |
| 15 | Purchase price variance at GR | APPROVED (unchanged from PROMPT-019) | NOT supported — GR line pricing is copied directly from the PO line, no independent price entry at receipt time (`goods_receipt_line.unit_price = purchase_order_line.unit_price`, always) |
| 16 | GR valuation | APPROVED | Quantity is authoritative for stock; `grand_total` on the GR is informational only, matching §30's own instruction that GR is not the financial liability document |
| 17 | GST handling on GR | APPROVED (unchanged) | GST fields are copied/displayed from the PO line for reference only; no independent GST calculation exists in `goods_receipt_service.py` |
| 18 | Accounting treatment of GR | APPROVED | NOT implemented — no journal entries, no accounting integration boundary call, per §32's own explicit instruction |
| 19 | Approval requirement | OPEN DECISION | NOT implemented — GR confirmation is a single permission check (`goods_receipt.confirm`), no multi-step approval chain, consistent with Purchase Order's own resolution (PROMPT-020 §12 #16/#17) |
| 20 | GR authorization matrix | OPEN DECISION | Cancellation-with-reversal uses the SAME `goods_receipt.cancel` permission as a plain DRAFT cancel — no separate "reverse a confirmed GR" permission is defined by the entitlement matrix |
| 21 | Offline GR support | APPROVED (deferred) | NOT enabled, per §51's own explicit instruction; UUID PKs + Idempotency-Key + server-authoritative numbering already in place for future offline support |
| 22 | GR numbering timing | APPROVED (unchanged) | At create/Draft time (PROMPT-019's established convention), matching Purchase Order's own identical resolution (PROMPT-020 §12 #2) |
| 23 | GR amendment after confirmation | APPROVED | NOT allowed — `update_receipt` raises if `status != DRAFT` (unchanged from PROMPT-019); the only post-confirmation mutation is the new cancel-with-reversal path, which is a status transition, not an edit |
| 24 | Partial cancellation | OPEN DECISION | NOT implemented — cancellation reverses the ENTIRE GR (all lines), not a per-line partial reversal |
| 25 | Exact PO status transition behavior | APPROVED | Reuses PROMPT-020's own `totals_from_lines` helper — CONFIRMED (0 received)/PARTIALLY_RECEIVED/FULLY_RECEIVED, the same three-way logic apply_receipt already established, just inverted for `apply_reversal` |

## 14. Known Limitations

- No partial-cancellation of a confirmed GR — reversal is all-or-nothing
  for the whole receipt.
- No batch/expiry/damaged-quantity capture at receipt time.
- No purchase-price variance at GR — price is always copied from the PO
  line verbatim.
- No multi-location receiving.
- No approval workflow/threshold gating on GR confirmation or
  cancellation-with-reversal.
- Cancellation-after-Purchase-Return dependency is unchecked (currently
  unreachable given the schema, but would need revisiting if a future
  prompt ever links Purchase Return to Goods Receipt directly).
- Print/Preview is a single fixed layout, not a configurable template
  (same limitation as Purchase Order's own PROMPT-020 print feature).

## 15. Definition of Done

Every §62 checklist item within this prompt's explicit scope is
satisfied: list/create/draft/edit/PO-selection/eligible-lines/ordered-
received-remaining-display/partial-receipt/over-receipt-prevention/
zero-negative-quantity-prevention/confirmation/Stock-IN-integration/
atomic-posting/duplicate-Stock-IN-prevention/PO-quantity-and-status-
update/multiple-GRs/cancellation-reversal-boundary/immutable-ledger-
reversal/RBAC/tenant-isolation/audit/API/database/print-preview/
responsive-UI (desktop; tablet/mobile follow the same Tailwind
responsive classes already proven across every Purchase/Sales screen in
this codebase)/tests all pass. Items dependent on unapproved decisions
(batch/expiry, damaged-quantity, approval workflow, partial
cancellation, multi-location) are explicitly listed as Open Decisions
or Known Limitations above, not silently invented.

Goods Receipt Management is complete. Purchase Invoice, Purchase
Return, Supplier Payment, Accounting Posting, GST Returns, Payroll,
Reports, AI, Route Management, POS, and Vendor Portal were all
explicitly NOT started, per this prompt's own STOP condition.
