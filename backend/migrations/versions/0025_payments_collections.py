"""Payments & Collections Management (PROMPT-024): Payment / Payment
Allocation tables, invoice paid_amount/payment_status cache columns,
and the customer_receipt.*/supplier_payment.* permission catalogue.

Revision ID: 0025_payments_collections
Revises: 0024_purchase_invoice_management
Create Date: 2026-09-18

§2's central rule drives the whole schema: a Payment is a financial
transaction, NEVER the same record as how it is applied to an invoice —
`payment` and `payment_allocation` are two separate tables, not a
manually-editable "paid amount" field on the invoice. §38's own
conceptual field list is implemented close to verbatim; the only
proposed additions beyond it are `unallocated_amount` (cache, §13's own
mandate to never silently discard an unallocated remainder) and the
cheque-lifecycle columns (§6/§7).

`payment.customer_id`/`.supplier_id` mutual exclusivity per
`party_type` (§4) and `payment_allocation.sales_invoice_id`/
`.purchase_invoice_id` mutual exclusivity (§38) are both enforced by
CHECK constraints, not just application code (§4's own explicit
instruction: "Enforce this at database and API validation levels. Do
not rely only on frontend validation.").

`sales_invoice.paid_amount`/`.payment_status` and
`purchase_invoice.paid_amount`/`.payment_status` (§15/§16) are
reconciliation CACHE columns — the authoritative source is always
SUM(payment_allocation.allocated_amount) across every currently-POSTED
Payment, recomputed by PaymentService under the invoice's own row lock
at POST/REVERSE time (same discipline as product.stock_qty_cache from
PROMPT-010). They are never a create/update input of the Sales/Purchase
Invoice APIs.

This migration also introduces brand-new tables and brand-new
permission codes for the first time since PROMPT-019 (PROMPT-020-023
only added columns or reused existing permissions) — so it follows
migration 0021's own precedent exactly: Row-Level Security is enabled
on both new tables with a `tenant_isolation_<table>` policy, and the
new permission codes are backfilled onto every EXISTING tenant's
OWNER/MANAGER/SALESPERSON roles (not just newly-created ones), not left
to `seed_role_permissions()`'s lazy on-role-creation-only behavior.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "0025_payments_collections"
down_revision = "0024_purchase_invoice_management"
branch_labels = None
depends_on = None

_PAYMENT_PERMISSIONS = {
    "customer_receipt.view": "View tenant customer receipts",
    "customer_receipt.create": "Create a customer receipt",
    "customer_receipt.edit": "Edit a draft customer receipt",
    "customer_receipt.post": "Post a customer receipt (invoice outstanding impact)",
    "customer_receipt.reverse": "Reverse a posted customer receipt",
    "supplier_payment.view": "View tenant supplier payments",
    "supplier_payment.create": "Create a supplier payment",
    "supplier_payment.edit": "Edit a draft supplier payment",
    "supplier_payment.post": "Post a supplier payment (invoice outstanding impact)",
    "supplier_payment.reverse": "Reverse a posted supplier payment",
}

# §36/§50 open decision OD-012 — resolved by mirroring the established
# "Salesperson drafts, Owner/Manager posts" shape used identically
# across every Sales document type; Supplier Payment stays Owner/
# Manager only (same FRD-Table-7-driven reasoning as Purchase itself).
_ROLE_DEFAULT_PERMISSIONS = {
    "OWNER": list(_PAYMENT_PERMISSIONS.keys()),
    "MANAGER": list(_PAYMENT_PERMISSIONS.keys()),
    "SALESPERSON": ["customer_receipt.view", "customer_receipt.create", "customer_receipt.edit"],
}


def upgrade() -> None:
    op.add_column("sales_invoice", sa.Column("paid_amount", sa.Numeric(15, 2), nullable=False, server_default="0"))
    op.add_column("sales_invoice", sa.Column("payment_status", sa.String(20), nullable=False, server_default="UNPAID"))
    op.add_column("purchase_invoice", sa.Column("paid_amount", sa.Numeric(15, 2), nullable=False, server_default="0"))
    op.add_column("purchase_invoice", sa.Column("payment_status", sa.String(20), nullable=False, server_default="UNPAID"))

    op.create_table(
        "payment",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("payment_number", sa.String(50), nullable=False),
        sa.Column("party_type", sa.String(20), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("customer.id"), nullable=True),
        sa.Column("supplier_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("supplier.id"), nullable=True),
        sa.Column("payment_date", sa.Date, nullable=False, server_default=sa.text("CURRENT_DATE")),
        sa.Column("payment_method", sa.String(20), nullable=False),
        sa.Column("amount", sa.Numeric(15, 2), nullable=False),
        sa.Column("reference_number", sa.String(100), nullable=True),
        sa.Column("notes", sa.String(1000), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="DRAFT"),
        sa.Column("client_transaction_id", sa.String(100), nullable=True),
        sa.Column("cheque_number", sa.String(50), nullable=True),
        sa.Column("cheque_date", sa.Date, nullable=True),
        sa.Column("cheque_bank_name", sa.String(200), nullable=True),
        sa.Column("cheque_status", sa.String(20), nullable=True),
        sa.Column("cleared_date", sa.Date, nullable=True),
        sa.Column("allocated_amount", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("unallocated_amount", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("accounting_posting_reference", sa.String(100), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("row_version", sa.BigInteger, nullable=False, server_default="1"),
        sa.UniqueConstraint("tenant_id", "payment_number", name="uq_payment_number"),
        sa.CheckConstraint("party_type IN ('CUSTOMER','SUPPLIER')", name="ck_payment_party_type"),
        sa.CheckConstraint(
            "(party_type = 'CUSTOMER' AND customer_id IS NOT NULL AND supplier_id IS NULL) OR "
            "(party_type = 'SUPPLIER' AND supplier_id IS NOT NULL AND customer_id IS NULL)",
            name="ck_payment_party_consistency",
        ),
        sa.CheckConstraint("payment_method IN ('CASH','UPI','BANK_TRANSFER','CHEQUE')", name="ck_payment_method"),
        sa.CheckConstraint("status IN ('DRAFT','POSTED','REVERSED')", name="ck_payment_status"),
        sa.CheckConstraint(
            "cheque_status IS NULL OR cheque_status IN ('PENDING','CLEARED','BOUNCED')", name="ck_payment_cheque_status"
        ),
        sa.CheckConstraint("amount > 0", name="ck_payment_amount_positive"),
        sa.CheckConstraint("allocated_amount >= 0", name="ck_payment_allocated_amount"),
        sa.CheckConstraint("unallocated_amount >= 0", name="ck_payment_unallocated_amount"),
    )
    op.create_index("idx_payment_tenant", "payment", ["tenant_id"])
    op.create_index("idx_payment_customer", "payment", ["tenant_id", "customer_id"])
    op.create_index("idx_payment_supplier", "payment", ["tenant_id", "supplier_id"])
    op.create_index("idx_payment_status", "payment", ["status"])
    # §30: a partial unique index — only enforced when a client actually
    # supplies a client_transaction_id, the domain-level idempotency
    # layer on top of the HTTP Idempotency-Key guard.
    op.create_index(
        "uq_payment_client_transaction_id",
        "payment",
        ["tenant_id", "client_transaction_id"],
        unique=True,
        postgresql_where=sa.text("client_transaction_id IS NOT NULL"),
    )

    op.create_table(
        "payment_allocation",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("payment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("payment.id"), nullable=False),
        sa.Column("sales_invoice_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sales_invoice.id"), nullable=True),
        sa.Column("purchase_invoice_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("purchase_invoice.id"), nullable=True),
        sa.Column("allocated_amount", sa.Numeric(15, 2), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("row_version", sa.BigInteger, nullable=False, server_default="1"),
        sa.CheckConstraint(
            "(sales_invoice_id IS NOT NULL AND purchase_invoice_id IS NULL) OR "
            "(purchase_invoice_id IS NOT NULL AND sales_invoice_id IS NULL)",
            name="ck_payment_allocation_invoice_consistency",
        ),
        sa.CheckConstraint("allocated_amount > 0", name="ck_payment_allocation_amount_positive"),
    )
    op.create_index("idx_payment_allocation_tenant", "payment_allocation", ["tenant_id"])
    op.create_index("idx_payment_allocation_payment", "payment_allocation", ["payment_id"])
    op.create_index("idx_payment_allocation_sales_invoice", "payment_allocation", ["sales_invoice_id"])
    op.create_index("idx_payment_allocation_purchase_invoice", "payment_allocation", ["purchase_invoice_id"])

    for table in ("payment", "payment_allocation"):
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY tenant_isolation_{table} ON "{table}" '
            f"USING (tenant_id::text = current_setting('app.tenant_id', true))"
        )

    connection = op.get_bind()

    permission_ids: dict[str, str] = {}
    for code, description in _PAYMENT_PERMISSIONS.items():
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
    for table in ("payment_allocation", "payment"):
        op.execute(f'DROP POLICY IF EXISTS tenant_isolation_{table} ON "{table}"')
        op.drop_table(table)

    op.drop_column("purchase_invoice", "payment_status")
    op.drop_column("purchase_invoice", "paid_amount")
    op.drop_column("sales_invoice", "payment_status")
    op.drop_column("sales_invoice", "paid_amount")
    # Permission/role_permission seed rows left in place, matching precedent.
