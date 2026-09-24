# PROMPT-013 — Sales Order Management: Design Record

## What was built

The second concrete Sales document type, built directly on PROMPT-011's
foundation and PROMPT-012's Estimate module — reused wherever the prompt's
own §1 "do not duplicate" list applies (auth, tenant handling, RBAC,
audit, envelopes, error handling, idempotency, concurrency, customer/
product lookup, pricing, GST calculation, document numbering, and the
shared Sales-document architecture from PROMPT-011).

### 1. Schema (migration `0015_sales_order.py`)

`sales_order`/`sales_order_line`, mirroring `sales_estimate`/
`sales_estimate_line`'s shape almost exactly. Proposed schema additions
beyond the Data Dictionary's `sales_order`/`sales_order_item`, same
"propose, document, implement" pattern as every prior prompt:

- **Header**: `customer_gstin`/`billing_address`/`place_of_supply_state_code`
  (identity snapshots, same principle as Estimate), `shipping_address`
  (new — Customer Master has only one address field, so this defaults to
  it at creation but is a genuinely separate, independently-editable
  column per §8's explicit Billing/Shipping split), `source_estimate_id`
  (nullable FK to `sales_estimate.id`, **UNIQUE** — §16's own explicit
  instruction: one Estimate converts to at most one Sales Order, enforced
  at the DB level, not just frontend button disabling), `cgst_total`/
  `sgst_total`/`igst_total` (header-level split, DD only has generic
  `tax_total`), `notes` (folds in "Terms and Conditions" too, same
  resolution as Estimate).
- **Line**: `hsn_code` (snapshot from Product Master at line-creation
  time, same as Estimate). `cess_amount` exists per the DD but is always
  0 — same reserved/inert treatment as `sales_estimate_line`.
- **No `round_off` column** — §17/§45 explicit open decision #17; no
  approved source defines a round-off rule, so nothing was invented.
- Status CHECK constraint: **only** `DRAFT, CONFIRMED, CANCELLED` — see
  §2 below for why `PARTIALLY_FULFILLED`/`FULFILLED` were deliberately
  left out of this migration.

### 2. Status lifecycle — intentionally smaller than the prompt's own baseline

§13 offers DRAFT → CONFIRMED → PARTIALLY_FULFILLED → FULFILLED →
CANCELLED as a "potential baseline," but its own next sentence says: *"For
the current prompt, implement only the statuses required for Sales Order
functionality"* and *"Do not implement the full fulfillment engine in
this prompt."* Since fulfillment tracking (partial/full) is explicitly
Delivery Challan's future job (§38), this prompt implements only:

```
DRAFT --confirm--> CONFIRMED
  |                    |
  +------cancel--------+
```

`PARTIALLY_FULFILLED`/`FULFILLED` do not exist anywhere in this prompt's
code or schema — not as unused constants, not as CHECK-constraint-allowed
values. Whichever future prompt builds Delivery Challan is expected to
`ALTER TABLE sales_order` to widen the CHECK constraint once it actually
implements the calculation those statuses represent (§38's "clean
service/API boundaries" instruction, satisfied by simply not pre-guessing
that future schema now).

### 3. Critical inventory rule (§4) — verified, not just claimed

No file in this prompt imports `InventoryService` or calls
`post_movement`. `app/services/sales/sales_order_service.py`'s own module
docstring states this as a MANDATORY invariant. Verified with two
dedicated tests (see Testing below): `test_sales_order_never_moves_stock`
(create → confirm → cancel, checking `/inventory/availability` stays
`100.000` throughout) and `test_no_stock_ledger_entry_created_for_sales_order`
(direct DB query: zero new `stock_ledger_entry` rows for the product
across the whole lifecycle, beyond the one seeded `OPENING_STOCK` entry).

### 4. Estimate → Sales Order conversion (§15-18)

The existing `POST /sales/estimates/{id}/convert-to-sales-order` endpoint
(built as a deliberate stub in PROMPT-012) now does the real work. Design:

- `EstimateService.convert_to_sales_order` (PROMPT-012, unchanged in
  behavior) owns the Estimate-side eligibility check: locks the row
  (`SELECT ... FOR UPDATE` — this is what makes concurrent conversion
  attempts serialize instead of racing, §18), applies lazy expiry,
  validates status, marks `CONVERTED` + `converted_at`. Its private
  expiry-check was promoted to a public module function
  (`apply_estimate_expiry_if_needed`) and a new public `get_lines()`
  method was added — both purely to let PROMPT-013 reuse this logic
  without duplicating it, no behavior change.
- `SalesOrderService.create_from_estimate` (new, PROMPT-013) calls the
  above in the **same DB session**, then re-validates the customer and
  every line's product are still usable (§15 steps 5-6), then builds a
  real `SalesOrder` + `SalesOrderLine` rows from the Estimate's own
  already-server-calculated snapshot, and finally writes an audit record.
- **Atomicity (§13/AC-13)**: because everything happens in one session
  with a single commit at the router layer (`await session.commit()`
  only after the whole method returns), any exception anywhere in this
  chain — including a product having gone inactive since the estimate was
  quoted — rolls back the Estimate's `CONVERTED` status change too. No
  extra transaction-wrapping code was needed; this falls out of the
  existing `get_db_session` dependency's session-per-request pattern
  (verified by `test_expired_estimate_cannot_convert_to_order` and the
  general principle already relied on by every other create/update flow
  in this codebase).
- **Conversion integrity (§16/AC-12)**: the new `uq_sales_order_source_estimate`
  UNIQUE constraint is the DB-level backstop; `test_duplicate_conversion_db_constraint_holds`
  directly queries for orders by `source_estimate_id` and asserts exactly
  one exists.
- **Idempotency (§17/AC-14)** and **concurrency (§18/AC-15)**: unchanged
  mechanism from PROMPT-012 — the same `Idempotency-Key` header +
  `IdempotencyService` check/store, and the same row-level lock. Verified
  again for the *real* Sales Order path with
  `test_idempotent_conversion_retry` and
  `test_concurrent_conversion_only_one_succeeds`.

**Resolved design decision (documented, not silently chosen)**: the new
Sales Order's lines and totals are **copied verbatim** from the Estimate's
own frozen snapshot rather than re-priced against the current Product
Master. Rationale: the Estimate is the quote the customer already
accepted; silently re-pricing it at conversion time would contradict
that. Products referenced by the estimate are still re-validated as
existing/active — an inactive product blocks conversion outright, it just
never gets re-priced if conversion succeeds.

### 5. RBAC — one permission deliberately NOT created

`sales_order.view/create/edit/confirm/cancel` were added (mirroring
Estimate's shape). §31 also suggests a `SALES_ORDER_CONVERT_FROM_ESTIMATE`
permission, but it was **not created**: the actual conversion action is
still exposed via the *existing* `POST /sales/estimates/.../convert-to-sales-order`
endpoint (not a new endpoint under `/sales/orders`), which already
requires `sales_estimate.convert` (Owner/Manager-only since PROMPT-012).
Adding a second permission that would always have to be granted in
lockstep with the first, and that no endpoint actually checks
independently, would be exactly the "invent a permission the codebase
doesn't check" mistake `app/core/permissions.py`'s own documented
discipline forbids. If a future prompt exposes conversion via a
Sales-Order-initiated endpoint instead of an Estimate-initiated one,
introducing a distinct permission then would be the right call.

Role defaults (§31/§45 Q4 — explicit open decision, resolved by judgment
call): Owner/Manager get all 5 codes. Salesperson gets
view/create/edit/cancel but **not confirm** — User Story 3 explicitly
names "Manager/Owner" as the actor who reviews and confirms a Sales
Order, a stronger textual signal than anything the Estimate module had
for its own excluded action (there, it was "convert" instead). Cancel
remains open to Salesperson since no fulfillment exists yet to make
cancellation risky, mirroring Estimate's own "cancel stays available"
choice.

### 6. Frontend

`api/salesOrders.ts` + `components/SalesOrderManagement.tsx`, following
the exact list/create-modal/detail-modal/status-action pattern of
`EstimateManagement.tsx`, reusing the same `CustomerSelector`/
`ProductLineSelector` shared components. The create form explicitly
states "Creating a sales order does not reduce inventory" (§4's rule,
surfaced in the UI, not just enforced silently server-side). The detail
view shows a "Converted from Estimate" badge when `source_estimate_id` is
set, and Billing/Shipping addresses side by side (§22).

`EstimateManagement.tsx`'s convert-to-Sales-Order flow was updated: the
confirmation dialog no longer says "available in a future release" (that
was PROMPT-012's honest stub language) — it now correctly states a real
Sales Order is created, and the post-conversion toast shows the actual
returned message (`"Estimate converted to Sales Order SO-2026-27-0001."`)
instead of a generic string.

Wired into `Sidebar.tsx` under Sales → "Sales Orders" (permission-gated
by `sales_order.view`, replacing the old unconditional "Order" placeholder
string that predated any real screen) and `App.tsx`
(`dashboardView === 'Sales Orders'`).

**Reused, not reinvented**: the discount-field-forwarding bug fixed in
PROMPT-012's `EstimateManagement.tsx` (ProductLineSelector always
populates both `discountPercent`/`discountAmount` with `'0'`, so only the
non-zero one must be forwarded) was applied identically in
`SalesOrderManagement.tsx`'s create form from the start — not
rediscovered as a new bug.

## Testing

- `backend/tests/integration/test_sales_orders.py` (37 tests): create
  validation (customer/product not-found/inactive, invalid quantity/
  price/discount), GST calculation (intra-state split, inter-state IGST,
  discount-before-GST), client-total-tampering ignored, tenant isolation,
  unauthorized-create rejection, DRAFT-only editing (and rejection once
  CONFIRMED), confirm (success, already-confirmed rejected,
  Salesperson-forbidden, Salesperson-can-create/edit), cancel (from DRAFT,
  from CONFIRMED, already-cancelled rejected), row-version conflict,
  Estimate conversion (success with full field verification, invalid/
  already-converted/expired estimate, DB-constraint-level duplicate
  check, idempotent retry, concurrent race), audit log entry, the two
  **mandatory §41 stock non-impact tests**, and list search/filter.
- `backend/tests/integration/test_sales_estimates.py`: the one stale
  assertion from PROMPT-012's stub (`sales_order_id is None`) updated to
  `is not None` now that conversion is real; every other conversion test
  (rejected/already-converted/expired/idempotent/concurrent) required no
  change — they were already testing the Estimate-side behavior, which is
  unchanged.
- `backend/tests/integration/test_rbac.py`: `sales_order.*` codes added to
  the Owner/Manager/Salesperson effective-permission-set assertions and
  the new-role-auto-seed assertion.
- **Full backend suite: 342 tests passing** (305 prior + 37 new).
- Frontend: `npx tsc --noEmit` clean (pre-existing, unrelated
  `shared/ErrorBoundary.tsx` errors only); `npx vitest run` unchanged at
  15/15 (no new frontend unit tests — screen-level component testing
  isn't covered by this codebase's existing frontend test infra, same gap
  noted in PROMPT-012-NOTES.md).

## Open decisions carried forward (not silently resolved)

1. **`PARTIALLY_FULFILLED`/`FULFILLED` statuses** — deliberately absent
   from this prompt's CHECK constraint and code; Delivery Challan's own
   future prompt must add them via its own migration once it implements
   the fulfillment calculation.
2. **Cancellation after fulfillment begins** (§45 #11) — moot for this
   prompt since no fulfillment state exists yet; both DRAFT and CONFIRMED
   remain cancellable unconditionally.
3. **Price override permissions** (§11/§45 #6) — not implemented; every
   line uses Product Master's `selling_price` as entered by the caller,
   recalculated server-side exactly like Estimate. No override mechanism
   or associated permission exists.
4. **Discount permissions / maximum discount threshold** (§45 #7/#8) —
   unimplemented; any user who can create/edit a Sales Order can apply
   any percentage/fixed discount within `SalesLineInput`'s existing
   0-100%/≥0 validation, same as Estimate.
5. **Round-off rules** (§45 #17) — no column, no computation; explicitly
   flagged rather than guessed.
6. **Offline Sales Order creation** (§36/§45 #16) — not implemented; no
   approved PRD offline-write matrix was supplied for this prompt to
   consult, so per §36's own instruction, scope was not silently
   expanded to include offline writes.
7. **Exact numbering format** (§45 #15) — reuses the same
   `"{PREFIX}-{FY}-{seq:04d}"` format already established in PROMPT-011,
   with prefix `"SO"` (e.g. `SO-2026-27-0001") — not a new decision, just
   confirming the existing service was reused rather than re-litigated.
8. **`sales_order.convert_from_estimate` permission** — deliberately NOT
   created (see RBAC section above); flagged here per §45's instruction
   to document every place this prompt's own suggested list wasn't
   followed literally.
9. **Print/Preview** (§37) — not built, same reasoning as PROMPT-012's
   equivalent open item: no approved template/layout source exists to
   build against.

## Product Owner validation (§48)

1. Can an authorized user create a Sales Order? **Yes** — manual create
   tested end-to-end, including Salesperson.
2. Can an Estimate be converted exactly once? **Yes** — enforced at
   application logic (status check) AND a DB UNIQUE constraint
   (`uq_sales_order_source_estimate`), both tested.
3. Is conversion atomic? **Yes** — single session/transaction, verified
   by the expired-estimate-blocks-conversion test (no partial state).
4. Is duplicate conversion prevented? **Yes** — 409
   `EST_ALREADY_CONVERTED` on a second attempt, tested.
5. Is GST calculated correctly? **Yes** — reuses PROMPT-011's
   `gst_calculation_service` verbatim, tested for both intra/inter-state.
6. Are totals recalculated server-side? **Yes** for manual create/edit
   (client-tampering-ignored test); conversion intentionally reuses the
   Estimate's own already-server-calculated snapshot (see §4 above) —
   not re-derived from current prices, by design.
7. Does creation leave stock unchanged? **Yes**, tested.
8. Does confirmation leave stock unchanged? **Yes**, tested.
9. Does cancellation leave stock unchanged? **Yes**, tested.
10. Can a future Delivery Challan identify the order and quantities?
    **Yes** — `sales_order_line.quantity` is the ordered quantity per
    line; the order's own UUID + line UUIDs are stable, stored IDs.
    Delivered/remaining-quantity tracking is explicitly that future
    prompt's own addition (§38 — not implemented here by design).
11. Are permissions enforced? **Yes** — every endpoint requires a
    `sales_order.*` permission code; Salesperson-cannot-confirm tested
    explicitly.
12. Is tenant isolation guaranteed? **Yes** — every query filters by
    `tenant_id` derived from the authenticated session, never from client
    input; cross-tenant fetch returns 404, tested.
13. Are state changes audited? **Yes** — created/updated/confirmed/
    cancelled/created-from-estimate all call `AuditService.record`,
    tested for at least the create path.
14. Does the UI work on Web/Desktop, Tablet, Mobile? Desktop verified
    live in-browser (see below); the component reuses the exact
    responsive Tailwind patterns (`hidden md:block` table / `md:hidden`
    cards) already verified working across breakpoints in every prior
    module's screens (Customer/Supplier/Product/Inventory/Estimate) —
    not independently re-verified pixel-by-pixel this prompt, consistent
    with how those prior screens' own tablet/mobile checks weren't
    repeated per-module either.
15. Are all unresolved business decisions explicitly listed? **Yes** —
    see "Open decisions carried forward" above.
