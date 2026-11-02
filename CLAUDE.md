# CLAUDE.md

Guidance for Claude Code (or any fresh session) picking up this project.

## 1. Project Overview

A multi-tenant SaaS MVP for FMCG distributors, wholesalers, and retail
businesses in India — billing, inventory, accounting, GST, and basic payroll,
with an offline-first PWA for field sales. This session has built only the
**technical foundation and authentication/authorization layer**; no business
modules (customer, product, sales, accounting, GST, payroll, etc.) exist yet.

**Tech stack:**
- Backend: FastAPI (Python 3.13) + SQLAlchemy 2.0 (async, `asyncpg`) + Alembic
  + PostgreSQL 16, in `backend/`
- Frontend: React 19 + Vite 6 + TypeScript, Tailwind (CDN), `lucide-react`
  icons, at the project root (this was originally a Google AI Studio
  scaffold — `metadata.json`/`GEMINI_API_KEY` are leftovers, unrelated to the
  actual product)
- API: REST/JSON at `/api/v1`, UUID identifiers, `TIMESTAMPTZ`/UTC timestamps
- Auth: JWT in an httpOnly cookie (not localStorage), single 60-minute token,
  **no refresh token** (documented architecture decision, see
  PROMPT-003-NOTES.md)
- Local Postgres: v16 on **port 5433** (not 5432 — a different, pre-existing
  Postgres 18 also runs on this machine on 5432; don't confuse them), db
  `saas_mvp_dev`, role `saas_app`. Credentials live only in `backend/.env`
  (gitignored) — regenerate/ask the user if you don't have them.

## 2. What's Been Built (PROMPT-001 through PROMPT-018)

Each numbered prompt has a `PROMPT-00N-NOTES.md` file at the repo root — **read
those before touching related code**. They record conflicts found against the
baseline docs, open decisions, and exact rationale. Summary:

| Prompt | What it added |
|---|---|
| 001 | Backend/frontend project skeleton, config loader, DB session, correlation-ID middleware, structured JSON logging, standard API envelopes, exception hierarchy, audit service, `row_version` concurrency helper, PWA manifest/service worker, test harness |
| 002 | `POST /auth/sign-up` — atomic Tenant+Owner creation, idempotency-key handling, rate limiting, GST format validation (no real provider) |
| 003 | `POST /auth/login`, `/logout`, `/me`, `/session-status` — httpOnly cookie sessions, server-side revocation (`auth_session` table), login lockout, `AuthContext` + `ProtectedRoute` on the frontend |
| 004 | `POST /auth/forgot-password`, `/reset-password/validate`, `/reset-password` — anti-enumeration, single-use hashed tokens, session revocation on reset. **No real email provider** — a dev-only console stub prints the reset link to stdout |
| 005 | `/users` CRUD — Owner-only writes, Manager read-only, Salesperson no access; new users get a random unusable password + immediate reset link (reuses PROMPT-004's flow, no admin-visible passwords ever) |
| 006 | Real RBAC: `permission`/`role_permission` tables populated (were empty before), `/roles` + `/permissions` read-only endpoints, `require_permission()` now actually works (was previously always-empty), frontend nav/buttons gated by `hasPermission()` instead of hardcoded role strings |
| 007 | Customer Management (first business/master-data module): `customer` table (extends the Data Dictionary v3.0 baseline with proposed FR-CUST-01/02 fields — owner_name, email, city, pincode, region, gps_location), full CRUD + activate/deactivate, GSTIN/state cross-validation, system-generated tenant-scoped customer codes, `customers.*` permissions (Owner/Manager full, Salesperson create/edit-only per FR-CUST-07), replaces the old AI-Studio mock `AddCustomer`/`ViewCustomer` screens with a real backend-wired `CustomerManagement` screen |
| 008 | Supplier Management (Customer's sibling module): `supplier` table (extends baseline with proposed FR-SUPP-01 fields — contact_person, email, city, pincode; deliberately **excludes** region/gps_location/credit_limit per FR-SUPP-02, and has no bank fields at all — blocked upstream on ERD-DEC-04), full CRUD + activate/deactivate, GSTIN/state cross-validation, `suppliers.*` permissions (same Owner/Manager-full, Salesperson create/edit-only shape as Customer, per FR-SUPP-05), new `SupplierManagement` screen under Purchase → Suppliers |
| 009 | Product Master: `product` table (fully specified by baseline already, no field additions needed), plus new `unit_of_measure` and `product_unit_conversion` tables (product.base_uom_id is a mandatory FK). SKU is user-entered (unlike system-generated customer/supplier codes). `gst_rate` is a free numeric field, not a hardcoded rate list (GST rate versioning blocked on ERD-DEC-05). `stock_qty_cache`/`reorder_level`/`batch_no`/`expiry_date` columns exist per baseline but have no write path — reserved for the future Inventory module. `products.*` permissions are **stricter** than Customer/Supplier: Salesperson gets `products.view` only, no create/edit/deactivate (FR-PROD-04). New `ProductManagement` screen under Items → Products, with inline unit quick-create and unit-conversion management |
| 010 | Inventory Foundation & Stock Ledger: new `location` (single lazily-provisioned "MAIN" row per tenant, no management UI), `stock_ledger_entry` (append-only, enforced by a DB trigger — see below), `stock_adjustment` tables. `product.stock_qty_cache` gets its first writer here, always updated transactionally with the ledger insert. Negative stock is prohibited by default (FRD's own OQ-008 stays formally open). Idempotency-Key required on all 4 mutating endpoints (opening-stock/stock-in/stock-out/adjustments), reusing PROMPT-002's `IdempotencyService`. Row-level locking (`SELECT ... FOR UPDATE`) prevents concurrent stock-out races. **Found and fixed a real pre-existing bug**: migration 0001's `audit_log` immutability via `REVOKE ... FROM PUBLIC` never actually worked (table ownership bypasses it) — fixed for both `stock_ledger_entry` (migration 0011) and `audit_log` (migration 0012, via a spawned follow-up task) using BEFORE UPDATE/DELETE triggers instead. New `InventoryManagement` screen under Items → Inventory |
| 011 | Sales & Billing Foundation: **no concrete document type was built** — §71's own Definition of Done explicitly forbids a full Estimate/Sales Order/Delivery Challan/Sales Invoice/Sales Return workflow in this prompt, and the DB baseline has no generic "sales" table to hang a placeholder screen on (each document type has its own fully-specified table + `_line` child, reserved for its own future prompt). Built the shared service-layer infrastructure those future prompts will import: `app/services/sales/gst_calculation_service.py` (pure GST calc — tax-exclusive price, discount-before-GST, CGST+SGST vs IGST by state comparison), `app/services/sales/document_numbering_service.py` + new `document_number_sequence` table (server-authoritative, tenant+doc-type+FY-scoped numbering, format `PREFIX-FY-0001`), `app/services/sales/sales_validation_service.py` (customer/product existence+ownership+active checks reusing PROMPT-007/009's services), and renamed `InventoryService._post_movement` → public `post_movement` as the formal Sales→Inventory integration contract (no migration needed — STOCK_IN/STOCK_OUT already exist). No new `sales.*` permissions and no new API endpoints — nothing to gate/expose yet. Two reusable unmounted frontend components (`shared/CustomerSelector.tsx`, `shared/ProductLineSelector.tsx`) built for the first real document-type prompt to consume |
| 012 | Sales Estimate Management (first concrete Sales document type): new `sales_estimate`/`sales_estimate_line` tables (proposed additions beyond the baseline — `valid_until_date`, customer identity snapshot fields, header-level CGST/SGST/IGST totals, `notes`, `converted_at`, line-level `hsn_code`), full lifecycle (DRAFT→SENT→ACCEPTED/REJECTED/CANCELLED, lazy EXPIRED-on-read, →CONVERTED), server-authoritative `EST-{FY}-0001` numbering and GST calc reused directly from PROMPT-011's shared services. "Convert to Sales Order" was a **boundary/interface stub only** at the time (marks CONVERTED + records `converted_at`, no real Sales Order row — filled in by PROMPT-013). `sales_estimate.*` permissions: Owner/Manager full, Salesperson everything except `.convert`. First screen to actually mount PROMPT-011's `CustomerSelector`/`ProductLineSelector`; new `EstimateManagement` screen under Sales → Estimates |
| 013 | Sales Order Management (second concrete Sales document type): new `sales_order`/`sales_order_line` tables mirroring `sales_estimate`'s shape (proposed additions: `shipping_address`, `source_estimate_id` UNIQUE FK to `sales_estimate.id`, header CGST/SGST/IGST totals, `notes`, line-level `hsn_code`). Status lifecycle is deliberately **only** DRAFT→CONFIRMED→CANCELLED — `PARTIALLY_FULFILLED`/`FULFILLED` are NOT implemented (reserved for whichever future prompt builds Delivery Challan). **§4's mandatory rule: Sales Order never moves stock** — no file in `sales_order_service.py` imports `InventoryService`, verified by two dedicated tests checking `/inventory/availability` and the `stock_ledger_entry` table stay untouched across create/confirm/cancel. PROMPT-012's `POST /sales/estimates/{id}/convert-to-sales-order` stub now does the real work: `SalesOrderService.create_from_estimate` calls `EstimateService.convert_to_sales_order` in the same session (atomic — one failure rolls back both), then builds the Sales Order by copying the Estimate's own already-calculated snapshot verbatim (not re-priced). `sales_order.*` permissions: Owner/Manager full, Salesperson everything except `.confirm` (User Story 3 names Manager/Owner as the confirming actor). No separate "convert_from_estimate" permission was created — conversion stays gated by the existing `sales_estimate.convert`. New `SalesOrderManagement` screen under Sales → Sales Orders, reusing the same `CustomerSelector`/`ProductLineSelector` components |
| 014 | Delivery Challan Management (third concrete Sales document type — the **first that actually moves stock**): new `delivery_challan`/`delivery_challan_line` tables (no pricing/GST columns at all — a pure dispatch record). Extends PROMPT-013's Sales Order: added `sales_order_line.delivered_quantity` and widened `sales_order`'s status CHECK to finally allow `PARTIALLY_FULFILLED`/`FULFILLED` (exactly what PROMPT-013 deliberately withheld). `DeliveryChallanService.confirm_challan` is the atomic core — locks the Sales Order row (reusing `SalesOrderService.get_order_locked`), re-validates remaining quantity against LIVE data, calls `InventoryService.post_movement(STOCK_OUT, source_id=<the delivery_challan_line's id>)` per line (per-line, not per-header, so the existing `uq_stock_ledger_entry_source` constraint still gives one-movement-per-line duplicate protection), then calls the new `SalesOrderService.apply_delivery` to increment `delivered_quantity` and recompute the order's overall fulfillment status — all in one transaction. Cancellation-after-confirmation (with stock reversal) was explicitly NOT implemented — only DRAFT challans can be cancelled — per the prompt's own "flag as Open Decision if not approved" instruction. `delivery_challan.*` permissions mirror Sales Order's shape (Salesperson: everything except `.confirm`). The suggested `GET /sales/orders/{id}/delivery-eligibility` endpoint was added to the existing `sales_orders.py` router rather than duplicated. New `DeliveryChallanManagement` screen under Sales → Delivery Challans, with a self-contained Sales-Order-picker + live ordered/delivered/remaining quantity table in its create flow. Live-verified end-to-end in-browser: stock 100 → confirm an 8-unit delivery → stock 92, source Sales Order correctly flips to `PARTIALLY_FULFILLED` |
| 015 | Sales Invoice Management (fourth concrete Sales document type — the authoritative billing transaction): new `sales_invoice`/`sales_invoice_line` tables, plus `delivery_challan_line.invoiced_quantity` (mirrors PROMPT-014's own `delivered_quantity` pattern one level up the chain). Two invoice types gated by a CHECK constraint (`ck_sales_invoice_source_consistency`): `DIRECT_SALES_INVOICE` (no source DC, calls `InventoryService.post_movement(STOCK_OUT)` itself, one `source_id=<line.id>` per line — reuses PROMPT-014's per-line duplicate-protection pattern verbatim) vs `DELIVERY_CHALLAN_SALES_INVOICE` (source DC required, **never imports or calls any stock-movement primitive** — the double-stock-deduction prevention is structural/architectural, not a runtime guard, verified by a dedicated test asserting zero new `stock_ledger_entry` rows). `SalesInvoiceService.post_invoice` is the atomic core, branching on `invoice_type` before any stock code executes; the DC-based branch locks the source challan (`DeliveryChallanService.get_challan_locked`), re-validates live invoiceable quantity (`delivered_quantity - invoiced_quantity`), and increments `dc_line.invoiced_quantity` as pure bookkeeping. DC-based invoice line pricing is **prorated from the originating Sales Order line** (via `delivery_challan_line.source_sales_order_line_id`) since a Delivery Challan carries no price/GST at all — the SO line's absolute `discount_amount` is converted to an equivalent discount percentage so it scales correctly for partial invoicing. Status lifecycle DRAFT→POSTED→CANCELLED; POSTED invoices are immutable (`update_invoice` rejects any edit once posted, and rejects `line_inputs` entirely for DC-based invoices even in DRAFT — "cancel and recreate instead"). New minimal integration-boundary services, each just an audit-log entry plus an opaque reference string (no real GL/GST schema invented, since neither is approved yet): `app/services/accounting/accounting_posting_service.py` (returns `ACCPOST-<id>`) and `app/services/sales/gst_reporting_service.py` (returns `GSTTXN-<id>`) — both called from `post_invoice` regardless of invoice type. e-Invoice fields (`irn`, `ack_number`, `ack_date`, `einvoice_status`, `qr_code_data`) exist as reserved nullable columns only, untouched until a future PROMPT-018. `sales_invoice.*` permissions mirror Sales Order/Delivery Challan's shape (Salesperson: everything except `.post`). `GET /sales/delivery-challans/{id}/invoice-eligibility` and `POST /sales/delivery-challans/{id}/create-invoice` were added to the existing `delivery_challans.py` router rather than duplicated (imports `_to_detail` from `sales_invoices.py`). New `SalesInvoiceManagement` screen under Sales → Sales Invoices, plus a DC-initiated "Create Sales Invoice" flow added to `DeliveryChallanManagement.tsx`'s detail view. Live-verified end-to-end in-browser (the mandatory §47 scenario): stock 92 → confirm a 15-unit Delivery Challan → stock 77 → create+post a Sales Invoice from that same Delivery Challan for all 15 units → stock **stays at 77** (not 62), invoice detail shows both `ACCPOST-...` and `GSTTXN-...` references populated |

| 016 | Sales Return Management (fifth Sales document type — the first that REVERSES a prior transaction instead of extending one): new `sales_return`/`sales_return_line` tables, plus `sales_invoice_line.returned_quantity` (mirrors PROMPT-015's own `invoiced_quantity` pattern one level up the chain). Every Sales Return requires a source POSTED Sales Invoice (`source_invoice_id` NOT NULL FK, per the Data Dictionary baseline itself — no ad-hoc/standalone return path exists). `SalesReturnService.confirm_return` is the atomic core: locks the source invoice (`SalesInvoiceService.get_invoice_locked`, a new public wrapper added this prompt), re-validates live Returnable Quantity (`invoice_line.quantity - invoice_line.returned_quantity`) per line under that lock, calls `InventoryService.post_movement(STOCK_IN, source_type='SALES_RETURN', source_id=<return_line.id>)` per line — the mirror image of Delivery Challan/direct Sales Invoice's STOCK_OUT — then increments `invoice_line.returned_quantity` as pure bookkeeping. Return line pricing is **prorated from the originating Sales Invoice line** (identical percentage-based proration technique to PROMPT-015's DC→Invoice pricing) since price/GST are always derived from the source invoice line, never accepted from the client. Status lifecycle DRAFT→CONFIRMED→CANCELLED (named CONFIRMED, not POSTED, since a Return is inventory-only like Delivery Challan); only DRAFT is cancellable — no reversal-on-cancel exists (mirrors Delivery Challan/Sales Invoice's identical resolution). Return reason is a proposed, non-final taxonomy (DAMAGED/WRONG_PRODUCT/EXCESS_QUANTITY/QUALITY_ISSUE/CUSTOMER_REJECTION/OTHER — OTHER requires a `reason_description`), since no approved FRD/Data-Dictionary reason master exists. Reuses PROMPT-015's `AccountingPostingService`/`GstReportingService` integration-boundary pattern verbatim via two new additive methods (`post_sales_return`/`record_return_transaction`) — conceptual audit-trail entries only, no real GL/GST schema, and explicitly **not** a Credit Note (no credit-note table/reference exists; PROMPT-017's own scope). `sales_return.*` permissions mirror Sales Order/Delivery Challan/Sales Invoice's shape (Salesperson: everything except `.confirm`) — flagged as a weaker-signal judgment call this time, since this prompt's own User Stories say "authorized user" rather than naming Owner/Manager explicitly. `GET /sales/invoices/{id}/return-eligibility` was added to the existing `sales_invoices.py` router rather than duplicated (gated by `sales_return.create`, same convention as PROMPT-015's own `invoice-eligibility` gated by `sales_invoice.create`). New `SalesReturnManagement` screen under Sales → Sales Returns, with a self-contained Invoice-picker + eligibility-table create flow, plus an Invoice-initiated "Create Sales Return" flow added to `SalesInvoiceManagement.tsx`'s POSTED-invoice detail view. All 26 new tests (including the mandatory §42 stock test, §43 multiple-return test, and §44 concurrency test) passed on the first full run |

| 017 | Credit Note & Debit Note Management (sixth Sales document type — the first that is a PURE FINANCIAL ADJUSTMENT with ZERO inventory effect): new `credit_debit_note`/`credit_debit_note_line` tables (one shared table pair for both note types, distinguished by `note_type`), plus `sales_invoice_line.credited_quantity`/`.debited_quantity` (mirrors PROMPT-016's own `returned_quantity` pattern one level up the chain, tracked separately per note type on the same source line). Every note requires a source POSTED Sales Invoice (`source_invoice_id` NOT NULL FK, per the Data Dictionary baseline itself) — Credit-Note-from-Sales-Return is explicitly NOT implemented (no such column exists, no approved requirement confirms it — Open Decision #5). `CreditDebitNoteService.post_note` is the atomic core: locks the source invoice (reusing `SalesInvoiceService.get_invoice_locked`/`.get_lines`), re-validates live eligible quantity (`quantity - credited_quantity` or `quantity - debited_quantity`, depending on `note_type`) per line under that lock, increments the appropriate running-total column, then records accounting/GST integration entries — **this file never imports `InventoryService` at all**, making the zero-stock-impact guarantee structural, not a runtime check, verified by dedicated tests for both note types. Note line pricing is prorated from the originating Sales Invoice line, identical technique to Sales Return's own line pricing. Status lifecycle DRAFT→POSTED→CANCELLED; only DRAFT is cancellable. `reason` is deliberately free text, NOT a controlled enum (§4 of this prompt explicitly forbade inventing a reason taxonomy, unlike Sales Return's own prompt). Debit Note's eligibility rule and accounting direction are both explicitly flagged as Open Decisions (#10/#28) — implemented as a conservative mirror-image of Credit Note's own resolution, pending Product Owner confirmation. Reuses PROMPT-015/016's `AccountingPostingService`/`GstReportingService` integration-boundary pattern via two new additive methods (`post_credit_debit_note`/`record_credit_debit_note_transaction`). `credit_note.*`/`debit_note.*` permissions (10 codes) mirror the established shape (Salesperson: everything except `.post`). `GET /sales/invoices/{id}/adjustment-eligibility` was added to the existing `sales_invoices.py` router (gated by EITHER `credit_note.create` OR `debit_note.create`, checked dynamically since it serves both note types — the `/sales/credit-debit-notes` router itself also dynamically checks `note_type`-specific permissions per request rather than one static dependency, since one table serves two document types). New `CreditDebitNoteManagement` screen under Sales → Credit/Debit Notes, with separate "Credit Note"/"Debit Note" create buttons sharing one Invoice-picker + eligibility-table form. All 26 new tests (including the mandatory §48 no-stock test for both note types, §49 credit-limit test, and §50 concurrency test) passed on the first full run |

| 018 | E-Invoice & E-Way Bill Integration (the FIRST prompt to integrate with an external GST/NIC system rather than manage only internal business documents): new `integration_configuration` (one row per tenant, lazily provisioned like `InventoryService.ensure_default_location()` — no config-management API/UI exists yet), `einvoice`/`eway_bill` (one row per Sales Invoice each — `sales_invoice_id` UNIQUE per tenant, since a Sales Invoice gets at most one IRN/E-Way Bill in this MVP), and `integration_operation` (the operational/reconciliation log) tables. No real provider is approved (§43 Open Decision #1) — `app/services/gst_integration/provider.py`'s `SandboxSimulatorProvider` is the only implementation, a deterministic dev/test-only stub (mirrors `NullGSTProvider`/`ConsolePasswordRecoveryProvider`'s "real interface, fake backend, raises loudly in production" discipline) with a `force_outcome` test hook for TIMEOUT/UNAVAILABLE/AUTH_FAILED/RATE_LIMITED fault injection. **Two-layer idempotency**: the existing `IdempotencyService` (HTTP replay guard, reused verbatim) PLUS a new domain-level guard — `EInvoiceService.generate`/`EWayBillService.generate` lock the `einvoice`/`eway_bill` row (`SELECT ... FOR UPDATE`) and refuse to proceed if status is already `GENERATED` or in a `LOCKED_STATUSES` in-flight state, which is what actually prevents two *different* idempotency keys from both reaching the provider. **`STATUS_UNKNOWN` handling (the critical §24 scenario)**: a provider TIMEOUT never triggers a blind resubmission — the next `generate()` call reconciles via `get_irn_status`/`get_eway_bill_status` FIRST, and if a safe retry is needed, REUSES the original attempt's idempotency key rather than minting a new one. Applicability (§8/§18) is deliberately NOT a legal-threshold rule engine — no approved turnover/transaction-type rule exists anywhere in this codebase's sources — it's a tenant-level `einvoice_enabled`/`eway_bill_enabled` toggle plus a posted/not-cancelled check, versioned (`RULE_VERSION`) for a future real rule engine to replace. `einvoice.*`/`eway_bill.*` permissions: Owner/Manager full, Salesperson VIEW ONLY for both (stricter than every prior module — submitting to/cancelling against a government system was judged higher-commitment than any prior "post"/"confirm"). New `EinvoiceEwayBillPanel.tsx` component mounted inside `SalesInvoiceManagement.tsx`'s POSTED-invoice detail view (no separate screen, per §34's own instruction). All 26 new tests (successful generation, missing GSTIN/HSN, non-applicable, duplicate/concurrent generate, provider timeout→reconciliation, provider unavailable/auth-failure, cancellation, tenant isolation, RBAC, both E-Invoice and E-Way Bill) passed after two test-setup fixes (missing opening-stock seed; missing customer state_code/address) and one real implementation fix (AUTH_FAILED was misclassified as a permanent validation error instead of a transient `ExternalServiceError`) |

| 019 | Purchase Management Foundation (the FIRST Purchase-side document chain — Supplier → Purchase Order → Goods Receipt → Purchase Invoice → Purchase Return, mirroring the proven Sales chain's architecture): new `purchase_order`/`purchase_order_line`, `goods_receipt`/`goods_receipt_line`, `purchase_invoice`/`purchase_invoice_line`, `purchase_return`/`purchase_return_line` tables (8 new tables, all "propose, document, implement" additions on top of the approved baseline). **Purchase Order never touches inventory** (mirrors Sales Order, §4/§10's mandatory rule — no `InventoryService` import anywhere in `purchase_order_service.py`). **Goods Receipt confirmation is the first Purchase document to move stock** — one `InventoryService.post_movement(STOCK_IN, source_type=GOODS_RECEIPT, source_id=<gr_line.id>)` per line, mirrors Delivery Challan exactly, with `PurchaseOrderService.apply_receipt` updating `purchase_order_line.received_quantity` and recomputing PARTIALLY_RECEIVED/FULLY_RECEIVED status. **Purchase Invoice branches on `invoice_type`** (`DIRECT_PURCHASE_INVOICE` calls `post_movement` itself; `GOODS_RECEIPT_PURCHASE_INVOICE` never calls it at all, only increments `goods_receipt_line.invoiced_quantity`) — the double-stock-duplication prevention is structural, identical to PROMPT-015's Sales Invoice DC-branch discipline, verified by a dedicated test asserting stock never doubles. GR-based invoice line pricing does NOT need discount proration in this foundation (`goods_receipt_line.discount_amount` is always 0 — no receipt-time discount input path exists), unlike Sales Invoice's DC-branch or Purchase Return's own proration. **Purchase Return creates STOCK_OUT**, requires a source POSTED Purchase Invoice (`source_purchase_invoice_id` NOT NULL per the baseline itself — no GR-sourced or standalone return path), mirrors Sales Return's proration technique and proposed non-final `return_reason` taxonomy. **No accounting/GST integration boundary exists for Purchase Invoice** — an explicit, documented scope exclusion per this prompt's own §14 instruction, unlike Sales Invoice's `AccountingPostingService`/`GstReportingService` calls. **Salesperson gets ZERO Purchase permissions** (`purchase_order.*`/`goods_receipt.*`/`purchase_invoice.*`/`purchase_return.*`, 20 codes total) — resolved as a DIRECT reading of FRD Table 7 (lists Purchase as "Owner, Manager" with no Salesperson row at all), NOT a weaker-signal judgment call like several prior Sales-module RBAC decisions. New `PurchaseOrderManagement`/`GoodsReceiptManagement`/`PurchaseInvoiceManagement`/`PurchaseReturnManagement` screens under Purchase, plus a new `shared/SupplierSelector.tsx` (Purchase's counterpart to `shared/CustomerSelector.tsx`). All 27 new tests (including the mandatory no-duplicate-stock-in-from-GR-invoice test, over-receipt/excess-return prevention, concurrent-receipt protection, and idempotent retry on GR-confirm/invoice-post/return-confirm) passed on the first full run — see `PROMPT-019-NOTES.md` for the full Open Decisions table (15 items) |

| 020 | Purchase Order Management (completes the PO workflow PROMPT-019 established as a foundation): most of the "complete PO workflow" §1 asked for — create/draft/edit/confirm/cancel, server-authoritative numbering, ordered/received/remaining tracking, partial receiving, over-receipt prevention, row-version concurrency, stock-impact discipline — was already built and tested in PROMPT-019, so this prompt's own work is the genuinely new surface area: 4 new optional header fields (`supplier_reference`/`expected_delivery_date`/`payment_terms`/`delivery_terms`, migration 0022), ordered/received/remaining quantities now exposed on the LIST screen (not just detail) via a new `QuantityTotals`/`totals_from_lines`/`_quantity_totals_for_orders` helper set (the list variant aggregates a whole page in ONE query, never N+1), explicit line-level `remaining_quantity`, and three new `purchase_order.view`-gated endpoints: `GET .../related-documents` (Goods Receipts sourced from the PO, plus — transitively, via those GRs' `source_goods_receipt_id` — any Purchase Invoices linked to them, since a Purchase Invoice has no direct PO reference of its own per PROMPT-019's Open Decision #2), `GET .../receiving-summary` (the authoritative ordered/received/remaining view, distinct from `/receipt-eligibility` which is scoped to creating a NEW Goods Receipt), and `GET .../audit-history` (the FIRST audit-log READ path anywhere in this codebase — `audit_log` had been write-only through every prior prompt; deliberately narrow, PO-scoped only, confirms tenant ownership first for the same 404-for-cross-tenant discipline used everywhere else). **Idempotent confirm/cancel (AC-20) needed no new server logic** — the existing status-guard + row-version check already prevents duplicate PO numbers/duplicate transitions/duplicate audit events on a retried request, explicitly verified by two new tests asserting exactly one audit event survives a duplicate attempt. New frontend: create-form fields for all 4 new header fields, list-screen "Expected Delivery"/"Qty (Ord/Rcv/Rem)" columns, detail-modal Related Documents + Audit History sections, and a brand-new `PrintPreviewModal` (§36) — the first print/preview capability anywhere in this codebase, a `@media print`-driven full-page layout invoking the browser's own `window.print()`, explicitly headed "PURCHASE ORDER" with a "Not a tax invoice" footer disclaimer per that section's own instruction not to represent a PO as an Invoice. All 14 new tests passed on the first full run; PROMPT-019's own 27 `test_purchase_foundation.py` tests re-run unmodified and still pass — see `PROMPT-020-NOTES.md` for the full 29-item Open Decisions table (currency/freight/PO-approval-workflow/PO-versioning/location all explicitly flagged OPEN DECISION, not silently resolved) |

| 021 | Goods Receipt Management (completes the GR workflow PROMPT-019 established as a foundation, mirroring PROMPT-020's identical "foundation was already 90% of it" pattern for Purchase Order): create-from-PO/draft/edit/confirm/list/view, eligible-PO-line loading, ordered/received/remaining tracking, partial receiving, over-receipt prevention, numbering, concurrency, idempotency, RBAC, tenant isolation, and the mandatory one-Stock-IN-per-line-on-confirm rule were already built and tested in PROMPT-019 — this prompt's own genuinely new work is **confirmed-GR cancellation with a compensating Stock OUT reversal** (§23-25, previously only DRAFT could be cancelled at all), gated by (a) no downstream Purchase Invoice against any line (`goods_receipt_line.invoiced_quantity == 0` for every line, else `GR_HAS_DOWNSTREAM_INVOICE`/422) and (b) `InventoryService`'s own negative-stock guard (a reversal that would drive stock negative — because the received goods were already consumed elsewhere — is rejected with a 409, not forced through). The reversal reuses `InventoryService.post_movement` itself (STOCK_OUT, a NEW `source_type='GOODS_RECEIPT_REVERSAL'` distinct from the original `'GOODS_RECEIPT'` so both entries coexist under the same `uq_stock_ledger_entry_source` constraint without colliding — the original STOCK_IN is never edited or deleted, INVARIANT 7 holds structurally) and a new `PurchaseOrderService.apply_reversal` (the mirror image of PROMPT-019's own `apply_receipt`, decrementing `received_quantity` and recomputing PO status back down through FULLY_RECEIVED/PARTIALLY_RECEIVED/CONFIRMED via PROMPT-020's own `totals_from_lines` helper, never resurrecting a CANCELLED order). Also added: a new `supplier_delivery_note` header field (migration 0023), per-line `stock_movement_id`/`stock_movement_reversed` visibility (§42 "Inventory Impact"), and two new `goods_receipt.view`-gated endpoints mirroring PROMPT-020's Purchase Order pattern exactly — `GET .../related-documents` (source PO + linked Purchase Invoices) and `GET .../audit-history`. New frontend: Supplier Delivery Note create-form field, an "Inventory Impact" detail section, Related Documents + Audit History sections, a CONFIRMED-aware Cancel button with reversal-specific confirmation copy, and a `GrPrintPreviewModal` mirroring Purchase Order's own print feature (headed "GOODS RECEIPT", footer disclaiming "Not a Purchase Invoice", with Received-By/Approved-By signature lines). All 17 new tests passed after fixing two real implementation bugs found during first-run verification (confirm-endpoint response missing its own stock-movement info; a test-authoring gap around invoiced_quantity only incrementing at POST, not DRAFT-create, time) — PROMPT-019/020's own 41 tests re-run unmodified and still pass — see `PROMPT-021-NOTES.md` for the full 25-item Open Decisions table |

| 022 | Purchase Invoice Management (completes the PI workflow PROMPT-019 established as a foundation, third "foundation was already 90% of it" prompt after PROMPT-020/021): create direct/from-GR, draft/edit/post, numbering, GST calc, idempotency, concurrency, RBAC, and the DIRECT-vs-GR stock decision were already built and tested in PROMPT-019 — this prompt's own genuinely new work is **PO-linked invoicing ("Supported Flow 2")** and **POSTED-invoice cancellation with reversal** (§33-35). A new THIRD invoice_type, `PURCHASE_ORDER_PURCHASE_INVOICE` (migration 0024, new `purchase_invoice.source_purchase_order_id`/`purchase_invoice_line.source_purchase_order_line_id` columns), lets one invoice consolidate eligible quantity across MULTIPLE confirmed Goods Receipts under a Purchase Order — critically this is NOT a third stock-impact scenario, it's Scenario A computed at the PO level: a requested PO-line quantity is fanned out across that PO line's own contributing GR lines (oldest first), so ONE requested line can produce SEVERAL `purchase_invoice_line` rows, each still tracing to a specific `goods_receipt_line` and sharing the SAME `invoiced_quantity` counter single-GR invoicing already uses (INVARIANT 5 — one physical receipt never counted twice, verified by a dedicated test that GR-based and PO-consolidated invoicing against the same GR correctly compete for the same remaining quantity). `post_invoice`'s non-DIRECT branch was generalized from "lock the ONE GR the invoice names" to "lock every DISTINCT GR the invoice's own LINES reference" (sorted, to avoid a lock-ordering deadlock) — the one change that makes both GR-sourced and PO-consolidated invoices share the same posting code path with zero special-casing. **Cancellation-with-reversal** (previously DRAFT-only) now handles POSTED too, gated by no downstream Purchase Return (`purchase_invoice_line.returned_quantity == 0` on every line, else `PINV_HAS_DOWNSTREAM_RETURN`/422): a DIRECT invoice's cancellation posts a compensating STOCK_OUT per line (new `source_type='PURCHASE_INVOICE_REVERSAL'`, mirrors Goods Receipt's own `GOODS_RECEIPT_REVERSAL` pattern from PROMPT-021 exactly — coexists with the original `'PURCHASE_INVOICE'` STOCK_IN entry under `uq_stock_ledger_entry_source` without colliding); a GR/PO-sourced invoice's cancellation NEVER touches stock (§35 — the source GR remains the physical receipt), only releases its own bookkeeping claim on each line's source `goods_receipt_line.invoiced_quantity`. Also added: `supplier_invoice_date`/`due_date` header fields, a non-blocking `duplicate_supplier_invoice_warning` flag (§7 — uniqueness policy stays an explicit Open Decision, never enforced as a DB constraint), a system-determined `stock_impact` field (`STOCK_IN_REQUIRED`/`STOCK_ALREADY_RECEIVED`, never user-editable), per-line stock-movement visibility for DIRECT invoices, and two new `purchase_invoice.view`-gated endpoints (`/related-documents`, `/audit-history`) plus two new `purchase_invoice.create`-gated endpoints on `/purchase/orders` (`/invoiceable-items`, `/create-invoice`) mirroring PROMPT-020/021's identical supporting-endpoint pattern. New frontend: a second "From PO" create button opening a PO-picker + invoiceable-items table (mirrors Goods Receipt's own PO-picker pattern), Stock Impact section on the detail screen, Related Documents + Audit History sections, a reversal-aware Cancel dialog, and a `PiPrintPreviewModal` mirroring Purchase Order/Goods Receipt's own print features. All 19 new tests passed after fixing one real shared regression (`goods_receipts.py`'s own `create-invoice` endpoint broke when `_to_detail` gained a required `po_number` parameter — a pure call-site fix, not a new business-logic bug) and two test-authoring issues; PROMPT-019/020/021's own 58 tests re-run unmodified and still pass — see `PROMPT-022-NOTES.md` for the full 27-item Open Decisions table |

| 023 | Purchase Return Management (completes the PR workflow PROMPT-019 established as a foundation, fourth and final "foundation was already 90% of it" prompt in the Purchase chain after PROMPT-020/021/022): create against a source POSTED Purchase Invoice, draft/edit, confirm (one STOCK_OUT per line), server-authoritative numbering, the returnable-quantity formula (`invoice_line.quantity - invoice_line.returned_quantity`, server-recalculated under a row lock at confirm time), over-return prevention, idempotent confirm, row-version concurrency, RBAC, and tenant isolation were already built and tested in PROMPT-019 — this prompt's own genuinely new work is **CONFIRMED-return cancellation with a compensating Stock IN reversal** (§33-35, previously only DRAFT could be cancelled), following Goods Receipt's PROMPT-021 precedent exactly one level further down the chain: a new `source_type='PURCHASE_RETURN_REVERSAL'` STOCK_IN entry (same `source_id` as the original `'PURCHASE_RETURN'` STOCK_OUT, coexisting under `uq_stock_ledger_entry_source` without colliding — the original entry is never edited or deleted) plus releasing the return's own claim on the source invoice line's `returned_quantity` bookkeeping counter so the quantity becomes returnable again. Unlike a DIRECT Purchase Invoice's own reversal (PROMPT-022), this compensating movement is a STOCK_IN and can never be rejected for going negative — restocking previously-removed goods only ever increases stock. No downstream-dependency guard was needed (§34) because no table in this codebase currently references `purchase_return` at all (no Credit/Debit Note, Supplier Payment, or Accounting Posting link exists yet — flagged as Open Decision, not silently assumed permanent). Also added: per-line `stock_movement_id`/`stock_movement_reversed` visibility (mirrors GR/PI's own §42-style Stock Impact), and two new `purchase_return.view`-gated endpoints (`/related-documents` — source Purchase Invoice plus, transitively, source Purchase Order and contributing Goods Receipts, reusing `PurchaseInvoiceService.get_related_documents` rather than re-deriving that traceability logic — and `/audit-history`) mirroring PO/GR/PI's identical supporting-endpoint pattern. New frontend: a Stock Impact section, Related Documents + Audit History sections, a reversal-aware Cancel dialog (Cancel now shown for both DRAFT and CONFIRMED), and a `PrPrintPreviewModal` mirroring Purchase Order/Goods Receipt/Purchase Invoice's own print features, headed "PURCHASE RETURN". No database migration was needed — every column this prompt required already existed from PROMPT-019. All 12 new tests passed after two test-writing fixes (a wrong `AuditLog.before`/`.after` attribute name — the model's actual columns are `before_json`/`after_json`; and a related-documents test that invoiced via the single-GR path, which never populates `purchase_invoice.source_purchase_order_id`, switched to the PO-consolidated invoicing path instead); PROMPT-019/020/021/022's own 93 tests re-run unmodified and still pass — see `PROMPT-023-NOTES.md` for the full 33-item Open Decisions table |

| 024 | Payments & Collections Management (the FIRST prompt outside the Sales/Purchase document chains — a new cross-cutting financial module sitting alongside both): implements Customer Receipts (money in, against Sales Invoices) and Supplier Payments (money out, against Purchase Invoices) as **one shared `payment`/`payment_allocation` data model and one shared `PaymentService`**, exposed through two thin per-direction API namespaces (`/customer-receipts`, `/supplier-payments`, migration 0025) — mirrors the codebase's established "unified service, per-direction thin routers" convention rather than duplicating logic. **§2's central rule — a payment is never the same record as its allocation — is structural**: `payment_allocation` is a separate table (never a field on the invoice), and new `sales_invoice.paid_amount`/`.payment_status` + `purchase_invoice.paid_amount`/`.payment_status` are reconciliation CACHE columns recomputed from `SUM(payment_allocation.allocated_amount)` across currently-POSTED payments — the exact same discipline as `product.stock_qty_cache` (PROMPT-010). A DRAFT payment has zero financial effect (mirrors every prior document type's "DRAFT is soft, POST is authoritative" rule); posting locks every DISTINCT invoice an allocation touches in SORTED order (PROMPT-022's own deadlock-avoidance generalization, reused verbatim) before re-validating live outstanding under the lock. **On-account (partial) posting is supported by construction** — `unallocated_amount` is tracked, never silently discarded, because §13's own mandate and the mandatory TC-018 test made a hard "must-be-fully-allocated" gate structurally untenable (documented as a resolved-but-flagged Open Decision, OD-001). **Reversal is a status flip (POSTED→REVERSED) on the immutable original row** — amount/method/date/allocation fields are never edited, only full reversal is supported (no partial reversal, OD-003) — mirroring every other document type's own header-level cancel pattern rather than inventing a compensating-ledger-entry mechanism Payments doesn't have yet (that's PROMPT-025's Accounting Posting Matrix). **Cheque lifecycle is a separate concept from payment status** (§7): a POSTED cheque payment reduces outstanding immediately on posting (per the prompt's own explicit example), `cheque_status` starts PENDING and never auto-flips to CLEARED; a BOUNCED transition REUSES the reversal mechanism rather than a parallel exclusion path, restoring outstanding through the same controlled transaction (§19). Idempotency is two-layer (PROMPT-018 precedent): the existing HTTP `Idempotency-Key` guard, PLUS a new domain-level `client_transaction_id` unique-per-tenant index — a duplicate returns the existing payment rather than erroring. This is also the **first prompt since PROMPT-019 to introduce brand-new tables and brand-new permission codes**, so migration 0025 follows migration 0021's own precedent exactly rather than the "reuse existing permissions" habit of PROMPT-020-023: Row-Level Security is enabled on both new tables, and the new `customer_receipt.*`/`supplier_payment.*` codes are backfilled onto every EXISTING tenant's roles (not just newly-created ones). RBAC (§36/§50 OD-012, a documented judgment call): Owner/Manager get full CRUD+post+reverse for both directions; Salesperson gets Customer Receipt view/create/edit only (mirrors the established "Salesperson drafts, Owner/Manager posts" shape used identically across every Sales document type) and ZERO Supplier Payment access (mirrors Purchase's own FRD-Table-7-driven "Owner/Manager only" rule). New `AccountingPostingService.post_payment` integration boundary (§32, conceptual stub, no real GL). New frontend: `CustomerReceiptManagement`/`SupplierPaymentManagement` screens under a new "Payments" sidebar group, with dynamic method-specific fields, an outstanding-invoices allocation grid ("allocate oldest first" convenience, server remains authoritative), and cheque-lifecycle actions on the detail view. All 24 new tests passed after two test-authoring fixes (missing opening-stock seed before posting a Sales Invoice; a GST-inclusive total miscalculated in a multi-invoice test); the full backend regression suite re-run and still passes — see `PROMPT-024-NOTES.md` for the full 15-item Open Decisions table |

| 025 | Accounting Posting Matrix & Journal Engine (replaces the "conceptual entries" stub `AccountingPostingService` had carried since PROMPT-015 with a REAL double-entry ledger): new `chart_of_account`/`account_mapping`/`accounting_period`/`journal_entry`/`journal_line` tables (migration 0026, RLS-enabled — third and latest prompt since PROMPT-019 to introduce brand-new tables + permission codes, following migration 0021/0025's exact precedent of backfilling existing tenants' roles). **`JournalService` is the ONE generic double-entry engine** every posting rule goes through (`post_journal`/`reverse_journal`/`reverse_journal_for_source`) — no module implements its own accounting logic. `AccountingPostingService`'s four EXISTING methods (`post_sales_invoice`/`post_sales_return`/`post_payment`/`post_credit_debit_note`) were rewritten to build real `JournalLineInput` lists instead of an audit-only JSON blob — **every existing call site needed ZERO changes** (same method names/params/`-> str` return, now the real `journal_number`). Two NEW methods close the accounting boundary PROMPT-019 §14 explicitly deferred: `post_purchase_invoice`/`post_purchase_return`, wired into `purchase_invoice_service.post_invoice`/`purchase_return_service.confirm_return`. **No account id is ever hard-coded** — every posting rule names a `posting_rule_code` (`app.core.accounting_constants`), resolved per-tenant by `ChartOfAccountsService` against a lazily-seeded, EXPLICITLY EDITABLE default 16-account FMCG Chart of Accounts (§56 OD-001/OD-002 — not an approved final COA). **No COGS/Inventory journal leg is ever posted anywhere** (OD-005/006/007/024 unresolved by design — Stock Ledger remains the sole inventory source of truth) and **no Goods Receipt journal exists** (OD-008/009/025 unresolved) — "Purchase Expense" is used as a deliberate placeholder, not "Inventory" (OD-004/010). **Idempotency is a DB-level unique `(tenant_id, source_type, source_id, posting_event_type)` constraint** — `post_journal` checks-before-insert AND catches `IntegrityError` as a race-safe backstop (mirrors `DocumentNumberingService`'s own SAVEPOINT-retry precedent), so concurrent duplicate postings can never create two journals. **Reversal is a brand-new journal with swapped debit/credit** (`reversal_of_journal_id` set, `posting_event_type=REVERSAL`) — the original's own lines/amounts are NEVER touched, only its `status` flips POSTED→REVERSED; wired automatically into `PurchaseInvoiceService.cancel_invoice`'s POSTED branch, `PurchaseReturnService.cancel_return`'s CONFIRMED branch, and `PaymentService.reverse_payment` (which transitively covers cheque-bounce too), plus a manual `POST /accounting/journals/{id}/reverse` endpoint for Owner/Manager. An `accounting_period` posting GUARD exists (§35) but no close/reopen workflow was built (OD-018/019 stay open — a period can currently never become CLOSED). New `accounting.view_journals`/`.view_chart_of_accounts`/`.manage_account_mappings`/`.reverse_journal` permissions — Owner/Manager only, Salesperson gets none (financial GL access judged inappropriate, mirrors Purchase's own precedent). New frontend: `AccountingManagement.tsx` (Journals/Chart of Accounts/Account Mappings tabs, journal detail with balance-status footer and manual Reverse action) under a new "Accounting" sidebar sub-item. All 18 new tests passed after two fixes (a missing `accounting_posting_reference` field on `PurchaseInvoiceDetail`/`PurchaseReturnDetail` — added to the model but not threaded through the schema/router; and a test asserting the wrong error code for double-reversal, `ACC-010` not `ACC-015`, since "already reversed" is more specifically `ACC_REVERSAL_ALREADY_EXISTS` than the generic `ACC_NOT_REVERSIBLE`); `test_rbac.py`'s two permission-enumeration tests needed the new `accounting.*` codes added to their expected sets (same recurring maintenance PROMPT-024 first re-introduced); the full backend regression suite re-run and still passes — see `PROMPT-025-NOTES.md` for the full 25-item Open Decisions table |

| 026 | GST Rule Engine & GST Reporting (builds the REPORTING layer on top of the GST CALCULATION engine that already existed and was already correctly shared — `app.services.sales.gst_calculation_service`, PROMPT-011, was confirmed by direct code reading to already be the one authoritative `calculate_line`/`calculate_document_totals`/`determine_gst_treatment` used unmodified by every Sales AND Purchase document service; AC-001/AC-002 were already satisfied before this prompt, not newly built): new `gst_transaction`/`gst_transaction_line` tables (migration 0027, RLS-enabled — fourth prompt since PROMPT-019 to introduce brand-new tables + permission codes, following migration 0021/0025/0026's exact precedent) **replace the audit-log-only stub `GstReportingService` had used since PROMPT-015** — its 3 existing methods (`record_invoice_transaction`/`record_return_transaction`/`record_credit_debit_note_transaction`) keep identical signatures/`-> str` returns (now a real `gst_transaction.id`, not an opaque `GSTTXN-<id>` string), and 4 NEW methods close the Purchase-side gap that existed since PROMPT-019 (zero Input GST/ITC tracking) — `record_purchase_invoice_transaction`/`reverse_purchase_invoice_transaction`/`record_purchase_return_transaction`/`reverse_purchase_return_transaction`, wired into `purchase_invoice_service.post_invoice`/`.cancel_invoice` and `purchase_return_service.confirm_return`/`.cancel_return` exactly where `AccountingPostingService`'s own PROMPT-025 calls already sit. **Sign convention is the core design decision**: a transaction that increases the tenant's GST position (Sales Invoice, Debit Note, Purchase Invoice) is stored positive; one that decreases it (Sales Return, Credit Note, Purchase Return) is stored negative; a REVERSAL row (Purchase Invoice/Return POSTED-cancellation only, mirroring PROMPT-025's `reversal_of_journal_id` pattern exactly via `reversal_of_transaction_id`) negates its own ORIGINAL — this makes period-level `SUM()` give the correct net GST position with zero bucket-type special-casing anywhere, and the ORIGINAL row is NEVER edited (§21 immutability, verified by a dedicated test that changes a product's `gst_rate` after posting and confirms the snapshot is untouched). **GSTR-1/GSTR-3B/dashboard/reconciliation are entirely computed-on-demand** from `gst_transaction` (`app/services/gst/gstr_service.py`) — no persisted, editable "GST Return" entity exists (§27/§31 honored structurally: no DRAFT→VALIDATED→SUBMITTED state is stored anywhere, since no portal submission exists — OD-010/OD-011 stay open). Reconciliation cross-checks `gst_transaction` period totals against `journal_line` totals joined through `account_mapping` by `OUTPUT_*`/`INPUT_*` posting_rule_code — the GST engine itself never creates or touches any accounting journal (§25's separation is structural: zero `JournalService`/`AccountingPostingService` imports anywhere under `app/services/gst/`). **GSTIN/HSN validation (`app/services/gst/gst_validation_service.py`, format-only — no live provider, OD-004) is deliberately NOT a hard gate on Sales/Purchase posting** — wired only into `validate_gstr1`/`validate_gstr3b` (an entirely new surface with no prior behavior to break), a documented risk-management decision to avoid retrofitting a newly-invented strict check into the 606-test-covered posting flows of 6 different document services without an approved requirement demanding it. New `/api/v1/gst/*` router is deliberately narrow — no `POST /gst/calculate`/`POST /gst/validate` (§40's own instruction against letting arbitrary clients submit numbers for the server to calculate/validate honored literally); only read/aggregate endpoints (`/transactions`, `/dashboard`, `/returns/gstr1`, `/returns/gstr1/validate`, `/returns/gstr3b`, `/returns/gstr3b/validate`, `/reconciliation`, plus JSON-only `/returns/gstr1/export`/`/returns/gstr3b/export` — no CSV/Excel writer, no statutory-schema-conformant file, per OD-008/OD-009). New `gst.view`/`.prepare_returns`/`.export` permissions — Owner/Manager only, Salesperson none (mirrors Accounting's identical financial-access precedent). New frontend: `GstManagement.tsx` (Dashboard/Transactions/GSTR-1/GSTR-3B/Reconciliation tabs) wired into the sidebar's "GST Filing" item, which had existed as an unwired placeholder since before this session. All 15 new tests passed after two fixes: a real regression (restored the `GST_TRANSACTION_CREATED`/`GST_TRANSACTION_REVERSED` audit-log entry under the SOURCE entity's own `entity_type`/`entity_id` that the old stub had written and 3 pre-existing PROMPT-015/016/017 tests asserted on — same class of bug PROMPT-025 hit with `ACCOUNTING_POSTED`, fixed the identical way) and a `date >= character varying` type-mismatch bug in the reconciliation query's period-boundary comparison; the full backend regression suite re-run and still passes — see `PROMPT-026-NOTES.md` for the full 24-item Open Decisions table |

| 027 | Reports, Dashboards & Financial Statements (a READ-ONLY reporting layer over every authoritative module built so far — Sales, Purchase, Inventory/Stock Ledger, Payments, Accounting Journals, GST, Customers, Suppliers, Products; §2's own mandatory principle — "reports must not become a second source of truth" — is honored structurally: ZERO new business tables, every report is a SQL aggregation over already-posted rows in `sales_invoice`/`purchase_invoice`/`sales_return`/`purchase_return`/`credit_debit_note`/`stock_ledger_entry`/`payment`/`journal_entry`/`journal_line`/`chart_of_account`/`gst_transaction`): 7 new `app/services/reports/` service modules (`sales_report_service.py`, `purchase_report_service.py`, `inventory_report_service.py`, `receivables_payables_service.py`, `payment_report_service.py`, `accounting_report_service.py`, `dashboard_service.py`) and one router, `/api/v1/reports/*` (26 endpoints — Dashboard; Sales Summary/Invoice Register/Customer-wise/Product-wise/Returns; Purchase Summary/Invoice Register/Supplier-wise/Product-wise/Returns; Inventory Current Stock/Stock Movements/Product History; Receivables; Payables; Payment Register/Method Summary/Cheque Report; General Ledger/Trial Balance/P&L/Balance Sheet; GST Summary/Transactions/HSN Summary). **Net Sales formula (§56 OD-010, resolved for M1)**: Taxable Sales (POSTED invoices) − Sales Returns (CONFIRMED) − Credit Notes (POSTED) + Debit Notes (POSTED); **Net Purchase (OD-011)**: Taxable Purchase − Purchase Returns (no Purchase-side Credit/Debit Note exists in this codebase). **Outstanding is always `invoice.grand_total − invoice.paid_amount` computed directly on the invoice** — deliberately NOT `customer.balance`/`supplier.balance` (separate reconciliation caches, not trusted as the report's own source of truth, §2 applied one level down). **General Ledger's per-account balance query uses a pre-aggregated subquery, not a naive double-outer-join** — a real bug was caught and fixed during implementation where chaining `ChartOfAccount LEFT JOIN JournalLine LEFT JOIN JournalEntry(status+date filter)` silently included line amounts whose journal_entry didn't match the date filter, since a later failed outer join never retroactively nulls an earlier one's already-matched row (see `accounting_report_service.py`'s own code comment). **Balance Sheet's "Current Period Earnings" is NOT a plug** — it's the SAME Net Profit the P&L computes from the SAME posted journal lines; `Assets = Liabilities + Equity + Net Profit` is a mathematical identity of double-entry bookkeeping (the Trial Balance's own debit=credit guarantee, rearranged), verified (not assumed) by a dedicated balance-check test. **Dashboard KPIs call the IDENTICAL report-service method (same date range) the corresponding detailed report itself calls** — reconciliation between Dashboard and detailed reports is structural by construction, not a separate periodic check, verified by dedicated tests. **Inventory Value is deliberately never shown** (§8/OD-002/OD-003 — no inventory valuation method is approved; showing a number would silently invent a financial policy). **GST reporting views are a thin delegation to `app.services.gst.gstr_service.GstrService` (PROMPT-026)** — zero GST calculation logic duplicated (§39). **Export (Excel/CSV/PDF) is NOT implemented** — every report returns JSON only (OD-018/019/020, mirrors PROMPT-026's own GST-export precedent); a `reports.export` permission exists but is unused by any endpoint, an explicit forward-compatibility placeholder. New `reports.view_dashboard`/`.view_sales`/`.view_purchase`/`.view_inventory`/`.view_receivables`/`.view_payables`/`.view_payments`/`.view_general_ledger`/`.view_trial_balance`/`.view_profit_loss`/`.view_balance_sheet`/`.view_gst`/`.export` permissions (13 total, migration 0028 — permission-only, no new tables, no RLS needed) — Owner/Manager get all 13; Salesperson gets only `view_dashboard`/`view_sales`/`view_inventory` (mirroring their existing Sales/Inventory view access), explicitly excluded from Receivables/Payables/Payments/GL/TB/P&L/BS/GST (OD-022/023/024 resolved conservatively, mirroring Accounting/GST's own Owner/Manager-only precedent). New frontend: `ReportsManagement.tsx` (9 top-level tabs with sub-tabs) wired into the sidebar's "Reports" item, which had existed as an unwired placeholder since before this session. All 32 new tests passed on the first full run — no implementation bugs found in that pass, since every field-name/join assumption was verified against the actual schema (via a dedicated research pass) before any code was written; the full backend regression suite re-run and still passes — see `PROMPT-027-NOTES.md` for the full 30-item Open Decisions table |

| 028 | PWA Offline, Local Persistence, Sync & Conflict Resolution (extends PROMPT-001's own PWA foundation — `public/manifest.json`/`public/sw.js`/`pwa/registerServiceWorker.ts`, which explicitly deferred "offline business write/sync workflows" to a future prompt — this is that prompt): a narrow, explicitly-scoped offline-write surface (§2's own minimum: Sales Invoice creation, Customer quick-add, Supplier quick-add — Stock Movement, Payments, and Purchase all stay online-only, unchanged). **Architecture decision — no new generic `POST /sync` endpoint**: the sync engine (`pwa/syncEngine.ts`) REPLAYS the SAME REST endpoints the online UI already uses (`POST /customers`, `POST /suppliers`, `POST /sales/invoices`), sending the record's own `client_transaction_id` as the `Idempotency-Key` header — reusing PROMPT-002's already-built, already-tested `IdempotencyService` rather than adding a second, parallel creation path. `POST /sales/invoices` already required this header (PROMPT-015); **the one necessary backend change** was making it OPTIONAL on `POST /customers`/`POST /suppliers` (previously unsupported at all) so all three offline-writable entities share the identical duplicate-prevention guarantee — fully backward compatible, verified by re-running the existing 54 customer/supplier tests with zero regressions. New `pwa/` modules: `offlineTypes.ts` (the `SyncStatus` state machine — `LOCAL_DRAFT→PENDING_SYNC→SYNCING→SYNCED`/`SYNC_FAILED`/`CONFLICT`/`REQUIRES_ACTION`, never a boolean `is_synced`), `offlineDb.ts` (native IndexedDB, no third-party wrapper added — ONE `sync_queue` store whose `status` field doubles as the "offline draft"/"queue"/"synced"/"failed"/"conflict" categories §8 describes as conceptually separate, plus 4 master-data read-cache stores), `connectivity.ts` (a REAL API health-check ping before bulk sync — never trusts `navigator.onLine` alone, §21), `syncEngine.ts` (dependency-ordered sync via a `{ __local_ref: queue_id }` placeholder substitution — an offline invoice referencing a not-yet-synced offline customer is never submitted with a dangling local reference), `masterDataCache.ts`, `offlineInvoiceService.ts` (provisional-only discount-before-GST calculation for display, explicitly never trusted — the server always recalculates authoritatively at sync time), `offlineCustomerSupplierService.ts`. **Conflict classification is a pure, unit-tested function** (`classifySyncFailure`: network/5xx→TRANSIENT auto-retried with exponential backoff; 401/403→AUTHORIZATION; 409→BUSINESS_CONFLICT; 400/422→VALIDATION; 404→DEPENDENCY_FAILURE — only TRANSIENT is ever auto-retried, everything else goes to `CONFLICT`/`REQUIRES_ACTION` for explicit user review in the new Sync Center, never last-write-wins). **Stock conflict handling reuses PROMPT-010's own already-resolved negative-stock-prohibited policy verbatim** — no new stock policy was invented; an offline invoice that would oversell surfaces the EXISTING 409 as `CONFLICT`. **Offline invoice sync only ever calls invoice CREATE (assigns the real, gapless, server-authoritative `invoice_number` immediately, confirmed by reading `sales_invoice_service.py` — numbering happens at create, not post), never invoice POST** — this means GST/Accounting/E-Invoice processing structurally cannot occur from an offline sync (all three only trigger at POST time, a separate, unchanged, online-only user action), verified by a dedicated test rather than a runtime guard. New frontend: `ConnectivityBadge.tsx` (persistent header sync-status indicator), `SyncCenter.tsx` (pending/synced/failed/conflict/action-required views, retry/cancel/review), `OfflineInvoiceCapture.tsx` (offline invoice creation with inline offline-customer quick-add) — wired into `Header.tsx`/`Sidebar.tsx`/`App.tsx`. `AuthContext.tsx`'s `logout` now warns (via confirm dialog, never a silent delete) if unsynchronized transactions exist before proceeding — nothing anywhere in this codebase ever auto-deletes a `PENDING_SYNC`/`SYNC_FAILED`/`CONFLICT`/`REQUIRES_ACTION` record. All 30 new frontend unit tests (pure logic: failure classification, backoff growth/cap, dependency ordering, provisional GST calc) and 7 new backend tests (Customer/Supplier/Invoice idempotent-replay duplicate prevention, draft-not-posted confirmation) passed on the first run; the full regression suite re-run and still passes — see `PROMPT-028-NOTES.md` for the full 30-item Open Decisions table and the explicit list of what was NOT independently browser-verified this session (real IndexedDB/Service-Worker/offline-restart behavior — jsdom has no IndexedDB implementation and no polyfill dependency was added) |

| 029 | Employee, Payroll & Basic Salary Management (M1 BASIC payroll ONLY — zero PF/ESI/TDS/statutory compliance anywhere, verified structurally: no such posting_rule_code or component type exists anywhere in the schema, not just omitted from the UI): a "propose, document, implement" module in its entirety, 10 new tables (`employee`, `salary_component`, `salary_structure`(+`_line`), `attendance`, `leave_request`, `payroll_period`, `payroll_run`, `payroll_record`(+`_line`)). **`payroll_record` IS the payslip** — no separate `payslip` table, since a payslip has no independent lifecycle of its own; `payslip_number` (format `PAYSLIP-{FY}-{seq:04d}`, assigned only at FINALIZE) lives directly on it. **Salary Structure is effective-dated with NO `effective_to` column** — the applicable structure for any payroll date is always "the one with the latest `effective_from` <= that date," which structurally guarantees a later structure can never retroactively change already-calculated payroll (verified by a dedicated test: creating a ₹99,999 structure effective 3 months later leaves an already-finalized run's net salary at its original ₹25,000). **Payroll Run lifecycle is DRAFT→CALCULATED→FINALIZED (+REVERSED), NOT the prompt's own suggested 5-stage DRAFT/CALCULATED/REVIEWED/APPROVED/FINALIZED chain** — no approved source defines a separate reviewer/approver role, so a dedicated review gate would have invented an unapproved workflow; mirrors the established "DRAFT→POSTED(+CANCELLED)" 2-3 stage pattern every other document type in this codebase already uses. **The calculation engine (`app/services/payroll/payroll_calculation_service.py`) resolves mid-period-joining, mid-period-exit, AND unpaid-leave proration with ONE unified formula** (`payable_days / calendar_days`, calendar-day basis — no working-day calendar/holiday master exists in this codebase) instead of three separate ad-hoc rules — deductions are prorated by the identical factor as earnings. Unmarked attendance days default to PRESENT (exception-based marking, an explicit documented convention, not an oversight). **Employee Code uses a NEW sibling method on the existing numbering service**, `DocumentNumberingService.next_number_no_fy` — unlike every GST/financial document number (which resets every financial year), an employee code must never repeat even across years, so this method reuses the identical concurrency-safe `DocumentNumberSequence` row-locking mechanism with a constant `financial_year_label="ALL"` sentinel instead of a real FY label. **Accounting integration is a new `AccountingPostingService.post_payroll_run` method** (mirrors every prior posting-rule addition exactly — `DR Salary Expense / CR Salary Deductions Payable (if >0) / CR Salary Payable`) — `PayrollRunService` owns calculation/snapshot/orchestration, `JournalService` (PROMPT-025, untouched) owns journal creation/balancing/reversal, zero duplicated double-entry logic (verified: no debit==credit check exists anywhere under `app/services/payroll/`). New `employees.*`/`salary.*`/`attendance.*`/`leave.*`/`payroll.*` permissions (16 total, migration 0029) — Owner/Manager get all 16, Salesperson gets NONE (a direct reading — HR/payroll data has no plausible Salesperson use case, mirrors Purchase's own "not ambiguous" precedent); salary figures are additionally gated behind a SEPARATE `salary.view`/`salary.manage` permission distinct from `employees.view`, so employee-list access alone never exposes compensation. New frontend: `PayrollManagement.tsx` (Employees/Attendance/Leave/Payroll tabs, with inline salary-structure and payslip views) wired into the sidebar's "Payroll" item, which had existed as an unwired placeholder since before this session. **No offline-write path exists for payroll at all** — never wired into PROMPT-028's sync engine, so it's blocked by simple omission rather than a runtime guard. **No dedicated `/reports/payroll/*` endpoints were added** — `PayrollManagement.tsx`'s own list views cover the Payroll Register/Employee List equivalent for M1; a formal Reports-module integration was deferred as a documented limitation, not silently dropped. All 21 new tests passed after fixing one real bug (`leave_service.py`'s `days` field returned an unquantized `Decimal` — `"2"` instead of the DB's own `Numeric(6,2)` scale `"2.00"` — on the CREATE response; fixed in the service, not by loosening the test); the full backend regression suite re-run and still passes — see `PROMPT-029-NOTES.md` for the full 32-item Open Decisions table |

**Test status as of end of PROMPT-029: 681 backend tests (pytest), 38 frontend
tests (Vitest) — all passing.** Always rerun both after changes:
```bash
cd backend && ./.venv/Scripts/python.exe -m pytest tests/ -q      # Windows venv
npx vitest run                                                     # from repo root
```

## 3. Architectural Decisions & Conventions

### Source-of-truth documents
`Document/` contains the actual approved baseline: FRD v2.0, User Flow Spec
v1.0, API Contract Spec v1.0, Database Design & Data Dictionary v3.0 (as an
xlsx with Table Register / Constraints & Indexes / Design Standards /Open
Decisions sheets), and an ERD v2.0. **No PRD v3.0 file actually exists** —
its content is paraphrased across the other four documents, which has been
sufficient so far. Read these before inventing any business rule.

### The "propose, document, implement" pattern for schema gaps
Several times, the approved DB baseline was missing something a prompt
needed (e.g. no `idempotency_key` table, no `auth_session` table, no
`user.name` column, no `password_reset_token` table). The established
pattern — **keep using it** — is:
1. Don't silently invent it or silently skip it.
2. Add it via a normal Alembic migration, with a docstring explaining why.
3. Document it in that prompt's `PROMPT-00N-NOTES.md` as a "proposed schema
   addition" needing eventual sign-off against the real Database Design doc.

### Permission catalogue discipline (important, easy to get wrong)
`app/core/permissions.py` only defines permissions for capabilities that
**actually exist in code** (`users.*`, `roles.*`, `permissions.*`). The API
Contract's "representative" permission examples for unbuilt modules
(customer.*, product.*, sales.*, etc.) were deliberately **not** pre-created.
**When you build a new module, add its permissions to that file and to
`ROLE_DEFAULT_PERMISSIONS` at that time** — don't invent a full permission
model in advance of the module existing.

### Naming/structure conventions
- Backend error codes: short prefix + number, e.g. `REG-001` (sign-up),
  `AUTH-001` (login), `RESET-001` (password reset), `USR-001` (user mgmt) —
  see `app/core/error_codes.py`. Add new prefixes per feature area.
- Backend folders: `app/api/v1/*.py` (routers, thin), `app/services/<area>/`
  (business logic), `app/models/`, `app/schemas/` (Pydantic), `app/core/`
  (cross-cutting: config, security, deps, exceptions, permissions,
  rate_limit, login_lockout, correlation, concurrency).
- Every mutable table has `id, tenant_id?, created_by, created_at, updated_by,
  updated_at, row_version` (see `app/db/base.py` mixins). Optimistic
  concurrency via `row_version` + `If-Match`/`expected_row_version` is
  standard on every update/activate/deactivate endpoint.
- Audit: `AuditService.record()` is the *only* way anything writes to
  `audit_log` (append-only, enforced by a BEFORE UPDATE/DELETE trigger —
  migration 0012 — since the app's DB role owns the table and a bare
  `REVOKE UPDATE, DELETE ... FROM PUBLIC` doesn't stop a table owner).
- Frontend: `components/` (screens/widgets), `context/` (React context
  providers — `AuthContext`, `ThemeContext`, `ToastContext`,
  `NavigationContext`), `api/` (one file per backend resource area, all
  routed through `api/client.ts`'s `apiRequest`/`apiRequestList`), `shared/`
  (cross-cutting UI: `ProtectedRoute`, `LoadingState`, `EmptyState`,
  `ErrorBoundary`).
- Tests live in `backend/tests/{unit,integration}/` and `tests/{unit,
  component}/` at the repo root (frontend, Vitest).

### Security defaults established — don't relitigate these
- Passwords: bcrypt via `passlib`, never logged, never returned by any API.
- Sessions: httpOnly + SameSite=Lax cookie, not localStorage (removes XSS
  token-theft surface) — see PROMPT-003-NOTES.md for the full rationale.
- Anti-enumeration: forgot-password and similar endpoints return identical
  responses whether or not the account exists — verified with tests, not
  just claimed.
- Backend authorization is always authoritative; frontend hiding
  (`hasPermission()`) is UX only and every hidden action is independently
  re-checked server-side (and tested that way).
- Tenant isolation: cross-tenant lookups return the same 404 as "not found"
  (never a distinguishable error) — this pattern is used everywhere a
  resource is fetched by ID.

## 4. Known Open Decisions (do not silently resolve — flag and ask, or match existing pattern)

These are carried forward across multiple `PROMPT-00N-NOTES.md` files:
- **Phone uniqueness scope** (platform-wide vs. tenant-scoped) — currently
  configurable (`settings.phone_uniqueness_scope`, defaults to `"tenant"`,
  i.e. unenforced at the DB level). This causes real, documented ambiguity in
  login-by-phone if two tenants ever share a phone number.
- **Exact password complexity policy** — only a minimum length is enforced
  (`settings.password_min_length = 8`); the referenced legacy FRD with exact
  rules was never supplied.
- **Real GST verification provider** and **real email delivery provider** —
  both are open; only dev-only stubs exist (`NullGSTProvider`,
  `ConsolePasswordRecoveryProvider`). `get_recovery_provider()` will *raise*
  at startup if `ENVIRONMENT=production` with no real provider configured —
  this is intentional, not a bug.
- **Platform Administrator role** — no platform module exists yet, so no
  permissions are defined for it and no platform admin can currently be
  created through any implemented flow.
- **Manager's exact write permissions** — still view-only-by-default on the
  Users module (no approved source defines more than "Limited" there); but
  as of PROMPT-007/008/009/010, Manager has *full* Customer, Supplier,
  Product and Inventory access, since FR-CUST-07/FR-SUPP-05/FR-PROD-04/
  FR-STK-04/Table 7 explicitly define those modules' matrices. Note
  Salesperson's access is NOT uniform across these: create/edit on
  Customer/Supplier, but **view-only** on Products and Inventory
  (FR-PROD-04/FR-STK-04 are stricter — Salesperson can't record any manual
  stock movement until a Sales module exists to grant an indirect path).
  Don't assume any single Salesperson pattern applies to a future module —
  check its own approved source.
- **FRD FR-SI-07 vs. PROMPT-004's no-OTP constraint** — a direct conflict
  between the approved FRD (which specifies OTP-based password reset) and
  this session's explicit instruction to not implement OTP. Resolved in
  favor of the more specific/recent instruction (email-link reset), but the
  FRD itself was never updated to match — flag this if anyone asks why
  password reset doesn't use OTP.
- **Customer/Supplier/Product master proposed-field additions, code
  generation, GSTIN/phone uniqueness, credit-limit blocking, opening
  balance/stock** (PROMPT-007/008/009) — see PROMPT-007/008/009-NOTES.md's
  "Open decisions carried forward" sections for the full list; the same
  class of gaps as the items above, not re-litigated here.
- **Supplier bank information** — entirely unimplemented, blocked on
  **ERD-DEC-04** (BankAccount master not fully specified in the approved
  ERD). Don't add bank fields to `supplier` without that upstream decision
  being made first.
- **Product GST rate versioning** — entirely unimplemented, blocked on
  **ERD-DEC-05** (GST rate master/versioning "should be finalized in GST
  Rule Matrix", not yet done). `product.gst_rate` is a plain numeric field
  with no history/effective-dating.
- **Product stock quantity** (`stock_qty_cache`) — as of PROMPT-010, this
  now HAS a writer: `app/services/inventory/inventory_service.py`'s
  `_post_movement()`, transactionally alongside every ledger insert. Never
  write to it from anywhere else (FR-STK-05: the ledger is authoritative).
  `reorder_level` still has no writer anywhere — it's read-only at 0 for
  every product until a future prompt exposes it for editing, which also
  means the Inventory "low stock" filter is currently inert.
- **Negative stock** (OQ-008, still formally open in the FRD itself) —
  PROMPT-010 implements it as prohibited by default (stock-out/adjustment-
  out rejected if it would go negative). See PROMPT-010-NOTES.md if this
  needs revisiting.
- **Inventory location** — single lazily-provisioned "MAIN" location per
  tenant (`InventoryService.ensure_default_location()`), no location
  management API/UI exists. Multi-location/Transfer movements are out of
  scope (§8 of PROMPT-010).
- **Sales document types, numbering, GST rules** — PROMPT-011 built the
  shared services (`app/services/sales/`); PROMPT-012/013 built the first
  two concrete document types (Sales Estimate, Sales Order) on top of
  them. Delivery Challan/Sales Invoice/Sales Return still don't exist.
  When building the next document type: reuse
  `gst_calculation_service`/`document_numbering_service`/
  `sales_validation_service`/`InventoryService.post_movement` rather than
  reimplementing any of them, and add that document's own
  `sales_<type>.*`-style permission codes at that time.
- **Sales Estimate → Sales Order conversion is real, as of PROMPT-013** —
  `POST /sales/estimates/{id}/convert-to-sales-order` now creates an
  actual `sales_order` row (`SalesOrderService.create_from_estimate`) and
  returns its real `sales_order_id`. The new order's lines/totals are
  copied verbatim from the Estimate's own frozen snapshot, not re-priced
  against current Product Master prices — see PROMPT-013-NOTES.md for the
  rationale.
- **Sales Order status, as of PROMPT-014**: DRAFT, CONFIRMED,
  PARTIALLY_FULFILLED, FULFILLED, CANCELLED all exist (migration 0016
  widened `ck_sales_order_status`). `PARTIALLY_FULFILLED`/`FULFILLED` are
  set ONLY by `SalesOrderService.apply_delivery`, called from
  `DeliveryChallanService.confirm_challan` — never by any Sales Order
  endpoint directly. `sales_order_line.delivered_quantity` (also new in
  migration 0016) is the running total; `quantity - delivered_quantity`
  is "remaining," always derived, never stored separately.
- **Sales Order itself still never touches inventory directly (§4 of
  PROMPT-013, mandatory, unchanged)** — `sales_order_service.py` still
  never imports `InventoryService`/calls `post_movement`. Stock only
  moves via `delivery_challan_service.py`'s `confirm_challan`, which is
  now the FIRST Sales document type permitted to call `post_movement`.
  Verified by dedicated tests in both `test_sales_orders.py` (Sales Order
  alone never moves stock) and `test_delivery_challans.py` (Delivery
  Challan does, exactly once per line, exactly at confirm time).
- **Delivery Challan cancellation-after-confirmation is NOT implemented**
  (PROMPT-014 §11/§45 open decision #3/#4) — only DRAFT challans can be
  cancelled (`CANCELLABLE_STATUSES = {DRAFT}` in
  `app/models/delivery_challan.py`). There is no one-click reversal for a
  CONFIRMED challan's stock-out; see PROMPT-014-NOTES.md for the
  recommended future design (a `DELIVERY_CHALLAN_REVERSAL` source_type
  STOCK_IN movement) if this gets approved later.
- **Every Delivery Challan requires a source Sales Order** —
  `delivery_challan.source_sales_order_id` is `NOT NULL`; there is no
  standalone/ad-hoc Delivery Challan creation path in this codebase yet
  (PROMPT-014 open decision #11, resolved conservatively).
- **Sales Invoice's double-stock-deduction prevention, as of PROMPT-015, is
  architectural, not a runtime check** — the `DELIVERY_CHALLAN_SALES_INVOICE`
  branch of `SalesInvoiceService.post_invoice` never imports or calls
  `InventoryService`/`post_movement` at all; only the `DIRECT_SALES_INVOICE`
  branch does. Don't "helpfully" add a stock-movement call to the DC-based
  branch for consistency — that would silently reintroduce double deduction
  since the Delivery Challan already moved that stock at its own confirm
  time. See PROMPT-015-NOTES.md §16/§47.
- **Sales Invoice from a Delivery Challan prices its lines by proration, not
  by copying** — a `delivery_challan_line` has no price/GST columns at all
  (PROMPT-014's design). `SalesInvoiceService.create_invoice_from_challan`
  derives price/discount from the *originating* `sales_order_line` (via
  `delivery_challan_line.source_sales_order_line_id`), converting that SO
  line's absolute `discount_amount` to a percentage first so it scales
  correctly when the invoice quantity is smaller than what was delivered
  (partial/multiple invoicing per DC). Don't copy `discount_amount` verbatim
  onto a DC-based invoice line — see PROMPT-015-NOTES.md for why that would
  overcharge or undercharge on any partial invoice.
- **Sales Invoice accounting/GST integration is a deliberate stub, not a
  real subsystem** — `app/services/accounting/accounting_posting_service.py`
  and `app/services/sales/gst_reporting_service.py` only write an
  `AuditLog` entry and return an opaque reference string
  (`ACCPOST-<id>`/`GSTTXN-<id>`), stored on `sales_invoice` as plain text,
  NOT as foreign keys — no real GL account codes or GST transaction table
  exist yet (blocked on an approved Accounting Posting Matrix / GST module,
  neither of which exists). Don't invent real ledger/GST tables to "finish"
  this without that upstream approval.
- **Sales Invoice cancellation is DRAFT-only, same resolution as Delivery
  Challan** — `CANCELLABLE_STATUSES = {DRAFT}` in `app/models/
  sales_invoice.py`; a POSTED invoice cannot be cancelled or edited
  (immutability is enforced in `update_invoice`/`cancel_invoice`, not just
  by convention). No credit-note-style reversal exists yet — that's
  explicitly out of scope per PROMPT-015's own Stop Condition.
- **e-Invoice fields on `sales_invoice`** (`irn`, `ack_number`, `ack_date`,
  `einvoice_status`, `qr_code_data`) are reserved nullable columns only —
  no code writes to them yet. Reserved for a future PROMPT-018; don't wire
  them up without that prompt.
- **Sales Return is inventory-only, structurally separate from Credit
  Note (PROMPT-016)** — `SalesReturnService.confirm_return` creates a
  STOCK_IN and increments `sales_invoice_line.returned_quantity`; it
  never creates, references, or implies a Credit Note (no such table
  exists — PROMPT-017's own scope). Don't add a `credit_note_id` column
  or auto-create logic without that upstream approval.
- **Sales Return status is DRAFT/CONFIRMED/CANCELLED, not POSTED** — named
  to match Delivery Challan (inventory-only) rather than Sales Invoice
  (a billing document). `CANCELLABLE_STATUSES = {DRAFT}` in
  `app/models/sales_return.py`; a CONFIRMED return cannot be cancelled or
  reversed (no compensating STOCK_OUT exists) — same resolution as every
  prior stock-moving Sales document's cancellation-after-confirmation
  question.
- **Sales Return's `return_reason` is a proposed, non-final taxonomy**
  (`DAMAGED`/`WRONG_PRODUCT`/`EXCESS_QUANTITY`/`QUALITY_ISSUE`/
  `CUSTOMER_REJECTION`/`OTHER`) — no approved FRD/Data-Dictionary reason
  master exists. `OTHER` requires a non-empty `reason_description`
  (enforced both in the Pydantic schema and the service layer). Don't
  treat this list as final without Product Owner sign-off.
- **Sales Return pricing is prorated from the source Sales Invoice
  line**, never accepted from the client — the invoice line's
  `discount_amount` is converted to an equivalent percentage before
  `gst_calculation_service.calculate_line` is called with the return's
  own (possibly smaller) quantity, the same technique PROMPT-015 used for
  DC-based invoice lines. Don't copy `discount_amount` verbatim for a
  partial return — see PROMPT-016-NOTES.md for why that would misstate
  the return value.
- **`sales_invoice_line.returned_quantity`** (PROMPT-016 addition,
  migration 0018) — cumulative quantity already returned via CONFIRMED
  Sales Returns against that invoice line. Only ever written by
  `SalesReturnService.confirm_return`. `quantity - returned_quantity` is
  "returnable quantity," always derived, never stored separately —
  identical pattern to `delivery_challan_line.invoiced_quantity` and
  `sales_order_line.delivered_quantity` one level up the chain each time.
- **Salesperson's Sales Return permissions are a documented, weaker-
  signal judgment call (Open Decision, PROMPT-016 §47 #18)** — this
  prompt's own User Stories say "authorized user," not "Owner/Manager"
  (unlike Sales Order/Delivery Challan/Sales Invoice, which each had an
  explicit User-Story-3 naming). Resolved by mirroring the established
  4-for-4 pattern anyway (Salesperson gets everything except `.confirm`)
  for consistency, but flagged as needing Product Owner confirmation, not
  a settled business rule.
- **Credit Note / Debit Note create ZERO stock movement, structurally
  (PROMPT-017)** — `credit_debit_note_service.py` never imports
  `InventoryService`; there is no stock code in that file to accidentally
  run. Don't "helpfully" add a stock-movement call for either note type —
  Sales Return (PROMPT-016) owns ALL physical inventory movement; Credit/
  Debit Note is a pure financial/GST adjustment (§2/§3/§22 of that
  prompt). Verified by dedicated tests for both note types.
- **Credit Note and Debit Note share ONE table pair** (`credit_debit_note`
  / `credit_debit_note_line`), distinguished by `note_type`
  (`'CREDIT_NOTE'`/`'DEBIT_NOTE'`, widened from the Data Dictionary
  baseline's VARCHAR(10) to fit these self-describing values — documented
  deviation, not silent). RBAC in `app/api/v1/credit_debit_notes.py`
  checks the `note_type`-specific permission per request dynamically
  (`credit_note.*` vs `debit_note.*`) rather than a single static
  `require_permission(...)` dependency — keep that pattern if you add a
  new action to this router.
- **Every Credit/Debit Note requires a source POSTED Sales Invoice** —
  `credit_debit_note.source_invoice_id` is `NOT NULL`; there is no
  Credit-Note-from-Sales-Return path (PROMPT-017 open decision #5 — the
  baseline schema has no such column). Don't add one without an approved
  schema change.
- **`sales_invoice_line.credited_quantity`/`.debited_quantity`**
  (PROMPT-017 addition, migration 0019) — cumulative quantity already
  adjusted via POSTED Credit Notes / Debit Notes against that invoice
  line. Only ever written by `CreditDebitNoteService.post_note`, per
  `note_type`. `quantity - credited_quantity` is "creditable quantity";
  the debited-quantity cap is a **documented, unconfirmed placeholder**
  (Open Decision #10/#28, PROMPT-017-NOTES.md) — no approved source
  confirms a Debit Note should really be bounded by the original invoiced
  quantity at all (e.g. a short-billing correction might need to exceed
  it). Don't treat this as a settled business rule.
- **Debit Note's accounting direction is an explicit Open Decision
  (#28), not a confirmed rule** — `AccountingPostingService.
  post_credit_debit_note` implements it as the conventional mirror-
  opposite of Credit Note (Debit AR / Credit Revenue+GST) purely as a
  safe placeholder. Do not treat this as authoritative without Product
  Owner / Accounting module sign-off.
- **Credit/Debit Note's `reason` field is deliberately free text, NOT a
  controlled enum** — unlike Sales Return's own proposed reason
  taxonomy (PROMPT-016), this prompt's own §4 explicitly forbade
  inventing a reason taxonomy without approved requirements. Don't add a
  CHECK constraint or enum here without that approval.
- **`ProductLineSelector`'s discount fields default to `'0'`, not empty**
  — any new consumer of `shared/ProductLineSelector.tsx` (Estimate and
  Sales Order both already apply this fix) must forward only whichever of
  `discountPercent`/`discountAmount` is actually non-zero to the backend
  (never both, even though both are always populated in the component's
  own state) — see PROMPT-012-NOTES.md for the bug this caused.
- **`audit_log`/`stock_ledger_entry` immutability** — enforced by a
  BEFORE UPDATE/DELETE trigger (migrations 0012/0011 respectively), NOT
  by the `REVOKE UPDATE, DELETE ... FROM PUBLIC` statements that are also
  present — those REVOKEs do nothing because the app's DB role owns both
  tables, and PostgreSQL ownership bypasses a role's own grant/revoke
  restrictions. If you add another append-only table, use a trigger, not
  a bare REVOKE.
- **No real GST/NIC integration provider exists (PROMPT-018)** —
  `app/services/gst_integration/provider.py`'s `SandboxSimulatorProvider`
  is a deterministic, fully-local dev/test stub; `get_einvoice_provider()`/
  `get_eway_bill_provider()` RAISE if `is_production` is true, the same
  fail-loudly discipline as `get_recovery_provider()`. Do not wire a real
  provider in without an explicit product/security/legal decision (§43
  Open Decision #1, PROMPT-018-NOTES.md).
- **E-Invoice/E-Way Bill idempotency is two layers, not one** — the
  existing `IdempotencyService` (HTTP replay guard) is necessary but NOT
  sufficient on its own; `EInvoiceService.generate`/`EWayBillService.
  generate` additionally lock the `einvoice`/`eway_bill` row and check
  its `status` before proceeding — THIS is what stops two different
  Idempotency-Keys from both reaching the provider. Don't remove the row
  lock thinking the HTTP-level guard alone is enough.
- **`STATUS_UNKNOWN` (provider timeout) must reconcile before ever
  retrying** — never add a code path that calls `generate_irn`/
  `generate_eway_bill` again without first calling `get_irn_status`/
  `get_eway_bill_status` when the record is in `STATUS_UNKNOWN`. When a
  safe retry is needed, it reuses the ORIGINAL attempt's idempotency key
  (stored on the prior `integration_operation` row), never a fresh one.
- **E-Invoice/E-Way Bill applicability is a tenant toggle, not a legal
  rule engine** — `integration_configuration.einvoice_enabled`/
  `.eway_bill_enabled` (default true, lazily provisioned per tenant) plus
  a posted/not-cancelled check is the ENTIRE applicability rule. No
  turnover threshold, B2B/B2C carve-out, or transaction-type rule is
  implemented — none is approved anywhere in this codebase's source
  documents (§43 Open Decision #4/#5). Don't invent one.
- **No automatic background retry exists for E-Invoice/E-Way Bill** —
  `integration_configuration.max_retry_attempts`/`.retry_backoff_seconds`/
  `.rate_limit_per_minute` columns exist but are NOT enforced by any
  retry loop; every retry in this MVP is a fresh user-triggered request
  (§43 Open Decision #8/#9/#10 — no background-worker technology exists
  anywhere in this codebase).
- **Sales Invoice's reserved `irn`/`ack_number`/`ack_date`/
  `einvoice_status`/`qr_code_data` columns (migration 0017) are now
  written to** — kept in sync as a denormalized snapshot by
  `EInvoiceService`'s `_sync_invoice_snapshot`, but the AUTHORITATIVE
  record is the new `einvoice` table. Don't write to those invoice
  columns from anywhere else.
- **Purchase Order never touches inventory, structurally (PROMPT-019,
  mirrors Sales Order's identical rule)** — `purchase_order_service.py`
  never imports `InventoryService`/calls `post_movement`. Stock only
  moves via `goods_receipt_service.py`'s `confirm_receipt` (STOCK_IN)
  and `purchase_return_service.py`'s `confirm_return` (STOCK_OUT).
- **Purchase Invoice's double-stock-duplication prevention is
  architectural, not a runtime check (PROMPT-019, mirrors PROMPT-015's
  identical Sales Invoice design)** — the `GOODS_RECEIPT_PURCHASE_INVOICE`
  branch of `PurchaseInvoiceService.post_invoice` never imports or calls
  `InventoryService`/`post_movement`; only the `DIRECT_PURCHASE_INVOICE`
  branch does. Don't add a stock-movement call to the GR-based branch —
  the Goods Receipt already moved that stock at its own confirm time.
- **GR-based Purchase Invoice line pricing does NOT need discount
  proration in this foundation** — unlike Sales Invoice's DC-branch or
  Purchase Return's own line pricing, `goods_receipt_line.discount_amount`
  is always 0 (no receipt-time discount input path exists), so
  `PurchaseInvoiceService.create_invoice_from_receipt` copies the GR
  line's price/GST directly. If a future prompt adds receipt-time
  discounts, this will need the same percentage-proration technique
  used elsewhere in this codebase.
- **No accounting/GST integration boundary exists for Purchase
  Invoice** — a deliberate, explicit scope exclusion per PROMPT-019's
  own §14 instruction ("Do not implement accounting posting in this
  prompt"), unlike Sales Invoice's `AccountingPostingService`/
  `GstReportingService` calls (PROMPT-015). Don't "helpfully" add these
  calls for consistency without new instruction.
- **Every Purchase Return requires a source POSTED Purchase Invoice**
  (`purchase_return.source_purchase_invoice_id` NOT NULL) — there is no
  GR-sourced or standalone Purchase Return path (PROMPT-019, matches
  the baseline schema itself, same resolution shape as Sales Return's
  `source_invoice_id`).
- **Salesperson gets ZERO Purchase permissions (PROMPT-019) — NOT a
  weak-signal judgment call, unlike several Sales-module RBAC
  decisions** — FRD Table 7 lists Purchase Orders/Goods Receipt/
  Purchase Invoice as "Owner, Manager" with no Salesperson row at all.
  `purchase_order.*`/`goods_receipt.*`/`purchase_invoice.*`/
  `purchase_return.*` (20 codes) are on OWNER/MANAGER only.
- **No ad-hoc (PO-less) Goods Receipt path is exercised** — 
  `goods_receipt.source_purchase_order_id` is nullable in the schema,
  but no service method in PROMPT-019 creates one without a source
  Purchase Order. Don't assume this path works without adding and
  testing it first.
- **No direct Purchase-Order-to-Invoice path exists** — `purchase_invoice`
  has no `source_purchase_order_id` column at all; a Purchase Invoice is
  either fully direct (no source) or sourced from a Goods Receipt, never
  directly from a Purchase Order skipping the receipt step.
- **Purchase Order confirmed/cancelled is idempotent via its existing
  status guard + row_version check, not a new mechanism (PROMPT-020)**
  — don't add an `Idempotency-Key`/`_idempotent_post` wrapper to
  `confirm_order`/`cancel_order` "for consistency" with create/GR-confirm/
  invoice-post; a retried confirm/cancel is already safely rejected
  (412 stale row_version, or 422 already-transitioned) with zero
  duplicate audit events, matching Sales Order's own established
  convention. Explicitly verified by
  `test_duplicate_confirmation_request_rejected_no_duplicate_state`/
  `test_duplicate_cancellation_request_rejected_no_duplicate_state` in
  `test_purchase_order_management.py`.
- **`audit_log` now has its first READ path** (PROMPT-020,
  `PurchaseOrderService.get_audit_history` / `GET /purchase/orders/
  {id}/audit-history`) — deliberately narrow and PO-scoped, NOT a
  general audit-log browsing API. If a future prompt needs audit
  history for another document type, add its own narrow, entity-scoped
  read method (mirroring this one's tenant-ownership-check-first
  discipline) rather than building a generic `/audit-log` endpoint
  without an approved requirement for one.
- **Purchase Order list/detail ordered/received/remaining quantities**
  (PROMPT-020, migration-free — computed, not stored) — `QuantityTotals`/
  `PurchaseOrderService.totals_from_lines` (pure, from an already-
  fetched line list) vs `_quantity_totals_for_orders` (ONE aggregate
  query for a whole list page, never N+1) are two DIFFERENT code paths
  for the same computation — use `totals_from_lines` wherever the lines
  are already in hand (get/create/update/receiving-summary), and only
  use the aggregate query for `list_orders`. Don't call
  `_quantity_totals_for_orders` in a per-row loop.
- **Purchase Order's `currency`/`location_id`/freight/PO-approval-
  workflow/PO-revision-versioning are all explicit Open Decisions, not
  silently resolved (PROMPT-020 §48)** — no currency column was added
  (this MVP assumes INR-only throughout), no location_id FK was added
  (M1 has exactly one lazily-provisioned "MAIN" location, PROMPT-010
  §8), no freight/landed-cost field exists, confirmation is a single
  permission check with no multi-step/threshold approval chain, and
  `row_version` is optimistic-concurrency only, not a user-facing
  revision history. See `PROMPT-020-NOTES.md` §12 for the full 29-item
  table before building any of these without new instruction.
- **Goods Receipt cancellation is now a REAL reversal for a CONFIRMED
  receipt, not just a DRAFT-only status change (PROMPT-021)** —
  `GoodsReceiptService.cancel_receipt`'s CONFIRMED branch posts one
  compensating STOCK_OUT per line (`source_type='GOODS_RECEIPT_REVERSAL'`,
  same `source_id` as the original STOCK_IN's `source_type='GOODS_RECEIPT'`
  entry — they coexist under `uq_stock_ledger_entry_source` without
  colliding) and calls the new `PurchaseOrderService.apply_reversal` to
  roll back `received_quantity`/status. Gated by TWO conditions, both of
  which must be checked before touching anything: (a) no line's
  `goods_receipt_line.invoiced_quantity > 0` (else `GR_HAS_DOWNSTREAM_
  INVOICE`/422), and (b) `InventoryService.post_movement`'s own
  negative-stock guard (409 if the received stock was already consumed
  elsewhere). Don't add a "force reverse" override without new
  instruction — the second guard in particular is a correctness
  invariant, not an inconvenience to route around.
- **The original Goods Receipt STOCK_IN ledger entry is NEVER edited or
  deleted on cancellation (INVARIANT 7, PROMPT-021)** — only a NEW
  compensating STOCK_OUT entry is added. If you add reversal support to
  another stock-moving document (Purchase Invoice, Sales Invoice,
  Delivery Challan, etc.), follow this exact pattern: a distinct
  `source_type` value (e.g. `<DOCUMENT>_REVERSAL`) reusing the same
  `source_id`, never an UPDATE/DELETE against `stock_ledger_entry` —
  the table's own BEFORE UPDATE/DELETE trigger (migration 0011) would
  reject an edit attempt anyway, but the service-layer design should
  never even try.
- **`GoodsReceiptService.stock_movement_info_for_lines` is public,
  called from BOTH `get_receipt` and the `confirm` router endpoint
  (PROMPT-021)** — don't revert the confirm endpoint to building its
  response from `confirm_receipt`'s own return value alone; that value
  has no stock-movement id attached, so a client reading the CONFIRM
  response directly (rather than re-fetching via GET) would incorrectly
  see `stock_movement_id: null` even though the ledger entry exists.
  This was a real bug caught during PROMPT-021's own test-writing pass.
- **Purchase Invoice's `invoiced_quantity` bookkeeping columns
  (`goods_receipt_line.invoiced_quantity`,
  `sales_invoice_line.returned_quantity`, etc.) only increment at POST/
  CONFIRM time, never at DRAFT-creation time** — this is an established
  pattern across the whole codebase (PROMPT-015 onward), not new to
  PROMPT-021, but it's an easy trap when writing a downstream-dependency
  check or a test: creating a DRAFT document against a source line does
  NOT yet count as a dependency for that source line's own cancellation/
  reversal guards. Only a POSTED/CONFIRMED downstream document does.
- **Purchase Invoice now has a THIRD invoice_type,
  `PURCHASE_ORDER_PURCHASE_INVOICE` (PROMPT-022) — this is NOT a third
  stock-impact scenario, it's still Scenario A (no stock movement)**,
  computed at the PO level instead of requiring one pre-selected GR. A
  requested PO-line quantity is fanned out across that PO line's own
  contributing confirmed GR lines (oldest first) — ONE requested line
  can produce SEVERAL `purchase_invoice_line` rows, each still tracing
  to a specific `goods_receipt_line` via `source_goods_receipt_line_id`
  (never invoice-before-receipt — see the Open Decision #2 resolution
  in `PROMPT-022-NOTES.md`). Both `GOODS_RECEIPT_PURCHASE_INVOICE` and
  `PURCHASE_ORDER_PURCHASE_INVOICE` share the SAME `goods_receipt_line.
  invoiced_quantity` counter — don't add a second, PO-scoped invoiced-
  quantity counter for the new type; that would break INVARIANT 5 (one
  physical receipt must not be counted twice) by letting the two paths
  independently over-invoice the same underlying receipt.
- **`PurchaseInvoiceService.post_invoice`'s non-DIRECT branch locks
  EVERY DISTINCT source Goods Receipt an invoice's own LINES reference
  (sorted, to avoid lock-ordering deadlocks), not just one
  (PROMPT-022)** — this generalization (from "lock `invoice.source_
  goods_receipt_id`") is what lets `GOODS_RECEIPT_PURCHASE_INVOICE`
  (always exactly one GR) and `PURCHASE_ORDER_PURCHASE_INVOICE`
  (possibly several) share one code path. If you add a fourth invoice
  type that references source documents some other way, follow this
  "derive locked resources from the lines actually present" pattern
  rather than re-introducing a header-level single-source assumption.
- **Purchase Invoice cancellation is now a REAL reversal for a POSTED
  invoice (PROMPT-022), following Goods Receipt's own PROMPT-021
  precedent exactly** — a DIRECT invoice's cancellation posts a
  compensating STOCK_OUT per line (`source_type='PURCHASE_INVOICE_
  REVERSAL'`, coexists with the original `'PURCHASE_INVOICE'` STOCK_IN
  entry under `uq_stock_ledger_entry_source` without colliding); a
  GR/PO-sourced invoice's cancellation NEVER touches stock (§35 — the
  source GR remains the physical receipt), only releases its own
  bookkeeping claim on each line's source `goods_receipt_line.
  invoiced_quantity`. Gated by no downstream Purchase Return
  (`purchase_invoice_line.returned_quantity == 0` on every line, else
  `PINV_HAS_DOWNSTREAM_RETURN`/422) and, for the DIRECT path,
  `InventoryService`'s own negative-stock guard (409 if the stock was
  already consumed elsewhere) — same two-guard shape as Goods Receipt's
  own reversal. Don't add a "force reverse" override without new
  instruction.
- **Supplier invoice number uniqueness is a non-blocking WARNING, not
  an enforced constraint (PROMPT-022 §7)** — `PurchaseInvoiceService.
  check_duplicate_supplier_invoice` is queried by the router and
  surfaced as `duplicate_supplier_invoice_warning` on create/update/get
  responses; it never rejects the request. Don't add a DB unique
  constraint on `(tenant_id, supplier_id, supplier_invoice_number)`
  without an explicit approved uniqueness policy — the baseline's own
  Data Dictionary annotation says "Duplicate policy to confirm."
- **Purchase Return cancellation is now a REAL reversal for a CONFIRMED
  return, not just a DRAFT-only status change (PROMPT-023)** —
  `PurchaseReturnService.cancel_return`'s CONFIRMED branch posts one
  compensating STOCK_IN per line (`source_type='PURCHASE_RETURN_
  REVERSAL'`, same `source_id` as the original `'PURCHASE_RETURN'`
  STOCK_OUT entry — they coexist under `uq_stock_ledger_entry_source`
  without colliding, the original is never edited/deleted) and
  decrements the source invoice line's `returned_quantity` bookkeeping
  counter, releasing that quantity for reuse. Unlike Goods Receipt's own
  reversal (PROMPT-021) or a DIRECT Purchase Invoice's own reversal
  (PROMPT-022) — both of which can be rejected by the negative-stock
  guard — this reversal is a STOCK_IN and can NEVER be rejected that
  way; restocking previously-removed goods only ever increases stock.
- **No downstream-dependency guard exists for Purchase Return
  cancellation (PROMPT-023 §34) — because nothing downstream exists
  yet, not because the check was skipped** — no table in this codebase
  currently references `purchase_return` (no Credit/Debit Note,
  Supplier Payment, or Accounting Posting link exists). If a future
  prompt adds any such link, it MUST add an explicit guard here first
  (mirroring `PINV_HAS_DOWNSTREAM_RETURN`'s own pattern) before this
  cancellation path can be considered complete against that new
  document type — see `PROMPT-023-NOTES.md` §19 Known Limitations.
- **A Purchase Return's lines always trace to exactly one source
  Purchase Invoice** — there is no PO-consolidated or multi-invoice
  return (the mirror image of Purchase Invoice's own PO-consolidated
  type from PROMPT-022 was considered and explicitly NOT built — see
  Open Decisions #32/#33 in `PROMPT-023-NOTES.md`).
- **Payments & Collections is a NEW cross-cutting module, not owned by
  either the Sales or Purchase document chain (PROMPT-024)** —
  `payment`/`payment_allocation` (migration 0025) are the FIRST tables
  in this codebase outside those two chains. `sales_invoice.
  paid_amount`/`.payment_status` and `purchase_invoice.paid_amount`/
  `.payment_status` are new reconciliation CACHE columns, only ever
  written by `PaymentService` — don't write to them from anywhere else
  (same discipline as `product.stock_qty_cache`).
- **A Payment's reversal is a status flip on the SAME immutable row
  (POSTED→REVERSED), not a new compensating-ledger-entry (PROMPT-024
  §17)** — unlike Goods Receipt/Purchase Invoice/Purchase Return's own
  `<DOCUMENT>_REVERSAL` stock-ledger pattern, Payments has no append-
  only ledger of its own yet (that arrives with PROMPT-025's Accounting
  Posting Matrix). `PaymentAllocation` rows are never deleted on
  reversal — `_recalculate_invoice_payment_state` only aggregates
  allocations whose PARENT payment is currently POSTED, so a REVERSED
  payment's allocations simply stop counting. Only FULL reversal is
  supported (no partial reversal).
- **A BOUNCED cheque reuses the Payment reversal mechanism, not a
  separate exclusion path (PROMPT-024 §19)** —
  `PaymentService.mark_cheque_status` calls `reverse_payment` internally
  when transitioning to BOUNCED. Don't add a second "exclude this
  payment's allocations from outstanding" code path — there is
  deliberately only one.
- **On-account (partial) payment posting is supported by construction,
  not a settled product decision (PROMPT-024 §50 OD-001)** — a payment
  can post with `allocated_amount < amount`; the difference is tracked
  as `unallocated_amount`, never silently discarded. This was resolved
  from §13's own mandate and the mandatory TC-018 test, not guessed —
  flag it if a stricter "must be fully allocated before posting" policy
  is later approved.
- **This is the first prompt since PROMPT-019 to introduce brand-new
  tables and brand-new permission codes** — migration 0025 follows
  migration 0021's own precedent (Row-Level Security enabled per new
  table + new permission codes backfilled onto every EXISTING tenant's
  roles, not just newly-created ones) rather than the "reuse existing
  permissions" pattern PROMPT-020-023 used. If a future prompt adds
  another brand-new table/permission set, follow this same precedent.
- **`AccountingPostingService` is now a REAL double-entry ledger, not a
  stub (PROMPT-025)** — `sales_invoice.accounting_posting_reference`
  etc. now hold real `journal_number`s (e.g. `JRN-2026-27-0001`), not
  opaque `ACCPOST-<id>` strings. Every posting rule goes through the
  ONE generic `JournalService.post_journal` — don't add a second,
  module-specific journal-creation code path.
- **No account id is ever hard-coded anywhere in this codebase — every
  posting rule resolves through a `posting_rule_code`** (`app.core.
  accounting_constants.POSTING_RULE_CODES`), looked up per-tenant via
  `ChartOfAccountsService.resolve_account`. The seeded default Chart of
  Accounts (`DEFAULT_ACCOUNT_SEED`) is explicitly a starting point, not
  an approved final COA — don't treat its account codes/names as fixed.
- **No COGS/Inventory journal leg exists anywhere (PROMPT-025 §56
  OD-005/006/007/024)** — Sales Invoice/Purchase Invoice posting only
  ever touches Receivable/Payable/Revenue/Expense/GST accounts, never
  an Inventory or COGS account. The Stock Ledger (PROMPT-010) remains
  the sole inventory source of truth; don't add an inventory-valuation-
  dependent journal line without that policy being approved first.
- **No Goods Receipt journal exists (OD-008/009/025)** — Goods Receipt
  still creates zero accounting entries, exactly as before PROMPT-025.
  Purchase-side financial recognition happens ONLY at Purchase Invoice
  posting, mirroring the Sales-side "recognition at Invoice, not at
  Delivery Challan" precedent.
- **Journal reversal is a brand-new journal with `reversal_of_journal_
  id` set, never an edit to the original (PROMPT-025 §33)** — wired
  automatically into `PurchaseInvoiceService.cancel_invoice`'s POSTED
  branch, `PurchaseReturnService.cancel_return`'s CONFIRMED branch, and
  `PaymentService.reverse_payment` (which transitively covers cheque-
  bounce). If a future prompt adds POSTED-cancellation-with-reversal to
  another accounting-aware document type (Sales Invoice, Sales Return,
  Credit/Debit Note — none of which currently support cancelling a
  POSTED instance), it must call `AccountingPostingService`'s own
  reversal method at that point, following this exact pattern.
- **`accounting_period` is a posting GUARD only, not a period-close
  workflow (OD-018/019)** — a period row can currently never become
  CLOSED through any implemented code path. Don't build UI/API assuming
  period-close exists until a future prompt actually implements it.
- **The GST CALCULATION engine (`app.services.sales.
  gst_calculation_service`, PROMPT-011) was already the one authoritative
  engine before PROMPT-026 — confirmed by code reading, not rebuilt.**
  PROMPT-026 only added the REPORTING layer (`gst_transaction`/
  `gst_transaction_line`, PROMPT-026) on top of it. Don't add a second
  GST-calculation code path anywhere — every module reuses
  `calculate_line`/`calculate_document_totals`/`determine_gst_treatment`
  unmodified.
- **`gst_transaction` mirrors `journal_entry`'s exact idempotency/
  reversal shape (PROMPT-026)** — `(tenant_id, source_type, source_id,
  event_type)` is unique; a REVERSAL is a brand-new row with NEGATED
  amounts (never an edit to the ORIGINAL, §21 immutability — verified by
  a dedicated test that changes a product's `gst_rate` after posting and
  confirms the snapshot is unchanged). Sign convention: Sales Invoice/
  Debit Note/Purchase Invoice are POSITIVE; Sales Return/Credit Note/
  Purchase Return are NEGATIVE — this is what makes a period `SUM()`
  give the correct net GST position without bucket-type special-casing.
  If you add reversal support to another document type, follow this
  exact "new row, negated amounts, `reversal_of_transaction_id` set"
  pattern rather than editing the original.
- **GstReportingService now creates REAL rows, not an audit-only stub
  (PROMPT-026)** — its 3 pre-existing methods (`record_invoice_
  transaction`/`record_return_transaction`/`record_credit_debit_note_
  transaction`) kept identical signatures for zero call-site changes; 4
  NEW methods (`record_purchase_invoice_transaction`/`reverse_purchase_
  invoice_transaction`/`record_purchase_return_transaction`/`reverse_
  purchase_return_transaction`) close the Purchase-side Input GST/ITC
  gap that existed since PROMPT-019. Every method ALSO writes a
  `GST_TRANSACTION_CREATED`/`GST_TRANSACTION_REVERSED` AuditLog entry
  scoped to the SOURCE entity's own `entity_type`/`entity_id` (not
  `gst_transaction`'s) — don't remove that audit call thinking the
  `gst_transaction` row alone is sufficient; a source document's own
  `GET .../audit-history` endpoint depends on it, exactly the same class
  of bug PROMPT-025 hit with `ACCOUNTING_POSTED`.
- **GSTIN/HSN validation is NOT a hard gate on Sales/Purchase document
  posting (PROMPT-026, deliberate)** — `app/services/gst/
  gst_validation_service.py`'s format checks are wired ONLY into
  `GstrService.validate_gstr1`/`validate_gstr3b` (return-preparation
  time), never into any document service's own post/confirm flow. Don't
  add a validation call to `sales_invoice_service.py`/
  `purchase_invoice_service.py` etc. "for consistency" without checking
  whether it would break existing test fixtures that use invalid/missing
  GSTIN or HSN test data — this was assessed and deliberately deferred.
- **No persisted "GST Return" entity, no DRAFT/VALIDATED/SUBMITTED
  status column anywhere (PROMPT-026 §56 OD-010/OD-011)** — GSTR-1/
  GSTR-3B/dashboard/reconciliation are entirely computed on demand from
  `gst_transaction` every time they're requested. Don't add a "Submit to
  GST Portal" button or any code path that could be read as claiming a
  return was actually filed — no real submission provider exists.
- **The GST engine never creates or touches an accounting journal, and
  vice versa (PROMPT-026 §25, structural)** — `app/services/gst/` has
  zero imports of `JournalService`/`AccountingPostingService`; the only
  connection between the two modules is `GstrService.reconciliation`,
  which READS `journal_line` (joined through `account_mapping`) purely
  to cross-check totals, never writes to it.
- **The Reporting layer (PROMPT-027) introduced ZERO new business
  tables** — every report is a live SQL aggregation over already-
  authoritative tables. If you add a new report, follow this same
  discipline: never invent a persisted/materialized report table, never
  recalculate a business/accounting/GST value a source module already
  computed. `app/services/reports/*.py`'s own module docstrings each
  carry that report family's Definition/Source/Formula/Date-Basis spec —
  read the relevant one before changing or extending a report.
- **Outstanding (Receivables/Payables) is always `invoice.grand_total -
  invoice.paid_amount` computed directly on the invoice** — NOT
  `customer.balance`/`supplier.balance` (separate reconciliation caches
  that exist but are deliberately not used as this report's source of
  truth). Don't switch to the cache columns without verifying they're
  actually kept in sync with `payment_allocation` first.
- **General Ledger's per-account balance query pre-aggregates
  `journal_line`+`journal_entry` in a subquery BEFORE joining to
  `chart_of_account`, never as two chained outer joins (PROMPT-027, a
  real bug caught during implementation)** — two chained outer joins
  (ChartOfAccount → JournalLine → JournalEntry-with-date-filter) do NOT
  correctly exclude a line when only the date-filtered JournalEntry join
  fails to match, since a later failed outer join never retroactively
  nulls an earlier one's already-matched row. If you write another
  per-account/per-period accounting aggregation, follow `accounting_
  report_service.py`'s own `_account_balances` pattern (pre-aggregate
  in a subquery first), not a naive multi-outer-join.
- **Balance Sheet's "Current Period Earnings" line is the SAME Net
  Profit the P&L computes from the SAME posted journal lines — never a
  plug value** (PROMPT-027 §37/§38). `Assets = Liabilities + Equity +
  NetProfit` is a mathematical identity of double-entry bookkeeping,
  not an assumption — the balance check (`is_balanced`/`difference`)
  is a genuine integrity verification against a real bug, not a
  tautology. Don't "simplify" this into deriving Equity as `Assets -
  Liabilities` — that WOULD be a plug and would defeat the point of the
  validation.
- **Dashboard KPIs are reconciled with detailed reports BY
  CONSTRUCTION** (PROMPT-027 §41) — `DashboardService` calls the
  identical `SalesReportService`/`PurchaseReportService`/
  `ReceivablesPayablesService` method (same date range) each detailed
  report itself calls, rather than maintaining a second calculation.
  Don't add a new dashboard KPI by writing fresh aggregation logic if an
  equivalent report-service method already exists — call that instead.
- **Report/dashboard export (Excel/CSV/PDF) is NOT implemented
  (PROMPT-027 §62 OD-018/019/020)** — every `/reports/*` endpoint
  returns JSON only. A `reports.export` permission exists (seeded,
  assigned to Owner/Manager) but no endpoint currently checks it —
  don't assume it's wired to anything.
- **Inventory Value is never computed or shown anywhere in Reports
  (PROMPT-027 §8/OD-002/OD-003)** — `dashboard.inventory.inventory_
  value` is always `null`. No inventory valuation method (FIFO/
  weighted-average/standard-cost) is approved. Don't add one without
  that approval — this mirrors PROMPT-025's own identical COGS
  restraint one level up.
- **Report/export VIEWING is not audited (PROMPT-027 §52, deliberate)**
  — no precedent exists anywhere in this codebase for auditing read-only
  GET requests, and doing so for potentially high-volume report views
  was judged out of proportion without an approved requirement forcing
  it. Don't add report-view audit logging without new instruction.
- **The offline sync engine (PROMPT-028) reuses the EXISTING `POST
  /customers`/`POST /suppliers`/`POST /sales/invoices` endpoints — there
  is NO generic `POST /sync` endpoint anywhere in this codebase.** If
  you expand offline-write scope to another entity, follow this same
  pattern (make that entity's create endpoint accept an OPTIONAL
  `Idempotency-Key` header if it doesn't already, mirroring `customers.py`/
  `suppliers.py`'s own addition) rather than building a second,
  parallel creation path.
- **Offline sync only ever CREATES a Sales Invoice (DRAFT, real
  server-assigned `invoice_number`) — it never POSTS one.** GST/
  Accounting/E-Invoice processing all happen at POST time, a separate,
  unchanged, online-only user action via the existing Sales Invoice
  screen. Don't add an auto-post-after-sync code path — that would
  violate §32/§33's own explicit "accounting/GST only after server
  posting" mandate.
- **`pwa/offlineDb.ts`'s `sync_queue` store IS the offline state machine
  (PROMPT-028 §20)** — a record's `status` field moves through
  `LOCAL_DRAFT → PENDING_SYNC → SYNCING → SYNCED` (or `SYNC_FAILED`/
  `CONFLICT`/`REQUIRES_ACTION`) in place; there is no separate physical
  store per category and no boolean `is_synced` flag anywhere. Don't
  add one — use the existing status enum.
- **Stock conflicts during offline sync reuse PROMPT-010's own already-
  resolved negative-stock-prohibited policy** — no new stock policy
  exists for offline sync specifically. If that policy ever changes,
  `pwa/syncEngine.ts`'s `classifySyncFailure` needs no changes (it just
  maps whatever the existing endpoint returns); only `InventoryService`
  itself would need updating.
- **Nothing in this codebase ever auto-deletes a `PENDING_SYNC`/
  `SYNC_FAILED`/`CONFLICT`/`REQUIRES_ACTION` sync-queue record**
  (PROMPT-028 §51, a structural guarantee, not just a tested behavior)
  — only a user-initiated cancel of a not-yet-synced item removes one
  from active consideration (and even then it's marked, not deleted).
  Don't add a cleanup job that could violate this without an explicit,
  safe retention policy design (OD-009/OD-010 stay open).
- **Real-browser IndexedDB/Service-Worker/offline-restart behavior was
  NOT independently verified in this session** (PROMPT-028) — jsdom
  (this project's Vitest environment) has no IndexedDB implementation
  and no polyfill dependency was added; only the pure, side-effect-free
  sync-engine logic (conflict classification, backoff, dependency
  ordering) is automated-tested. Don't claim TC-001–003/008/009/032/
  033/043–050 pass without actual browser verification first.
- **`payroll_record` (+`payroll_record_line`) IS the payslip — there is
  no separate `payslip` table (PROMPT-029)**. Don't create one; add
  columns to `payroll_record` instead if a future prompt needs more
  payslip fields.
- **Salary Structure has NO `effective_to` column, by design
  (PROMPT-029 §11/§12)** — the structure applicable for any date is
  always "the one with the latest `effective_from` <= that date."
  Don't add an end-date column "for clarity" — doing so would require
  also enforcing non-overlap between `effective_from`/`effective_to`
  pairs, which this design deliberately avoids needing.
- **Payroll Run lifecycle is DRAFT→CALCULATED→FINALIZED(+REVERSED) —
  NOT a 5-stage DRAFT/REVIEWED/APPROVED chain (PROMPT-029 §35/OD-021)**
  — no approved source defines a separate reviewer role. If a future
  prompt adds one, it needs its own explicit instruction first; don't
  infer it from the original PROMPT-029 spec's own suggested (but
  unapproved) 5-stage wording.
- **Payroll proration (mid-period joining, mid-period exit, unpaid
  leave) is ONE unified `payable_days / calendar_days` formula
  (PROMPT-029 §21-§24, OD-016/017/018)** — not three separate rules.
  `app/services/payroll/payroll_calculation_service.py`'s own module
  docstring has the full rationale. Don't add a separate proration
  formula for one of the three scenarios without revisiting all three
  together.
- **`DocumentNumberingService.next_number_no_fy` (PROMPT-029) is for
  identifiers that must NEVER reset annually** (currently only Employee
  Code) — distinct from `next_number` (every GST/financial document,
  resets every financial year). If a future prompt needs another
  permanent, non-resetting sequence, reuse `next_number_no_fy` rather
  than inventing a new counter mechanism.
- **Payroll accounting posting is CONSOLIDATED (one journal per payroll
  run), never per-employee (PROMPT-029 §59 OD-025)** — `Accounting
  PostingService.post_payroll_run` takes the run's own totals, not a
  per-employee breakdown. Don't post per-employee journals without new
  instruction — that would multiply journal volume for no approved
  reason.
- **No PF/ESI/TDS/statutory payroll exists anywhere (PROMPT-029 §3/§67,
  structural)** — no such posting_rule_code, salary component type, or
  calculation exists in the schema. Don't add one without explicit
  Product Owner approval and a new prompt — this is a hard MVP
  boundary, repeatedly emphasized in the source spec.
- **Payroll has NO offline-write path (PROMPT-029 §61)** — never wired
  into PROMPT-028's `pwa/syncEngine.ts`. Don't add one without revisiting
  PROMPT-028's own offline-write scope decision (OD-001) first.

## 4b. Microservices migration (branch `feature/microservices-phase-1a`)

Incremental, approved plan: Phase 1A (foundation) -> 1B (extract Identity, Tenant, Master Data) only after explicit approval. **The monolith in `backend/app` still serves the whole API.**
- `backend/gateway/` — reverse-proxy gateway (routing table `app/core/routing.py`, `AUTH_MODE=passthrough|verify`). Run its tests in their OWN process: `cd backend/gateway && pytest` (the monolith also has a top-level `app` package).
- `backend/shared/` — framework-only kit (logging, error envelope, JWT verify, correlation, `ServiceClient`). No business logic, no DB. Tests: `cd backend && pytest shared/tests`.
- `database/documentation/schema-ownership.json` — table -> future owning schema; guarded by `tests/unit/test_schema_ownership.py` (every new model MUST be added to it). No table has been moved.
- **RLS is ENABLED but not FORCEd and the app role owns the tables, so it is NOT enforced for the app** (`database/documentation/rls-status.md`). Isolation relies on application filtering. Do not assume RLS protects you.
- Sales/Inventory/Accounting/GST must stay in one process/transaction until Outbox + idempotent consumers + compensation + reconciliation are built and tested (`docs/architecture/transactional-boundary.md`).
- Run backend tests against a LOCAL Postgres (override `DATABASE_URL`), never the Supabase DB: integration tests commit real rows.

## 5. What's Pending / Next Steps

- **PROMPT-030 onward**: no further prompts have been given yet.
  PROMPT-029 built the Employee, Payroll & Basic Salary Management
  module (Employee Master, effective-dated Salary Structure/
  Components, Attendance, Leave, Payroll Period/Run, payslips, and
  Accounting integration) on top of every module through PROMPT-028.
  Still unbuilt/explicitly deferred: dedicated `/reports/payroll/*`
  endpoints (Payroll Register/Employee List/Attendance Report — the
  equivalent data exists in `PayrollManagement.tsx`'s own views, but no
  formal Reports-module integration was built), payslip PDF generation
  (OD-027), payroll export formats (OD-028), Department/Designation
  master tables (OD-006/OD-007), employee self-service/portal access
  (OD-030/OD-031), per-employee (rather than whole-run) payroll
  correction, and any statutory payroll compliance (PF/ESI/TDS/
  Professional Tax — explicitly and repeatedly out of scope, §3/§67).
  See `PROMPT-029-NOTES.md` §13 for the full 32-item Open Decisions
  table before building any of these without new instruction.
  PROMPT-028 built the offline-first PWA foundation (Sales Invoice
  creation, Customer/Supplier quick-add, sync queue, conflict
  classification, Sync Center) on top of every module through
  PROMPT-027. Still unbuilt/explicitly deferred: automatic storage-
  retention/cleanup for old SYNCED records (OD-009/OD-010), tenant-
  aggregate operational sync metrics (§58 — no telemetry infrastructure
  exists anywhere in this codebase to extend), offline data encryption
  beyond the browser's own IndexedDB storage (OD-018), a storage-quota
  warning UI (OD-019), in-place edit-then-retry for a failed offline
  invoice (only cancel-and-recreate exists, OD-014), and manager-
  approval escalation for stock conflicts (OD-027/OD-028). See
  `PROMPT-028-NOTES.md` §15 for the full 30-item Open Decisions table
  before building any of these without new instruction. Real-device/
  real-browser verification of the offline experience (airplane mode,
  actual browser restart, actual service-worker update) is also still
  outstanding — see that document's own Known Limitations.
  PROMPT-027 built the Reports, Dashboards & Financial Statements layer
  on top of every module through PROMPT-026 — Management Dashboard, 5
  Sales reports, 5 Purchase reports, 3 Inventory reports, Receivables,
  Payables, 3 Payment reports, General Ledger, Trial Balance, P&L,
  Balance Sheet, and 3 GST reporting views (26 endpoints total). Still
  unbuilt/explicitly deferred: any export format (Excel/CSV/PDF — JSON
  only exists), receivables/payables ageing buckets and an "overdue"
  concept (OD-006/007/008/009), inventory valuation and COGS (OD-002/
  004/005, carried from PROMPT-025), report/export audit logging,
  report caching, and click-through UI drill-down from a report row to
  its source document screen (the underlying source-number/id data
  exists on every report row, but no frontend navigation wiring was
  built for it). See `PROMPT-027-NOTES.md` §14 for the full 30-item
  Open Decisions table before building any of these without new
  instruction.
  PROMPT-026 built the GST Rule Engine's REPORTING layer (`gst_
  transaction`, GSTR-1/GSTR-3B preparation, validation, reconciliation,
  dashboard) on top of the GST CALCULATION engine that already existed
  since PROMPT-011 and was already correctly shared by every Sales and
  Purchase document type. Still unbuilt/explicitly deferred: a real
  GSTIN verification provider (OD-004), GST rate effective-dating/
  versioning (OD-002), exempt/nil-rated/zero-rated/non-GST taxability
  classification (OD-006), the exact statutory GSTR-1/GSTR-3B schema
  (OD-008/OD-009), any GST portal submission capability (OD-010/OD-011),
  CSV/Excel export (only JSON export exists), and wiring GSTIN/HSN
  validation into the Sales/Purchase posting flows themselves rather
  than only at return-preparation time. See `PROMPT-026-NOTES.md` §14
  for the full 24-item Open Decisions table before building any of these
  without new instruction.
  PROMPT-025 gave the Payments & Collections module's own `Accounting
  PostingService.post_payment` boundary (left as a stub by PROMPT-024)
  real meaning, and closed the Purchase Invoice/Purchase Return
  accounting boundary PROMPT-019 §14 explicitly deferred. The engine
  is structured to support downstream financial reporting (stable
  journal/line IDs, source references, dates, account references,
  tenant, audit — §49/AC-025) but **no report screen exists yet**
  (Trial Balance, General Ledger, P&L, Balance Sheet are all explicit
  non-scope per PROMPT-025 §57) — a natural, explicitly-named next
  candidate given the engine now exists to feed it, but **wait for
  explicit instruction**; don't infer scope. Manual Journal Entry
  remains unapproved (OD-017) — don't add a generic journal-creation
  endpoint without that approval. Account Mapping editing (view-only in
  this prompt), Chart of Accounts editing, and the accounting-period
  close workflow are all still unbuilt. PROMPT-020/021/022/023 each
  completed the "full workflow" pass for
  Purchase Order, Goods Receipt, Purchase Invoice, and Purchase Return
  respectively, on top of PROMPT-019's shared foundation (related-
  documents/audit-history/print-preview for all four; Goods Receipt,
  Purchase Invoice, and now Purchase Return additionally got confirmed/
  posted-cancellation-with-reversal — see §4's open decisions above and
  `PROMPT-020/021/022/023-NOTES.md` for their full Open Decisions
  tables). **Every Purchase document type has now completed its full
  workflow pass** — none remain at PROMPT-019 foundation level.
  PROMPT-024 added the Payments & Collections module (Customer Receipts
  + Supplier Payments) as a new cross-cutting financial layer sitting
  alongside both chains; PROMPT-025 then gave its own `AccountingPosting
  Service.post_payment` boundary (and every other document type's own
  boundary) real double-entry meaning. Detailed PO/GR/PI/PR reporting,
  an ad-hoc (PO-less) Goods Receipt path, cheque-clearance-date bank
  reconciliation, and `customer.balance`/`supplier.balance` party-level
  reconciliation (still unwritten since PROMPT-007/008) are all still
  unbuilt — but **wait for explicit instruction**; don't infer scope.
  Whichever comes first
  should reuse `app/services/gst_integration/` if it also needs GST/NIC
  integration (e.g. a real provider decision would touch `provider.py`'s
  factory functions, not scatter provider-specific logic through new
  code), reuse `app/services/accounting/accounting_posting_service.py`/
  `app/services/sales/gst_reporting_service.py` if it also needs an
  accounting/GST integration boundary, reuse `app/services/purchase/` /
  `InventoryService.post_movement` for anything Purchase-side (including
  the `<DOCUMENT>_REVERSAL`-style "new source_type, same source_id"
  pattern PROMPT-021/022 established for compensating movements — lock
  every DISTINCT source document a multi-source document's own LINES
  reference, sorted, not just one, per PROMPT-022's own generalization
  of `post_invoice`), and reuse `PurchaseOrderService.totals_from_lines`/
  the `/related-documents`+`/receiving-summary`+`/audit-history`+
  `/invoiceable-items` endpoint pattern PROMPT-020/021/022 established
  if another document type needs the same treatment, rather than
  re-deriving any of that.
- The dev database (`saas_mvp_dev`) currently has some accumulated test data
  from repeated pytest runs across this session (integration tests commit to
  the real DB, not a rollback-safe transaction) — harmless, but worth a
  cleanup pass eventually if it grows large.
- Known cosmetic/non-blocking items: a `DeprecationWarning` from
  `python-jose`'s internal `datetime.utcnow()` usage appears in test output;
  it's a third-party library issue, not actionable here.

## 6. Environment Gotchas (Windows-specific, already solved — don't redo)

- asyncpg does not fully support Windows' default `ProactorEventLoop` —
  `tests/conftest.py` switches to `WindowsSelectorEventLoopPolicy` and uses
  `NullPool` for the test DB engine (`ENVIRONMENT=testing` triggers this in
  `app/db/session.py`). Don't "fix" this by reverting it.
- The frontend dev server runs on **port 3000** (see `vite.config.ts`), not
  Vite's default 5173 — `backend/.env`'s `CORS_ALLOW_ORIGINS` must include
  it, and already does.
- To run both servers locally: `cd backend && uvicorn app.main:app --port
  8000` and, separately, `npm run dev` from the repo root.
