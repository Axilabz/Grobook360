# PROMPT-010 — Inventory Foundation & Stock Ledger: Design Record

## Conflict found — STOP and identify (per the global instruction)

The Data Dictionary v3.0's `stock_ledger_entry` table has `quantity` and
`uom_id` but **no normalized/base-quantity column**, even though this
prompt's own §12 explicitly lists "quantity, unit, normalized/base
quantity where applicable" as an expected ledger field. Resolved the same
way every prior schema gap was: proposed a `base_quantity` column
(NUMERIC 18,3), documented in migration `0011`'s docstring. `quantity`/
`uom_id` remain exactly what the caller entered (preserving the original
value, §27); `base_quantity` is that movement expressed in the product's
base UOM via Product Master's own conversion table (never a second
conversion engine), so balance aggregation never needs a per-row
conversion join at read time.

The DD's constraint note on `movement_type` reads literally "IN/OUT/
ADJUSTMENT" — three values — while §13 lists ten conceptual movement
types (STOCK_IN, STOCK_OUT, OPENING_STOCK, ADJUSTMENT_IN, ADJUSTMENT_OUT,
SALES, PURCHASE, SALES_RETURN, PURCHASE_RETURN, DELIVERY_CHALLAN,
TRANSFER). Treated the DD note as shorthand, not a literal enum (the
column is `VARCHAR(20)`, comfortably wide enough for every one of those
names — strong evidence the DD's own author anticipated more than three
literal values). Direction is folded into the type name so no separate,
potentially-contradictory `direction` column exists (§56). The CHECK
constraint added in this migration covers only the five types **this
prompt actually implements** (OPENING_STOCK, STOCK_IN, STOCK_OUT,
ADJUSTMENT_IN, ADJUSTMENT_OUT); SALES/PURCHASE/etc. are for the Sales/
Purchase prompts that need them to add via their own one-line migration
against `ck_stock_ledger_entry_movement_type` — not pre-guessed here.
TRANSFER specifically needs a second location, out of scope per §8.

## A second bug found and fixed while building this prompt's own tests

