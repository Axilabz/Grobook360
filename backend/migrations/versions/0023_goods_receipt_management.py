"""Goods Receipt Management (PROMPT-021): supplier delivery note header
field.

Revision ID: 0023_goods_receipt_management
Revises: 0022_purchase_order_management
Create Date: 2026-09-11

PROMPT-021's own §5/§28 header-field list names `supplier_delivery_note`
(the supplier's own delivery-note/challan reference) — not in the
approved Data Dictionary v3.0 baseline, so added here as a documented
proposed addition (nullable, optional per §60 Open Decision #8), the
same "propose, document, implement" pattern used for every prior
Purchase/Sales header-field addition.

Deliberately NOT added in this migration (see PROMPT-021-NOTES.md open
decisions for the full rationale): a `receipt_location_id` FK — M1 only
ever has one lazily-provisioned "MAIN" location per tenant (PROMPT-010
§8), the same reasoning PROMPT-020 already applied to Purchase Order's
own `location_id` decision (migration 0022).

No goods_receipt_line schema change is needed for confirmed-GR
cancellation/reversal (§23-25) — the reversal's compensating Stock OUT
reuses `goods_receipt_line.id` as its `stock_ledger_entry.source_id`
with a NEW `source_type` ('GOODS_RECEIPT_REVERSAL', see
`app/core/purchase_constants.py`), which the existing
`uq_stock_ledger_entry_source (tenant_id, source_type, source_id)`
constraint already accommodates without any DDL change.
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0023_goods_receipt_management"
down_revision = "0022_purchase_order_management"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("goods_receipt", sa.Column("supplier_delivery_note", sa.String(100), nullable=True))


def downgrade() -> None:
    op.drop_column("goods_receipt", "supplier_delivery_note")
