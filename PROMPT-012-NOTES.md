# PROMPT-012 — Sales Estimate Management: Design Record

## What was built

The first concrete Sales document type, built directly on top of
PROMPT-011's shared foundation (`gst_calculation_service`,
`document_numbering_service`, `sales_validation_service`,
`sales_constants`, `sales_common` schemas, `CustomerSelector`/
`ProductLineSelector`).

### 1. Schema (migration `0014_sales_estimate.py`)

Two new tables — named `sales_estimate`/`sales_estimate_line` (not bare
`estimate`/`estimate_line`) to avoid colliding with the English word in
future search/grep. Proposed schema additions beyond the approved Data
Dictionary's `estimate` table, documented per the established "propose,
document, implement" pattern:

- **Header**: `valid_until_date` (§10's validity-period requirement has no
  DD column), `customer_gstin`/`billing_address`/
  `place_of_supply_state_code` (transaction-time snapshots — the DD's
  `estimate` table has no customer-identity snapshot columns at all, and
  the snapshot principle established in PROMPT-007-010 requires one so a
  later Customer edit can't silently rewrite a historical document),
  `cgst_total`/`sgst_total`/`igst_total` (the DD only has a generic
  `tax_total`; GST invoicing needs the CGST/SGST/IGST split shown on the
  document itself), `notes`, `converted_at`.
- **Line**: `hsn_code` (snapshot, same rationale as customer snapshot
  fields — a Product's HSN can change after the estimate is issued).
  `cess_amount` exists per the DD but is always `0` — no cess rate source
  exists anywhere in the system (same gap PROMPT-011 already flagged).
- Status CHECK constraint: `DRAFT, SENT, ACCEPTED, REJECTED, EXPIRED,
  CANCELLED, CONVERTED`. Unique constraints:
  `(tenant_id, estimate_number)` and `(estimate_id, line_no)`.
- Seeds `sales_estimate.*` permissions (view/create/edit/send/accept/
  reject/cancel/convert) and backfills existing roles — see RBAC below.

### 2. Status lifecycle

```
DRAFT --send--> SENT --accept--> ACCEPTED --convert--> CONVERTED
  |                |                  |
  +--cancel--------+--reject----------+
                   |
                 (lazy expiry, any status in {DRAFT,SENT,ACCEPTED} with
                  valid_until_date < today, flips to EXPIRED on next read)
```

`REJECTED`/`EXPIRED`/`CANCELLED`/`CONVERTED` are terminal
(`TERMINAL_STATUSES`); `DRAFT`/`SENT`/`ACCEPTED` are convertible
(`CONVERTIBLE_STATUSES`). Editing lines is DRAFT-only.

**Expiry approach**: lazy ("approach C") — no scheduled job. Every read
(`GET` detail, `GET` list) and every state-changing action first checks
`valid_until_date` against today and flips the status to `EXPIRED` (with
an audit entry) before proceeding, persisting the flip on that same
request. This was a documented open decision (§16 of the prompt) with no
approved source mandating a background job; a lazy check keeps this
prompt's scope backend-only with no new infrastructure (schedulers,
cron) that doesn't exist anywhere else in this codebase yet.

### 3. Conversion to Sales Order — boundary/interface only

`convert_to_sales_order` marks `status=CONVERTED` + `converted_at` and
returns a `ConversionResult` with `sales_order_id: null` and an
explanatory `message`. **No real Sales Order row is created** — that
table doesn't exist yet (PROMPT-013's scope, per the same "one document
type per prompt" pattern PROMPT-011 established). This mirrors
PROMPT-011's own resolution of an identical tension: the prompt asks for
"conversion to Sales Order" as part of Estimate's lifecycle, but building
a real Sales Order table/workflow here would be exactly the "next
document type automatically" the Stop Condition forbids. The frontend
surfaces this honestly — the confirmation dialog and success state say
"Sales Order creation will be available in a future release" rather than
implying a document was actually created.

### 4. Backend (`app/services/sales/estimate_service.py`, `app/api/v1/sales_estimates.py`)

Router prefixed `/sales/estimates`. `EstimateService` reuses
`sales_validation_service` for customer/product checks,
`gst_calculation_service` for line/document totals (client-submitted
totals are always ignored — server recalculates, per PROMPT-011's §60
principle, verified by a dedicated
`test_client_total_tampering_ignored` test), and
`DocumentNumberingService` for `EST-{FY}-{seq:04d}` numbers. Every
mutating endpoint uses `row_version`/`expected_row_version` optimistic
concurrency; `create`/`convert-to-sales-order` require an
`Idempotency-Key` header (the existing PROMPT-002/010 mechanism, reused
— not reinvented).

**Two real bugs found and fixed while testing:**

1. `convert_to_sales_order` raised `ValidationAppError` (422) for the
   "already converted" case instead of `ConflictError` (409) — every
   other "duplicate/already-done" error in this codebase (`CUST-002`,
   `SUPP-002`, `PROD-002`, `INV-004`) uses 409. Fixed by importing and
   raising `ConflictError`, with `EST-003` as the associated code.
2. A test (`test_duplicate_conversion_rejected`) had broken logic —
   `expected_row_version: converted["status"] and estimate["row_version"] + 1`
   — computing a nonsensical value via a stray boolean short-circuit.
   Fixed by fetching the estimate's real post-conversion `row_version`
   via `GET` before attempting the second (expected-409) conversion.

### 5. Frontend (`api/salesEstimates.ts`, `components/EstimateManagement.tsx`)

Follows the same list/create-modal/detail-modal/status-action pattern as
`CustomerManagement.tsx`/`SupplierManagement.tsx`/`ProductManagement.tsx`/
`InventoryManagement.tsx`, and is the **first screen to actually mount**
PROMPT-011's `shared/CustomerSelector.tsx` and
`shared/ProductLineSelector.tsx` — exactly the use case they were built
for. Wired into `Sidebar.tsx` under "Sales" (permission-gated by
`sales_estimate.view`, same UX-only-hiding pattern as every other module)
and `App.tsx` (`dashboardView === 'Estimates'`).

Status action buttons (Send/Accept/Reject/Cancel/Convert) are shown only
when the estimate's current status is in that action's allowed-from set
— mirroring `estimate_service.py`'s own `_ACTION_ALLOWED_FROM` map for
UX, while the backend remains the sole authority (identical pattern to
every prior module's `hasPermission()` hiding). Reject/Cancel/Convert
show a confirmation dialog first; Convert's dialog explicitly states the
action creates no real Sales Order yet.

**A real bug was found and fixed during live browser verification**:
`ProductLineSelector`'s `SalesLineDraft` always fills both
`discountPercent` and `discountAmount` with `'0'` as a default (so its
own live preview math always has values to work with). The estimate
create form was naively forwarding both as non-null to the API
(`discount_percent: l.discountPercent || null` — `'0'` is truthy as a
string, so this was never actually null), which the backend correctly
rejects with `422 VALIDATION_ERROR` ("Specify either discount_percent or
discount_amount, not both"). Fixed in `EstimateManagement.tsx`'s
`handleSave` by checking the *numeric* value of each field and only
forwarding whichever one is actually non-zero (never both). This is a
reusable component (`ProductLineSelector`) contract gap that the next
document-type prompt (Sales Order) should be aware of when it builds its
own create form against the same component.

## RBAC

`sales_estimate.view/create/edit/send/accept/reject/cancel/convert` added
to `app/core/permissions.py` and `ROLE_DEFAULT_PERMISSIONS`. OWNER and
MANAGER get all 8. SALESPERSON gets all except `.convert` — no approved
source resolves this distinction (per the FRD's Role×Module matrix
"Limited" language, same ambiguity as every prior module); it mirrors the
"Salesperson gets full day-to-day lifecycle except the single
higher-commitment action" pattern already used for
Customer/Supplier `.deactivate` — a Salesperson can create, send, and
even accept/reject/cancel an estimate, but converting it into a
higher-commitment downstream document is treated as a Manager/Owner-level
decision. This is an explicit judgment call, not a specified rule.

## Testing

- `backend/tests/integration/test_sales_estimates.py` (34 tests): create
  validation (customer/product not-found/inactive, non-positive quantity,
  negative price, both-discount-types, invalid validity date), GST
  calculation (intra-state CGST+SGST split, inter-state IGST, discount
  applied before GST), client-total-tampering ignored, tenant isolation,
  permission checks (Salesperson can create/send/accept/reject/cancel but
  not convert), DRAFT-only editing, invalid status transitions rejected,
  row-version conflict (412), lazy expiry (GET flips status, expired
  cannot convert), conversion (success, already-converted rejected with
  409, idempotent retry, concurrent attempts), audit log entries, list
  search/filter/pagination.
- `backend/tests/integration/test_rbac.py` updated: `sales_estimate.*`
  codes added to the Owner/Manager/Salesperson effective-permission-set
  assertions.
- **Full backend suite: 305 tests passing** (271 prior + 34 new).
- Frontend: no new Vitest files added (no existing test infra covers
  screen-level component behavior yet, consistent with prior modules);
  `npx tsc --noEmit` and `npx vitest run` both pass (15/15, unchanged) —
  the 3 pre-existing `shared/ErrorBoundary.tsx` type errors are unrelated
  to this prompt (untouched file, predates this session's PROMPT-012
  work).
- **Live browser verification** (this session): signed up a fresh tenant,
  created a product and a customer, created an estimate via
  `EstimateManagement.tsx` (confirmed the discount-field bug above during
  this step and fixed it), verified the GST breakdown (CGST ₹9.00 + SGST
  ₹9.00 on a ₹100 taxable / 18% intra-state line, ₹118.00 grand total),
  transitioned DRAFT→SENT, then converted to "Sales Order" and confirmed
  the terminal `CONVERTED` status with no further action buttons and the
  correct "future release" messaging in the confirmation dialog.

## Open decisions carried forward (not silently resolved)

1. **Exact Sales Order schema/behavior** — PROMPT-013's scope; this
   prompt's conversion boundary only records intent (`CONVERTED` +
   `converted_at`), not a real linked row.
2. **Whether an EXPIRED estimate should be resurrectable** (e.g. an
   Owner manually extending `valid_until_date` and reverting to DRAFT) —
   not implemented; EXPIRED is currently terminal like every other
   non-CONVERTED end state.
3. **Salesperson `.convert` exclusion** — an explicit judgment call (see
   RBAC section), not derived from an approved source; flag if a future
   prompt's requirements contradict it.
4. **`ProductLineSelector`'s always-populated discount fields** — the
   shared component itself was not changed (it's used correctly for its
   own live-preview purposes); the bug was in how the consuming form
   translated its output into an API payload. The next document-type
   screen reusing this component should apply the same
   "only forward the non-zero discount field" logic this prompt now
   uses in `EstimateManagement.tsx`, or `ProductLineSelector` itself
   should be changed once a second consumer exists to justify the
   refactor.
5. **Print/Preview UI** (§17 of the prompt) — not built. No approved
   template/layout source was supplied, and generating a print-ready
   document layout is a distinct, sizeable piece of scope; flagging
   rather than guessing at a layout.
