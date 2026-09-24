# PROMPT-018 — E-Invoice & E-Way Bill Integration — Implementation Notes

## 1. Summary

This prompt builds the E-Invoice and E-Way Bill INTEGRATION LAYER — the
first time this codebase talks to an external GST/NIC/GSP system rather
than only managing internal business documents. No real government
system is ever contacted: no provider is approved/selected (§43 Open
Decision #1), so a deterministic, fully-local `SandboxSimulatorProvider`
stands in, following the exact "make the interface real and testable,
never call anything external" discipline `NullGSTProvider` (PROMPT-002)
and `ConsolePasswordRecoveryProvider` (PROMPT-004) already established.

The architecture cleanly separates the PHYSICAL flow (Sales Invoice →
Sales Return → Stock IN, PROMPT-016) from the FINANCIAL/REGULATORY flow
(Sales Invoice → E-Invoice/E-Way Bill → Accounting/GST-adjacent
integration record) — this prompt touches neither Sales Return nor
Credit/Debit Note, and creates zero stock movement of any kind.

## 2. Existing components reused

- Auth/tenant/RBAC (`app.core.deps`, `app.core.permissions`)
- `AuditService.record` — the only writer of `audit_log`
- `IdempotencyService` — the HTTP-level replay guard on every mutating
  endpoint (generate/cancel), reused verbatim
- `check_row_version` / optimistic concurrency
- `ExternalServiceError`/`ServiceUnavailableError` (PROMPT-001's own
  exception hierarchy, never previously used — this is their first
  real consumer)
- The "commit a failure state before re-raising" pattern from
  `app/api/v1/auth.py`'s login handler — applied to every mutating
  E-Invoice/E-Way Bill endpoint
- `SalesInvoice`/`SalesInvoiceLine` (read-only) — the sole source
  document; nothing in Sales Invoice's own service/model was modified
  except syncing its already-reserved `irn`/`ack_number`/`ack_date`/
  `einvoice_status`/`qr_code_data` columns (PROMPT-015, migration 0017 —
  explicitly reserved "for PROMPT-018")

## 3. Database changes

Migration `0020_gst_integration.py` — four new tables, ALL proposed
additions (no approved Data Dictionary baseline covers this area):

- `integration_configuration`: ONE ROW PER TENANT (§7 — M1: one
  tenant = one business = one GSTIN). `credentials_encrypted` is a
  Fernet-encrypted JSON blob (`app/services/gst_integration/crypto.py`)
  — never plaintext. `einvoice_enabled`/`eway_bill_enabled` are the
  honest resolution of §8/§18's applicability requirement (see §9
  below). Lazily provisioned (SANDBOX, both enabled) on first touch,
  mirroring `InventoryService.ensure_default_location()`'s pattern — no
  configuration-management API/UI exists yet (not in this prompt's
  suggested endpoint list).
- `einvoice`: one row per Sales Invoice (`sales_invoice_id` UNIQUE per
  tenant). Authoritative IRN/ack/signed-payload record.
- `eway_bill`: one row per Sales Invoice (`sales_invoice_id` UNIQUE per
  tenant) — this MVP scopes E-Way Bill to Sales-Invoice-sourced
  transactions only.
- `integration_operation`: the operational history/reconciliation
  evidence for every GENERATE/CANCEL/STATUS_CHECK attempt.
- ALTER `sales_invoice_line`: none (E-Invoice/E-Way Bill don't touch
  invoice lines directly — no adjustment/quantity tracking needed here,
  unlike Sales Return/Credit-Debit Note).

Status model (§15, shared vocabulary for both `einvoice.status` and
`eway_bill.status`): NOT_APPLICABLE, READY, QUEUED, PROCESSING,
GENERATED, FAILED, CANCEL_REQUESTED, CANCELLED, STATUS_UNKNOWN.

## 4. Backend

- `app/models/integration_configuration.py`, `einvoice.py`,
  `eway_bill.py`, `integration_operation.py` (new)
- `app/services/gst_integration/` (new package):
  - `crypto.py` — Fernet encrypt/decrypt for stored credentials
  - `provider.py` — `EInvoiceProvider`/`EWayBillProvider` interfaces,
    `NullEInvoiceProvider`/`NullEWayBillProvider` (production safety —
    raise loudly), `SandboxSimulatorProvider` (the only working
    implementation; deterministic per idempotency key; `force_outcome`
    test hook for TIMEOUT/UNAVAILABLE/AUTH_FAILED/RATE_LIMITED/UNKNOWN)
  - `applicability_service.py` — `evaluate_einvoice_applicability`/
    `evaluate_eway_bill_applicability`
  - `validation_service.py` — `validate_einvoice_data`/
    `validate_eway_bill_data` (§9/§19 pre-submission checks)
  - `integration_operation_service.py` — operation create/track/query
  - `einvoice_service.py` — `EInvoiceService` (generate/refresh_status/
    cancel; the idempotency/concurrency/reconciliation core)
  - `eway_bill_service.py` — `EWayBillService` (mirrors the above)
