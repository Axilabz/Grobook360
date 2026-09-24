# PROMPT-027 — Reports, Dashboards & Financial Statements

## 1. Pre-implementation design summary

### 1.1 Requirement understanding
Build a centralized, READ-ONLY reporting layer over every authoritative module built so far (Sales, Purchase, Inventory/Stock Ledger, Payments, Accounting Journals, GST, Customers, Suppliers, Products) — a Management Dashboard, 5 Sales reports, 5 Purchase reports, 3 Inventory reports, Receivables/Payables, 3 Payment reports, and the four core financial statements (General Ledger, Trial Balance, P&L, Balance Sheet), plus GST reporting views that delegate to (never duplicate) PROMPT-026's own GST engine.

### 1.2 Reporting architecture
`BUSINESS TRANSACTION → AUTHORITATIVE MODULE → ACCOUNTING/GST/STOCK LEDGER → REPORTING LAYER → REPORT/DASHBOARD` (§2's own diagram, honored literally). No new business tables were created — every report is a SQL aggregation over already-existing, already-authoritative tables (`sales_invoice`, `purchase_invoice`, `sales_return`, `purchase_return`, `credit_debit_note`, `stock_ledger_entry`, `payment`/`payment_allocation`, `journal_entry`/`journal_line`, `chart_of_account`, `gst_transaction`). New code lives entirely under `app/services/reports/` (7 new service modules) plus one router (`app/api/v1/reports.py`).

### 1.3 Report catalogue
Dashboard (1) · Sales: Summary, Invoice Register, Customer-wise, Product-wise, Returns (5) · Purchase: Summary, Invoice Register, Supplier-wise, Product-wise, Returns (5) · Inventory: Current Stock, Stock Movements, Product Stock History (3) · Receivables, Payables (2) · Payments: Register, Method Summary, Cheque Report (3) · Accounting: General Ledger, Trial Balance, P&L, Balance Sheet (4) · GST: Summary, Transactions, HSN Summary (3, all thin delegations to `GstrService`). **26 report endpoints total.**

### 1.4 Dashboard KPI catalogue
Net Sales/Net Purchase (period-scoped), Receivables/Payables Total Outstanding (all-time snapshot), Output/Input/Net GST (current return period), Low Stock Item count, Customer Collections/Supplier Payments (period-scoped). **Inventory Value is deliberately NOT shown** (§8/OD-002/OD-003 — no inventory valuation method is approved).

### 1.5 Metric definitions (see also inline docstrings in each service file)
- **Net Sales** = Taxable Sales (POSTED invoices) − Sales Returns (CONFIRMED) − Credit Notes (POSTED) + Debit Notes (POSTED) — §56 OD-010 resolved for M1.
- **Net Purchase** = Taxable Purchase (POSTED invoices) − Purchase Returns (CONFIRMED) — §56 OD-011 resolved for M1 (no Purchase-side Credit/Debit Note exists in this codebase).
- **Outstanding** (Receivables/Payables) = `invoice.grand_total − invoice.paid_amount`, computed directly on the invoice — not `customer.balance`/`supplier.balance` (separate reconciliation caches, not used as the report's source of truth, per §2's "one source of truth" principle applied one level down).
- **Trial Balance closing balance** = `debit_total − credit_total` for debit-normal accounts (ASSET/EXPENSE/COGS), the negation for credit-normal accounts (LIABILITY/EQUITY/REVENUE) — standard double-entry convention, not a judgment call.
- **Balance Sheet "Current Period Earnings"** = the SAME Net Profit the P&L computes, from the SAME posted journal lines — not a plug. `Assets = Liabilities + Equity + Net Profit` is a mathematical identity of double-entry bookkeeping (Trial Balance's own debit=credit guarantee, rearranged), not an empirical check that could reasonably fail absent an actual bug.

### 1.6-1.15 Calculation specifications
See each service file's own module docstring for the full spec (Definition/Source/Formula/Date Basis) per report family: `sales_report_service.py`, `purchase_report_service.py`, `inventory_report_service.py`, `receivables_payables_service.py`, `payment_report_service.py`, `accounting_report_service.py`, `dashboard_service.py`.

### 1.16 GST reporting specification
`/reports/gst/*` are thin pass-throughs to `app.services.gst.gstr_service.GstrService` (PROMPT-026) — zero GST calculation logic duplicated (§39 honored literally).

### 1.17 Source-of-truth mapping
Sales/Purchase reports → `sales_invoice`/`purchase_invoice`/`sales_return`/`purchase_return`/`credit_debit_note` (status-filtered). Inventory reports → `stock_ledger_entry` (never Sales/Purchase tables — §25). Receivables/Payables → invoice `paid_amount`/`grand_total`. Payments → `payment`. Accounting → `journal_line`/`journal_entry` (POSTED only). GST → `gst_transaction` via the existing `GstrService`.

### 1.18 Date basis per report
Sales/Purchase reports: the document's own date (`invoice_date`/`document_date`/`return_date`/`note_date` — §4, no separate posting_date column exists on these tables since POST happens synchronously). Accounting reports (GL/TB/P&L/BS): `journal_entry.posting_date` (§45's explicit mandate, not `created_at`). Payments: `payment_date`. Inventory: `occurred_at`. GST: `gst_transaction.return_period` (monthly, unchanged from PROMPT-026).

### 1.19 Database/query impact
Zero new tables. Migration `0028_reports.py` adds ONLY the `reports.*` permission catalogue (13 codes) — no RLS needed (no new table). New indexed-column queries throughout; General Ledger's per-account balance query uses a pre-aggregated subquery (not a naive double outer-join — see `accounting_report_service.py`'s own code comment for the specific bug that approach would have caused).

