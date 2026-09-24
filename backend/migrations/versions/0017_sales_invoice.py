"""Sales Invoice (PROMPT-015) + sales_invoice.* permission catalogue +
Delivery Challan invoiced-quantity tracking.

Revision ID: 0017_sales_invoice
Revises: 0016_delivery_challan
Create Date: 2026-10-03

The fourth and final MVP Sales document type — the authoritative billing
transaction. Two creation paths converge on one table:

- DIRECT_SALES_INVOICE: billed without a source document; posting creates
  a Stock OUT itself (the first and only OTHER document type besides
  Delivery Challan permitted to call `InventoryService.post_movement`).
- DELIVERY_CHALLAN_SALES_INVOICE: billed against an already-CONFIRMED
  Delivery Challan; posting creates NO stock movement at all, because the
  Delivery Challan already reduced stock at ITS OWN confirm time (§2/§16
  — this is the single most safety-critical rule in this prompt).

Data Dictionary v3.0 specifies `sales_invoice`/`sales_invoice_item` (SALES
domain) for the core identity/financial/GST columns — reused verbatim for
the same field set Estimate/Sales Order already established (subtotal,
discount_total, taxable_total, cgst/sgst/igst_total, tax_total,
grand_total; line quantity/unit_price/discount/taxable/gst/line_total).

Proposed schema additions (same "propose, document, implement" pattern):

- `sales_invoice.customer_gstin`, `.billing_address`, `.shipping_address`,
  `.place_of_supply_state_code` (snapshots, same principle as every prior
  Sales document).
- `sales_invoice.customer_type` ('B2B'/'B2C', derived from GSTIN presence
  at creation time — the same rule `ValidatedCustomer.is_b2b` already
  uses): §8/§22 explicitly list "Customer Type" as GST-reporting metadata
  the invoice must retain; no new business rule invented, just persisting
  a fact already computed elsewhere.
- `sales_invoice.invoice_type` ('DIRECT_SALES_INVOICE' /
  'DELIVERY_CHALLAN_SALES_INVOICE'): §9's own required controlled type.
- `sales_invoice.source_delivery_challan_id` (nullable FK, UNIQUE-per-line
  enforcement lives on the LINE table, not here — see below),
  `.source_sales_order_id` (nullable FK, populated transitively from the
  source DC's own source order when DC-based; NULL for direct invoices).
- `sales_invoice.accounting_posting_reference`,
  `.gst_transaction_reference` (both nullable VARCHAR): §21/§22's
  integration-boundary contract — see
  `app/services/accounting/accounting_posting_service.py` and
  `app/services/sales/gst_reporting_service.py`. Neither is a foreign key
  to a real ledger/GST table, because neither the Accounting Posting
  Matrix nor a GST transaction table exists yet — they are opaque
  reference strings a future module can resolve, not a schema commitment
  to their eventual shape (documented Open Decision #18).
- `sales_invoice.irn`, `.ack_number`, `.ack_date`, `.einvoice_status`,
  `.qr_code_data` (all nullable): §23's e-Invoice integration boundary —
  reserved columns, never written to by this prompt (PROMPT-018's own
  scope per that section's own numbering). No `signed_invoice_data`
  column: an NIC-signed invoice payload is a large opaque blob with no
  approved size/format yet; reserving a column for content nobody can
  specify the shape of would be inventing a contract, not documenting
  one — PROMPT-018 adds it once the actual e-Invoice spec is available.
- `sales_invoice.notes`: covers "Notes" and "Terms" (§8) as one field,
  identical resolution to every prior Sales document.
- `sales_invoice_line.hsn_code`: line-level HSN snapshot, same as every
  prior Sales document line.
- `sales_invoice_line.source_delivery_challan_line_id` (nullable FK):
  §24's per-DC-line invoiceable-quantity tracking needs a stable
  per-line link, mirroring `delivery_challan_line.source_sales_order_line_id`'s
  own pattern one level up the chain.

No `round_off` column: §17 Open Decision #17 restated for Invoice, same
as Estimate/Sales Order — no approved rounding rule exists.

Delivery Challan changes (this same migration, since Sales Invoice cannot
enforce §16's double-stock-deduction rule without it):

- `delivery_challan_line.invoiced_quantity` (NUMERIC(18,3), default 0):
  cumulative quantity already invoiced against this delivery line,
  incremented only by `SalesInvoiceService.post_invoice`. `CHECK
  (invoiced_quantity >= 0 AND invoiced_quantity <= current_delivery_quantity)`
  is the DB-level backstop for "invoiced can never exceed delivered" (§24) —
  the same class of constraint as `sales_order_line.delivered_quantity`'s
  own CHECK from migration 0016. The real "does this specific new invoice
  request exceed the CURRENTLY remaining invoiceable amount" comparison
  still happens in application code under a row lock (same reasoning as
  migration 0016's identical caveat for Sales Order).

Status model (§10, explicit open decision #1): adopted the prompt's own
recommended baseline verbatim — DRAFT, POSTED, CANCELLED. No
"PARTIALLY_INVOICED"-style status on Delivery Challan itself: like Sales
Order's fulfillment tracking, per-DC-line invoiced-quantity is a plain
column comparison, not a status machine.

Cancellation-after-posting (§11/§35, explicit open decisions #4-7): NOT
implemented — mirrors Delivery Challan's own identical resolution in
PROMPT-014 for the identical reason (no approved reversal mechanism for
stock/accounting/GST exists). `ck_sales_invoice_status` still allows
CANCELLED (for a DRAFT to be cancelled); the application layer restricts
POSTED -> CANCELLED until reversal design is approved.

Numbering: reuses `document_number_sequence`/`DocumentNumberingService`
with document_type="SALES_INVOICE" (already reserved in
`app.core.sales_constants` since PROMPT-011) — no separate numbering
mechanism, per §19's explicit instruction.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0017_sales_invoice"
down_revision = "0016_delivery_challan"
branch_labels = None
depends_on = None

_SALES_INVOICE_PERMISSIONS = {
    "sales_invoice.view": "View tenant sales invoices",
    "sales_invoice.create": "Create a sales invoice (direct or from a delivery challan)",
    "sales_invoice.edit": "Edit a draft sales invoice",
    "sales_invoice.post": "Post a sales invoice (stock/accounting/GST impact)",
    "sales_invoice.cancel": "Cancel a draft sales invoice",
}

# No approved source defines exact per-role Sales Invoice permissions
# (§41/§52 Q2/Q3 — open decisions, documented in PROMPT-015-NOTES.md).
# Resolved by mirroring Sales Order/Delivery Challan's established shape:
# Salesperson gets the full day-to-day lifecycle except POST — User Story
# 3 explicitly names "Owner/Manager" as the actor for whom posted
# invoices become immutable, the same textual signal that resolved this
# identical question for Sales Order (confirm) and Delivery Challan
# (confirm) in the two prior prompts.
_ROLE_DEFAULT_PERMISSIONS = {
    "OWNER": [
        "sales_invoice.view", "sales_invoice.create", "sales_invoice.edit",
        "sales_invoice.post", "sales_invoice.cancel",
    ],
    "MANAGER": [
        "sales_invoice.view", "sales_invoice.create", "sales_invoice.edit",
        "sales_invoice.post", "sales_invoice.cancel",
    ],
    "SALESPERSON": [
        "sales_invoice.view", "sales_invoice.create", "sales_invoice.edit", "sales_invoice.cancel",
    ],
}


def upgrade() -> None:
    # --- Delivery Challan invoiced-quantity tracking (needed by Sales Invoice) ---
    op.add_column(
        "delivery_challan_line",
        sa.Column("invoiced_quantity", sa.Numeric(18, 3), nullable=False, server_default="0"),
    )
    op.create_check_constraint(
        "ck_delivery_challan_line_invoiced_quantity",
        "delivery_challan_line",
        "invoiced_quantity >= 0 AND invoiced_quantity <= current_delivery_quantity",
    )

    # --- Sales Invoice tables ---
    op.create_table(
        "sales_invoice",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("invoice_number", sa.String(50), nullable=False),
        sa.Column("invoice_date", sa.Date, nullable=False, server_default=sa.text("CURRENT_DATE")),
        sa.Column("invoice_type", sa.String(40), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("customer.id"), nullable=False),
        sa.Column("customer_gstin", sa.CHAR(15), nullable=True),
        sa.Column("customer_type", sa.String(10), nullable=False, server_default="B2C"),
        sa.Column("billing_address", sa.String(500), nullable=True),
        sa.Column("shipping_address", sa.String(500), nullable=True),
        sa.Column("place_of_supply_state_code", sa.CHAR(2), nullable=True),
        sa.Column("source_delivery_challan_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("delivery_challan.id"), nullable=True),
        sa.Column("source_sales_order_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sales_order.id"), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="DRAFT"),
        sa.Column("subtotal", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("discount_total", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("taxable_total", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("cgst_total", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("sgst_total", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("igst_total", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("tax_total", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("grand_total", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("notes", sa.String(1000), nullable=True),
        # Integration boundaries — see module docstring. Opaque references,
        # not foreign keys to tables that don't exist yet.
        sa.Column("accounting_posting_reference", sa.String(100), nullable=True),
        sa.Column("gst_transaction_reference", sa.String(100), nullable=True),
        # e-Invoice boundary (§23) — reserved for PROMPT-018, never written here.
        sa.Column("irn", sa.String(100), nullable=True),
        sa.Column("ack_number", sa.String(50), nullable=True),
        sa.Column("ack_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("einvoice_status", sa.String(30), nullable=True),
        sa.Column("qr_code_data", sa.Text, nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("row_version", sa.BigInteger, nullable=False, server_default="1"),
        sa.UniqueConstraint("tenant_id", "invoice_number", name="uq_sales_invoice_number"),
        sa.CheckConstraint("status IN ('DRAFT','POSTED','CANCELLED')", name="ck_sales_invoice_status"),
        sa.CheckConstraint(
            "invoice_type IN ('DIRECT_SALES_INVOICE','DELIVERY_CHALLAN_SALES_INVOICE')",
            name="ck_sales_invoice_type",
        ),
        sa.CheckConstraint("customer_type IN ('B2B','B2C')", name="ck_sales_invoice_customer_type"),
        # §2/§16: a DIRECT invoice has no source DC; a DC-based invoice
        # MUST have one — enforced at the DB level, not just app logic.
        sa.CheckConstraint(
            "(invoice_type = 'DIRECT_SALES_INVOICE' AND source_delivery_challan_id IS NULL) OR "
            "(invoice_type = 'DELIVERY_CHALLAN_SALES_INVOICE' AND source_delivery_challan_id IS NOT NULL)",
            name="ck_sales_invoice_source_consistency",
        ),
        sa.CheckConstraint("subtotal >= 0", name="ck_sales_invoice_subtotal"),
        sa.CheckConstraint("discount_total >= 0", name="ck_sales_invoice_discount_total"),
        sa.CheckConstraint("grand_total >= 0", name="ck_sales_invoice_grand_total"),
    )
    op.create_index("idx_sales_invoice_tenant", "sales_invoice", ["tenant_id"])
    op.create_index("idx_sales_invoice_customer", "sales_invoice", ["tenant_id", "customer_id"])
    op.create_index("idx_sales_invoice_source_dc", "sales_invoice", ["tenant_id", "source_delivery_challan_id"])
    op.create_index("idx_sales_invoice_source_so", "sales_invoice", ["tenant_id", "source_sales_order_id"])
    op.create_index("idx_sales_invoice_status", "sales_invoice", ["status"])

    op.create_table(
        "sales_invoice_line",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("invoice_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sales_invoice.id"), nullable=False),
        sa.Column("line_no", sa.Integer, nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("product.id"), nullable=True),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("hsn_code", sa.String(8), nullable=True),
        sa.Column("quantity", sa.Numeric(18, 3), nullable=False),
        sa.Column("uom_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("unit_of_measure.id"), nullable=False),
        sa.Column("unit_price", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("discount_amount", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("taxable_amount", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("gst_rate", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column("cgst_amount", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("sgst_amount", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("igst_amount", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("cess_amount", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("line_total", sa.Numeric(15, 2), nullable=False, server_default="0"),
        # Proposed addition — see module docstring.
        sa.Column("source_delivery_challan_line_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("delivery_challan_line.id"), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("row_version", sa.BigInteger, nullable=False, server_default="1"),
        sa.UniqueConstraint("invoice_id", "line_no", name="uq_sales_invoice_line_no"),
        sa.CheckConstraint("quantity > 0", name="ck_sales_invoice_line_quantity"),
        sa.CheckConstraint("unit_price >= 0", name="ck_sales_invoice_line_unit_price"),
        sa.CheckConstraint("discount_amount >= 0", name="ck_sales_invoice_line_discount"),
        sa.CheckConstraint("gst_rate >= 0 AND gst_rate <= 100", name="ck_sales_invoice_line_gst_rate"),
    )
    op.create_index("idx_sales_invoice_line_tenant", "sales_invoice_line", ["tenant_id"])
    op.create_index("idx_sales_invoice_line_invoice", "sales_invoice_line", ["invoice_id"])
    op.create_index("idx_sales_invoice_line_source_dc_line", "sales_invoice_line", ["source_delivery_challan_line_id"])

    for table in ("sales_invoice", "sales_invoice_line"):
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY tenant_isolation_{table} ON "{table}" '
            f"USING (tenant_id::text = current_setting('app.tenant_id', true))"
        )

    connection = op.get_bind()

    permission_ids: dict[str, str] = {}
    for code, description in _SALES_INVOICE_PERMISSIONS.items():
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
    for table in ("sales_invoice_line", "sales_invoice"):
        op.execute(f'DROP POLICY IF EXISTS tenant_isolation_{table} ON "{table}"')
    op.drop_table("sales_invoice_line")
    op.drop_table("sales_invoice")

    op.drop_constraint("ck_delivery_challan_line_invoiced_quantity", "delivery_challan_line", type_="check")
    op.drop_column("delivery_challan_line", "invoiced_quantity")
    # Permission/role_permission seed rows left in place, matching precedent.