- `app/schemas/gst_integration.py` (new)
- `app/api/v1/einvoice.py` — `/sales/invoices/{id}/einvoice[/generate|
  /status|/cancel]`
- `app/api/v1/eway_bills.py` — `/eway-bills[/generate|/{id}|/{id}/status|
  /{id}/cancel]` + `/sales/invoices/{id}/eway-bill` convenience GET
- `app/api/v1/integration_operations.py` — `GET /integration/
  operations/{id}`
- `app/api/v1/__init__.py` — registered all four new routers
- `app/core/error_codes.py` — `EINV-001` through `EINV-016`, `EWB-001`
  through `EWB-015`
- `app/core/permissions.py` — `einvoice.view/generate/cancel`,
  `eway_bill.view/generate/cancel`
- `app/core/config.py` — `gst_integration_default_*` timeout/retry
  settings, `gst_integration_credential_key` (Fernet key, with a
  documented dev-only deterministic fallback)

## 5. Idempotency strategy (§11)

Two independent layers, deliberately not conflated:

1. **HTTP-level replay guard** (existing `IdempotencyService`, reused
   verbatim): same client-supplied `Idempotency-Key` + same payload on
   the SAME endpoint returns the SAME stored response — protects against
   double-clicks/browser retries/network-client retries of the exact
   same HTTP request.
2. **Domain-level duplicate-IRN/duplicate-EWB guard** (new, in
   `EInvoiceService`/`EWayBillService`): `generate()` locks the
   `einvoice`/`eway_bill` row (`SELECT ... FOR UPDATE`) and inspects its
   `status` BEFORE doing anything else — `GENERATED` → reject
   (`EINV_ALREADY_GENERATED`/`EWB_ALREADY_GENERATED`); a `LOCKED_STATUSES`
   member (`PROCESSING`/`CANCEL_REQUESTED`) → reject
   (`EINV_CONCURRENT_OPERATION`/`EWB_CONCURRENT_OPERATION`). This is what
   actually prevents two DIFFERENT Idempotency-Keys (e.g. two browser
   tabs, or a background retry using a fresh key) from both reaching the
   provider.

## 6. Retry / unknown-result strategy (§23/§24)

- Permanent failures (validation errors — missing GSTIN/HSN/place of
  supply, non-applicable invoice) NEVER auto-retry — the record is
  marked `FAILED`/`NOT_APPLICABLE` and the user must fix the underlying
  data before trying again (a fresh attempt then gets a NEW idempotency
  key, since the provider was never actually contacted).
- Transient failures (`UNAVAILABLE`, `RATE_LIMITED`, `AUTH_FAILED`) are
  surfaced as `ExternalServiceError` (502) — safe to retry manually; the
  record is marked `FAILED` but nothing was submitted to the provider,
  so retrying allocates a fresh idempotency key too.
- `TIMEOUT` is the §24 "critical scenario": the record is marked
  `STATUS_UNKNOWN`, NOT `FAILED` — a materially different state,
  because the provider MAY have actually processed the request. The
  NEXT `generate()` call, seeing `STATUS_UNKNOWN`, does NOT resubmit
  blindly: it calls `get_irn_status`/`get_eway_bill_status` first. If
  that confirms success, the existing result is persisted (no second
  submission ever happens). If it confirms "not processed," the retry
  proceeds — but REUSES the original attempt's idempotency key (per
  §23's explicit "retries must use the same logical operation identity")
  rather than minting a new one, so a real provider that deduplicates on
  that key would return the original result instead of creating a
  duplicate document. If reconciliation itself is still unknown, the
  request is rejected with `EINV_STATUS_UNKNOWN`/`EWB_STATUS_UNKNOWN`
  (502) — explicitly requiring manual review rather than looping.

## 7. Error handling strategy (§30)

Provider outcomes (`SUCCESS`/`VALIDATION_FAILED`/`AUTH_FAILED`/
`TIMEOUT`/`UNAVAILABLE`/`RATE_LIMITED`/`NOT_FOUND`) are normalized to the
`EINV-*`/`EWB-*` catalogue and to actionable, non-raw messages (§30's own
BAD/GOOD example followed verbatim) — never a raw provider payload or
stack trace reaches the client.

