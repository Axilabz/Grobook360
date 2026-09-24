"""Document number sequence (PROMPT-011 Sales & Billing Foundation).

Revision ID: 0013_document_number_sequence
Revises: 0012_audit_log_immutable
Create Date: 2026-09-11

Proposed schema addition (same class of gap as `idempotency_key` in
PROMPT-002): Data Dictionary v3.0 has no generic Sales document table and
therefore no numbering-sequence table either — each future document-type
prompt (Estimate, Sales Order, Delivery Challan, Sales Invoice, ...) will
own its own header table, but §34/§35 require the SAME server-authoritative,
FY-scoped numbering mechanism for all of them. This table is that shared
mechanism, so future prompts don't each invent their own counter.

No RBAC/API surface of its own — it's an internal building block consumed
by `app/services/sales/document_numbering_service.py`.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0013_document_number_sequence"
down_revision = "0012_audit_log_immutable"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "document_number_sequence",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("document_type", sa.String(20), nullable=False),
        sa.Column("financial_year_label", sa.String(10), nullable=False),
        sa.Column("last_number", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("row_version", sa.BigInteger, nullable=False, server_default="1"),
        sa.UniqueConstraint(
            "tenant_id", "document_type", "financial_year_label", name="uq_document_number_sequence_scope"
        ),
        sa.CheckConstraint("last_number >= 0", name="ck_document_number_sequence_last_number"),
    )
    op.create_index("idx_document_number_sequence_tenant", "document_number_sequence", ["tenant_id"])

    op.execute('ALTER TABLE "document_number_sequence" ENABLE ROW LEVEL SECURITY')
    op.execute(
        'CREATE POLICY tenant_isolation_document_number_sequence ON "document_number_sequence" '
        "USING (tenant_id::text = current_setting('app.tenant_id', true))"
    )


def downgrade() -> None:
    op.execute('DROP POLICY IF EXISTS tenant_isolation_document_number_sequence ON "document_number_sequence"')
    op.drop_table("document_number_sequence")
