# Phase 1C — policy map for every table (generated from the migrated database)

Policy for all tenant tables: `FOR ALL USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (<same>)`, ENABLE + FORCE. Unset/empty context matches nothing (fail closed); a malformed value raises an error.

Tables reviewed: **64** (incl. `alembic_version`). Runtime role: `grobook_app`.

| # | Table | RLS | FORCE | Key | Policies | grobook_app privileges | Notes |
|---|---|---|---|---|---|---|---|
| 1 | `account_mapping` | yes | yes | tenant_id | 1 | DELETE,INSERT,SELECT,UPDATE |  |
| 2 | `accounting_period` | yes | yes | tenant_id | 1 | DELETE,INSERT,SELECT,UPDATE |  |
| 3 | `alembic_version` | no | no | — | 0 | none | Migration bookkeeping. No access for the runtime role. |
| 4 | `attendance` | yes | yes | tenant_id | 1 | DELETE,INSERT,SELECT,UPDATE |  |
| 5 | `audit_log` | yes | yes | tenant_id | 1 | INSERT,SELECT | Tenant policy + append-only privileges (SELECT, INSERT). UPDATE/DELETE additionally blocked by trigger (migration 0012). |
| 6 | `auth_session` | yes | yes | tenant_id | 1 | DELETE,INSERT,SELECT,UPDATE | Nullable tenant_id; NEWLY protected in 0038. Session validation sets tenant from the signed JWT first. |
| 7 | `chart_of_account` | yes | yes | tenant_id | 1 | DELETE,INSERT,SELECT,UPDATE |  |
| 8 | `credit_debit_note` | yes | yes | tenant_id | 1 | DELETE,INSERT,SELECT,UPDATE |  |
| 9 | `credit_debit_note_line` | yes | yes | tenant_id | 1 | DELETE,INSERT,SELECT,UPDATE |  |
| 10 | `customer` | yes | yes | tenant_id | 1 | DELETE,INSERT,SELECT,UPDATE |  |
| 11 | `delivery_challan` | yes | yes | tenant_id | 1 | DELETE,INSERT,SELECT,UPDATE |  |
| 12 | `delivery_challan_line` | yes | yes | tenant_id | 1 | DELETE,INSERT,SELECT,UPDATE |  |
| 13 | `document_number_sequence` | yes | yes | tenant_id | 1 | DELETE,INSERT,SELECT,UPDATE |  |
| 14 | `einvoice` | yes | yes | tenant_id | 1 | DELETE,INSERT,SELECT,UPDATE |  |
| 15 | `employee` | yes | yes | tenant_id | 1 | DELETE,INSERT,SELECT,UPDATE |  |
| 16 | `eway_bill` | yes | yes | tenant_id | 1 | DELETE,INSERT,SELECT,UPDATE |  |
| 17 | `goods_receipt` | yes | yes | tenant_id | 1 | DELETE,INSERT,SELECT,UPDATE |  |
| 18 | `goods_receipt_line` | yes | yes | tenant_id | 1 | DELETE,INSERT,SELECT,UPDATE |  |
| 19 | `gst_transaction` | yes | yes | tenant_id | 1 | DELETE,INSERT,SELECT,UPDATE |  |
| 20 | `gst_transaction_line` | yes | yes | tenant_id | 1 | DELETE,INSERT,SELECT,UPDATE |  |
| 21 | `idempotency_key` | yes | yes | tenant_id | 2 | DELETE,INSERT,SELECT,UPDATE | Nullable tenant_id; NEWLY protected in 0038. Definer reads sign-up endpoint rows only (via function). |
| 22 | `integration_configuration` | yes | yes | tenant_id | 1 | DELETE,INSERT,SELECT,UPDATE |  |
| 23 | `integration_operation` | yes | yes | tenant_id | 1 | DELETE,INSERT,SELECT,UPDATE |  |
| 24 | `invoice_template_configuration` | yes | yes | tenant_id | 1 | DELETE,INSERT,SELECT,UPDATE |  |
| 25 | `journal_entry` | yes | yes | tenant_id | 1 | DELETE,INSERT,SELECT,UPDATE |  |
| 26 | `journal_line` | yes | yes | tenant_id | 1 | DELETE,INSERT,SELECT,UPDATE |  |
| 27 | `leave_request` | yes | yes | tenant_id | 1 | DELETE,INSERT,SELECT,UPDATE |  |
| 28 | `location` | yes | yes | tenant_id | 1 | DELETE,INSERT,SELECT,UPDATE |  |
| 29 | `password_reset_token` | yes | yes | tenant_id | 2 | DELETE,INSERT,SELECT,UPDATE | Nullable tenant_id; NEWLY protected in 0038. Definer role reads (id, user_id, tenant_id, token_hash) only. |
| 30 | `payment` | yes | yes | tenant_id | 1 | DELETE,INSERT,SELECT,UPDATE |  |
| 31 | `payment_allocation` | yes | yes | tenant_id | 1 | DELETE,INSERT,SELECT,UPDATE |  |
| 32 | `payroll_period` | yes | yes | tenant_id | 1 | DELETE,INSERT,SELECT,UPDATE |  |
| 33 | `payroll_record` | yes | yes | tenant_id | 1 | DELETE,INSERT,SELECT,UPDATE |  |
| 34 | `payroll_record_line` | yes | yes | tenant_id | 1 | DELETE,INSERT,SELECT,UPDATE |  |
| 35 | `payroll_run` | yes | yes | tenant_id | 1 | DELETE,INSERT,SELECT,UPDATE |  |
| 36 | `permission` | no | no | — | 0 | INSERT,SELECT | Global reference data, no tenant column. No RLS by design. Runtime role: SELECT, INSERT only (get-or-create of permission codes); no UPDATE/DELETE. |
| 37 | `product` | yes | yes | tenant_id | 1 | DELETE,INSERT,SELECT,UPDATE |  |
| 38 | `product_unit_conversion` | yes | yes | tenant_id | 1 | DELETE,INSERT,SELECT,UPDATE |  |
| 39 | `purchase_invoice` | yes | yes | tenant_id | 1 | DELETE,INSERT,SELECT,UPDATE |  |
| 40 | `purchase_invoice_line` | yes | yes | tenant_id | 1 | DELETE,INSERT,SELECT,UPDATE |  |
| 41 | `purchase_order` | yes | yes | tenant_id | 1 | DELETE,INSERT,SELECT,UPDATE |  |
| 42 | `purchase_order_line` | yes | yes | tenant_id | 1 | DELETE,INSERT,SELECT,UPDATE |  |
| 43 | `purchase_return` | yes | yes | tenant_id | 1 | DELETE,INSERT,SELECT,UPDATE |  |
| 44 | `purchase_return_line` | yes | yes | tenant_id | 1 | DELETE,INSERT,SELECT,UPDATE |  |
| 45 | `role` | yes | yes | tenant_id | 1 | DELETE,INSERT,SELECT,UPDATE |  |
| 46 | `role_permission` | yes | yes | tenant_id | 1 | DELETE,INSERT,SELECT,UPDATE |  |
| 47 | `salary_component` | yes | yes | tenant_id | 1 | DELETE,INSERT,SELECT,UPDATE |  |
| 48 | `salary_structure` | yes | yes | tenant_id | 1 | DELETE,INSERT,SELECT,UPDATE |  |
| 49 | `salary_structure_line` | yes | yes | tenant_id | 1 | DELETE,INSERT,SELECT,UPDATE |  |
| 50 | `sales_estimate` | yes | yes | tenant_id | 1 | DELETE,INSERT,SELECT,UPDATE |  |
| 51 | `sales_estimate_line` | yes | yes | tenant_id | 1 | DELETE,INSERT,SELECT,UPDATE |  |
| 52 | `sales_invoice` | yes | yes | tenant_id | 1 | DELETE,INSERT,SELECT,UPDATE |  |
| 53 | `sales_invoice_line` | yes | yes | tenant_id | 1 | DELETE,INSERT,SELECT,UPDATE |  |
| 54 | `sales_order` | yes | yes | tenant_id | 1 | DELETE,INSERT,SELECT,UPDATE |  |
| 55 | `sales_order_line` | yes | yes | tenant_id | 1 | DELETE,INSERT,SELECT,UPDATE |  |
| 56 | `sales_return` | yes | yes | tenant_id | 1 | DELETE,INSERT,SELECT,UPDATE |  |
| 57 | `sales_return_line` | yes | yes | tenant_id | 1 | DELETE,INSERT,SELECT,UPDATE |  |
| 58 | `stock_adjustment` | yes | yes | tenant_id | 1 | DELETE,INSERT,SELECT,UPDATE |  |
| 59 | `stock_ledger_entry` | yes | yes | tenant_id | 1 | INSERT,SELECT | Tenant policy + append-only privileges (SELECT, INSERT). UPDATE/DELETE additionally blocked by trigger (migration 0011). |
| 60 | `supplier` | yes | yes | tenant_id | 1 | DELETE,INSERT,SELECT,UPDATE |  |
| 61 | `tenant` | yes | yes | id | 2 | DELETE,INSERT,SELECT,UPDATE | Root table, keyed by `id`. Policy `id = ctx` (USING + WITH CHECK). Sign-up sets ctx to the new tenant id before inserting. |
| 62 | `unit_of_measure` | yes | yes | tenant_id | 1 | DELETE,INSERT,SELECT,UPDATE |  |
| 63 | `user` | yes | yes | tenant_id | 2 | DELETE,INSERT,SELECT,UPDATE | Nullable tenant_id: rows without a tenant are invisible/unwritable (tenant-less users unsupported). Definer role reads (id, tenant_id, phone, email) only. |
| 64 | `user_role` | yes | yes | tenant_id | 1 | DELETE,INSERT,SELECT,UPDATE |  |

All tables owned by `grobook_owner` (owner/migration role); `grobook_app` owns nothing.