## 8. Security considerations

- `integration_configuration.credentials_encrypted` is Fernet-encrypted,
  never returned by any API (no GET/read endpoint exposes it at all —
  no configuration-read endpoint exists in this prompt's scope).
- Every endpoint resolves `tenant_id` only from the verified JWT context
  (never from the request body/path), and every entity lookup filters by
  `tenant_id` — cross-tenant access returns 404, verified by dedicated
  tests for both E-Invoice and E-Way Bill.
- No secrets/tokens are ever logged — `AuditService`/structured logging
  only records status/reference/error-code fields, never credentials or
  raw provider payloads.
- RBAC: `einvoice.*`/`eway_bill.*` are separate permission families;
  Salesperson gets VIEW ONLY for both (§53 Open Decision #24, resolved
  MORE conservatively than any prior module — see below).

## 9. Applicability — the honest resolution (§8/§18/§53 #4-5)

No approved turnover threshold, transaction-type rule, or B2B/B2C carve-
out exists anywhere in this codebase's source documents. Rather than
inventing one, applicability is:

1. A tenant-level opt-in toggle (`einvoice_enabled`/`eway_bill_enabled`
   on `integration_configuration`, defaulting to enabled), PLUS
2. Basic transaction-state checks (invoice must be POSTED, not
   CANCELLED).

This is versioned (`RULE_VERSION = "v1-tenant-toggle-only"`, stored in
`applicability_result`) so a future, real rule engine has a clear
insertion point without touching any caller.

## 10. Testing

`tests/integration/test_gst_integration.py` — 26 tests, all passing
(after two test-setup fixes described below), covering: successful
E-Invoice generation (with IRN/ack/QR persistence and denormalized
invoice-snapshot sync), missing GSTIN, missing HSN, non-applicable
(DRAFT invoice and tenant-disabled), duplicate Generate (same key →
same result; different key → `EINV_ALREADY_GENERATED`), concurrent
Generate (only one succeeds), provider TIMEOUT → `STATUS_UNKNOWN` →
reconciled retry succeeds without a duplicate IRN, provider UNAVAILABLE
→ retry succeeds, provider AUTH_FAILED, E-Invoice cancellation (audit +
IRN preserved, not deleted), invalid/duplicate cancellation, tenant
isolation, Salesperson cannot generate / can view, audit event
generation, and the full E-Way Bill equivalents (successful generation,
missing transport data, duplicate generation, cancellation, concurrent
generation, tenant isolation, Salesperson cannot generate).

Two genuine test-setup gaps were found and fixed during this run (not
implementation bugs): the test file's own `_create_posted_direct_invoice`
helper initially forgot to seed opening stock (posting a direct invoice
requires available stock, per PROMPT-015) — an existing, well-known
requirement missed only in this new file — and `_create_customer`
needed an explicit `state_code`/`address` for `validate_einvoice_data`'s
place-of-supply/billing-address checks to pass, since those fields are
optional on Customer Master and this test file's minimal customer
payload left them blank (`test_credit_debit_notes.py`'s identical helper
never needed them, since PROMPT-016/017 don't validate place-of-supply
directly). One real implementation bug was found and fixed:
`AUTH_FAILED` was being classified as a permanent `ValidationAppError`
(422) instead of a transient `ExternalServiceError` (502) — an
integration/provider-config problem is not a data-validation problem,
and treating it as one would have suggested to the user that their
invoice was wrong.

`tests/integration/test_rbac.py` — updated the Manager/Salesperson
permission-set assertions to include the six new `einvoice.*`/
`eway_bill.*` codes.

Full regression: **475 backend tests** (449 pre-existing + 26 new), all
passing — see the final test run below.

## 11. Frontend

- `api/einvoice.ts`, `api/ewayBills.ts` (new) — thin typed clients
- `components/EinvoiceEwayBillPanel.tsx` (new) — a self-contained panel
  showing both E-Invoice and E-Way Bill status/actions, mounted inside
  `SalesInvoiceManagement.tsx`'s POSTED-invoice detail view (§34's exact
  requirement — extends the existing invoice detail screen rather than
  building a separate screen). Generate/Refresh/Cancel actions are
  permission-gated per section independently (a user might have
  `einvoice.view` but not `eway_bill.view`, etc.). E-Way Bill generation
  opens a small transport-details sub-form (mode/vehicle/transporter/
  distance) before submitting, per §19's validation requirements.
