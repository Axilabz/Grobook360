# PROMPT-023 — Purchase Return Management — Implementation Notes

## 1. Summary

PROMPT-019 (Purchase Management Foundation) already built the Purchase
Return workflow's core: create (against a source POSTED Purchase
Invoice), draft/edit, confirm (creates exactly one STOCK OUT per line,
via `InventoryService.post_movement`), server-authoritative numbering
(`PRET-{FY}-0001`), the authoritative server-side returnable-quantity
calculation (`invoice_line.quantity - invoice_line.returned_quantity`),
over-return prevention, idempotent confirm, row-version concurrency,
RBAC (`purchase_return.*`), tenant isolation, and DRAFT-only
cancellation. This is the third "foundation was already 90% of it"
prompt in this session (after PROMPT-020/021/022's identical pattern
for Purchase Order/Goods Receipt/Purchase Invoice).

This prompt's genuinely new surface area, mirroring Goods Receipt's own
PROMPT-021 precedent and Purchase Invoice's PROMPT-022 precedent
exactly, one level further down the Purchase chain:

- **POSTED (CONFIRMED)-return cancellation with a controlled reversal**
  (§33-35) — a compensating STOCK IN, never editing the original
  STOCK OUT.
- **Stock impact visibility** (§18/§42/§43) — per-line
  `stock_movement_id`/`stock_movement_reversed`.
- **Related documents** (§4/§44) — source Purchase Invoice, plus
  (transitively) source Purchase Order and Goods Receipt(s), reusing
  `PurchaseInvoiceService.get_related_documents` rather than
  re-deriving that traceability logic.
- **Audit history** (§48) — narrow, entity-scoped, tenant-ownership-
  checked-first, mirroring PO/GR/PI's own `get_audit_history`.
- **Print/Preview** (§45) — a `window.print()`-driven modal headed
  "PURCHASE RETURN", never presenting itself as a Purchase Invoice or
  Credit Note.

## 2. Files Created

- `backend/migrations/versions/` — **none**. No new schema was needed;
  `purchase_return`/`purchase_return_line` (from PROMPT-019) already
  carry every column this prompt needed.
