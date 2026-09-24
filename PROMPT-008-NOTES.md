# PROMPT-008 — Supplier Management: Design Record

## Conflict found — STOP and identify (per the global instruction)

Same class of gap as PROMPT-007: the approved Database Design v3.0
`supplier` table (Data Dictionary sheet) defines only `id, tenant_id,
supplier_code, name, gstin, state_code, address, phone,
credit_terms_days, balance, status` + audit/row_version. **FR-SUPP-01**
("Confirmed") additionally requires an owner/contact person, optional
email, city and pin code on the same create/edit screen. Resolved the same
way — proposed schema addition, documented in migration `0009`'s docstring,
not silently dropped or invented differently.

**Important asymmetry vs. Customer, found and respected rather than
copied blindly**: **FR-SUPP-02** is an explicit, direct instruction —
*"Do not capture Customer-only Region/Beat, GPS or Credit Limit fields for
Supplier."* PROMPT-007's `customer` table has `region`, `gps_location` and
`credit_limit`; **none of those three exist on `supplier`**, by design.
This was checked before writing the migration, not assumed from the
Customer pattern.

**FR-SUPP-05** ("Confirmed") answers the RBAC open-decision list directly,
identically in shape to FR-CUST-07: *"Owner, Manager and Salesperson may
create/edit suppliers; deactivation is Owner/Manager controlled."*
Implemented verbatim.

## Existing Supplier Schema Assessment (required by §59.2)

| Field (approved DD v3.0) | Kept as-is |
|---|---|
| id, tenant_id, supplier_code, name, gstin, state_code, address, phone, credit_terms_days, balance, status, audit/row_version | Yes, unchanged |

| Field added (proposed, FR-SUPP-01) | Reason |
|---|---|
| `contact_person` (NOT NULL) | FR-SUPP-01 "owner/contact"; named `contact_person` rather than reusing Customer's `owner_name` — the FRD's own wording for Supplier is more generic ("owner/contact") than Customer's ("owner name"), fitting a B2B purchasing-contact context |
| `email` (nullable) | FR-SUPP-01 "optional email" |
| `city`, `pincode` (nullable) | FR-SUPP-01 required display fields; baseline only has a single freeform `address` |

**Deliberately NOT added**:
- **`region`, `gps_location`, `credit_limit`** — explicitly forbidden by
  FR-SUPP-02, not merely absent from the baseline. This is the one place
  PROMPT-008 must NOT mirror PROMPT-007.
- **No `supplier_type` column** — FR-SUPP-03 defines GST-registration
  status as derived from blank/non-blank `gstin`, same as Customer's
  FR-CUST-03; no approved source defines a separate classification value.
- **No bank-account fields at all.** Data Dictionary v3.0's own Open
  Decisions sheet (**ERD-DEC-04**) states a BankAccount master "is required
  by bank transaction/reconciliation" but is "not fully specified in
  current ERD" — i.e. explicitly and upstream-acknowledged as unresolved.
  §61 Q16-20 (bank fields, masking, role access) are therefore reported
  here as **open/blocked on ERD-DEC-04**, not answered — nothing was
  invented to fill the gap. No bank UI, no bank API fields, no bank audit
  events exist in this implementation.
- **No `country` column** — same BR-001/ASM-002 single-country-market
  reasoning as PROMPT-007.
- **No separate billing/shipping address** — Data Dictionary v3.0 has
  exactly one `address` column for supplier too.

## Naming note

