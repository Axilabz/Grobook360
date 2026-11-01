"""Manual Stock Movements -> Accounting Ledger integration.

Revision ID: 0035_inventory_accounting
Revises: 0034_rbac_matrix_alignment
Create Date: 2026-10-24

Adds `stock_ledger_entry.unit_cost` (nullable, purely for audit
traceability of what cost was actually used to value a movement — the
authoritative running Weighted Average Cost lives on `product.cost_price`,
maintained by `InventoryService`).

Backfills 3 new Chart-of-Accounts entries (`INVENTORY`, `OPENING_BALANCE_
EQUITY`, `STOCK_ADJUSTMENT` — see `app.core.accounting_constants.
DEFAULT_ACCOUNT_SEED`) for every EXISTING tenant. This is necessary
because `ChartOfAccountsService.ensure_default_chart_of_accounts` only
seeds a tenant's Chart of Accounts/Account Mappings when it has ZERO
mapping rows — an already-signed-up tenant (which already has mapping
rows from its own first accounting posting) would otherwise never pick up
these 3 new codes, and `resolve_account` does NOT auto-create a missing
mapping (it raises). This is the first migration to backfill `chart_of_
account`/`account_mapping` directly (migration 0026 created those tables
fresh, with nothing pre-existing to backfill) — the insert-if-not-exists
idempotency style mirrors migration 0031's own backfill of new permission
codes onto existing tenants, adapted to these two tables.

Only Manual Stock Movements (Opening Stock, Stock In, Stock Out,
Adjustment) use these 3 accounts — the existing Sales/Purchase Invoice
posting rules are completely untouched by this migration.
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0035_inventory_accounting"
down_revision = "0034_rbac_matrix_alignment"
branch_labels = None
depends_on = None

_NEW_ACCOUNTS = {
    # posting_rule_code: (code, name, account_type)
    "INVENTORY": ("1090", "Inventory", "ASSET"),
    "OPENING_BALANCE_EQUITY": ("3010", "Opening Balance Equity", "EQUITY"),
    "STOCK_ADJUSTMENT": ("5040", "Stock Adjustment", "EXPENSE"),
}


def upgrade() -> None:
    op.add_column("stock_ledger_entry", sa.Column("unit_cost", sa.Numeric(15, 2), nullable=True))

    connection = op.get_bind()
    tenant_ids = [row[0] for row in connection.execute(sa.text("SELECT id FROM tenant")).fetchall()]

    for tenant_id in tenant_ids:
        for posting_rule_code, (code, name, account_type) in _NEW_ACCOUNTS.items():
            existing_mapping = connection.execute(
                sa.text(
                    "SELECT 1 FROM account_mapping WHERE tenant_id = :tenant_id AND posting_rule_code = :code"
                ),
                {"tenant_id": str(tenant_id), "code": posting_rule_code},
            ).fetchone()
            if existing_mapping is not None:
                continue

            account_row = connection.execute(
                sa.text(
                    "INSERT INTO chart_of_account "
                    "(id, tenant_id, code, name, account_type, is_active, is_system_default, "
                    "created_at, updated_at, row_version) "
                    "VALUES (gen_random_uuid(), :tenant_id, :code, :name, :account_type, true, true, "
                    "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 1) "
                    "RETURNING id"
                ),
                {"tenant_id": str(tenant_id), "code": code, "name": name, "account_type": account_type},
            ).fetchone()
            account_id = str(account_row[0])

            connection.execute(
                sa.text(
                    "INSERT INTO account_mapping "
                    "(id, tenant_id, posting_rule_code, account_id, created_at, updated_at, row_version) "
                    "VALUES (gen_random_uuid(), :tenant_id, :posting_rule_code, :account_id, "
                    "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 1)"
                ),
                {"tenant_id": str(tenant_id), "posting_rule_code": posting_rule_code, "account_id": account_id},
            )


def downgrade() -> None:
    connection = op.get_bind()
    for posting_rule_code in _NEW_ACCOUNTS:
        connection.execute(
            sa.text("DELETE FROM account_mapping WHERE posting_rule_code = :code"), {"code": posting_rule_code}
        )
    for code, _name, _account_type in _NEW_ACCOUNTS.values():
        connection.execute(sa.text("DELETE FROM chart_of_account WHERE code = :code"), {"code": code})
    op.drop_column("stock_ledger_entry", "unit_cost")