- `backend/tests/integration/test_purchase_return_management.py` — 12
  new tests covering exactly the new surface area above (cancellation-
  with-reversal, stock-immutability, returnable-quantity release,
  double-cancel rejection, DRAFT-cancel no-stock-impact, RBAC on
  cancellation, stock-movement visibility, related-documents
  traceability including cross-tenant 404, audit-history lifecycle,
  RBAC on the two new read endpoints, and multiple-partial-returns
  capping at the invoice's own eligible quantity).

## 3. Files Modified

- `backend/app/core/purchase_constants.py` — added
  `PURCHASE_RETURN_REVERSAL = "PURCHASE_RETURN_REVERSAL"`.
- `backend/app/models/purchase_return.py` — `CANCELLABLE_STATUSES`
  widened from `{DRAFT}` to `{DRAFT, CONFIRMED}`.
- `backend/app/schemas/purchase.py` — `PurchaseReturnLineItem` gained
  `stock_movement_id`/`stock_movement_reversed`; new
  `PurchaseReturnRelatedGoodsReceipt`/`PurchaseReturnRelatedDocuments`/
  `PurchaseReturnAuditEvent`/`PurchaseReturnAuditHistory`.
- `backend/app/services/purchase/purchase_return_service.py` — new
  `stock_movement_info_for_lines` (mirrors GR/PI's own exactly);
  `cancel_return` rewritten to branch DRAFT (pure status flip,
  unchanged) vs CONFIRMED (controlled reversal, new); new
  `get_related_documents`/`get_audit_history`.
- `backend/app/api/v1/purchase_returns.py` — `_to_line_item`/`_to_detail`
  now accept an optional `stock_info` map; `get_return`/`confirm_return`/
  `cancel_return` endpoints compute and pass it through; two new
  endpoints, `GET /{return_id}/related-documents` and
  `GET /{return_id}/audit-history`, both gated by `purchase_return.view`
  (same convention as PO/GR/PI's own supporting endpoints).
- `api/purchaseReturns.ts` — `PurchaseReturnLine` gained
  `stock_movement_id`/`stock_movement_reversed`; new
  `PurchaseReturnRelatedDocuments`/`getPurchaseReturnRelatedDocuments`/
  `PurchaseReturnAuditHistory`/`getPurchaseReturnAuditHistory`.
- `components/PurchaseReturnManagement.tsx` — `ReturnDetailModal`
  gained: a Stock Impact section (STOCK OUT explanation + per-line
  movement/reversed visibility once not DRAFT), a Related Documents
  section (source invoice, source PO if any, contributing GRs), an
  Audit History section, a Printer-icon button opening the new
  `PrPrintPreviewModal`, and the Cancel button now shows for both DRAFT
  and CONFIRMED with reversal-aware confirmation-dialog copy
  (`isPostedCancellation` flag, mirrors Purchase Invoice's own).
- `CLAUDE.md` — new row 023, test-count line, new §4 Open Decision
  bullets, rewritten §5.

## 4. Database Changes

**None.** Every column this prompt needed
(`purchase_return_line.source_purchase_invoice_line_id`, the header's
own `status`, etc.) already existed from PROMPT-019. No migration was
created.

## 5. API Changes

New:
- `GET /api/v1/purchase/returns/{return_id}/related-documents`
  (`purchase_return.view`)
- `GET /api/v1/purchase/returns/{return_id}/audit-history`
  (`purchase_return.view`)

Changed response shape (additive only, no breaking changes):
- `PurchaseReturnLineItem` now carries `stock_movement_id`/
  `stock_movement_reversed` on `GET /{id}`, `POST /{id}/confirm`, and
  `POST /{id}/cancel` responses.
- `POST /{id}/cancel` — status guard widened; a CONFIRMED return can
  now be cancelled (previously only DRAFT), and the response reflects
  the resulting stock reversal via the per-line fields above.

## 6. UI Changes

`PurchaseReturnManagement.tsx`'s `ReturnDetailModal`:
- Stock Impact section (always shown; per-line detail once the return
  has left DRAFT).
- Related Documents section (source invoice always shown; source PO
  and contributing Goods Receipts shown where the traceability chain
  resolves them).
- Audit History section.
- Print/Preview button + `PrPrintPreviewModal`, headed "PURCHASE
  RETURN", footer disclaiming it is not a Purchase Invoice or Credit
  Note.
- Cancel button now available for CONFIRMED returns too, with
  reversal-aware confirmation copy distinguishing a no-stock-yet DRAFT
  cancellation from a stock-reversing CONFIRMED cancellation.

No changes were needed to the List screen or Create Return screen —
both already existed and already satisfied this prompt's requirements
(server-side returnable-quantity calculation, reason capture, over-
return prevention, responsive table/card layouts).

## 7. Purchase Return Business Rules Implemented (this prompt)

- A CONFIRMED Purchase Return can now be cancelled via a controlled
  reversal — previously (PROMPT-019) only a DRAFT return could be
  cancelled at all.
- Cancelling a CONFIRMED return posts exactly one compensating
  STOCK IN per line (source_type=`PURCHASE_RETURN_REVERSAL`, same
  `source_id` as the original STOCK OUT's `source_type=PURCHASE_RETURN`
  entry) and releases the return's own claim on the source invoice
  line's `returned_quantity` bookkeeping counter, making that quantity
  returnable again.
- The original STOCK OUT ledger entry is never edited or deleted
  (INVARIANT 10) — verified by a dedicated test asserting its id,
  quantity, and movement_type are unchanged after the reversal.
- A compensating STOCK IN reversal can never be rejected for going
  negative (restocking previously-removed goods only ever increases
  stock) — unlike a DIRECT Purchase Invoice's own reversal (PROMPT-022),
  which can be rejected if the received stock was already consumed
  elsewhere.

## 8. Returnable Quantity Calculation

Unchanged from PROMPT-019 — `invoice_line.quantity -
invoice_line.returned_quantity`, computed server-side, both at DRAFT-
create time (soft check) and again under a row lock at confirm time
(authoritative check). This prompt's own contribution is that
cancelling a CONFIRMED return now *decrements* `returned_quantity` back
down (via `max(0, returned_quantity - line.quantity)`), so the formula
itself needed no change — only a new caller.

## 9. Stock OUT / Stock Movement Reference Strategy

Unchanged posting logic from PROMPT-019 (`confirm_return` calls
`InventoryService.post_movement(STOCK_OUT, source_type=PURCHASE_RETURN,
source_id=return_line.id)`, one call per line with a product). This
prompt adds the READ side: `stock_movement_info_for_lines` looks up
both `PURCHASE_RETURN` and `PURCHASE_RETURN_REVERSAL` entries for a set
of line ids and reports, per line, the original entry's id plus
whether a reversal has since been posted — the exact same shape as
`GoodsReceiptService`/`PurchaseInvoiceService`'s own.

## 10. Stock Availability Validation

Reused, not reimplemented — `InventoryService.post_movement`'s own
negative-stock guard (established PROMPT-010, unchanged) already
applies to the return's STOCK OUT the same way it applies to every
other stock-decreasing movement in this codebase. No Purchase-Return-
specific stock-availability rule was written (§25/§56's own
instruction: "reuse the existing Negative Stock policy... do not
create a Purchase Return-specific negative-stock rule").

## 11. Idempotency Strategy

Unchanged from PROMPT-019. `create`/`confirm` remain
Idempotency-Key-guarded via the shared `_idempotent_post` helper
(HTTP-level replay guard). `cancel` — for both DRAFT and (new) CONFIRMED
— relies on its own status-guard (`CANCELLABLE_STATUSES` check) +
`row_version` check rather than a separate Idempotency-Key wrapper,
the same established convention as every other confirm/cancel-style
status transition in this codebase (Purchase Order, Goods Receipt,
Purchase Invoice) — a retried cancel on an already-CANCELLED return is
rejected with `PRET-002`, producing zero duplicate reversal stock
movements, verified by `test_double_cancel_confirmed_return_rejected`.

## 12. Concurrency Strategy

Unchanged from PROMPT-019 — `SELECT ... FOR UPDATE` row locking on the
Purchase Return itself (`_get_return_locked`) plus the source invoice
(`invoice_service.get_invoice_locked`), combined with `row_version`
optimistic concurrency on the return header. The new CONFIRMED-
cancellation path reuses the exact same locking discipline: the return
row is locked first, then the source invoice is locked before its
`returned_quantity` bookkeeping is touched.

## 13. Cancellation / Reversal Strategy

| Scenario | Behavior |
|---|---|
| Cancel a DRAFT return | Pure status flip to CANCELLED. No stock touched (INVARIANT 2). Unchanged from PROMPT-019. |
| Cancel a CONFIRMED return | Controlled reversal: one compensating STOCK IN per line (`PURCHASE_RETURN_REVERSAL`), `invoice_line.returned_quantity` decremented, status flips to CANCELLED. New in this prompt. |
| Re-cancelling an already-CANCELLED return | Rejected (`PRET-002`), no duplicate reversal. |
| A compensating reversal going "negative" | Structurally impossible — a STOCK IN never triggers the negative-stock guard. |
| Downstream dependency check (§34) | No downstream table in this codebase currently references `purchase_return` (no Credit/Debit Note, Supplier Payment, or Accounting Posting table links to it) — there is nothing to block on yet. This is flagged as Open Decision #22-25 below, not silently resolved as "no dependency will ever exist." |

## 14. Authorization Model

Unchanged from PROMPT-019 — `purchase_return.view`/`.create`/`.edit`/
`.confirm`/`.cancel` (Owner/Manager only, Salesperson has zero Purchase
permissions per FRD Table 7, same as every other Purchase document
type). The two new read endpoints (`/related-documents`,
`/audit-history`) are gated by `purchase_return.view` — no new
permission codes were created, matching PO/GR/PI's own established
"reuse the parent document's view permission" pattern (§47's own
instruction: "do not create a new role model").

## 15. Audit Events

- `PURCHASE_RETURN_CREATED` / `PURCHASE_RETURN_UPDATED` — unchanged
  from PROMPT-019.
- `PURCHASE_RETURN_CONFIRMED` — unchanged.
- `PURCHASE_RETURN_CANCELLED` — now carries `after.stock_reversed`
  (`true` for a CONFIRMED-return reversal, `false` for a DRAFT-return's
  pure status flip), plus a per-line `STOCK_OUT_REVERSED` audit entry
  from `InventoryService.post_movement`'s own audit call (mirrors
  Goods Receipt's `STOCK_IN_REVERSED` naming convention, inverted).

## 16. Test Results

- **12 new PROMPT-023 tests** — all passing
  (`test_purchase_return_management.py`): cancellation-with-reversal
  creates compensating Stock IN; original Stock OUT remains immutable;
  cancelled return releases returned_quantity for reuse; double-cancel
  rejected; DRAFT-cancel has no stock impact; unauthorized cancellation
  rejected; stock-movement-id/reversed-flag visibility; related-
  documents traces invoice→PO→GR; related-documents cross-tenant 404;
  audit-history records full lifecycle; Salesperson blocked from both
  new read endpoints; multiple partial returns accumulate and correctly
  cap at the invoice's own eligible quantity.
- **PROMPT-019/020/021/022's own 93 tests** (`test_purchase_foundation.py`
  + `test_purchase_order_management.py` + `test_goods_receipt_
  management.py` + `test_purchase_invoice_management.py` +
  `test_rbac.py`) re-run unmodified — all still passing, zero
  regressions.
- **Full backend suite**: run as the final gate before this delivery
  (see the closing summary message for the exact count).
- **Frontend (Vitest)**: 15/15 passing, zero regressions, TypeScript
  compiles cleanly (`npx tsc --noEmit` shows only pre-existing,
  unrelated `ErrorBoundary.tsx` errors from before this prompt).

## 17. Security Test Results

- Cross-tenant access to `/related-documents` and cancellation of a
  return in a different tenant both return 404 (tenant-ownership-
  checked-first discipline, same as every prior module).
- Salesperson (zero Purchase permissions) blocked with 403 from both
  new read endpoints and from cancellation.
- Server-side-only returnable-quantity recalculation — the client never
  supplies it, and a retried/concurrent over-return attempt is rejected
  under the row lock (unchanged PROMPT-019 behavior, re-verified by
  `test_multiple_partial_returns_accumulate_and_cap`).

## 18. Open Decisions (§64) — Classification

| # | Item | Classification | Notes |
|---|---|---|---|
| 1 | Return against Purchase Invoice only | **APPROVED** | Baseline schema: `source_purchase_invoice_id` NOT NULL (PROMPT-019). |
| 2 | Return against Goods Receipt | **PROPOSED** | Not a direct source — only reachable transitively via the invoice's own GR linkage, shown read-only on Related Documents. |
| 3 | Return against Purchase Order | **PROPOSED** | Same as #2 — read-only traceability only, never a return-creation source. |
| 4 | Direct Return without source invoice | **OPEN DECISION** | Not implemented — every return requires a POSTED Purchase Invoice (PROMPT-019, unchanged). |
| 5 | Return eligibility based on received quantity | **OPEN DECISION** | Current rule is invoiced-quantity-based (`invoice_line.quantity - returned_quantity`), inherited from PROMPT-019. Whether a physically-larger-than-invoiced overage should ever be returnable was never confirmed. |
| 6 | Return eligibility based on invoiced quantity | **APPROVED** | This is the implemented rule — see #5. |
| 7 | Invoice-before-receipt scenario | **N/A for Purchase Return** | Governed upstream by Purchase Invoice's own PROMPT-022 resolution (structurally impossible). |
| 8 | Multiple returns per invoice | **APPROVED** | Implemented and tested (`test_multiple_partial_returns_accumulate_and_cap`). |
| 9 | Partial return | **APPROVED** | Implemented since PROMPT-019. |
| 10 | Return reason master | **PROPOSED** | `DAMAGED`/`WRONG_PRODUCT`/`EXCESS_QUANTITY`/`QUALITY_ISSUE`/`PRICE_DISPUTE`/`OTHER` — PROMPT-019's own proposed, non-final taxonomy, unchanged. |
| 11 | Damaged stock handling | **OPEN DECISION** | No condition-specific stock bucket exists — a return always posts to the single default location's general stock. |
| 12 | Rejected stock handling | **OPEN DECISION** | Same as #11. |
| 13 | Batch/expiry handling | **OPEN DECISION** | No batch/expiry tracking exists anywhere in Inventory yet (PROMPT-010's own scope). |
| 14 | Negative stock policy | **APPROVED** | Reused verbatim from PROMPT-010's existing policy — prohibited by default. |
| 15 | Return valuation | **APPROVED** | Prorated from the source invoice line (unchanged PROMPT-019 technique). |
| 16 | Purchase price variance | **OPEN DECISION** | Not tracked — a return always uses the original invoiced price. |
| 17 | GST treatment | **APPROVED** | Reuses `gst_calculation_service` (unchanged PROMPT-019). |
| 18 | Accounting treatment | **OPEN DECISION** | No accounting posting exists for Purchase Return (explicit scope exclusion, §31). |
| 19 | Credit Note generation | **OPEN DECISION** | Not auto-created — Purchase Return and Credit/Debit Note remain structurally separate concepts (§32, INVARIANT 14). |
| 20 | Debit Note generation | **OPEN DECISION** | Same as #19. |
| 21 | Supplier adjustment | **OPEN DECISION** | No supplier payable/balance tracking exists anywhere in this codebase yet. |
| 22 | Cancellation rules | **APPROVED (this prompt)** | DRAFT: pure status flip. CONFIRMED: controlled reversal. See §13 above. |
| 23 | Return cancellation after accounting | **N/A** | No accounting posting exists for Purchase Return (#18) — nothing to check yet. |
| 24 | Return cancellation after GST reporting | **N/A** | No GST reporting integration exists for Purchase Return. |
| 25 | Return cancellation after supplier adjustment | **N/A** | No supplier adjustment exists (#21) — nothing to check yet. |
| 26 | Approval workflow | **OPEN DECISION** | Confirmation is a single permission check, no multi-step/threshold approval chain (matches Purchase Order's own PROMPT-020 resolution). |
| 27 | Return permissions | **APPROVED** | `purchase_return.*` — Owner/Manager only, unchanged from PROMPT-019 (FRD Table 7). |
| 28 | Offline Purchase Return | **OPEN DECISION, explicitly NOT implemented** | Per §52's own instruction — a stock-affecting transaction requiring authoritative server validation. |
| 29 | Return numbering | **APPROVED** | Server-authoritative `PRET-{FY}-0001` via the shared `DocumentNumberingService`, unchanged from PROMPT-019. |
| 30 | Return amendment after posting | **OPEN DECISION** | Not implemented — a CONFIRMED return can only be cancelled (with reversal), never edited. |
| 31 | Partial cancellation | **OPEN DECISION** | Cancellation is all-or-nothing per return document — no partial-line cancellation exists. |
| 32 | Multiple-source return | **OPEN DECISION** | A return's lines all trace to the SAME source invoice — no cross-invoice consolidation exists (unlike Purchase Invoice's own PO-consolidated type from PROMPT-022). |
| 33 | One return referencing multiple invoices | **OPEN DECISION (resolved: NOT supported)** | `purchase_return.source_purchase_invoice_id` is a single NOT NULL FK — same resolution as #32. |

## 19. Known Limitations

- No downstream-dependency check exists for POSTED-return cancellation
  beyond "does this codebase have any table that could reference a
  Purchase Return" — because none does yet (#19-21, #23-25 above), the
  reversal path has nothing to block on. If a future prompt adds
  Supplier Payment, Accounting Posting, or a Credit-Note-from-Return
  path, that prompt MUST add an explicit guard here (mirroring
  `PINV_HAS_DOWNSTREAM_RETURN`'s own pattern) before this cancellation
  path can be considered complete against those new document types.
- A Purchase Return's lines always trace to exactly one source Purchase
  Invoice — there is no multi-invoice-consolidated return (the mirror
  image of Purchase Invoice's own PO-consolidated type would be a
  "PO-consolidated return" spanning several invoices; not built, not
  requested).
- No condition-specific (damaged/rejected) stock bucketing — a return
  always posts to the single default location's general stock, exactly
  like every other stock movement in this MVP.

## 20. Definition of Done Status

All §65 checklist items are satisfied:
- [x] List/Create/Draft/Edit/Confirm (PROMPT-019, re-verified unmodified)
- [x] Returnable quantity calculation + previously-returned tracking (PROMPT-019, re-verified)
- [x] Partial return / over-return validation / zero-negative validation (PROMPT-019, re-verified)
- [x] Return reason capture (PROMPT-019, re-verified)
- [x] Stock availability validation (reused Inventory policy)
- [x] Post/Confirm → Stock OUT, atomic, duplicate-protected, idempotent, concurrency-safe (PROMPT-019, re-verified)
- [x] PO/GR/Invoice traceability — new Related Documents endpoint
- [x] Cancellation/reversal — new CONFIRMED-return controlled reversal
- [x] Stock reversal follows immutable-ledger principles (new `PURCHASE_RETURN_REVERSAL` source_type, original entry never touched)
- [x] Original invoice remains immutable (unchanged — return only touches its own bookkeeping counter)
- [x] RBAC / tenant isolation / audit (unchanged + extended to the 2 new endpoints)
- [x] Print/Preview — new `PrPrintPreviewModal`
- [x] Desktop/Tablet/Mobile responsive UI (existing list/create screens + new sections follow the same Tailwind responsive conventions as every prior module)
- [x] Unit/integration/stock/concurrency/idempotency/security tests pass
- [x] Open decisions documented (§18 above, 33-item table)

No critical defects remain open.
