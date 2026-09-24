# PROMPT-009 — Product Master: Design Record

## Conflict found — STOP and identify (per the global instruction)

Unlike `customer`/`supplier` (PROMPT-007/008), Data Dictionary v3.0's
`product` table is **already fully specified** for this prompt's scope —
no proposed field additions were needed. FR-PROD-01 ("Confirmed") lists
exactly the fields the baseline already has: name, SKU, HSN, GST rate, Cost
Price, Selling Price, MRP, UOM. This was verified before writing code, not
assumed from the Customer/Supplier precedent.

**No category/subcategory/brand/product_type/description anywhere** —
absent from both the Data Dictionary and FR-PROD-01. Per §11/§12 (don't
invent Category/Brand just because FMCG products commonly have them), none
were added.

**Genuine tension found and resolved explicitly**: FR-PROD-01 itself lists
"opening stock" as a create/edit field, and FR-PROD-03 says the list should
show "stock ... status." But `product.stock_qty_cache` is explicitly a
**cache**, and FR-STK-05/ASM-004 (both Confirmed) state *"Product stock
quantity is a cache over Stock Ledger... must not be treated as source of
truth"* and *"Requires reconciliation capability."* Writing to
`stock_qty_cache` directly from Product Master — even as "opening stock" —
would make the cache diverge from its own ledger the moment the (not yet
built) Stock Ledger module exists, which is exactly the inconsistency
FR-STK-05 warns against. **Resolved by displaying it read-only (always 0
until Inventory exists) and giving it no write path anywhere in this
module** — "opening stock" is deferred entirely to the future Stock Ledger
prompt, which is the only place FR-STK-05 permits writes to happen.

**Batch/Expiry**: the FRD's own Scope Matrix (Table 4, row 14) marks this
**OPEN** — *"Schema reserved; exact product behavior not confirmed."*
`batch_no`/`expiry_date` columns are created (matching the approved schema)
but have no input field anywhere in this module, per the FRD's own
not-yet-confirmed status — implementing behavior for them would be
inventing the very thing the FRD says isn't decided.

## Existing Product Schema Assessment (required by §71.2)

| Field (approved DD v3.0) | Kept as-is |
|---|---|
| id, tenant_id, sku, name, hsn_code, gst_rate, base_uom_id, cost_price, selling_price, mrp, reorder_level, stock_qty_cache, batch_no, expiry_date, status, audit/row_version | Yes, unchanged |

No proposed field additions on `product` itself. Two supporting tables the
Table Register already lists (MASTER domain) but no prior prompt created —
built here because `product.base_uom_id` is a mandatory FK to one of them:

- **`unit_of_measure`**: id, tenant_id, code (UNIQUE per tenant), name,
  precision (0-6, default 2), audit/row_version — exactly per DD.
- **`product_unit_conversion`**: id, tenant_id, product_id, from_uom_id,
  to_uom_id, conversion_factor (NUMERIC 18,6, >0), audit/row_version —
  exactly per DD, **plus two proposed additions**: `UNIQUE(tenant_id,
  product_id, from_uom_id, to_uom_id)` and `CHECK(from_uom_id <>
  to_uom_id)`. Neither exists in the Constraints & Indexes sheet, but both
  directly implement §19's own requirements ("prevent duplicate conversion
  definitions", "prevent invalid circular/self-conversion") — the same
  class of low-risk schema tightening PROMPT-006 did for `user_role`.

## GST rate: no hardcoded list, no versioning invented

`product.gst_rate` is `NUMERIC(5,2)`, nullable, DD note: *"Configurable
rate baseline."* **ERD-DEC-05** (Open Decisions sheet) says a *"versioned/
configurable GST master should be finalized in GST Rule Matrix"* — future
work, not done yet. Consistent with that and with §14 ("do not hardcode GST
rates in UI components"), `gst_rate` is a **free numeric input** (0-100, 2
decimals), not a dropdown of fixed values like 5/12/18/28 — hardcoding that
list would itself be exactly the thing §14 forbids. GST rate versioning/
effective-dating (§73 Q14-17) is reported here as still open, deferred to
whenever the GST Rule Matrix is finalized.

## SKU: user-entered (a deliberate difference from customer_code/supplier_code)

Customer/Supplier codes (PROMPT-007/008) are system-generated because
they're purely internal references. SKU is different: it is FMCG industry
terminology for a code that must often match a manufacturer's or
distributor's own external labeling/packaging — forcing tenants to accept
an internally-generated `PROD-0001` instead would fight how the business
actually identifies its own goods. **Decision: SKU is user-entered,
required, normalized to uppercase, validated as
`^[A-Z0-9][A-Z0-9_-]{0,49}$`, unique per tenant** (DB constraint +
app-level duplicate check, `PROD-002` on conflict). Documented as an
explicit, reversible open decision (§73 Q1-4), not silently assumed from
the Customer/Supplier precedent.