Migration 0001's `audit_log` immutability (`REVOKE UPDATE, DELETE ...
FROM PUBLIC`) has **never actually worked**: the application's DB role
owns the table (created it via Alembic), and PostgreSQL table ownership
bypasses the owner's own grant/revoke restrictions entirely. Discovered
empirically while writing this prompt's own ledger-immutability test
(`test_inventory_api_037_ledger_update_rejected_at_db_level`), which
initially failed to raise against `stock_ledger_entry` for the identical
reason. Fixed for the new table with a `BEFORE UPDATE OR DELETE` trigger
(`prevent_stock_ledger_entry_mutation`), which fires regardless of table
ownership — the REVOKE statement is kept for defense-in-depth
documentation, but the trigger is what actually enforces it. Flagged the
pre-existing `audit_log` gap via a spawned follow-up task rather than
silently leaving it broken; that follow-up (migration `0012`) landed
during this same session and applies the identical trigger fix to
`audit_log`, plus a test that actually exercises it (which apparently
never existed before — exactly how the gap went unnoticed since
PROMPT-001). One bug in that follow-up's own test (an expired-ORM-
attribute access after `rollback()` crashing async SQLAlchemy with
`MissingGreenlet`) was also fixed in this session, to keep the full suite
green.

## Location: single-location M1, no management UI

§8 is explicit: M1 supports exactly one active location. The `location`
table is created per the approved Data Dictionary, but no
create/list/update API or screen exists for it — nothing in this
prompt's scope asks for one. Instead, `InventoryService.ensure_default_location()`
lazily get-or-creates a single row (`code="MAIN"`, `name="Main Location"`)
per tenant the first time that tenant posts any stock movement. This
resolves §68 Q3/Q4 pragmatically: Location exists structurally (so
`stock_ledger_entry.location_id` — NOT NULL per DD — is satisfiable and a
future multi-location prompt has a real row to extend) without requiring
a setup screen this prompt never asked for.

## Negative stock: prohibited (OQ-008 resolved, not silently — the FRD's own OQ-008 stays formally open)

The FRD's own Open Questions sheet (**OQ-008**) explicitly leaves this
open: *"Confirm negative-stock behavior and whether stock-out is
hard-blocked."* Not resolved by any other approved source. This
implementation adopts **Option A — negative stock prohibited** exactly as
this prompt's own §18 example describes (Available=10, Requested=15 →
REJECT with "Insufficient stock. Available quantity: {available}."), as
the safer, conventional default. This is a documented interpretation of
an FRD item still marked Open, not a claim that OQ-008 itself has been
formally closed — a business decision could later relax it (e.g., allow
negative stock for specific roles), which would mean adding a role check
before the `new_balance < 0` guard in `InventoryService._post_movement`,
not redesigning the ledger.

## Stock Adjustment: self-approved (no distinct reviewer role exists)

`stock_adjustment`'s approved schema (DRAFT default status,
nullable `approved_by`/`approved_at`) structurally supports a two-step
draft → review → approve workflow. No approved source (FRD, Role &
Entitlement Matrix, User Flow doc) names a reviewer role distinct from
the "Owner/Manager may record manual stock movements" authority FR-STK-04
already grants — inventing a second approver tier nobody asked for would
be exactly the kind of unrequested scope this project's conventions
forbid. **Resolved**: `POST /inventory/adjustments` creates the header
row and immediately self-approves it in the same transaction
(`approved_by` = the creating Owner/Manager, `approved_at` = now,
`status` = APPROVED) before posting the ledger entry — the DRAFT default
is used as the row's transient starting value, not as an exposed pending
state. A true multi-step review workflow (§68 Q15) is reported as an
explicit open decision, not implemented.

## Movement primitives exposed: Opening Stock, Stock-In, Stock-Out, Adjustment — no raw generic endpoint beyond these

§37's suggested endpoint list only shows `POST .../opening-stock` and
`POST .../adjustments`; §38 frames stock-in/out as an internal "reusable
stock movement service" future modules call. But §5's scope list and the
required test cases (INVENTORY-API-026 "Valid stock-in", 027 "Valid
stock-out") clearly expect a directly-testable stock-in/out capability
distinct from adjustment — so both were built as real endpoints, not just
an internal method. The distinction that keeps all four coherent:

- **Opening Stock** — exactly one per product, ever (enforced by a DB
  unique constraint on `(tenant_id, source_type, source_id)` with
  `source_id = product_id`). Establishes the initial position.
- **Stock-In / Stock-Out** — the generic manual primitives (`source_type`
  = `MANUAL_STOCK_IN`/`MANUAL_STOCK_OUT`, a fresh UUID per call), usable
  repeatedly, optional notes, no reason required. This is also literally
  the mechanism a future Goods-Receipt/Sales-Invoice/Delivery-Challan
  prompt should call (with its own `source_type`/`source_id`) rather than
  reinventing stock arithmetic — `InventoryService._post_movement` is
  built as that shared primitive per §38.
- **Adjustment** — requires a `reason`, creates a `stock_adjustment`
  header for traceability of *why* stock was corrected (physical count,
  damage, wastage, etc.) — a different business intent from routine
  stock-in/out even though both can move the ledger by the same amount.

All four call the identical `_post_movement()` core (lock → convert →
check negative-stock → insert ledger row → update `product.stock_qty_cache`
→ audit), so there is exactly one place stock arithmetic happens (§38).

## Concurrency

`SELECT ... FOR UPDATE` locks the `product` row before computing the new
balance, inside the same DB transaction as the ledger insert and cache
update (`begin_nested()` / SAVEPOINT). Two concurrent stock-out requests
against the same product are therefore serialized: the second waiter
re-reads the already-updated balance once the first commits, so "check
then update" cannot race into a negative balance. Verified with an actual
concurrent-request test (`asyncio.gather` of two simultaneous stock-outs
that together exceed available stock) — exactly one succeeds, the other
is rejected with `INV-003`, never both.

## Idempotency

Opening stock, stock-in, stock-out and adjustments all require an
`Idempotency-Key` header and reuse the exact `IdempotencyService` built in
PROMPT-002 for sign-up (same-key + same-payload → replay the stored
response without re-executing; same-key + different-payload → 409).
Verified: a retried stock-in with the same key returns the same movement
id and does not double-post (stock increases once, not twice).

## Unit conversion

Reuses Product Master's `product_unit_conversion` table exactly — no
second conversion engine (§27/§60.18). If the caller's `uom_id` isn't the
product's base unit, the service looks up a conversion row with
`from_uom_id = <entered unit>, to_uom_id = <base unit>` in that exact
direction; if none exists, rejects with "Unable to convert the selected
unit." (`INV-002`). **No automatic reverse-derivation** — §68 Q22
resolved as "no": if only `PCS → CTN` is defined, entering a quantity in
CTN is rejected rather than inverting the factor, since inverting an
arbitrarily-rounded factor can silently introduce precision drift the
prompt's own §17 forbids.

## Database changes

Migration `0011_inventory_foundation.py` creates `location`,
`stock_adjustment`, `stock_ledger_entry` (see Schema Assessment above),
enables RLS on all three, adds the append-only trigger to
`stock_ledger_entry`, and seeds the 5 `inventory.*` permissions
(backfilled for pre-existing roles, same pattern as migrations
0007-0010). `product.stock_qty_cache` (PROMPT-009, previously
write-less) gets its first and only writer here.

## API

`GET /inventory` (list + search + `stock_status` filter: in_stock/
zero_stock/low_stock — the last using **BRULE-DASH-01**'s already-approved
"low stock = current stock ≤ reorder level" rule, not an invented
threshold), `GET /inventory/{product_id}` (detail), `GET
/inventory/{product_id}/movements` (paginated, most-recent-first, each row
carries a `running_balance` computed from the full authoritative ledger
sequence — ordering rule: `occurred_at`, tie-broken by `created_at` then
`id`, resolving §68 Q23), `GET /inventory/availability/{product_id}`,
`POST /inventory/opening-stock`, `POST /inventory/stock-in`, `POST
/inventory/stock-out`, `POST /inventory/adjustments`. No `DELETE`, no
update of any movement — corrections require a compensating movement
(e.g. an `ADJUSTMENT_OUT` to reverse a mistaken `ADJUSTMENT_IN`), never an
edit (§25/§26).

## RBAC (FR-STK-04, not re-decided)

`inventory.view/opening_stock/adjust/stock_in/stock_out`.

| Role | view | opening_stock | adjust | stock_in | stock_out |
|---|---|---|---|---|---|
| OWNER | ✓ | ✓ | ✓ | ✓ | ✓ |
| MANAGER | ✓ | ✓ | ✓ | ✓ | ✓ |
| SALESPERSON | ✓ | — | — | — | — |
| PLATFORM_ADMINISTRATOR | — | — | — | — | — |

FR-STK-04 (Confirmed): *"Owner/Manager may record manual stock movements;
Salesperson may only cause stock movement through permitted sales
workflows"* — no Sales module exists yet, so Salesperson currently has
view-only inventory access, full stop. Split into five granular codes for
catalogue-style consistency with every other module, not because FR-STK-04
itself names them separately (same pattern as PROMPT-007/008/009).

## Security / atomicity

Tenant isolation (RLS + explicit `tenant_id` filters), cross-tenant
lookups return the same 404 as not-found, inactive-product rejection
(`INV-006`) before any movement is allowed, and every movement's ledger
insert + cache update happen inside one DB transaction (SAVEPOINT) — an
insert can never succeed while the cache update fails or vice versa
(§39). 35 new backend tests in `tests/integration/test_inventory.py`
cover the full matrix: opening stock (valid/invalid/unauthorized/
duplicate/audit), stock-in/out (valid/invalid quantity/insufficient
stock/invalid unit/conversion/idempotent retry/missing key), adjustments
(positive/negative/invalid/unauthorized/reason capture/negative-stock
protection/audit), list/detail/movements/tenant isolation, concurrent
stock-out, and ledger-immutability-at-the-DB-level. **Full suite: 244
backend tests passing** (209 prior + 35 new).

## Frontend

- `api/inventory.ts` — the four mutating calls each mint a fresh
  `crypto.randomUUID()` Idempotency-Key per call (client.ts already
  supported this header from PROMPT-001; just unused until now).
- `components/InventoryManagement.tsx` — list with search/stock-status
  filter, a movement-history modal (most-recent-first, running balance,
  reference column), and one shared `StockActionModal` parameterized by
  type (opening/in/out/adjust) that shows a live "Current Stock →
  Resulting Stock" preview (turns red with a warning line when the
  requested action would go negative, so the user sees the rejection
  coming before submitting, even though the server is the actual
  authority — §52). The unit dropdown in each action modal is populated
  from that specific product's base unit plus any conversion units
  already defined for it (fetched via `getProduct`), reusing Product
  Master's conversion data rather than inventing a separate unit list.
- Sidebar: the "Items" menu's placeholder "Stock" sub-item (dummy
  AI-Studio-scaffold label, never wired to anything) is replaced with a
  permission-gated "Inventory" entry (`inventory.view`), alongside
  "Products".
- Verified live end-to-end in-browser: fresh login (new `inventory.*`
  claims) → Items → Inventory → RICE-001 showing 0.000 stock → recorded
  opening stock of 100 PCS (preview correctly showed 0 → 100) → stock-out
  of 30 (confirmed 70.000 remaining) → movement history modal showing
  both entries most-recent-first with correct running balances
  (100.000 → 70.000) → attempted an oversized stock-out (999 against 70
  available) and confirmed the server rejected it with "Insufficient
  stock. Available quantity: 70.000." while the resulting-stock preview
  turned red with the warning line, and stock remained unchanged.
- No dedicated frontend component test added, consistent with established
  precedent (no prior module has one either).

## Open decisions carried forward (not silently resolved)

1. **Negative stock** (OQ-008, FRD's own item, still formally open):
   implemented as prohibited by default — see rationale above.
2. **Batch/expiry tracking** (OQ-007, FRD's own item, still formally
   open): `batch_no`/`expiry_date` columns exist on `stock_ledger_entry`
   per the approved schema but are never read or written by any code path
   here.
3. **Multi-step adjustment approval**: not implemented — self-approved at
   creation since no distinct reviewer role is defined anywhere approved.
4. **Multi-location / Transfer movements**: out of scope per §8 — a
   single lazily-provisioned "MAIN" location per tenant, no location
   management UI, no TRANSFER movement type in the DB CHECK constraint yet.
5. **Reverse unit-conversion auto-derivation**: not implemented — the
   exact `from → to` direction must already exist on the product, or the
   movement is rejected.
6. **Low-stock threshold**: uses the already-approved BRULE-DASH-01 rule
   (`reorder_level > 0 AND stock <= reorder_level`) — not a new invented
   threshold, but `reorder_level` itself is still not editable anywhere
   (PROMPT-009 left it read-only), so every product currently has
   `reorder_level = 0` and the low-stock filter is inert until a future
   prompt exposes that field for editing.
7. **`stock_adjustment` line items**: the approved schema has no
   adjustment-line child table, so each adjustment header maps to exactly
   one product/quantity/ledger-entry in this MVP (matching §50's
   single-product UX spec) — a multi-product adjustment batch sharing one
   `adjustment_number` is structurally possible (multiple ledger rows
   could share one `source_id`) but not built, since nothing in scope
   asked for it.
