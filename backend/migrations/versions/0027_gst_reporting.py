"""GST Rule Engine & GST Reporting (PROMPT-026): `gst_transaction` /
`gst_transaction_line` (the real GST snapshot/reporting dataset,
replacing the audit-log-only stub `GstReportingService` had used since
PROMPT-015), plus the `gst.*` permission catalogue.

Revision ID: 0027_gst_reporting
Revises: 0026_accounting_engine
Create Date: 2026-10-02

The single authoritative GST CALCULATION engine
(`app.services.sales.gst_calculation_service`, PROMPT-011) already exists
and is already shared correctly by both Sales and Purchase — this
migration does not touch it. What was missing was a real GST REPORTING
snapshot: `gst_reporting_service.py` only wrote an audit-log JSON blob
and returned an opaque `GSTTXN-<id>` string, and had NO equivalent at all
on the Purchase side (no Input GST tracking existed). `gst_transaction`
mirrors `journal_entry`'s exact idempotency/reversal shape (PROMPT-025)
on purpose: `(tenant_id, source_type, source_id, event_type)` is unique
(§42), a REVERSAL is a brand-new row with negated amounts, never an edit
to the ORIGINAL (§21 "historical GST values are immutable" — necessary
since Purchase Invoice/Purchase Return already support POSTED-state
cancellation-with-reversal per PROMPT-022/023, and that reversal must now
also reverse the GST snapshot, not just the accounting journal).
`source_type` reuses the identical `SRC_*` string vocabulary
`journal_entry.source_type` already uses so §24 reconciliation can join
the two tables directly.

Like migration 0021/0025/0026 (the only other prompts introducing
brand-new tables + brand-new permission codes since the RBAC
foundation), this migration enables Row-Level Security on both new
tables and backfills the new `gst.*` permission codes onto every
EXISTING tenant's OWNER/MANAGER roles (Salesperson gets none — GST
filing/reporting is judged financial/statutory access, mirrors
Accounting's own Owner/Manager-only precedent).

`purchase_invoice.gst_transaction_reference` / `purchase_return.
gst_transaction_reference` are added here too — no equivalent column
existed on either Purchase table before this prompt (mirrors the
identical column already on sales_invoice/sales_return/credit_debit_note
since PROMPT-015/016/017).
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "0027_gst_reporting"
down_revision = "0026_accounting_engine"
branch_labels = None
depends_on = None

_GST_PERMISSIONS = {
    "gst.view": "View GST transactions, dashboard and reconciliation",
    "gst.prepare_returns": "Calculate/refresh and validate GSTR-1 and GSTR-3B",
    "gst.export": "Export prepared GST return data",
}

_ROLE_DEFAULT_PERMISSIONS = {
    "OWNER": list(_GST_PERMISSIONS.keys()),
    "MANAGER": list(_GST_PERMISSIONS.keys()),
    "SALESPERSON": [],
}


def upgrade() -> None:
    op.add_column("purchase_invoice", sa.Column("gst_transaction_reference", sa.String(100), nullable=True))
    op.add_column("purchase_return", sa.Column("gst_transaction_reference", sa.String(100), nullable=True))

    op.create_table(
        "gst_transaction",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("source_type", sa.String(30), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_number", sa.String(50), nullable=True),
        sa.Column("event_type", sa.String(20), nullable=False),
        sa.Column("reversal_of_transaction_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("gst_transaction.id"), nullable=True),
        sa.Column("direction", sa.String(10), nullable=False),
        sa.Column("classification", sa.String(10), nullable=False),
        sa.Column("party_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("party_name", sa.String(200), nullable=True),
        sa.Column("party_gstin", sa.CHAR(15), nullable=True),
        sa.Column("place_of_supply_state_code", sa.CHAR(2), nullable=True),
        sa.Column("document_date", sa.Date, nullable=False),
        sa.Column("financial_year_label", sa.String(10), nullable=False),
        sa.Column("return_period", sa.String(7), nullable=False),
        sa.Column("taxable_value", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("cgst_amount", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("sgst_amount", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("igst_amount", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("cess_amount", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("total_gst", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("total_amount", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("row_version", sa.BigInteger, nullable=False, server_default="1"),
        sa.UniqueConstraint("tenant_id", "source_type", "source_id", "event_type", name="uq_gst_transaction_source_event"),
        sa.CheckConstraint("event_type IN ('ORIGINAL','REVERSAL')", name="ck_gst_transaction_event_type"),
        sa.CheckConstraint("direction IN ('OUTWARD','INWARD')", name="ck_gst_transaction_direction"),
        sa.CheckConstraint("classification IN ('B2B','B2C')", name="ck_gst_transaction_classification"),
    )
    op.create_index("idx_gst_transaction_tenant", "gst_transaction", ["tenant_id"])
    op.create_index("idx_gst_transaction_source", "gst_transaction", ["tenant_id", "source_type", "source_id"])
    op.create_index("idx_gst_transaction_period", "gst_transaction", ["tenant_id", "return_period"])
    op.create_index("idx_gst_transaction_gstin", "gst_transaction", ["tenant_id", "party_gstin"])

    op.create_table(
        "gst_transaction_line",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("gst_transaction_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("gst_transaction.id"), nullable=False),
        sa.Column("line_no", sa.Integer, nullable=False),
        sa.Column("hsn_code", sa.String(8), nullable=True),
        sa.Column("quantity", sa.Numeric(18, 3), nullable=False, server_default="0"),
        sa.Column("unit_price", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("gst_rate", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column("taxable_value", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("cgst_amount", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("sgst_amount", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("igst_amount", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("cess_amount", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("line_total", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("row_version", sa.BigInteger, nullable=False, server_default="1"),
    )
    op.create_index("idx_gst_transaction_line_tenant", "gst_transaction_line", ["tenant_id"])
    op.create_index("idx_gst_transaction_line_txn", "gst_transaction_line", ["gst_transaction_id"])
    op.create_index("idx_gst_transaction_line_hsn", "gst_transaction_line", ["tenant_id", "hsn_code"])

    for table in ("gst_transaction", "gst_transaction_line"):
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY tenant_isolation_{table} ON "{table}" '
            f"USING (tenant_id::text = current_setting('app.tenant_id', true))"
        )

    connection = op.get_bind()

    permission_ids: dict[str, str] = {}
    for code, description in _GST_PERMISSIONS.items():
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
    for table in ("gst_transaction_line", "gst_transaction"):
        op.execute(f'DROP POLICY IF EXISTS tenant_isolation_{table} ON "{table}"')
        op.drop_table(table)

    op.drop_column("purchase_return", "gst_transaction_reference")
    op.drop_column("purchase_invoice", "gst_transaction_reference")
    # Permission/role_permission seed rows left in place, matching precedent.