FR-SUPP-01 calls the days-based term field "payment terms"; the approved
Data Dictionary column is named `credit_terms_days` (not
`payment_terms_days` as Customer's is). The DB baseline's column name was
used as-is (§7/§60.9: don't invent a duplicate model) — the UI label reads
"Payment / Credit Terms (Days)" to bridge the FRD/schema naming difference
without renaming the approved column.

## Permission model (FR-SUPP-05 + Table 7, not re-decided)

`app/core/permissions.py`: `suppliers.view/create/update/activate/deactivate`
— identical shape and role mapping to Customer's:

| Role | view | create | update | activate | deactivate |
|---|---|---|---|---|---|
| OWNER | ✓ | ✓ | ✓ | ✓ | ✓ |
| MANAGER | ✓ | ✓ | ✓ | ✓ | ✓ |
| SALESPERSON | ✓ | ✓ | ✓ | — | — |
| PLATFORM_ADMINISTRATOR | — | — | — | — | — |

`activate` is symmetric with `deactivate` for the same reasoning documented
in PROMPT-007-NOTES.md (leaving reactivation off both roles that can
deactivate would make deactivation effectively permanent).

Backfilled existing pre-PROMPT-008 tenants' roles via migration `0009`
(same pattern as `0007`/`0008`). Updated `tests/integration/test_rbac.py`'s
two permission-set assertions again to include the new `suppliers.*` codes.

## Database changes

- Migration `0009_supplier_master.py`: creates `supplier` (see Schema
  Assessment above), enables but does not force RLS with a
  `tenant_isolation_supplier` policy, seeds the 5 `suppliers.*` permissions
  and backfills `role_permission` for every pre-existing role.
- Indexes: `tenant_id`, `gstin`, `phone` (same rationale as Customer's).

## API

`GET/POST /suppliers`, `GET/PATCH /suppliers/{id}`,
`POST /suppliers/{id}/activate|deactivate` — identical shape to
`app/api/v1/customers.py`. No `DELETE`. List supports `search`
(name/code/gstin/phone), `status`, `state_code`, `gst_registered` filters,
standard pagination.

GSTIN/state cross-validation is identical to Customer's: auto-derive state
from the GSTIN's first two digits when omitted, reject a supplied state
that disagrees. Format checks in `app/schemas/supplier.py`; the
value-dependent cross-check lives in
`app/services/suppliers/supplier_service.py` (needs the current stored
value on PATCH).

## Security / concurrency

Tenant isolation, cross-tenant-lookup-is-404, optimistic concurrency
(`row_version` / 412), and audit logging
(`SUPPLIER_CREATED/UPDATED/ACTIVATED/DEACTIVATED` via the existing
`AuditService`) all follow the identical PROMPT-005/007 pattern.

27 new backend tests in `tests/integration/test_suppliers.py` mirror
`test_customers.py`'s coverage (tenant isolation, RBAC incl. the
Salesperson "Limited" boundary, GSTIN validation/duplicate/state-mismatch,
concurrency, cross-tenant 404 parity), plus an explicit assertion that
`credit_limit`/`region`/`gps_location` are absent from the API response
(guarding FR-SUPP-02 against regression). **Full suite: 171 backend tests
passing** (117 original + 27 customer + 27 supplier; the 2 RBAC
permission-set tests were updated in place, not added, both times).

## Frontend

- `api/suppliers.ts`, `components/SupplierManagement.tsx` — same
  single-file list/modal/detail/confirm shape as
  `components/CustomerManagement.tsx`, reusing `shared/gstStateCodes.ts`.
  The form deliberately has **no** Region/Beat field, no GPS-capture
  button, and no Credit Limit input — the Commercial Information section
  is just "Payment / Credit Terms (Days)".
- Sidebar: added a "Suppliers" sub-item under the (previously childless)
  "Purchase" menu, gated by `suppliers.view`. Because "Purchase" had no
  other sub-items yet, `subItems` is set to `undefined` (not `[]`) when the
  permission is absent — an empty array is still truthy in the sidebar's
  `!!item.subItems` check and would render a dropdown arrow with nothing
  under it.
- Verified live end-to-end in-browser: login (fresh, to pick up the new
  `suppliers.*` claims — the existing single-60-minute-token/no-refresh
  architecture means a session started before this migration won't see the
  new permissions until its next login, the same documented staleness
  window PROMPT-006 already established) → Purchase → Suppliers nav →
  create (`SUPP-0001` allocated) → list → detail view → GSTIN `27...`
  correctly displayed state "Maharashtra" → confirmed no
  credit-limit/region/GPS fields anywhere in the create form.
- No dedicated frontend component test added, consistent with the
  established precedent (`UserManagement.tsx`/`CustomerManagement.tsx`
  have none either — the 15 frontend tests cover shared infrastructure).

## Open decisions carried forward (not silently resolved)

1. **`supplier_code` generation**: system-generated, tenant-scoped
   sequential (`SUPP-0001`, …) — same unresolved-upstream judgment call as
   `customer_code` in PROMPT-007.
2. **GSTIN uniqueness**: application-layer only (no duplicate *active*
   GSTIN per tenant), not a DB constraint — same as Customer.
3. **Phone uniqueness**: intentionally unenforced — same as Customer/User.
4. **Bank information (§61 Q16-20)**: entirely out of this
   implementation. Blocked on **ERD-DEC-04** (BankAccount master not fully
   specified upstream) — this is the FRD's own open item, not something
   PROMPT-008 introduces or resolves. Implementing bank fields now would
   mean inventing the exact entity ERD-DEC-04 says isn't ready yet.
5. **Opening balance**: `balance` exists in the approved schema but has no
   write path in this module — deferred entirely to the future
   Payments/Accounting module (mirrors PROMPT-007's decision #5).
6. **Historical-transaction snapshot principle** (§21): no transaction
   tables reference `supplier` yet (out of scope here) — same guidance as
   PROMPT-007-NOTES.md's #6, now applying to the future Purchase module:
   it must snapshot supplier name/GSTIN/address at transaction time rather
   than live-joining `supplier`.
7. **Can an inactive supplier be selected for a new purchase transaction?**
   (§61 Q27) — no Purchase module exists yet to enforce this; `status` is
   exposed for that future module to filter on.
