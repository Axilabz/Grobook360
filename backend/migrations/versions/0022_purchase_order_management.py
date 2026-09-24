"""Purchase Order Management (PROMPT-020): header field additions.

Revision ID: 0022_purchase_order_management
Revises: 0021_purchase_foundation
Create Date: 2026-09-07

PROMPT-020's own §4 header-field list names several fields the
PROMPT-019 foundation's `purchase_order` table doesn't yet carry:
`supplier_reference`, `expected_delivery_date`, `payment_terms`,
`delivery_terms`. Following the established "propose, document,
implement" pattern (see CLAUDE.md §3): none of these are in the approved
Data Dictionary v3.0 baseline either, so they are added here as
documented proposed additions, all nullable (optional per §48 Open
Decisions #6-9 below) so no existing row is broken.

Deliberately NOT added in this migration (see PROMPT-020-NOTES.md open
decisions for the full rationale):
- `location_id` — M1 only ever has one lazily-provisioned "MAIN"
  location per tenant (PROMPT-010 §8); a location FK on every Purchase
  Order would be dead weight until multi-location is approved.
- `currency` — this MVP is single-currency (INR) throughout; no other
  Sales or Purchase document carries a currency column either.
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0022_purchase_order_management"
down_revision = "0021_purchase_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("purchase_order", sa.Column("supplier_reference", sa.String(100), nullable=True))
    op.add_column("purchase_order", sa.Column("expected_delivery_date", sa.Date, nullable=True))
    op.add_column("purchase_order", sa.Column("payment_terms", sa.String(200), nullable=True))
    op.add_column("purchase_order", sa.Column("delivery_terms", sa.String(200), nullable=True))


def downgrade() -> None:
    op.drop_column("purchase_order", "delivery_terms")
    op.drop_column("purchase_order", "payment_terms")
    op.drop_column("purchase_order", "expected_delivery_date")
    op.drop_column("purchase_order", "supplier_reference")
