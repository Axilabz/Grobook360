"""Accounting Posting Matrix & Journal Engine (PROMPT-025): Chart of
Accounts, Account Mappings, Accounting Periods, Journal Entry/Line, and
the accounting.* permission catalogue.

Revision ID: 0026_accounting_engine
Revises: 0025_payments_collections
Create Date: 2026-09-25

This is the FIRST prompt to give the existing "conceptual accounting
entries" stub (`AccountingPostingService`, PROMPT-015 onward — audit-log
JSON blobs only, no real ledger) a genuine double-entry Journal Engine.
`chart_of_account`/`account_mapping` are a documented DEFAULT, EDITABLE
starting Chart of Accounts (§56 OD-001/OD-002/OD-003/OD-004/OD-011/
OD-012/OD-013 — NOT an approved final COA), lazily seeded per tenant on
first posting attempt (mirrors `InventoryService.ensure_default_
location()`'s precedent). `accounting_period` is a posting GUARD only
(§35) — no close/reopen workflow exists (OD-018/OD-019 stay open).
`journal_entry`/`journal_line` are the real ledger: `journal_line` has a
CHECK enforcing exactly one of debit/credit > 0 per line (§7);
`journal_entry` has a unique `(tenant_id, source_type, source_id,
posting_event_type)` constraint that IS the idempotency guarantee (§32)
— a source document can have at most one ORIGINAL journal and at most
one REVERSAL journal.

`purchase_invoice.accounting_posting_reference`/
`purchase_return.accounting_posting_reference` are added here too —
PROMPT-019 §14 explicitly excluded the accounting boundary for the
Purchase side; this prompt closes that gap (mirrors the identical
column already on sales_invoice/sales_return/credit_debit_note/payment).

Like migration 0021/0025 (the only other prompts introducing brand-new
tables + brand-new permission codes since the RBAC foundation), this
migration enables Row-Level Security on every new table and backfills
the new `accounting.*` permission codes onto every EXISTING tenant's
OWNER/MANAGER roles (Salesperson gets none — financial GL access is not
appropriate at that role, mirrors Purchase's own Owner/Manager-only
precedent).
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "0026_accounting_engine"
down_revision = "0025_payments_collections"
branch_labels = None
depends_on = None

_ACCOUNTING_PERMISSIONS = {
    "accounting.view_journals": "View tenant accounting journals",
    "accounting.view_chart_of_accounts": "View the tenant's Chart of Accounts",
    "accounting.manage_account_mappings": "View/manage posting-rule account mappings",
    "accounting.reverse_journal": "Reverse a posted accounting journal",
}

_ROLE_DEFAULT_PERMISSIONS = {
    "OWNER": list(_ACCOUNTING_PERMISSIONS.keys()),
    "MANAGER": list(_ACCOUNTING_PERMISSIONS.keys()),
    "SALESPERSON": [],
}


def upgrade() -> None:
    op.add_column("purchase_invoice", sa.Column("accounting_posting_reference", sa.String(100), nullable=True))
    op.add_column("purchase_return", sa.Column("accounting_posting_reference", sa.String(100), nullable=True))

    op.create_table(
        "chart_of_account",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("code", sa.String(20), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("account_type", sa.String(20), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("is_system_default", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("row_version", sa.BigInteger, nullable=False, server_default="1"),
        sa.UniqueConstraint("tenant_id", "code", name="uq_chart_of_account_code"),
        sa.CheckConstraint(
            "account_type IN ('ASSET','LIABILITY','EQUITY','REVENUE','EXPENSE','COGS')", name="ck_chart_of_account_type"
        ),
    )
    op.create_index("idx_chart_of_account_tenant", "chart_of_account", ["tenant_id"])

    op.create_table(
        "account_mapping",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("posting_rule_code", sa.String(50), nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("chart_of_account.id"), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("row_version", sa.BigInteger, nullable=False, server_default="1"),
        sa.UniqueConstraint("tenant_id", "posting_rule_code", name="uq_account_mapping_rule"),
    )
    op.create_index("idx_account_mapping_tenant", "account_mapping", ["tenant_id"])

    op.create_table(
        "accounting_period",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("financial_year_label", sa.String(10), nullable=False),
        sa.Column("status", sa.String(10), nullable=False, server_default="OPEN"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("row_version", sa.BigInteger, nullable=False, server_default="1"),
        sa.UniqueConstraint("tenant_id", "financial_year_label", name="uq_accounting_period_fy"),
        sa.CheckConstraint("status IN ('OPEN','CLOSED')", name="ck_accounting_period_status"),
    )
    op.create_index("idx_accounting_period_tenant", "accounting_period", ["tenant_id"])

    op.create_table(
        "journal_entry",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("journal_number", sa.String(50), nullable=False),
        sa.Column("journal_date", sa.Date, nullable=False),
        sa.Column("posting_date", sa.Date, nullable=False),
        sa.Column("source_type", sa.String(30), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_number", sa.String(50), nullable=True),
        sa.Column("posting_event_type", sa.String(20), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="DRAFT"),
        sa.Column("reversal_of_journal_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("journal_entry.id"), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False, server_default="INR"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("row_version", sa.BigInteger, nullable=False, server_default="1"),
        sa.UniqueConstraint("tenant_id", "journal_number", name="uq_journal_entry_number"),
        sa.UniqueConstraint(
            "tenant_id", "source_type", "source_id", "posting_event_type", name="uq_journal_entry_source_event"
        ),
        sa.CheckConstraint("status IN ('DRAFT','POSTED','REVERSED')", name="ck_journal_entry_status"),
        sa.CheckConstraint("posting_event_type IN ('ORIGINAL','REVERSAL')", name="ck_journal_entry_event_type"),
    )
    op.create_index("idx_journal_entry_tenant", "journal_entry", ["tenant_id"])
    op.create_index("idx_journal_entry_source", "journal_entry", ["tenant_id", "source_type", "source_id"])
    op.create_index("idx_journal_entry_status", "journal_entry", ["status"])
    op.create_index("idx_journal_entry_date", "journal_entry", ["tenant_id", "journal_date"])

    op.create_table(
        "journal_line",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("journal_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("journal_entry.id"), nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("chart_of_account.id"), nullable=False),
        sa.Column("debit_amount", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("credit_amount", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("reference_type", sa.String(30), nullable=True),
        sa.Column("reference_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("row_version", sa.BigInteger, nullable=False, server_default="1"),
        sa.CheckConstraint("debit_amount >= 0 AND credit_amount >= 0", name="ck_journal_line_nonnegative"),
        sa.CheckConstraint(
            "(debit_amount > 0 AND credit_amount = 0) OR (credit_amount > 0 AND debit_amount = 0)",
            name="ck_journal_line_exactly_one_side",
        ),
    )
    op.create_index("idx_journal_line_tenant", "journal_line", ["tenant_id"])
    op.create_index("idx_journal_line_journal", "journal_line", ["journal_id"])
    op.create_index("idx_journal_line_account", "journal_line", ["account_id"])

    for table in ("chart_of_account", "account_mapping", "accounting_period", "journal_entry", "journal_line"):
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY tenant_isolation_{table} ON "{table}" '
            f"USING (tenant_id::text = current_setting('app.tenant_id', true))"
        )

    connection = op.get_bind()

    permission_ids: dict[str, str] = {}
    for code, description in _ACCOUNTING_PERMISSIONS.items():
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
    for table in ("journal_line", "journal_entry", "accounting_period", "account_mapping", "chart_of_account"):
        op.execute(f'DROP POLICY IF EXISTS tenant_isolation_{table} ON "{table}"')
        op.drop_table(table)

    op.drop_column("purchase_return", "accounting_posting_reference")
    op.drop_column("purchase_invoice", "accounting_posting_reference")
    # Permission/role_permission seed rows left in place, matching precedent.