## Permission model (FR-PROD-04 + Table 7 — stricter than Customer/Supplier)

`app/core/permissions.py`: `products.view/create/update/activate/deactivate`.

| Role | view | create | update | activate | deactivate |
|---|---|---|---|---|---|
| OWNER | ✓ | ✓ | ✓ | ✓ | ✓ |
| MANAGER | ✓ | ✓ | ✓ | ✓ | ✓ |
| SALESPERSON | ✓ | — | — | — | — |
| PLATFORM_ADMINISTRATOR | — | — | — | — | — |

FR-PROD-04 (Confirmed): *"Owner and Manager may create/edit/deactivate;
Salesperson has read-only visibility."* Table 7 confirms **"View"** (not
"Limited") for Salesperson on Products — unlike Customer/Supplier, this was
checked explicitly rather than assumed identical, and Salesperson gets
`products.view` only, nothing else.

**Unit of Measure and Product Unit Conversion have no permission family of
their own** — gated by `products.view`/`products.create` instead. Neither
appears as its own row in any approved Role & Entitlement source, and both
are meaningless without a product to attach to; inventing a `units.*`
permission family would be exactly the "fill the matrix with assumptions"
pattern PROMPT-006 forbids. Adding a unit conversion specifically requires
`products.update` (editing a product's unit setup is an edit action).

Backfilled existing pre-PROMPT-009 tenants' roles via migration `0010`
(same pattern as `0007`/`0008`/`0009`). Updated the three RBAC
permission-set assertions in `tests/integration/test_rbac.py` again.

## Database changes

- Migration `0010_product_master.py`: creates `unit_of_measure`, `product`,
  `product_unit_conversion` (see Schema Assessment above), enables but does
  not force RLS on all three, seeds the 5 `products.*` permissions and
  backfills `role_permission` for every pre-existing role.
- Indexes: `tenant_id` (all three tables), plus `hsn_code`/`name` on
  `product` and `product_id` on `product_unit_conversion` for the query
  patterns this module actually uses.

## API

`GET/POST /products`, `GET/PATCH /products/{id}`,
`POST /products/{id}/activate|deactivate`, plus the nested
`POST /products/{id}/conversions` (§43: "use an appropriate nested
resource... do not create duplicate APIs" — no separate top-level
conversions resource). `GET/POST /units` — minimal list/create only, no
update/delete (open decision, §73 not directly asked but analogous to
customer/supplier's "no delete" pattern: a unit once referenced by a
product or conversion shouldn't silently change meaning underneath them).

Product detail embeds `unit_conversions: [...]` directly rather than
requiring a second round-trip. List responses stay lean (no conversions).

No `DELETE` anywhere in this module (§29/§60.23).

## Validation

- `sku`: required, uppercase alnum + hyphen/underscore, 1-50 chars, unique
  per tenant.
- `name`: required, 1-200 chars.
- `hsn_code`: optional; format-only check (4, 6 or 8 numeric digits per
  GST's HSN/SAC structure) — explicitly **not** external HSN master
  verification (§13).
- `gst_rate`: optional, 0-100, 2 decimal places — free numeric, not a
  picklist (see above).
- `base_uom_id`: required, must reference an existing tenant-owned
  `unit_of_measure` row (`PROD-004` if not).
- `cost_price`/`selling_price`/`mrp`: each `>= 0`, default 0. **No
  `selling_price <= mrp` enforcement** — not defined by any approved
  source (§25/§73 Q28); reported as an open decision, not invented policy.
- Unit conversion: `from_uom_id != to_uom_id` (DB CHECK + app check),
  `conversion_factor > 0`, duplicate `(product, from, to)` pairs rejected
  (`PROD-005`).

## Security / concurrency

Tenant isolation, cross-tenant-lookup-is-404, optimistic concurrency
(`row_version` / 412), and audit logging
(`PRODUCT_CREATED/UPDATED/ACTIVATED/DEACTIVATED`,
`UNIT_OF_MEASURE_CREATED`, `PRODUCT_UNIT_CONVERSION_CREATED` via the
existing `AuditService`) all follow the identical PROMPT-005/007/008
pattern.

38 new backend tests in `tests/integration/test_products.py` cover unit
create/duplicate, the full product CRUD/status/concurrency matrix, the
Salesperson read-only boundary (both a positive "can view" and negative
"cannot create/edit/deactivate" case — deliberately stricter than
Customer/Supplier's tests), SKU/HSN/GST-rate/price validation, and the full
unit-conversion validation set (zero/negative factor, invalid unit,
duplicate pair, self-conversion). **Full suite: 209 backend tests passing**
(171 prior + 38 new; the 3 RBAC permission-set assertions were updated in
place again, not added).

## Frontend

- `api/units.ts`, `api/products.ts`, `components/ProductManagement.tsx` —
  list/modal/detail/confirm shape consistent with
  `CustomerManagement.tsx`/`SupplierManagement.tsx`, plus a "Unit
  Information" section with an inline "Add a new unit" quick-create (no
  separate Units screen — consistent with Units having no dedicated
  permission family) and, in edit mode only, a "Unit Conversion" section
  listing existing conversions and letting the user add new ones.
- Sidebar: the pre-existing "Items" menu's placeholder `['Add Items', 'List
  Items', 'Stock']` sub-items (dummy AI-Studio-scaffold labels never wired
  to anything) are replaced with a permission-gated "Products" entry
  (`products.view`) ahead of the still-unbuilt "Stock" placeholder, which
  is left as-is since Inventory isn't in scope here.
- **Bug found and fixed during manual verification**: the "Add a new unit"
  quick-create button is shared between the Base Unit field and the Unit
  Conversion section, and its `onCreated` callback originally always called
  `setBaseUomCode(unit.code)` — so adding a unit purely to use in a
  conversion (in edit mode) silently overwrote the product's already-set
  Base Unit in the form. Fixed to only auto-select the new unit as Base
  Unit when none was chosen yet (`setBaseUomCode((prev) => prev || unit.code)`).
  Caught before any server-side state was affected (the bug only ever
  touched unsaved form state) — verified via a direct API call that the
  stored `base_uom_id` was never actually changed.
- Verified live end-to-end in-browser: fresh login (to pick up the new
  `products.*` claims) → Items → Products nav (permission-gated) → create
  unit "PCS" inline → create product `RICE-001` (HSN 1006, GST 5%, cost
  ₹80/selling ₹100/MRP ₹120) → list/detail views correct, Selling Price
  explicitly labeled "excl. GST", Stock shown as "0.000 (Inventory module
  pending)" → edit → create unit "CTN" → add conversion 1 CTN = 24 PCS →
  confirmed in both the edit form and the read-only detail view.
- No dedicated frontend component test added, consistent with established
  precedent (`UserManagement.tsx`/`CustomerManagement.tsx`/
  `SupplierManagement.tsx` have none either).

## Open decisions carried forward (not silently resolved)

1. **SKU generation**: user-entered (see rationale above) — the one
   deliberate divergence from Customer/Supplier's system-generated codes.
2. **GST rate versioning/effective-dating** (§73 Q14-17): blocked on
   **ERD-DEC-05** ("GST rate master... should be finalized in GST Rule
   Matrix") — a free numeric field for now, no history, no effective-from/
   to dates. Historical transactions (when Sales/Purchase exist) must
   capture the rate actually applied at transaction time themselves —
   Product Master's current `gst_rate` is never retroactively authoritative
   for a past transaction.
3. **Selling Price <= MRP**: not enforced anywhere (§25/§73 Q28) — no
   approved source requires it.
4. **Opening stock / stock_qty_cache**: no write path in this module at
   all (see "Conflict found" above) — entirely deferred to the future
   Stock Ledger module, which FR-STK-05 designates as the only legitimate
   writer.
5. **reorder_level**: same treatment as stock_qty_cache — column exists,
   read-only, tied to future Inventory/reorder-alert functionality
   (FR-DASH-05), out of scope here.
6. **Batch/expiry tracking**: the FRD's own Scope Matrix marks this OPEN —
   columns exist (schema-reserved), no business behavior implemented.
7. **Unit of Measure / Product Unit Conversion lifecycle**: create-only in
   this MVP — no update/delete for either. If a unit code needs correcting
   or a conversion needs removing, that's a future enhancement, not
   attempted here to keep the surface area minimal and avoid inventing a
   deletion/edit policy for master rows that may already be referenced.
8. **Historical-transaction snapshot principle** (§30): no transaction
   tables reference `product` yet (out of scope here) — same guidance as
   PROMPT-007/008-NOTES.md: once Sales/Purchase modules exist, they must
   snapshot product name/GST rate/HSN/price at transaction time rather than
   live-joining `product`, so a later master-data edit here never rewrites
   historical documents.
