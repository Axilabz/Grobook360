# PROMPT-026 — GST Rule Engine & GST Reporting

## 1. Pre-implementation design summary

### 1.1 Requirement understanding
Build a single authoritative GST calculation/reporting layer used by every transactional module — no module may compute or report its own GST. This is explicitly a REPORTING/GOVERNANCE prompt on top of GST calculation, not a redesign of calculation itself.

### 1.2 Existing GST architecture analysis
`app/services/sales/gst_calculation_service.py` (PROMPT-011) already IS the one authoritative calculation engine — `calculate_line`/`calculate_document_totals`/`determine_gst_treatment` are already reused, unmodified, by every Sales AND Purchase document service (Sales Invoice, Sales Return, Credit/Debit Note, Purchase Invoice, Purchase Return, Sales/Purchase Order). AC-001/AC-002 were therefore already satisfied before this prompt began — verified by direct code reading, not assumed. What was missing was the REPORTING layer: `app/services/sales/gst_reporting_service.py` was a stub since PROMPT-015 that only wrote an audit-log JSON blob and returned an opaque `GSTTXN-<id>` string — no real `gst_transaction` table existed, and Purchase Invoice/Purchase Return had **no equivalent call at all** (zero Input GST/ITC tracking).

### 1.3 GST calculation flow (unchanged, confirmed correct)
Source document service → `gst_calculation_service.calculate_line()` per line (discount-before-GST, tax-exclusive price) → `determine_gst_treatment()` compares tenant state vs counterparty state → CGST+SGST (intra-state) or IGST (inter-state) → `calculate_document_totals()` sums to header totals. Server-side only; client-submitted tax values are never trusted (verified pre-existing behavior, TC-040).

### 1.4 GST rule matrix (posting-time classification)
| Source | Direction | Sign | Classification basis |
|---|---|---|---|
| Sales Invoice | OUTWARD | + | `sales_invoice.customer_type` (B2B iff GSTIN present at creation) |
| Sales Return | OUTWARD | − | GSTIN presence on the return's own snapshot |
| Credit Note | OUTWARD | − | GSTIN presence on the note's own snapshot |
| Debit Note | OUTWARD | + | GSTIN presence on the note's own snapshot |
| Purchase Invoice | INWARD | + | Supplier GSTIN presence |
| Purchase Return | INWARD | − | Supplier GSTIN presence |

Sign convention is the load-bearing design decision (§21 below) — it is what makes `SUM()` over a period give the correct net GST position with zero bucket-type special-casing in every query.

### 1.5 Sales/Purchase/Return GST flow (implementation)
Every posting/confirm flow that already produced a GST-relevant total now ALSO calls `GstReportingService`, immediately after (Sales side) or newly added alongside (Purchase side) the existing `AccountingPostingService` call:
- `sales_invoice_service.post_invoice` → `record_invoice_transaction` (unchanged call, now records a real row)
- `sales_return_service.confirm_return` → `record_return_transaction` (unchanged call)
- `credit_debit_note_service.post_note` → `record_credit_debit_note_transaction` (unchanged call)
- `purchase_invoice_service.post_invoice` → `record_purchase_invoice_transaction` (**new**)
- `purchase_invoice_service.cancel_invoice` (POSTED branch) → `reverse_purchase_invoice_transaction` (**new**)
- `purchase_return_service.confirm_return` → `record_purchase_return_transaction` (**new**)
- `purchase_return_service.cancel_return` (CONFIRMED branch) → `reverse_purchase_return_transaction` (**new**)

### 1.6 GST snapshot design (§21/§22)
`gst_transaction`/`gst_transaction_line` mirror `journal_entry`/`journal_line`'s exact shape and discipline (PROMPT-025 precedent, reused deliberately): `(tenant_id, source_type, source_id, event_type)` unique constraint IS the idempotency guarantee; a REVERSAL is a brand-new row with negated amounts and `reversal_of_transaction_id` set; the ORIGINAL row is **never edited**. Every value is copied verbatim from the source document's own already-calculated columns — never recomputed.

