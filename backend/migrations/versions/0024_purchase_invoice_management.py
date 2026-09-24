"""Purchase Invoice Management (PROMPT-022): PO-linked invoicing,
supplier invoice date/due date, and confirmed-invoice cancellation
reversal support.

Revision ID: 0024_purchase_invoice_management
Revises: 0023_goods_receipt_management
Create Date: 2026-09-11

PROMPT-019's foundation only supported two invoice types: DIRECT (no
source document, creates its own Stock IN) and GOODS_RECEIPT-sourced
(one specific pre-selected GR, no stock impact). This prompt's own
"Supported Flow 2" (Supplier -> Purchase Order -> Purchase Invoice,
skipping a specific GR selection) requires a genuine schema addition:

- `purchase_invoice.source_purchase_order_id` (nullable FK) — header-
  level traceability for a THIRD invoice_type,
  `PURCHASE_ORDER_PURCHASE_INVOICE`, that consolidates eligible
  quantity across potentially MULTIPLE confirmed Goods Receipts under
  one Purchase Order in a single invoice (§9/§18/§57 TC-020's own
  "multiple GR linkage" scenario) rather than requiring the user to
  pre-pick one GR document. Every line on such an invoice still
  ultimately traces to a specific `goods_receipt_line` (via the
  existing `source_goods_receipt_line_id`) — the new type only changes
  HOW the eligible-quantity picker works, not the underlying stock/
  quantity-tracking invariant (INVARIANT 3/5: one physical receipt is
  never counted twice, enforced via the SAME `goods_receipt_line.
  invoiced_quantity` counter every invoicing path already shares).
- `purchase_invoice_line.source_purchase_order_line_id` (nullable FK) —
  which PO line a PO-consolidated invoice line was requested against
  (a line can still only carry ONE contributing GR line, per the
  existing `source_goods_receipt_line_id` column — a PO-line request
  spanning multiple GR lines becomes multiple `purchase_invoice_line`
  rows, one per contributing GR line, mirroring how a single PO line
  can already receive via multiple GRs).
- `purchase_invoice.supplier_invoice_date` (nullable date) and
  `.due_date` (nullable date) — named separately from `document_date`
  (this application's own internal invoice date) per §5/§13's own
  header-field list; neither is in the approved Data Dictionary v3.0
  baseline, added as documented proposed additions (§67 Open Decision
  #8: supplier invoice date rules are not otherwise approved, so no
  validation beyond "must be a valid date" is added here).

No column changes were needed to support confirmed-invoice cancellation
reversal (§33-35, mirrors PROMPT-021's Goods-Receipt reversal design
exactly) — the compensating STOCK_OUT reuses `purchase_invoice_line.id`
as its `stock_ledger_entry.source_id` with a NEW `source_type`
('PURCHASE_INVOICE_REVERSAL', see `app/core/purchase_constants.py`),
which `uq_stock_ledger_entry_source` already accommodates without
colliding with the original `source_type='PURCHASE_INVOICE'` STOCK_IN
entry. The downstream-dependency check for a GR/PO-sourced invoice
reuses the already-existing `purchase_invoice_line.returned_quantity`
column (added in migration 0021) — no new column needed there either.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "0024_purchase_invoice_management"
down_revision = "0023_goods_receipt_management"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "purchase_invoice",
        sa.Column("source_purchase_order_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("purchase_order.id"), nullable=True),
    )
    op.add_column("purchase_invoice", sa.Column("supplier_invoice_date", sa.Date, nullable=True))
    op.add_column("purchase_invoice", sa.Column("due_date", sa.Date, nullable=True))
    op.create_index("idx_purchase_invoice_source_po", "purchase_invoice", ["tenant_id", "source_purchase_order_id"])

    op.drop_constraint("ck_purchase_invoice_type", "purchase_invoice", type_="check")
    op.create_check_constraint(
        "ck_purchase_invoice_type",
        "purchase_invoice",
        "invoice_type IN ('DIRECT_PURCHASE_INVOICE','GOODS_RECEIPT_PURCHASE_INVOICE','PURCHASE_ORDER_PURCHASE_INVOICE')",
    )

    op.drop_constraint("ck_purchase_invoice_source_consistency", "purchase_invoice", type_="check")
    op.create_check_constraint(
        "ck_purchase_invoice_source_consistency",
        "purchase_invoice",
        "(invoice_type = 'DIRECT_PURCHASE_INVOICE' AND source_goods_receipt_id IS NULL AND source_purchase_order_id IS NULL) OR "
        "(invoice_type = 'GOODS_RECEIPT_PURCHASE_INVOICE' AND source_goods_receipt_id IS NOT NULL) OR "
        "(invoice_type = 'PURCHASE_ORDER_PURCHASE_INVOICE' AND source_purchase_order_id IS NOT NULL AND source_goods_receipt_id IS NULL)",
    )

    op.add_column(
        "purchase_invoice_line",
        sa.Column("source_purchase_order_line_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("purchase_order_line.id"), nullable=True),
    )
    op.create_index("idx_purchase_invoice_line_source_po_line", "purchase_invoice_line", ["source_purchase_order_line_id"])


def downgrade() -> None:
    op.drop_index("idx_purchase_invoice_line_source_po_line", table_name="purchase_invoice_line")
    op.drop_column("purchase_invoice_line", "source_purchase_order_line_id")

    op.drop_constraint("ck_purchase_invoice_source_consistency", "purchase_invoice", type_="check")
    op.create_check_constraint(
        "ck_purchase_invoice_source_consistency",
        "purchase_invoice",
        "(invoice_type = 'DIRECT_PURCHASE_INVOICE' AND source_goods_receipt_id IS NULL) OR "
        "(invoice_type = 'GOODS_RECEIPT_PURCHASE_INVOICE' AND source_goods_receipt_id IS NOT NULL)",
    )
    op.drop_constraint("ck_purchase_invoice_type", "purchase_invoice", type_="check")
    op.create_check_constraint(
        "ck_purchase_invoice_type",
        "purchase_invoice",
        "invoice_type IN ('DIRECT_PURCHASE_INVOICE','GOODS_RECEIPT_PURCHASE_INVOICE')",
    )

    op.drop_index("idx_purchase_invoice_source_po", table_name="purchase_invoice")
    op.drop_column("purchase_invoice", "due_date")
    op.drop_column("purchase_invoice", "supplier_invoice_date")
    op.drop_column("purchase_invoice", "source_purchase_order_id")
