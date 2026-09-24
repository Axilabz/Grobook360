# PROMPT-014 — Delivery Challan Management: Design Record

## What was built

The third concrete Sales document type, and the FIRST one that actually
moves stock (§3: "Delivery Challan = STOCK OUT", unlike Estimate/Sales
Order which never touch inventory). Built directly on PROMPT-010's Stock
Ledger, PROMPT-011's document numbering, and PROMPT-013's Sales Order.

### 1. Schema (migration `0016_delivery_challan.py`)

New `delivery_challan`/`delivery_challan_line` tables. Unlike Estimate and
Sales Order, this document carries **no pricing or GST columns at all** —
§9's own header/line field list has none (Delivery Challan is a pure
dispatch record; financial value is already fixed on the source Sales
Order and will be invoiced later by a future prompt). Proposed additions
(same "propose, document, implement" pattern): `shipping_address`,
`place_of_supply_state_code`, `total_quantity` on the header (snapshotted/
derived from the source Sales Order); `previously_delivered_quantity`,
`remaining_quantity` on the line (§9 explicitly lists these as minimum
line fields).

This migration also extends **Sales Order** (from PROMPT-013), since
Delivery Challan cannot function without it:
- `sales_order_line.delivered_quantity` (new column, default 0) — the
  cumulative quantity dispatched via CONFIRMED Delivery Challans. A
  `CHECK (delivered_quantity >= 0 AND delivered_quantity <= quantity)`
  constraint is the DB-level backstop for "delivered can never exceed
  ordered" (§5).
