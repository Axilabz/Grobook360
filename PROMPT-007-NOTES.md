# PROMPT-007 — Customer Management: Design Record

## Conflict found — STOP and identify (per the global instruction)

The approved Database Design v3.0 `customer` table (Data Dictionary sheet)
defines only: `id, tenant_id, customer_code, name, gstin, state_code,
address, phone, credit_limit, payment_terms_days, balance, status` +
audit/row_version columns. The approved (if legacy) FRD requirement
**FR-CUST-01** ("Confirmed / legacy FRD") additionally requires an owner
name, optional email, region/beat, city, pin code and GPS location on the
same create/edit screen, and **FR-CUST-02** requires a browser-geolocation
"Use Current Location" action. Data Dictionary v3.0 simply predates that
legacy requirement being reconciled into it — the same class of gap
PROMPT-005 hit for `user.name` (migration `0006_user_name`).

**Resolved the same way PROMPT-005 did**: added the FR-CUST-01/02 fields as
a documented "proposed schema addition" (migration
`0008_customer_master`'s docstring has the full per-field reasoning) rather
than silently dropping the legacy requirement or silently inventing
something different from either source.

Also found: the FRD's own Role x Module matrix (Table 7) says Customers is
"Full/Full/Limited/No" for Owner/Manager/Salesperson/Platform Admin, and
**FR-CUST-07** spells "Limited" out precisely: *"Owner, Manager and
Salesperson may create/edit; Owner/Manager may deactivate."* This directly
answers most of §59's open-decision list (who can create/edit/deactivate) —
implemented verbatim, not re-decided.

## Existing Customer Schema Assessment (required by §57.2)

| Field (approved DD v3.0) | Kept as-is |
|---|---|
| id, tenant_id, customer_code, name, gstin, state_code, address, phone, credit_limit, payment_terms_days, balance, status, audit/row_version | Yes, unchanged |

| Field added (proposed, FR-CUST-01/02) | Reason |
|---|---|
| `owner_name` (NOT NULL) | FR-CUST-01 required field, no baseline column |
| `email` (nullable) | FR-CUST-01 "optional email" |
| `city`, `pincode` (nullable) | FR-CUST-01 required display fields; baseline only has a single freeform `address` |
| `region` (nullable) | FR-CUST-01 "region/beat" — field-sales territory tag |
| `gps_location` (nullable) | FR-CUST-02 "Use Current Location" browser geolocation |

**Deliberately NOT added**, and why:
- **No `customer_type` / B2B-B2C column.** FR-CUST-03 ("Confirmed") already
  defines GST-registration status as *derived* from whether `gstin` is
  blank — no approved source defines a separate classification column, and
  §60/§9 forbid inventing one. `is_valid_gstin`/blank-GSTIN is the sole
  signal used everywhere (list filter, form UX, audit).
- **No `country` column.** BR-001/ASM-002 in the FRD: M1 is one
  tenant = one business, one GSTIN, effectively India-only. Nothing
  approved needs a country field yet.
- **No separate billing/shipping address.** Data Dictionary v3.0 has
  exactly one `address` column; §27 explicitly forbids inventing a
  multi-address model the baseline doesn't support.
- **`customer_code` generation**: not specified as system- vs. user-generated
  by any approved source (§59 Q2-4). Implemented as **system-generated**
  (`CUST-0001`, tenant-scoped, sequential, savepoint-retry on collision) —
  the same class of judgment call as PROMPT-005's random-password/reset-link
  choice: safe default, explicitly flagged here as an **open decision** a
  business owner could later override with a user-entered scheme.
- **GSTIN uniqueness**: not enforced at the DB level (no such constraint in
  Data Dictionary v3.0), but enforced at the **application** level exactly
  per §24's own recommended text: *"GSTIN should not have duplicate active
  customer records within the same tenant."* `CUST-002` on violation.
- **Phone uniqueness**: intentionally **not** enforced (§59 Q7-8 left open,
  consistent with the project's existing ERD-DEC-02 precedent for
  `user.phone`) — multiple customers may legitimately share a phone (family
  business, shared owner).
- **`balance`**: created exactly as the Data Dictionary's cache column
  (default 0) but this module gives it **no write path** — it is never a
  create/update input. Mutating it is Payments/Accounting's job (§29); this
  module only ever reads/displays it and flags `is_over_credit_limit`
  (advisory only, per FR-CUST-06 which is explicitly "Should" with the
  hard-block question left open by OQ-009 — never used to block anything
  here).

## Permission model (FR-CUST-07 + Table 7, not re-decided)

`app/core/permissions.py`: `customers.view/create/update/activate/deactivate`.

| Role | view | create | update | activate | deactivate |
|---|---|---|---|---|---|
| OWNER | ✓ | ✓ | ✓ | ✓ | ✓ |
| MANAGER | ✓ | ✓ | ✓ | ✓ | ✓ |
| SALESPERSON | ✓ | ✓ | ✓ | — | — |
| PLATFORM_ADMINISTRATOR | — | — | — | — | — |

`activate` is granted symmetrically with `deactivate` (Owner/Manager only) —
FR-CUST-07 doesn't name reactivation separately, but leaving it off both
roles that can deactivate would make deactivation effectively permanent,
which nothing approved intends. Flagged here rather than silently assumed.

Backfilled existing pre-PROMPT-007 tenants' roles via migration `0008`
(same pattern as `0007_rbac_permissions`). Updated
`tests/integration/test_rbac.py`'s two "gets no/view-only permissions"
tests to include the new customers.* codes — those assertions were
correctly literal before this prompt and are now correctly literal again.

## Database changes

- Migration `0008_customer_master.py`: creates `customer` (see Schema
  Assessment above), enables but does not force RLS with a
  `tenant_isolation_customer` policy (matching migration `0001`'s documented
  ERD-DEC-01-open pattern), seeds the 5 `customers.*` permissions and
  backfills `role_permission` for every pre-existing role.
- Indexes: `tenant_id` (required), plus `gstin` and `phone` for the search
  path (§50).

## API

`GET/POST /customers`, `GET/PATCH /customers/{id}`,
`POST /customers/{id}/activate|deactivate` — same shape as
`app/api/v1/users.py`. No `DELETE` (§23: deactivate, not delete — no
approval to hard-delete). List supports `search` (name/code/gstin/phone),
`status`, `state_code`, `gst_registered` filters, and standard pagination
(page/page_size, capped at 100, mirroring `/users`).

GSTIN/state cross-validation: state is auto-derived from the GSTIN's first
two digits when omitted (FR-CUST-04), and rejected if it's supplied but
disagrees with the GSTIN. Format-only checks live in
`app/schemas/customer.py`; the value-dependent cross-check (which needs the
*current* stored value on PATCH) lives in
`app/services/customers/customer_service.py`.

## Security / concurrency

- Tenant isolation, cross-tenant-lookup-is-404 (not a distinguishable
  error), optimistic concurrency (`row_version` / 412), and audit logging
  (`CUSTOMER_CREATED/UPDATED/ACTIVATED/DEACTIVATED` via the existing
  `AuditService`) all follow the PROMPT-005 pattern exactly.
- 27 new backend tests in `tests/integration/test_customers.py` cover the
  security-critical subset of §52/§53 (tenant isolation, RBAC incl. the
  Salesperson "Limited" boundary, GSTIN validation/duplicate/state-mismatch,
  concurrency, cross-tenant 404 parity). Full suite: **168 backend tests
  passing** (117 prior + 27 new + 24 updated-expectation RBAC tests still
  passing).

## Frontend

- `api/customers.ts` (mirrors `api/users.ts`), `shared/gstStateCodes.ts`
  (the public, official 2-digit GST state code list — display/selection
  data, not a business decision), `components/CustomerManagement.tsx`
  (single-file list + sectioned add/edit modal + detail modal + confirm
  dialog, mirroring `components/UserManagement.tsx`'s established shape).
- **Replaced** `components/AddCustomer.tsx` and `components/ViewCustomer.tsx`
  — the original AI-Studio-scaffold mock screens (dummy in-memory data, a
  hardcoded "Grocery Shop/Individual/…" customer-type dropdown never backed
  by any schema, and a client-side GSTIN lookup that shipped an API key and
  routed through three public CORS-proxy services). None of that scaffold
  was wired to any backend and it predates this prompt; it's deleted rather
  than left dead. Its one genuinely-approved idea (FR-CUST-02's "Use Current
  Location" browser geolocation button) is preserved in the new form.
- Sidebar: "Add Customer"/"View Customer" sub-items replaced with one
  permission-gated "Customers" entry (`customers.view`), consistent with
  how "Users" is gated. Frontend visibility is UX only — the backend
  independently re-checks every call.
- Verified live end-to-end in-browser: sign-up → login → Customers nav
  (correctly hidden/shown by permission) → create (`CUST-0001` allocated) →
  list/search/detail/edit → GSTIN entry auto-derives and displays the
  correct state ("33" → "Tamil Nadu") → desktop table renders correctly.
  Mobile-viewport visual confirmation was blocked by an environment
  rendering limitation in this session (the preview pane could not draw
  while backgrounded); the mobile/tablet CSS reuses the exact
  `hidden md:block` / `md:hidden` pattern already shipped and working in
  `UserManagement.tsx`, not a new responsive mechanism.
- No dedicated frontend component test was added for
  `CustomerManagement.tsx` — there is no existing per-screen component test
  for `UserManagement.tsx` either (the 15 frontend tests cover shared
  infrastructure: `ErrorBoundary`, `ForgotPassword`, contexts). Matching
  existing test-scope precedent rather than inventing new test
  infrastructure disproportionate to it.

## Open decisions carried forward (not silently resolved)

1. **`customer_code` generation**: system-generated, tenant-scoped
   sequential (`CUST-0001`, …). No approved source specifies this either
   way — flagged for eventual product sign-off.
2. **GSTIN uniqueness**: enforced at the application layer (no duplicate
   *active* GSTIN per tenant) per §24's own recommended default, not a DB
   constraint. Revisit if a business case needs multiple active customers
   sharing one GSTIN (e.g. multiple branches billed as one legal entity).
3. **Phone uniqueness**: intentionally unenforced, consistent with
   ERD-DEC-02's still-open status for `user.phone`.
4. **Credit-limit hard-block vs. advisory**: OQ-009 remains open in the FRD
   itself. This prompt implements advisory-only (`is_over_credit_limit`
   flag); hard-blocking is Sales module's decision to make, not Customer
   Management's.
5. **Opening balance**: `balance` exists in the approved schema but has no
   write path in this module — mutating it is deferred entirely to the
   future Payments/Accounting module (§29).
6. **Historical-transaction snapshot principle** (§21): no transaction
   tables reference `customer` yet (out of scope here), so this can't be
   implemented in this prompt — flagged as **guidance for the future Sales
   prompt**: once Sales tables exist, they must snapshot customer
   name/GSTIN/address at transaction time rather than live-joining
   `customer`, so a later name edit here never rewrites historical
   documents.