### 1.20 API impact
New `/api/v1/reports/*` router, 26 endpoints, matching §48's own naming exactly.

### 1.21 UI impact
New `ReportsManagement.tsx` (9 top-level tabs, sub-tabs within Sales/Purchase/Inventory/Payments/Accounting) wired into the sidebar's pre-existing, previously-unwired "Reports" placeholder item.

### 1.22 Export strategy
**Not implemented in M1** (§46/OD-018/OD-019/OD-020) — every report already returns full, filtered JSON (consistent with PROMPT-026's own GST-export precedent: JSON is the only format this MVP has ever produced for any report-like data). A dedicated `reports.export` permission is defined and seeded for forward-compatibility, but no endpoint currently checks it — flagged as an explicit limitation, not a silent gap.

### 1.23 Performance strategy
Every list/register endpoint is paginated (`page`/`page_size`, capped at 200) and uses server-side `GROUP BY`/`SUM` aggregation — no report loads a full dataset into application memory. General Ledger/current-stock have no artificial cap since they're already scoped to one account/one tenant.

### 1.24 Reconciliation strategy
Dashboard KPIs call the IDENTICAL report-service method (same date range) the corresponding detailed report calls — reconciliation is structural (by construction), not a separate periodic check. Verified by dedicated tests (`test_dashboard_loads_and_reconciles_with_sales_report`, `test_dashboard_receivables_equals_receivables_report`).

### 1.25 Security/RBAC impact
13 new `reports.*` permissions (§51, matching the prompt's own suggested names almost 1:1). Owner/Manager get all 13. Salesperson gets 3 (`view_dashboard`/`view_sales`/`view_inventory`) — mirrors their existing Sales/Inventory view access; Receivables/Payables/Payments/GL/TB/P&L/BS/GST reports are Owner/Manager-only (§62 OD-022/OD-023/OD-024 resolved conservatively, mirroring Accounting/GST's own identical precedent).

### 1.26 Audit impact
**Not implemented** (§52) — report VIEWING is not audited (would be extremely high-volume, low-value logging for read-only GET requests with no established precedent anywhere else in this codebase for auditing reads). Export auditing is moot since export isn't implemented. Flagged as an explicit, deliberate scope decision, not an oversight.

### 1.27 Open decisions
See §14 below.

---

## 2. Files created

**Backend:**
- `app/services/reports/__init__.py`, `sales_report_service.py`, `purchase_report_service.py`, `inventory_report_service.py`, `receivables_payables_service.py`, `payment_report_service.py`, `accounting_report_service.py`, `dashboard_service.py`
- `app/api/v1/reports.py`
- `migrations/versions/0028_reports.py`
- `backend/tests/integration/test_reports.py` (32 tests)

**Frontend:**
- `api/reports.ts`
- `components/ReportsManagement.tsx`

## 3. Files modified

- `app/core/permissions.py` — 13 `reports.*` permissions; OWNER/MANAGER get all, SALESPERSON gets 3.
- `app/core/error_codes.py` — `REP-001` through `REP-010`.
- `app/api/v1/__init__.py` — registers the new `reports` router.
- `backend/tests/integration/test_rbac.py` — 3 permission-enumeration tests updated (2 OWNER/MANAGER-shape tests + 1 SALESPERSON exact-set test that needed its own 3-code addition, a spot the prior 2 prompts didn't need to touch since Salesperson got zero `accounting.*`/`gst.*` codes).
- `components/Sidebar.tsx` — "Reports" item (previously an unwired placeholder) gated by `reports.view_dashboard`/`reports.view_sales`.
- `App.tsx` — renders `ReportsManagement`.

## 4. Database/query changes

`0028_reports` (down_revision `0027_gst_reporting`) — permission-only migration, no new tables, no RLS (nothing to isolate — every query still enforces `tenant_id` from the session). Applied successfully.

## 5. APIs created

All under `/api/v1/reports`:
`GET /dashboard` · `GET /sales/{summary,invoices,customers,products,returns}` · `GET /purchase/{summary,invoices,suppliers,products,returns}` · `GET /inventory/{current-stock,movements,history}` · `GET /receivables` · `GET /payables` · `GET /payments`, `/payments/method-summary`, `/payments/cheques` · `GET /accounting/{general-ledger,trial-balance,profit-loss,balance-sheet}` · `GET /gst/{summary,transactions,hsn-summary}`.

## 6. Report catalogue

See §1.3.

## 7. Metric definitions

See §1.5.

## 8. Sample report outputs

**Sales Summary** (1 invoice, ₹10,000 taxable, 18% intra-state):
```json
{"gross_sales": "10000.00", "discount": "0.00", "taxable_sales": "10000.00", "cgst": "900.00", "sgst": "900.00", "total_gst": "1800.00", "invoice_total": "11800.00", "net_sales": "10000.00"}
```

**Receivables** (same invoice, unpaid):
```json
{"data": [{"invoice_number": "INV-2026-27-0001", "invoice_amount": "11800.00", "paid_amount": "0.00", "outstanding": "11800.00", "payment_status": "UNPAID"}], "summary": {"total_receivables": "11800.00", "unpaid_count": 1}}
```

## 9. Dashboard KPI examples

```json
{"period": {"date_from": "2026-10-01", "date_to": "2026-10-09"}, "sales": {"net_sales": "10000.00"}, "receivables": {"total_outstanding": "11800.00"}, "inventory": {"low_stock_item_count": 0, "inventory_value": null}, "gst": {"return_period": "2026-10", "output_gst": "1800.00"}}
```

## 10. Financial statement examples

**Trial Balance** (after 1 Sales Invoice + 1 Purchase Invoice): every account listed with its natural debit/credit balance; `is_balanced: true`, `total_debit == total_credit` — verified by `test_trial_balance_balances`.

**Balance Sheet**: `total_assets == total_liabilities + total_equity` (where `total_equity` includes the unclosed "Current Period Earnings" line) — `is_balanced: true`, `difference: "0.00"` — verified by `test_balance_sheet_balances`.

## 11. Reconciliation results

- Dashboard Net Sales ↔ Sales Summary Net Sales: equal (`test_dashboard_loads_and_reconciles_with_sales_report`).
- Dashboard Receivables ↔ Receivables Report total: equal (`test_dashboard_receivables_equals_receivables_report`).
- Report GST Summary ↔ GST module's own dashboard: equal (`test_gst_summary_reconciles_with_gst_module`).
- Trial Balance: total debit = total credit (always, by double-entry construction, verified not assumed).
- Balance Sheet: Assets = Liabilities + Equity (always, by the same construction).

## 12. Test cases and results

**New file** `backend/tests/integration/test_reports.py` — 32 tests covering dashboard load+reconciliation (TC-001/002/003/047), Sales Summary/Register/Customer-wise/Product-wise/Returns (TC-004-009), Purchase Summary/Register/Supplier-wise/Product-wise/Returns (TC-010-014), Current Stock + Stock Movement traceability (TC-015/016), Receivables with full/partial payment (TC-017/018/019), Payables (TC-020), Payment Register/Method Summary/Cheque Report (TC-021/022/023), General Ledger/Trial Balance (TC-024/025), P&L/Balance Sheet (TC-027/028), GST reconciliation (TC-030), invalid/valid date-range filtering (TC-034), tenant isolation (TC-036), RBAC allow+deny (TC-037), pagination (TC-040).

**Result: 32/32 passed** on the first full run (no bugs found in this pass — all field-name/join assumptions verified correct against the actual schema before writing code).

## 13. Known limitations

- **Export (Excel/CSV/PDF) is not implemented** — every report returns JSON only; `reports.export` permission exists but is unused by any endpoint (§46/OD-018/OD-019/OD-020).
- **No ageing/overdue calculation anywhere** — `due_date` is opportunistically derived from `customer.payment_terms_days`/`supplier.credit_terms_days`/`purchase_invoice.due_date` where those already exist, but no "OVERDUE" status or ageing bucket is computed (§27/§29's own explicit instruction; OD-006/OD-007/OD-008/OD-009 stay open).
- **Report/export audit logging is not implemented** (§52) — a deliberate scope decision, not an oversight (see §1.26).
- **P&L's COGS section is always empty for a freshly-provisioned tenant** — no COGS account is seeded by `DEFAULT_ACCOUNT_SEED` (PROMPT-025), and `PURCHASE_EXPENSE` is classified as EXPENSE, not COGS — a direct consequence of PROMPT-025's own unresolved OD-004/OD-005 (perpetual vs. periodic inventory), carried forward, not newly invented here.
- **GST figures on the Dashboard always reflect the CURRENT calendar month**, independent of the dashboard's own selected Today/This-Week/This-FY/Custom period — `gst_transaction.return_period` is monthly-only by design (PROMPT-026), with no sub-month or multi-month aggregation to align with an arbitrary date range.
- **`reorder_level`-based LOW_STOCK detection is inert** — `reorder_level` has no writer anywhere in this codebase (confirmed by code reading), so it stays at 0 for every product, meaning the LOW_STOCK bucket in Current Stock / the Dashboard's low-stock KPI will show 0 until a future prompt gives that field a real writer.
- **Desktop/Tablet/Mobile UI was built with the established Tailwind responsive patterns (matching `AccountingManagement.tsx`/`GstManagement.tsx`) but not independently browser-verified in this session** — flagged, not claimed as tested (TC-041 through TC-046 not executed).
- **Caching is not implemented** (§57/OD-029) — every report query hits the database live; no caching layer exists to invalidate.

## 14. Open decisions (from the prompt's own §62 — none silently resolved)

| # | Decision | Status |
|---|---|---|
| OD-001 | Exact Management Dashboard KPI scope | Resolved for M1: see §1.4's catalogue |
| OD-002 | Inventory valuation method | Unresolved — not implemented |
| OD-003 | Whether Inventory Value is displayed in M1 | Resolved: **no** — `inventory.inventory_value` is always `null` |
| OD-004 | Exact COGS calculation method | Unresolved |
| OD-005 | Whether COGS is recognized at Delivery Challan or Sales Invoice | Unresolved (no COGS journal exists at all yet, per PROMPT-025) |
| OD-006 | Payment terms / invoice due date | Partially resolved — opportunistically derived where source fields already exist (see §13) |
| OD-007 | Receivables ageing buckets | Unresolved — not implemented |
| OD-008 | Payables ageing buckets | Unresolved — not implemented |
| OD-009 | Overdue definition | Unresolved — not implemented |
| OD-010 | Exact Net Sales formula | Resolved for M1 — see §1.5 |
| OD-011 | Exact Net Purchase formula | Resolved for M1 — see §1.5 |
| OD-012 | Credit Note treatment in Sales reports | Resolved for M1 — subtracted from Net Sales |
| OD-013 | Debit Note treatment in Sales/Purchase reports | Resolved for M1 — added to Net Sales (mirrors PROMPT-017/026's own resolution) |
| OD-014 | Cancelled invoice reporting behavior | Resolved for M1 — excluded from Summary/aggregate reports, shown (with status) in the Purchase Invoice Register for traceability |
| OD-015 | Reversal reporting behavior | Resolved for M1 — the accounting/GST reversal already nets correctly in GL/TB/GST reports; no separate "Original vs Reversal" reporting view was built beyond what GL/GST transaction listing already shows |
| OD-016 | Whether dashboard supports charts in M1 | Resolved: **no** — KPI cards only |
| OD-017 | Exact chart types if charts are approved | Not applicable (OD-016) |
| OD-018 | PDF export in M1 | Resolved: **no** |
| OD-019 | Excel export in M1 | Resolved: **no** |
| OD-020 | CSV export in M1 | Resolved: **no** (JSON only) |
| OD-021 | Asynchronous export threshold | Not applicable (no export exists) |
| OD-022 | Financial report visibility by role | Resolved for M1 — see §1.25 |
| OD-023 | Whether Salesperson can view customer outstanding | Resolved: **no** |
| OD-024 | Whether Manager can view P&L / Balance Sheet | Resolved: **yes** |
| OD-025 | Whether Platform Administrator can access tenant financial reports | Not applicable — no platform admin role exists yet (PROMPT-006's own open decision, unchanged) |
| OD-026 | Exact accounting treatment for GR / Inventory / COGS | Unresolved (carried from PROMPT-025) |
| OD-027 | Exact treatment of on-account payments in Receivables/Payables | Unresolved beyond what PROMPT-024 already resolved (on-account/`unallocated_amount` tracked on the Payment itself, not separately surfaced in Receivables/Payables) |
| OD-028 | Exact GST return reporting dimensions | Unresolved (carried from PROMPT-026 — statutory GSTR-1/3B schema not finalized) |
| OD-029 | Report caching policy | Resolved for M1: **no caching** — every query is live |
| OD-030 | Historical report correction/rebuild process | Unresolved — not applicable (nothing is pre-computed/materialized to rebuild) |

## 15. Definition of Done status

| # | Item | Status |
|---|---|---|
| 1-14 | Reporting architecture, Dashboard, Sales/Purchase/Inventory/Stock Movement/Receivables/Payables/Payment reports, GL, Trial Balance, P&L, Balance Sheet, GST reporting views | **Met** |
| 15-16 | Common filters, pagination | **Met** |
| 17 | Drill-down | **Partially met** — Sales/Purchase Invoice Register and Customer/Supplier-wise reports link back to source documents by number; a dedicated click-through UI drill-down (e.g. clicking a GL entry to open the source invoice) was not built in this pass, only the data needed for it |
| 18 | Export where approved | **Not applicable** — export not approved for M1 (OD-018/019/020) |
| 19 | Report calculations documented | **Met** — inline docstrings + this document |
| 20 | Source traceability | **Met** — every report row carries its source document number/type/id |
| 21 | Report reconciliation | **Met** — see §11 |
| 22-23 | Tenant isolation, RBAC | **Met** — verified by dedicated tests |
| 24 | Audit | **Not implemented** — see §1.26/§13 |
| 25-27 | Desktop/Tablet/Mobile UI | **Built**, not independently browser-verified this session |
| 28 | API documentation updated | **Met** (this document) |
| 29 | Database/query documentation updated | **Met** |
| 30 | Automated tests pass | **Met** — 32/32 new; full regression suite re-run (see closing summary) |
| 31-33 | Financial statements / GST / Inventory reconcile | **Met** — see §11 |
| 34 | No critical financial reporting defects remain | **Met** to the best of this session's verification |
| 35 | Unresolved reporting decisions documented | **Met** — §14 |

---

Per the prompt's own explicit stop condition: **PROMPT-027 is complete. Not proceeding to PROMPT-028 without further instruction.**
