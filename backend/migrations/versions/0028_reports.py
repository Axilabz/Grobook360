"""Reports, Dashboards & Financial Statements (PROMPT-027): the
`reports.*` permission catalogue.

Revision ID: 0028_reports
Revises: 0027_gst_reporting
Create Date: 2026-10-09

Unlike every other prompt since PROMPT-019 that introduced new
permission codes, this migration adds NO new tables — the reporting
layer is read-only and aggregates exclusively over existing
authoritative tables (`sales_invoice`, `purchase_invoice`, `sales_
return`, `purchase_return`, `credit_debit_note`, `stock_ledger_entry`,
`payment`/`payment_allocation`, `journal_entry`/`journal_line`,
`chart_of_account`, `gst_transaction`) — §2's own mandatory principle
("reports must not become a second source of truth"). No RLS is needed
here since no new table exists; every report query still enforces
`tenant_id` from the authenticated session, same as every other query
in this codebase.

Follows migration 0021/0025/0026/0027's own permission-backfill pattern
(new codes are backfilled onto every EXISTING tenant's roles, not just
newly-created ones) minus the table-creation/RLS steps those migrations
also needed.
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0028_reports"
down_revision = "0027_gst_reporting"
branch_labels = None
depends_on = None

_REPORT_PERMISSIONS = {
    "reports.view_dashboard": "View the management dashboard",
    "reports.view_sales": "View Sales reports",
    "reports.view_purchase": "View Purchase reports",
    "reports.view_inventory": "View Inventory/Stock reports",
    "reports.view_receivables": "View the Receivables (Customer Outstanding) report",
    "reports.view_payables": "View the Payables (Supplier Outstanding) report",
    "reports.view_payments": "View Payment reports",
    "reports.view_general_ledger": "View the General Ledger",
    "reports.view_trial_balance": "View the Trial Balance",
    "reports.view_profit_loss": "View the Profit & Loss statement",
    "reports.view_balance_sheet": "View the Balance Sheet",
    "reports.view_gst": "View GST reporting views",
    "reports.export": "Export report data",
}

_ALL_CODES = list(_REPORT_PERMISSIONS.keys())
_SALESPERSON_CODES = ["reports.view_dashboard", "reports.view_sales", "reports.view_inventory"]

_ROLE_DEFAULT_PERMISSIONS = {
    "OWNER": _ALL_CODES,
    "MANAGER": _ALL_CODES,
    "SALESPERSON": _SALESPERSON_CODES,
}


def upgrade() -> None:
    connection = op.get_bind()

    permission_ids: dict[str, str] = {}
    for code, description in _REPORT_PERMISSIONS.items():
        row = connection.execute(sa.text("SELECT id FROM permission WHERE code = :code"), {"code": code}).fetchone()
        if row is None:
            new_id = connection.execute(
                sa.text(
                    "INSERT INTO permission (id, code, description, created_at, updated_at, row_version) "
                    "VALUES (gen_random_uuid(), :code, :description, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 1) "
                    "RETURNING id"
                ),
                {"code": code, "description": description},
            ).fetchone()
            permission_ids[code] = str(new_id[0])
        else:
            permission_ids[code] = str(row[0])

    roles = connection.execute(sa.text("SELECT id, tenant_id, name FROM role")).fetchall()
    for role_id, tenant_id, role_name in roles:
        for code in _ROLE_DEFAULT_PERMISSIONS.get(role_name, []):
            permission_id = permission_ids[code]
            existing = connection.execute(
                sa.text("SELECT 1 FROM role_permission WHERE role_id = :role_id AND permission_id = :permission_id"),
                {"role_id": str(role_id), "permission_id": permission_id},
            ).fetchone()
            if existing is None:
                connection.execute(
                    sa.text(
                        "INSERT INTO role_permission (id, tenant_id, role_id, permission_id, created_at, updated_at, row_version) "
                        "VALUES (gen_random_uuid(), :tenant_id, :role_id, :permission_id, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 1)"
                    ),
                    {"tenant_id": str(tenant_id), "role_id": str(role_id), "permission_id": permission_id},
                )


def downgrade() -> None:
    # Permission/role_permission seed rows left in place, matching precedent
    # (migration 0026/0027's own downgrade() does not remove seeded
    # permission codes either).
    pass
