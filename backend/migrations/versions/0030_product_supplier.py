"""Product Master: primary supplier reference (user-requested follow-up).

Revision ID: 0030_product_supplier
Revises: 0029_employee_payroll
Create Date: 2026-09-23

Adds a nullable `supplier_id` FK from `product` to `supplier`, so a
product can record its preferred/primary vendor for reorder purposes.
Deliberately does NOT add separate `supplier_name`/`supplier_phone`
columns on `product` — those would be a denormalized snapshot that goes
stale the moment the supplier's own name/phone changes (Product is live
master data, not a posted transaction that needs a frozen historical
snapshot — see CLAUDE.md's own "never duplicate master data
unnecessarily" discipline, PROMPT-035). The API instead joins `supplier`
at read time so `supplier_name`/`supplier_phone` are always exposed
already-populated and always current, without a second, driftable copy.
Nullable throughout: an existing product with no supplier recorded yet is
a valid, non-error state — not every product need have one.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0030_product_supplier"
down_revision = "0029_employee_payroll"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "product",
        sa.Column("supplier_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("supplier.id"), nullable=True),
    )
    op.create_index("ix_product_supplier_id", "product", ["supplier_id"])


def downgrade() -> None:
    op.drop_index("ix_product_supplier_id", table_name="product")
    op.drop_column("product", "supplier_id")