### 1.7 Database impact
Migration `0027_gst_reporting.py`: 2 new tables (RLS-enabled, following migration 0021/0025/0026 precedent — new `gst.*` permissions backfilled onto every existing tenant's OWNER/MANAGER roles), plus `purchase_invoice.gst_transaction_reference`/`purchase_return.gst_transaction_reference` columns (mirroring the existing column on sales_invoice/sales_return/credit_debit_note).

### 1.8 API impact
New `/api/v1/gst/*` router — read/aggregate only (transactions, dashboard, GSTR-1, GSTR-3B, reconciliation, validate, export). Deliberately **no** `POST /gst/calculate` — §40's own instruction against letting arbitrary clients submit numbers for calculation was honored literally.

### 1.9 UI impact
New "GST Filing" screen (5 tabs: Dashboard/Transactions/GSTR-1/GSTR-3B/Reconciliation) under the sidebar's existing (previously unwired) "GST Filing" placeholder item.

### 1.10 Accounting integration impact
GST engine never creates journals (§25 honored — zero import of `JournalService`/`AccountingPostingService` from any GST file). Reconciliation reads `journal_line` joined through `account_mapping` by `posting_rule_code` to independently cross-check against `gst_transaction` totals for the same period.

### 1.11 E-Invoice integration impact
No change — `einvoice_service.py` already reads `sales_invoice`/`sales_invoice_line` columns directly (confirmed by code reading), which remain authoritative. Not rewired to read `gst_transaction` instead, since that would be a working-code change with no requirement forcing it; documented as a known limitation (§13 below).

### 1.12 GSTR-1/GSTR-3B data model
Computed on demand from `gst_transaction`/`gst_transaction_line` — no persisted, editable "GST Return" entity (§27's "not manually editable" honored structurally, not just by convention).

### 1.13 Validation framework
`app/services/gst/gst_validation_service.py` — pure GSTIN-format/HSN-format checks — wired into `GstrService.validate_gstr1`/`validate_gstr3b` (return-preparation time), deliberately **not** retrofitted into the 606-test-covered Sales/Purchase posting flows (see §12 Known Limitations for the full rationale).

### 1.14 Reconciliation approach
Period-scoped SUM comparison: `gst_transaction` totals (by direction) vs `journal_line` totals (by `OUTPUT_*`/`INPUT_*` posting_rule_code), both filtered to the same `return_period`.

### 1.15 Idempotency/Concurrency strategy
Identical to `JournalService` (PROMPT-025): check-before-insert plus `IntegrityError` catch-and-requery inside a SAVEPOINT, backstopped by the DB unique constraint.

### 1.16 Security/RBAC impact
New `gst.view`/`gst.prepare_returns`/`gst.export` — Owner/Manager only (mirrors Accounting's precedent; Salesperson gets none).

### 1.17 Audit impact
Restores the `GST_TRANSACTION_CREATED`/`GST_TRANSACTION_REVERSED` audit entries the old stub already wrote (scoped to the SOURCE entity's own `entity_type`/`entity_id`), now alongside a real `gst_transaction` row instead of only a JSON blob.

### 1.18 Open decisions
See §10 below — the full 24-item table from the prompt's own §54, none silently resolved.

---

## 2. Files created

**Backend:**
- `app/core/gst_constants.py`
- `app/models/gst_transaction.py`, `app/models/gst_transaction_line.py`
- `app/services/gst/__init__.py`, `app/services/gst/gst_validation_service.py`, `app/services/gst/gstr_service.py`
- `app/schemas/gst.py`
- `app/api/v1/gst.py`
- `migrations/versions/0027_gst_reporting.py`
- `backend/tests/integration/test_gst_reporting.py` (15 tests)

**Frontend:**
- `api/gst.ts`
- `components/GstManagement.tsx`

## 3. Files modified

- `app/services/sales/gst_reporting_service.py` — **rewritten**: same 3 method names/signatures (`record_invoice_transaction`/`record_return_transaction`/`record_credit_debit_note_transaction`), now creates real rows instead of an audit-only blob; 4 new methods for the Purchase side.
- `app/services/purchase/purchase_invoice_service.py` — wires `record_purchase_invoice_transaction` into `post_invoice`, `reverse_purchase_invoice_transaction` into `cancel_invoice`'s POSTED branch.
- `app/services/purchase/purchase_return_service.py` — same pattern for `confirm_return`/`cancel_return`.
- `app/models/purchase_invoice.py`, `app/models/purchase_return.py` — `gst_transaction_reference` column.
- `app/schemas/purchase.py`, `app/api/v1/purchase_invoices.py`, `app/api/v1/purchase_returns.py` — thread the new field through (model → schema → router, all three, to avoid PROMPT-025's own mid-prompt bug of forgetting the schema/router layer).
- `app/core/permissions.py` — `gst.view`/`gst.prepare_returns`/`gst.export`, added to OWNER/MANAGER.
- `app/core/error_codes.py` — `GST-001` through `GST-010`.
- `app/api/v1/__init__.py` — registers the new `gst` router.
- `backend/tests/integration/test_rbac.py` — 2 permission-enumeration tests updated with the 3 new `gst.*` codes.
- `components/Sidebar.tsx` — "GST Filing" item gated by `gst.view` (was an unwired placeholder since before this session).
- `App.tsx` — renders `GstManagement`.

## 4. Database migrations

`0027_gst_reporting` (down_revision `0026_accounting_engine`): `gst_transaction` (17 columns + audit/row-version mixin), `gst_transaction_line` (12 columns), both RLS-enabled; `purchase_invoice.gst_transaction_reference`/`purchase_return.gst_transaction_reference`; 3 new permission codes backfilled onto every existing tenant's OWNER/MANAGER roles. Applied successfully (`alembic upgrade head`).

## 5. APIs created

All under `/api/v1/gst`, `gst.view`-gated unless noted:
- `GET /transactions` (filters: return_period, source_type, classification, party_gstin, direction; paginated)
- `GET /transactions/{id}`
- `GET /dashboard?return_period=YYYY-MM`
- `GET /returns/gstr1?return_period=YYYY-MM`
- `POST /returns/gstr1/validate?return_period=YYYY-MM` (`gst.prepare_returns`)
- `GET /returns/gstr3b?return_period=YYYY-MM`
- `POST /returns/gstr3b/validate?return_period=YYYY-MM` (`gst.prepare_returns`)
- `GET /reconciliation?return_period=YYYY-MM`
- `GET /returns/gstr1/export`, `GET /returns/gstr3b/export` (`gst.export`, JSON only — see §12)

## 6. GST posting rules (matrix)

See §1.4 above.

## 7. Account mappings

Unchanged — the GST engine reads (never writes) `journal_line`/`account_mapping` for reconciliation only; it does not itself post to any account.

## 8. Journal / GST transaction examples

**Sales Invoice** `INV-2026-27-0001`, ₹10,000 taxable, 18% intra-state → `gst_transaction`: direction=OUTWARD, classification=B2B, taxable_value=10000, cgst=900, sgst=900, igst=0, total_gst=1800, total_amount=11800.

**Sales Return** against the above, ₹2,000 of the original taxable value → `gst_transaction`: direction=OUTWARD, taxable_value=**-2000**, cgst=**-180**, sgst=**-180**, total_amount=**-2360**.

**Purchase Invoice** `PINV-2026-27-0001`, ₹5,000 taxable, 18% intra-state → `gst_transaction`: direction=INWARD, taxable_value=5000, cgst=450, sgst=450, total_gst=900.

**Purchase Invoice cancellation** (POSTED→CANCELLED) → a second `gst_transaction` row, `event_type=REVERSAL`, taxable_value=**-5000**, cgst=**-450**, sgst=**-450**, `reversal_of_transaction_id` set to the ORIGINAL row's id — the ORIGINAL row itself is untouched (verified by `test_purchase_invoice_cancellation_reverses_gst_transaction`).

## 9. GSTR-1 / GSTR-3B sample output

**GSTR-1** (`GET /gst/returns/gstr1?return_period=2026-09`):
```json
{
  "return_period": "2026-09",
  "b2b": {"count": 1, "totals": {"taxable_value": "10000.00", "cgst": "900.00", "sgst": "900.00", "igst": "0.00", "cess": "0.00", "total_gst": "1800.00"}, "transactions": [...]},
  "b2c": {"count": 0, "totals": {...zero...}, "transactions": []},
  "credit_notes": {"count": 0, ...},
  "debit_notes": {"count": 0, ...},
  "hsn_summary": [{"hsn_code": "12345678", "taxable_value": "10000.00", "cgst": "900.00", "sgst": "900.00", "igst": "0.00", "cess": "0.00", "quantity": "10.000"}]
}
```

**GSTR-3B** (`GET /gst/returns/gstr3b?return_period=2026-09`):
```json
{
  "return_period": "2026-09",
  "outward_taxable_supplies": {"taxable_value": "10000.00", "cgst": "900.00", "sgst": "900.00", "igst": "0.00", "cess": "0.00", "total_gst": "1800.00"},
  "output_cgst": "900.00", "output_sgst": "900.00", "output_igst": "0.00",
  "inward_supplies": {"taxable_value": "5000.00", "cgst": "450.00", "sgst": "450.00", "igst": "0.00", "cess": "0.00", "total_gst": "900.00"},
  "input_tax_credit_cgst": "450.00", "input_tax_credit_sgst": "450.00", "input_tax_credit_igst": "0.00",
  "net_gst_payable": "900.00"
}
```

## 10. Validation examples

- `test_validate_gstr1_detects_missing_hsn`: a B2C invoice line with no HSN → `WARNING GST-003`.
- `test_validate_gstr1_detects_missing_gstin_for_b2b`: a directly-inserted B2B `gst_transaction` with no GSTIN → `ERROR GST-001`.

## 11. Reconciliation results

`test_reconciliation_shows_zero_difference`: posting one Sales Invoice and querying `/gst/reconciliation` for its period returns `output_gst_difference: "0.00"` — GST engine and Accounting totals agree exactly (AC-020/TC-030).

## 12. Test cases and results

**New file** `backend/tests/integration/test_gst_reporting.py` — 15 tests, covering (mapped to the prompt's own §52 numbering): TC-011/012 (Sales/Purchase Invoice snapshot creation, B2B+B2C), TC-013 (Sales Return reversal sign), TC-014 (Purchase Invoice cancellation reverses GST, original immutable), TC-015 (Credit Note adjustment), TC-017 (historical snapshot immutable after a product GST-rate change), TC-018/TC-030 (accounting = engine reconciliation), TC-020/TC-021 (GSTR-1/GSTR-3B dataset generation), TC-024 (missing-HSN detection), TC-024/GST-001 (missing-GSTIN detection, direct-insert scenario), TC-031 (idempotent recording — no duplicate row), TC-032 (tenant isolation), TC-033 (RBAC — Salesperson denied).

**Result: 15/15 passed** on the final run (after fixing a `date >= character varying` type-mismatch bug in the reconciliation query's period-boundary comparison, caught by `test_reconciliation_shows_zero_difference` itself).

**Regression found and fixed during verification** (same class of bug PROMPT-025 hit): my rewrite of `gst_reporting_service.py` initially dropped the `GST_TRANSACTION_CREATED` audit-log entry the old stub had written under the SOURCE entity's own `entity_type`/`entity_id` — 3 pre-existing tests (`test_sales_invoices.py::test_audit_and_integration_boundaries`, `test_sales_returns.py::test_audit_generation`, `test_credit_debit_notes.py::test_audit_generation`) asserted on it. Restored via a `_SOURCE_ENTITY_TYPE` mapping and an `AuditService.record()` call inside `GstReportingService._record()`, mirroring `AccountingPostingService`'s identical fix from the previous prompt.

**Full regression suite**: `test_rbac.py` (updated for 3 new permission codes), `test_sales_invoices.py`, `test_sales_returns.py`, `test_credit_debit_notes.py`, `test_purchase_invoice_management.py`, `test_purchase_return_management.py`, `test_purchase_foundation.py`, `test_accounting.py` all re-run — **zero regressions** after the audit-trail fix. Frontend: `npx vitest run` — 15/15 passed, zero regressions. `npx tsc --noEmit` clean except the pre-existing, unrelated `shared/ErrorBoundary.tsx` errors (present since before this session).

## 13. Known limitations

- **E-Invoice (`einvoice_service.py`) still reads `sales_invoice` columns directly, not `gst_transaction`** — both are authoritative and consistent (the GST engine only ever copies the invoice's own values verbatim), but they are two independent read paths rather than one. Rewiring e-Invoice to read from `gst_transaction` instead was judged out of scope without a requirement forcing it — flagged, not silently left inconsistent.
- **GSTIN/HSN validation is NOT a hard gate on Sales/Purchase document posting** — it runs only at GSTR-1/GSTR-3B preparation time (`validate_gstr1`/`validate_gstr3b`). This was a deliberate risk-management decision: retrofitting a newly-invented strict format check into the 606-test-covered posting flows of 6 different document services risked breaking existing behavior with no approved requirement demanding the stricter gate. See `app/services/gst/gst_validation_service.py`'s own module docstring.
- **No CSV/Excel export, no statutory-schema-conformant file** — `/gst/returns/gstr1/export` and `/gstr3b/export` return the same JSON dataset as the view endpoints (§39 itself lists JSON as an acceptable minimum format). Not claimed to be GST-portal-ready.
- **No persisted GST Return entity / no DRAFT→VALIDATED→READY_FOR_SUBMISSION→SUBMITTED lifecycle** — every value is computed fresh on every request from `gst_transaction`; `validate_*` returns issues without persisting a "validated" flag anywhere. No portal submission exists (OD-010/OD-011 stay open, per §31's own explicit instruction not to fabricate a submission state).
- **Cess is always 0** — `gst_calculation_service.calculate_line` never computes it (pre-existing, unchanged); `gst_transaction(_line).cess_amount` columns exist and are wired through but always receive 0.
- **No live GSTIN verification** — `is_valid_gstin_format` is a structural regex/format check only (OD-004, mirrors PROMPT-002's own identical open decision for sign-up's GSTIN field).
- **HSN Summary in GSTR-1 groups by exact `hsn_code` string only** — no HSN hierarchy/rollup (e.g. 6-digit vs 8-digit codes for the same product family are treated as distinct rows).

## 14. Open decisions (from the prompt's own §54 — none silently resolved)

| # | Decision | Status |
|---|---|---|
| OD-001 | Exact GST rate master structure | Unresolved — `product.gst_rate` remains a plain field (PROMPT-009's own open decision, unchanged) |
| OD-002 | GST rate effective-date/versioning | Unresolved — snapshots are immutable per-document (§21 solved for the REPORTING side), but no rate-history table exists |
| OD-003 | Exact HSN master source | Unresolved — `product.hsn_code` remains free text, no HSN master table |
| OD-004 | Live GSTIN verification provider | Unresolved — format-only validation, no provider abstraction wired to a real service |
| OD-005 | Exact place-of-supply rules for M1 | Unresolved — still a straight tenant-state-vs-counterparty-state comparison (PROMPT-011's own open decision, unchanged) |
| OD-006 | Exempt/nil-rated/zero-rated/non-GST classification scope | Unresolved — every transaction is implicitly "taxable"; no other classification exists |
| OD-007 | Exact B2C reporting classifications | Unresolved — only a flat B2B/B2C split, no B2C-large/B2C-small threshold split |
| OD-008 | Exact GSTR-1 statutory schema/version | Unresolved — this prompt's own dataset shape, not validated against any real NIC schema |
| OD-009 | Exact GSTR-3B statutory schema/version | Unresolved — same as OD-008 |
| OD-010 | Direct GST portal submission in M1 | Resolved: **not implemented** — no submission endpoint exists |
| OD-011 | GST return filing API/provider | Unresolved — no provider exists (consistent with OD-010) |
| OD-012 | GST return frequency | Resolved for M1: monthly only (`return_period` = "YYYY-MM") |
| OD-013 | Exact GST rounding policy | Unresolved — reuses `gst_calculation_service`'s existing `ROUND_HALF_UP` at 2dp (PROMPT-011's own open decision, unchanged) |
| OD-014 | Credit Note GST treatment | Resolved for M1: mirrors Sales Return (negative/reduction), matches PROMPT-017's own prior resolution |
| OD-015 | Debit Note GST treatment | Unresolved as a confirmed rule — implemented as the conservative mirror-opposite of Credit Note (positive), same judgment call PROMPT-017/025 already made, carried forward unchanged |
| OD-016 | Purchase Return GST treatment | Resolved for M1: mirrors Sales Return one level down the chain (negative/reduction of Input GST) |
| OD-017 | Whether reconciliation is mandatory before return finalization | Unresolved — reconciliation is available but not enforced as a gate on `validate_gstr1`/`validate_gstr3b` |
| OD-018 | Whether GST reports include draft transactions | Resolved for M1: **no** — `gst_transaction` rows are only ever created at POST/CONFIRM time, never for DRAFT documents |
| OD-019 | Treatment of cancelled invoices in GST reports | Resolved for M1: a POSTED-then-cancelled Purchase Invoice/Return produces a REVERSAL row that nets its own ORIGINAL to zero in period aggregation; a cancelled DRAFT never had a `gst_transaction` row to begin with |
| OD-020 | Treatment of E-Invoice cancellation in GST reporting | Unresolved — `EInvoiceService`'s own cancellation flow does not currently call into `GstReportingService` at all (Sales Invoice itself has no POSTED-cancellation path yet, per existing open decisions) |
| OD-021 | Tax rate source synchronization frequency | Not applicable — no external rate source exists |
| OD-022 | Manual GST override policy | Resolved for M1: **no override exists** — every value is server-derived, never client-editable (AC verified by TC-040-style existing invariants) |
| OD-023 | GST override approval workflow | Not applicable (no override exists, per OD-022) |
| OD-024 | Whether GST can be recalculated after document creation but before posting | Unchanged from pre-existing behavior — DRAFT documents can be edited (re-triggering `gst_calculation_service`) up until POST/CONFIRM; no `gst_transaction` row exists until then |

## 15. Definition of Done status

| # | Item | Status |
|---|---|---|
| 1-9 | GST Rule Engine, common calc service, Sales/Purchase reuse, CGST/SGST/IGST, discount-before-GST, GSTIN/HSN validation | **Met** (calc engine pre-existing and confirmed shared; validation exists at return-prep time — see §13 for the posting-time-gate scope decision) |
| 10-11 | GST snapshot, historical immutability | **Met** — verified by `test_gst_snapshot_immutable_after_product_rate_change` |
| 12-14 | Sales/Purchase Return reversal, Credit/Debit Note integration | **Met** |
| 15-16 | Accounting integration, E-Invoice integration boundary | **Met** (Accounting: reconciliation cross-check; E-Invoice: unchanged, still reads the same authoritative invoice columns — see §13) |
| 17-20 | GSTR-1/GSTR-3B preparation, validation, reconciliation | **Met** |
| 21-22 | Idempotency, concurrency | **Met** — mirrors `JournalService`'s proven pattern |
| 23-25 | Tenant isolation, RBAC, audit | **Met** — verified by dedicated tests |
| 26-28 | API/DB/UI documentation | **Met** (this document + inline docstrings + `CLAUDE.md`) |
| 29 | Automated tests pass | **Met** — 15/15 new, full regression suite re-run clean |
| 30-32 | Desktop/Tablet/Mobile UI | **Built** (Tailwind responsive classes, same card/table pattern as `AccountingManagement.tsx`) but **not independently browser-verified** in this session — flagged, not claimed as tested |
| 33 | No critical defects remain | **Met** to the best of this session's verification (one real regression was found and fixed — see §12) |
| 34 | Open decisions documented | **Met** — §14 above |
| 35 | Ready for downstream GST return/integration work | **Met** |

---

Per the prompt's own explicit stop condition: **PROMPT-026 is complete. Not proceeding to PROMPT-027 without further instruction.**