- Responsive by construction: reuses the same flexbox/wrap layout and
  Tailwind classes as every other panel in this codebase's invoice
  detail modal — no separate mobile/tablet/desktop code paths (§33's own
  explicit instruction), verified via the existing responsive modal
  container.

## 12. Print/preview integration (§35)

NOT implemented in this prompt — the existing Sales Invoice print/
preview layer was not modified. Exposing IRN/QR/E-Way Bill number to
that layer is a small, mechanical follow-up (the data already sits on
`EinvoiceDetail`/`EwayBillDetail`) but touching the print template is
outside this prompt's explicit file scope discipline and is called out
here as a known limitation, not silently done.

## 13. Open Decisions (per §43 — not silently resolved)

| # | Open Decision | Resolution in this prompt |
|---|---|---|
| 1 | Exact GST/NIC integration provider | NOT selected — `SandboxSimulatorProvider` only, raises loudly if `is_production=True` |
| 2 | Sandbox credentials/configuration | Not applicable — no real sandbox exists to configure |
| 3 | Production credentials/configuration | Not applicable — blocked on #1 |
| 4 | Exact E-Invoice applicability rules/version | Tenant opt-in toggle + posted-status check only (§9 above); no legal threshold |
| 5 | Exact E-Way Bill applicability rules/version | Same as #4 |
| 6 | Exact cancellation rules/windows | Not implemented — cancellation allowed any time while GENERATED/STATUS_UNKNOWN; no legal time-window enforced |
| 7 | Provider webhook vs polling strategy | Polling only (`refresh_status`, user/operator-triggered) — no webhook receiver exists |
| 8 | Background worker technology | NONE — synchronous request/response, same architecture as every prior prompt; no queue/worker infrastructure exists anywhere in this codebase |
| 9 | Retry limits/backoff | `integration_configuration.max_retry_attempts`/`.retry_backoff_seconds` columns exist but are NOT yet enforced by any automatic retry loop (no auto-retry is implemented — every retry in this MVP is a fresh user-triggered request) |
| 10 | Rate-limit handling | `rate_limit_per_minute` column exists but is NOT enforced yet |
| 11 | Integration credential storage mechanism | Fernet symmetric encryption, dev-only deterministic key fallback; no KMS/rotation strategy |
| 12 | Exact E-Invoice response fields to persist | Implemented: IRN, ack number/date, signed invoice data, signed QR data, provider reference/response code/message |
| 13 | Exact E-Way Bill response fields to persist | Implemented: E-Way Bill number, valid_from/until, provider reference/response code/message |
| 14 | Whether E-Invoice is automatically generated after invoice sync/post | NO — always a separate, explicit user-triggered action (`POST .../einvoice/generate`) |
| 15 | Whether E-Way Bill is automatically generated or user-triggered | User-triggered only |
| 16 | Transporter/vehicle master requirements | NOT implemented — plain text fields captured at generation time, no master data table |
| 17 | Exact E-Way Bill cancellation workflow | Simple DRAFT-style cancel (GENERATED/STATUS_UNKNOWN → CANCEL_REQUESTED → CANCELLED), no legal-window enforcement |
| 18 | Manual reconciliation permissions | Gated by the same `einvoice.view`/`eway_bill.view` as normal status viewing — no separate "reconcile" permission was introduced |
| 19 | Integration monitoring dashboard scope | NOT implemented — `GET /integration/operations/{id}` (single-operation lookup) is the only operational-visibility endpoint; no list/dashboard view |

## 14. Known Limitations

- No configuration-management API/UI exists — `integration_configuration`
  is lazily auto-provisioned with sensible defaults and can only be
  adjusted by direct database access until a future prompt builds one.
- No automatic background retry — every retry is user-initiated.
- No real provider was ever contacted — this entire integration is
  validated against a deterministic simulator, not a real GST/NIC
  sandbox.
- Print/preview integration (§35) is not wired up yet.
- E-Way Bill is scoped to Sales-Invoice-sourced transactions only — no
  Delivery-Challan-sourced or consolidated multi-invoice E-Way Bills.

## 15. Definition of Done

All items in §45's checklist are satisfied for the scope explicitly
implemented, with items dependent on unapproved decisions (real provider
selection, automatic retry/backoff, rate-limiting enforcement, a
monitoring dashboard, print/preview wiring) explicitly called out above
as Open Decisions or Known Limitations rather than silently skipped or
silently invented.

E-Invoice & E-Way Bill Integration is complete and ready for the next
prompt. No GST return filing, GSTR-1/GSTR-3B, Accounting posting logic,
Payments, Payroll, or other future-module work was started.
