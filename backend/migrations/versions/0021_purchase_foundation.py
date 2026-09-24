"""Purchase Management Foundation (PROMPT-019): Purchase Order, Goods
Receipt, Purchase Invoice, Purchase Return + their permission catalogues.

Revision ID: 0021_purchase_foundation
Revises: 0020_gst_integration
Create Date: 2026-09-06

The Purchase-side mirror of the Sales chain built across PROMPT-011
through PROMPT-017: Purchase Order (never moves stock) -> Goods Receipt
(the first to move stock, STOCK_IN) -> Purchase Invoice (STOCK_IN only
when DIRECT, i.e. no source Goods Receipt) -> Purchase Return (STOCK_OUT,
against a source Purchase Invoice). All four header/line table pairs are
already fully specified in Data Dictionary v3.0 (domain PURCHASE) —
reused verbatim for their exact baseline field set; only the same class
of proposed additions every Sales-document migration has used are added
here (documented in each model's own docstring, not repeated in full
here): header GST split (cgst/sgst/igst_total over baseline's combined
tax_total), party/place-of-supply snapshots, notes, and the per-line
running-total/traceability columns each downstream document type needs
on its own immediate parent line
(`purchase_order_line.received_quantity`,
`goods_receipt_line.invoiced_quantity`,
`purchase_invoice_line.returned_quantity`) — identical pattern to
`sales_order_line.delivered_quantity` /
`delivery_challan_line.invoiced_quantity` /
`sales_invoice_line.returned_quantity`.

Status models (§9, adopted verbatim from the prompt's own suggested
baselines):
- Purchase Order: DRAFT, CONFIRMED, PARTIALLY_RECEIVED, FULLY_RECEIVED,
  CANCELLED (mirrors Sales Order's identical shape).
- Goods Receipt: DRAFT, CONFIRMED, CANCELLED (mirrors Delivery Challan).
- Purchase Invoice: DRAFT, POSTED, CANCELLED (mirrors Sales Invoice).
- Purchase Return: DRAFT, CONFIRMED, CANCELLED (mirrors Sales Return).

Cancellation-after-confirmation/posting is NOT implemented for any of
the four types (§25/§46 open decision #21) — same resolution as every
prior stock/financial-impacting Sales document, for the identical
reason (no approved reversal mechanism exists).

This foundation deliberately does NOT create any accounting/GST/payment
tables (§14/§42 explicit boundary) — Purchase Invoice's "increase
supplier payable balance" (FR-PINV-02) and any GST integration are left
as documented integration boundaries for a future prompt, not
implemented here.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0021_purchase_foundation"
down_revision = "0020_gst_integration"
branch_labels = None
depends_on = None

_PURCHASE_PERMISSIONS = {
    "purchase_order.view": "View tenant purchase orders",
    "purchase_order.create": "Create a purchase order",
    "purchase_order.edit": "Edit a draft purchase order",
    "purchase_order.confirm": "Confirm a purchase order for receiving",
    "purchase_order.cancel": "Cancel a purchase order",
    "goods_receipt.view": "View tenant goods receipts",
    "goods_receipt.create": "Create a goods receipt against a purchase order",
    "goods_receipt.edit": "Edit a draft goods receipt",
    "goods_receipt.confirm": "Confirm a goods receipt and receive stock",
    "goods_receipt.cancel": "Cancel a draft goods receipt",
    "purchase_invoice.view": "View tenant purchase invoices",
    "purchase_invoice.create": "Create a purchase invoice (direct or from a goods receipt)",
    "purchase_invoice.edit": "Edit a draft purchase invoice",
    "purchase_invoice.post": "Post a purchase invoice (stock/payable impact)",
    "purchase_invoice.cancel": "Cancel a draft purchase invoice",
    "purchase_return.view": "View tenant purchase returns",
    "purchase_return.create": "Create a purchase return against a posted purchase invoice",
    "purchase_return.edit": "Edit a draft purchase return",
    "purchase_return.confirm": "Confirm a purchase return (stock OUT impact)",
    "purchase_return.cancel": "Cancel a draft purchase return",
}

# §38/§46 open decision #23 — but here NOT ambiguous: FRD's own Table 7
# (Role & Screen matrix) lists "Purchase Purchase Orders / Goods Receipt
# / Purchase Invoice — Owner, Manager" with NO Salesperson entry at all,
# unlike every Sales module's matrix row (which always names Salesperson
# too, usually "Limited"). Resolved per that explicit signal: Salesperson
# gets ZERO purchase permissions in this foundation — not a judgment
# call, a direct reading of the approved FRD matrix.
_ROLE_DEFAULT_PERMISSIONS = {
    "OWNER": list(_PURCHASE_PERMISSIONS.keys()),
    "MANAGER": list(_PURCHASE_PERMISSIONS.keys()),
    "SALESPERSON": [],
}


def upgrade() -> None:
    _status_check = "status IN ('DRAFT','CONFIRMED','PARTIALLY_RECEIVED','FULLY_RECEIVED','CANCELLED')"

    # --- Purchase Order ---
    op.create_table(
        "purchase_order",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("po_number", sa.String(50), nullable=False),
        sa.Column("supplier_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("supplier.id"), nullable=False),
        sa.Column("supplier_gstin", sa.CHAR(15), nullable=True),
        sa.Column("billing_address", sa.String(500), nullable=True),
        sa.Column("shipping_address", sa.String(500), nullable=True),
        sa.Column("place_of_supply_state_code", sa.CHAR(2), nullable=True),
        sa.Column("document_date", sa.Date, nullable=False, server_default=sa.text("CURRENT_DATE")),
        sa.Column("status", sa.String(30), nullable=False, server_default="DRAFT"),
        sa.Column("notes", sa.String(1000), nullable=True),
        sa.Column("subtotal", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("discount_total", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("taxable_total", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("cgst_total", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("sgst_total", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("igst_total", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("tax_total", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("grand_total", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("row_version", sa.BigInteger, nullable=False, server_default="1"),
        sa.UniqueConstraint("tenant_id", "po_number", name="uq_purchase_order_number"),
        sa.CheckConstraint(_status_check, name="ck_purchase_order_status"),
        sa.CheckConstraint("subtotal >= 0", name="ck_purchase_order_subtotal"),
        sa.CheckConstraint("grand_total >= 0", name="ck_purchase_order_grand_total"),
    )
    op.create_index("idx_purchase_order_tenant", "purchase_order", ["tenant_id"])
    op.create_index("idx_purchase_order_supplier", "purchase_order", ["tenant_id", "supplier_id"])
    op.create_index("idx_purchase_order_status", "purchase_order", ["status"])

    op.create_table(
        "purchase_order_line",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("purchase_order_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("purchase_order.id"), nullable=False),
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
        sa.Column("received_quantity", sa.Numeric(18, 3), nullable=False, server_default="0"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("row_version", sa.BigInteger, nullable=False, server_default="1"),
        sa.UniqueConstraint("purchase_order_id", "line_no", name="uq_purchase_order_line_no"),
        sa.CheckConstraint("quantity > 0", name="ck_purchase_order_line_quantity"),
        sa.CheckConstraint("unit_price >= 0", name="ck_purchase_order_line_unit_price"),
        sa.CheckConstraint("received_quantity >= 0 AND received_quantity <= quantity", name="ck_purchase_order_line_received_quantity"),
    )
    op.create_index("idx_purchase_order_line_tenant", "purchase_order_line", ["tenant_id"])
    op.create_index("idx_purchase_order_line_order", "purchase_order_line", ["purchase_order_id"])

    # --- Goods Receipt ---
    op.create_table(
        "goods_receipt",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("grn_number", sa.String(50), nullable=False),
        sa.Column("supplier_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("supplier.id"), nullable=False),
        sa.Column("supplier_gstin", sa.CHAR(15), nullable=True),
        sa.Column("place_of_supply_state_code", sa.CHAR(2), nullable=True),
        sa.Column("source_purchase_order_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("purchase_order.id"), nullable=True),
        sa.Column("document_date", sa.Date, nullable=False, server_default=sa.text("CURRENT_DATE")),
        sa.Column("status", sa.String(30), nullable=False, server_default="DRAFT"),
        sa.Column("notes", sa.String(1000), nullable=True),
        sa.Column("total_quantity", sa.Numeric(18, 3), nullable=False, server_default="0"),
        sa.Column("subtotal", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("discount_total", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("taxable_total", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("cgst_total", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("sgst_total", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("igst_total", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("tax_total", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("grand_total", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("row_version", sa.BigInteger, nullable=False, server_default="1"),
        sa.UniqueConstraint("tenant_id", "grn_number", name="uq_goods_receipt_number"),
        sa.CheckConstraint("status IN ('DRAFT','CONFIRMED','CANCELLED')", name="ck_goods_receipt_status"),
        sa.CheckConstraint("subtotal >= 0", name="ck_goods_receipt_subtotal"),
        sa.CheckConstraint("grand_total >= 0", name="ck_goods_receipt_grand_total"),
    )
    op.create_index("idx_goods_receipt_tenant", "goods_receipt", ["tenant_id"])
    op.create_index("idx_goods_receipt_source_po", "goods_receipt", ["tenant_id", "source_purchase_order_id"])
    op.create_index("idx_goods_receipt_status", "goods_receipt", ["status"])

    op.create_table(
        "goods_receipt_line",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("goods_receipt_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("goods_receipt.id"), nullable=False),
        sa.Column("line_no", sa.Integer, nullable=False),
        sa.Column("source_purchase_order_line_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("purchase_order_line.id"), nullable=True),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("product.id"), nullable=True),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("hsn_code", sa.String(8), nullable=True),
        sa.Column("ordered_quantity", sa.Numeric(18, 3), nullable=False, server_default="0"),
        sa.Column("previously_received_quantity", sa.Numeric(18, 3), nullable=False, server_default="0"),
        sa.Column("quantity", sa.Numeric(18, 3), nullable=False),
        sa.Column("remaining_quantity", sa.Numeric(18, 3), nullable=False, server_default="0"),
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
        sa.Column("invoiced_quantity", sa.Numeric(18, 3), nullable=False, server_default="0"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("row_version", sa.BigInteger, nullable=False, server_default="1"),
        sa.UniqueConstraint("goods_receipt_id", "line_no", name="uq_goods_receipt_line_no"),
        sa.CheckConstraint("quantity > 0", name="ck_goods_receipt_line_quantity"),
        sa.CheckConstraint("invoiced_quantity >= 0 AND invoiced_quantity <= quantity", name="ck_goods_receipt_line_invoiced_quantity"),
    )
    op.create_index("idx_goods_receipt_line_tenant", "goods_receipt_line", ["tenant_id"])
    op.create_index("idx_goods_receipt_line_receipt", "goods_receipt_line", ["goods_receipt_id"])
    op.create_index("idx_goods_receipt_line_source_po_line", "goods_receipt_line", ["source_purchase_order_line_id"])

    # --- Purchase Invoice ---
    op.create_table(
        "purchase_invoice",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("purchase_invoice_number", sa.String(50), nullable=False),
        sa.Column("supplier_invoice_number", sa.String(50), nullable=True),
        sa.Column("invoice_type", sa.String(40), nullable=False),
        sa.Column("supplier_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("supplier.id"), nullable=False),
        sa.Column("supplier_gstin", sa.CHAR(15), nullable=True),
        sa.Column("place_of_supply_state_code", sa.CHAR(2), nullable=True),
        sa.Column("source_goods_receipt_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("goods_receipt.id"), nullable=True),
        sa.Column("document_date", sa.Date, nullable=False, server_default=sa.text("CURRENT_DATE")),
        sa.Column("status", sa.String(30), nullable=False, server_default="DRAFT"),
        sa.Column("notes", sa.String(1000), nullable=True),
        sa.Column("subtotal", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("discount_total", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("taxable_total", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("cgst_total", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("sgst_total", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("igst_total", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("tax_total", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("grand_total", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("row_version", sa.BigInteger, nullable=False, server_default="1"),
        sa.UniqueConstraint("tenant_id", "purchase_invoice_number", name="uq_purchase_invoice_number"),
        sa.CheckConstraint("status IN ('DRAFT','POSTED','CANCELLED')", name="ck_purchase_invoice_status"),
        sa.CheckConstraint("invoice_type IN ('DIRECT_PURCHASE_INVOICE','GOODS_RECEIPT_PURCHASE_INVOICE')", name="ck_purchase_invoice_type"),
        sa.CheckConstraint(
            "(invoice_type = 'DIRECT_PURCHASE_INVOICE' AND source_goods_receipt_id IS NULL) OR "
            "(invoice_type = 'GOODS_RECEIPT_PURCHASE_INVOICE' AND source_goods_receipt_id IS NOT NULL)",
            name="ck_purchase_invoice_source_consistency",
        ),
        sa.CheckConstraint("subtotal >= 0", name="ck_purchase_invoice_subtotal"),
        sa.CheckConstraint("grand_total >= 0", name="ck_purchase_invoice_grand_total"),
    )
    op.create_index("idx_purchase_invoice_tenant", "purchase_invoice", ["tenant_id"])
    op.create_index("idx_purchase_invoice_supplier", "purchase_invoice", ["tenant_id", "supplier_id"])
    op.create_index("idx_purchase_invoice_source_gr", "purchase_invoice", ["tenant_id", "source_goods_receipt_id"])
    op.create_index("idx_purchase_invoice_status", "purchase_invoice", ["status"])

    op.create_table(
        "purchase_invoice_line",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("purchase_invoice_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("purchase_invoice.id"), nullable=False),
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
        sa.Column("source_goods_receipt_line_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("goods_receipt_line.id"), nullable=True),
        sa.Column("returned_quantity", sa.Numeric(18, 3), nullable=False, server_default="0"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("row_version", sa.BigInteger, nullable=False, server_default="1"),
        sa.UniqueConstraint("purchase_invoice_id", "line_no", name="uq_purchase_invoice_line_no"),
        sa.CheckConstraint("quantity > 0", name="ck_purchase_invoice_line_quantity"),
        sa.CheckConstraint("returned_quantity >= 0 AND returned_quantity <= quantity", name="ck_purchase_invoice_line_returned_quantity"),
    )
    op.create_index("idx_purchase_invoice_line_tenant", "purchase_invoice_line", ["tenant_id"])
    op.create_index("idx_purchase_invoice_line_invoice", "purchase_invoice_line", ["purchase_invoice_id"])
    op.create_index("idx_purchase_invoice_line_source_gr_line", "purchase_invoice_line", ["source_goods_receipt_line_id"])

    # --- Purchase Return ---
    op.create_table(
        "purchase_return",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("purchase_return_number", sa.String(50), nullable=False),
        sa.Column("supplier_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("supplier.id"), nullable=False),
        sa.Column("supplier_gstin", sa.CHAR(15), nullable=True),
        sa.Column("place_of_supply_state_code", sa.CHAR(2), nullable=True),
        sa.Column("source_purchase_invoice_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("purchase_invoice.id"), nullable=False),
        sa.Column("document_date", sa.Date, nullable=False, server_default=sa.text("CURRENT_DATE")),
        sa.Column("status", sa.String(30), nullable=False, server_default="DRAFT"),
        sa.Column("return_reason", sa.String(30), nullable=False),
        sa.Column("reason_description", sa.String(500), nullable=True),
        sa.Column("notes", sa.String(1000), nullable=True),
        sa.Column("total_return_quantity", sa.Numeric(18, 3), nullable=False, server_default="0"),
        sa.Column("subtotal", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("discount_total", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("taxable_total", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("cgst_total", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("sgst_total", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("igst_total", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("tax_total", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("grand_total", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("row_version", sa.BigInteger, nullable=False, server_default="1"),
        sa.UniqueConstraint("tenant_id", "purchase_return_number", name="uq_purchase_return_number"),
        sa.CheckConstraint("status IN ('DRAFT','CONFIRMED','CANCELLED')", name="ck_purchase_return_status"),
        sa.CheckConstraint(
            "return_reason IN ('DAMAGED','WRONG_PRODUCT','EXCESS_QUANTITY','QUALITY_ISSUE','PRICE_DISPUTE','OTHER')",
            name="ck_purchase_return_reason",
        ),
        sa.CheckConstraint("subtotal >= 0", name="ck_purchase_return_subtotal"),
        sa.CheckConstraint("grand_total >= 0", name="ck_purchase_return_grand_total"),
    )
    op.create_index("idx_purchase_return_tenant", "purchase_return", ["tenant_id"])
    op.create_index("idx_purchase_return_source_invoice", "purchase_return", ["tenant_id", "source_purchase_invoice_id"])
    op.create_index("idx_purchase_return_status", "purchase_return", ["status"])

    op.create_table(
        "purchase_return_line",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("purchase_return_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("purchase_return.id"), nullable=False),
        sa.Column("line_no", sa.Integer, nullable=False),
        sa.Column("source_purchase_invoice_line_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("purchase_invoice_line.id"), nullable=False),
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
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("row_version", sa.BigInteger, nullable=False, server_default="1"),
        sa.UniqueConstraint("purchase_return_id", "line_no", name="uq_purchase_return_line_no"),
        sa.CheckConstraint("quantity > 0", name="ck_purchase_return_line_quantity"),
    )
    op.create_index("idx_purchase_return_line_tenant", "purchase_return_line", ["tenant_id"])
    op.create_index("idx_purchase_return_line_return", "purchase_return_line", ["purchase_return_id"])
    op.create_index("idx_purchase_return_line_source_invoice_line", "purchase_return_line", ["source_purchase_invoice_line_id"])

    for table in (
        "purchase_order", "purchase_order_line", "goods_receipt", "goods_receipt_line",
        "purchase_invoice", "purchase_invoice_line", "purchase_return", "purchase_return_line",
    ):
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY tenant_isolation_{table} ON "{table}" '
            f"USING (tenant_id::text = current_setting('app.tenant_id', true))"
        )

    connection = op.get_bind()

    permission_ids: dict[str, str] = {}
    for code, description in _PURCHASE_PERMISSIONS.items():
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
    for table in (
        "purchase_return_line", "purchase_return", "purchase_invoice_line", "purchase_invoice",
        "goods_receipt_line", "goods_receipt", "purchase_order_line", "purchase_order",
    ):
        op.execute(f'DROP POLICY IF EXISTS tenant_isolation_{table} ON "{table}"')
        op.drop_table(table)
    # Permission/role_permission seed rows left in place, matching precedent.