- `sales_order.ck_sales_order_status` widened to allow
  `PARTIALLY_FULFILLED` and `FULFILLED` — exactly the two statuses
  PROMPT-013's own migration deliberately withheld pending this prompt
  (see that prompt's NOTES.md).

### 2. Status lifecycle — deliberately minimal (§11)

Only `DRAFT → CONFIRMED → CANCELLED`. The prompt's own §11 instruction —
*"Additional fulfillment information should be represented through the
source Sales Order status. Do not create unnecessary Delivery Challan
statuses"* — is followed literally: there is no Delivery-Challan-side
"partially delivered" concept. Fulfillment tracking lives entirely on the
Sales Order (`PARTIALLY_FULFILLED`/`FULFILLED`, set by
`SalesOrderService.apply_delivery`), never on the Delivery Challan itself.
One Delivery Challan is always exactly one dispatch event.

### 3. The atomic stock-out + fulfillment core (§3/§17/§22)

`DeliveryChallanService.confirm_challan` is the one place everything
converges, all inside a single DB transaction (single commit at the
router layer, matching every prior prompt's pattern):

1. Lock the Delivery Challan row (`SELECT ... FOR UPDATE`), check status
   is DRAFT and row_version matches.
2. Lock the source Sales Order row via
   `SalesOrderService.get_order_locked` — this is what makes two
   concurrent confirmations against Delivery Challans on the SAME Sales
   Order serialize instead of racing (§19).
3. Re-read the Sales Order's lines fresh, post-lock — under PostgreSQL's
   default READ COMMITTED isolation, this sees any `delivered_quantity`
   already committed by a Delivery Challan that won a race and committed
   first.
4. For each Delivery Challan line: recompute `remaining = ordered -
   live_delivered_quantity` and re-validate `current_delivery_quantity
   <= remaining` — this is the AUTHORITATIVE check (§19/§20), not the
   one done at DRAFT-creation time (which only checks against
   currently-visible data and is a UX convenience, not a guarantee).
5. Lock the Product row (`InventoryService.get_active_product_locked`)
   and call `InventoryService.post_movement(movement_type=STOCK_OUT,
   source_type="DELIVERY_CHALLAN", source_id=<the DELIVERY CHALLAN
   LINE's id>, ...)` — see §5 below for why the line's id, not the
   header's.
6. Call `SalesOrderService.apply_delivery(...)` to increment
   `delivered_quantity` on each affected Sales Order line and recompute
   the order's overall status from ALL its lines (so a Delivery Challan
   covering only some products correctly leaves the order
   PARTIALLY_FULFILLED, not FULFILLED).
7. Mark the Delivery Challan CONFIRMED, write the audit record.

Any exception at any step (insufficient stock, a product going inactive,
a concurrent line change) rolls back the ENTIRE transaction — the
Delivery Challan stays DRAFT, no stock moves, and the Sales Order's
`delivered_quantity` is untouched. This falls out of the existing
session-per-request pattern (`get_db_session`'s `AsyncSessionLocal()`
context manager rolls back on any uncommitted exception) — no new
transaction-wrapping code was needed, matching how
`SalesOrderService.create_from_estimate` already relies on the same
mechanism for its own atomicity guarantee.

### 4. Concurrency (§19/§20) — verified, not just claimed

Two levels of row locking, both already-established patterns reused
verbatim:
- **Sales Order row lock** (§19: "System MUST NOT allow total delivery >
  50") — via `SalesOrderService.get_order_locked`, the exact same
  `SELECT ... FOR UPDATE` helper PROMPT-013 already built for its own
  Estimate-conversion concurrency guarantee.
- **Product row lock** (§20: stock concurrency) — via
  `InventoryService.get_active_product_locked`, promoted from a private
  helper (`_get_active_product_locked`) to public, since every existing
  in-module caller (`record_stock_in`, `record_stock_out`, etc.) already
  used this exact lock-then-`post_movement` pattern; Delivery Challan is
  simply a new caller of the same primitive.

Verified with `test_concurrent_delivery_cannot_exceed_remaining` and
`test_concurrent_stock_consumption_does_not_go_negative` — two
Delivery Challans confirmed via `asyncio.gather`, asserting only one
succeeds (or both succeed if capacity allows, but never total delivered
exceeds ordered / stock never goes negative).

### 5. Duplicate-movement protection (§18/§34) — reused, not reinvented

`stock_ledger_entry`'s existing `uq_stock_ledger_entry_source (tenant_id,
source_type, source_id)` constraint (PROMPT-010, migration 0011) already
gives exactly the protection §18/§34 ask for — **provided** `source_id`
is set per-line, not per-header. A Delivery Challan can have multiple
lines, and the existing constraint allows only ONE ledger row per
`(source_type, source_id)` pair; using the header's id as `source_id`
for every line's movement would violate this constraint on the second
line of any multi-line challan. Using each `delivery_challan_line.id` as
`source_id` instead gives every movement a naturally unique, stable key
while still being fully traceable back to its Delivery Challan (join
`delivery_challan_line.id = stock_ledger_entry.source_id`, then
`delivery_challan_line.challan_id = delivery_challan.id`) — satisfying
§37's traceability requirement without any schema change to
`stock_ledger_entry` itself.

### 6. Idempotency

Create and confirm both require an `Idempotency-Key` header, reusing the
established `IdempotencyService` check/store pattern unchanged. Confirm's
idempotent replay is verified end-to-end
(`test_idempotent_confirmation_retry`): a retried confirm with the same
key returns the identical stored response and — critically — the second
call never re-executes `_execute()`, so no second Stock OUT is ever
attempted (the DB constraint above is the last-resort backstop if the
API-layer idempotency check were ever bypassed).

### 7. Cancellation — resolved conservatively (§11/§45 open decisions #3/#4)

§11 explicitly says: *"If confirmed stock has already been reduced,
cancellation must create a compensating STOCK IN movement. Only
implement this reversal if cancellation-after-confirmation is approved...
If business rules do not yet define it: flag as Open Decision."* No
approved source authorizes this reversal. Resolved conservatively:
**only DRAFT delivery challans can be cancelled** in this prompt
(`CANCELLABLE_STATUSES = {DRAFT}` in `delivery_challan.py`). Attempting to
cancel a CONFIRMED challan returns `DC-002` with an explanatory message.
See Open Decisions below.

### 8. RBAC

`delivery_challan.view/create/edit/confirm/cancel` mirror Sales Order's
shape exactly. Salesperson gets everything except `.confirm` — User
Story 3 again explicitly names "Owner/Manager" as the actor confirming
the stock-reducing action, the same textual signal that resolved this
identical question for Sales Order in PROMPT-013.

### 9. API

`GET/POST /sales/delivery-challans`, `GET/PATCH /sales/delivery-challans/{id}`,
`POST .../confirm`, `POST .../cancel` — new router. The suggested
`GET /sales/orders/{sales_order_id}/delivery-eligibility` endpoint (§31)
was added to the **existing** `sales_orders.py` router rather than
duplicated elsewhere, since it's fundamentally a Sales Order query (how
much of THIS order remains undelivered) — consistent with §31's own
"reuse, extend, do not duplicate" instruction.

### 10. Frontend

`api/deliveryChallans.ts` + `components/DeliveryChallanManagement.tsx`,
following the established list/create-modal/detail-modal/status-action
pattern. The create flow is self-contained (search-select a Sales Order,
load its delivery eligibility, enter per-line delivery quantities with
live remaining-quantity display and a hard client-side cap at the
remaining quantity — UX only, the server is authoritative). The confirm
dialog explicitly states *"This action will reduce inventory"* (§30's own
instruction to make the stock-impacting action explicit). Wired into
`Sidebar.tsx` under Sales → "Delivery Challans" (permission-gated by
`delivery_challan.view`) and `App.tsx`.

## Testing

- `backend/tests/integration/test_delivery_challans.py` (30 tests):
  create validation (invalid/cancelled/fulfilled source order, inactive
  product, invalid/excessive quantity), delivery eligibility, the
  mandatory §42 stock-movement scenario (stock 100 → DC 20 → stock 80,
  exactly one ledger entry), the mandatory §43 partial-delivery sequence
  (40 → 30 → 30 across three challans, Sales Order reaching FULFILLED),
  the mandatory §44 over-delivery rejection, insufficient-stock rejection
  with full-rollback verification, duplicate-confirmation rejection,
  idempotent retry, concurrent delivery and concurrent stock consumption,
  tenant isolation, permission checks (Salesperson cannot confirm but can
  create/edit/cancel), DRAFT-only editing, row-version conflict, audit
  generation (both `delivery_challan` and `sales_order` entity-type
  entries), cancellation (DRAFT succeeds, CONFIRMED rejected), and list
  search/filter/pagination.
- `backend/tests/integration/test_sales_orders.py`: unaffected — the
  Sales Order status/column changes are additive, no existing assertion
  changed.
- `backend/tests/integration/test_rbac.py`: `delivery_challan.*` codes
  added to the Owner/Manager/Salesperson effective-permission-set
  assertions and the new-role-auto-seed assertion.
- **Full backend suite**: see final verification run before this
  prompt's implementation summary.
- Frontend: `npx tsc --noEmit` clean (pre-existing, unrelated
  `shared/ErrorBoundary.tsx` errors only).

## Open decisions carried forward (not silently resolved)

1. **Cancellation-after-confirmation with stock reversal** (§11/§45 #3/#4)
   — NOT implemented. **Business impact**: once a Delivery Challan is
   confirmed, the only way to "undo" it today is a manual compensating
   stock-in via the existing Inventory module's manual stock-in endpoint
   (PROMPT-010) — there is no one-click reversal, and no link is recorded
   between such a manual correction and the original challan. **Recommended
   option**: a future small addition — allow cancelling a CONFIRMED
   Delivery Challan by calling `InventoryService.post_movement` with
   `movement_type=STOCK_IN`, `source_type="DELIVERY_CHALLAN_REVERSAL"`,
   `source_id=<the same delivery_challan_line.id>` (a different
   `source_type` avoids colliding with the original movement's unique
   constraint), and decrementing `sales_order_line.delivered_quantity`
   back down. **Decision needed from**: Product Owner, to confirm this is
   the desired reversal semantics before it's built.
2. **Negative stock policy** (§15/§45 #1) — inherited unchanged from
   PROMPT-010: prohibited by default. Delivery confirmation fails with
   `INV-003` (409) if available stock is less than the delivery quantity.
   Not re-decided here.
3. **Whether delivery can occur without a Sales Order** (§45 #11) —
   resolved as no. `delivery_challan.source_sales_order_id` is `NOT
   NULL`; only the "create from Sales Order" flow (§12) is implemented.
   **Business impact**: a business that ships goods without first raising
   a Sales Order (e.g. an ad-hoc counter sale) cannot use this module yet.
   **Recommended option**: if needed, a future prompt could make
   `source_sales_order_id` nullable and add a standalone-creation path
   with its own customer/product/quantity validation. **Decision needed
   from**: Product Owner.
4. **Whether all Sales Order lines must be eligible/included in one
   Delivery Challan** (§45 #12) — resolved as no: a Delivery Challan may
   cover any subset of a Sales Order's lines (including just one), each
   independently up to its own remaining quantity. This matches §5's own
   partial-delivery example (delivering Product A alone from a
   multi-product order is implicitly allowed).
5. **UOM conversion during delivery** (§45 #13) — not implemented.
   `delivery_challan_line.uom_id` is always the same UOM the Sales Order
   line was placed in; there is no "deliver in a different unit than
   ordered" flow. Matches the ordered quantity's own UOM at all times.
6. **Decimal quantity support** (§45 #14) — already supported: quantities
   are `NUMERIC(18,3)` throughout (same precision as every other
   quantity column in this codebase since PROMPT-009/010), not a new
   decision.
7. **Whether shipping address can differ from the Sales Order** (§45 #17)
   — resolved as yes (see model docstring): defaults to the Sales Order's
   shipping address but is independently editable per challan.
8. **Delivery date rules** (§45 #19) — no validation beyond "must be a
   valid date"; no rule preventing a challan date before the Sales Order
   date or in the future was specified anywhere, so none was invented.
9. **Print format requirements** (§28/§45 #20) — not implemented; no
   approved template/layout source exists to build against, same
   reasoning as PROMPT-012/013's identical open item.
10. **Offline Delivery Challan creation/confirmation** (§38/§45 #9/#10) —
    not implemented; no approved PRD offline-write matrix or Offline Sync
    Specification was supplied for this prompt to consult. Per §38's own
    instruction, scope was not silently expanded to include offline
    stock-impacting writes — this is the highest-risk category of open
    decision here, since an offline stock-out without server-authoritative
    validation could directly corrupt inventory.
11. **Multiple locations/warehouse behavior** (§45 #7) — inherited
    unchanged from PROMPT-010: single lazily-provisioned "MAIN" location
    per tenant. `DeliveryChallanService.confirm_challan` calls
    `InventoryService.ensure_default_location`, same as every other
    stock-movement caller.
