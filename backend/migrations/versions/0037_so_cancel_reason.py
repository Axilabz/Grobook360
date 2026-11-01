"""Sales Order cancellation reason — require a reason when cancelling.

Revision ID: 0037_so_cancel_reason
Revises: 0036_tenant_code
Create Date: 2026-10-25

Proposed schema addition (the usual "propose, document, implement"
pattern — see CLAUDE.md S3): no approved source defines a cancellation-
reason field for Sales Order, but this codebase already has the exact
precedent to follow — `einvoice.cancellation_reason`/`eway_bill.
cancellation_reason` (both `VARCHAR(500)`, required at the API layer via
`EinvoiceCancelRequest`/`EwayBillCancelRequest`, PROMPT-018). Mirrors that
shape exactly. Nullable at the DB level (only ever set when a CONFIRMED-
or-earlier order is cancelled; never required on any other transition).

Revision id kept short (<=32 chars) — `alembic_version.version_num` is
`VARCHAR(32)`; a longer descriptive id (tried first) failed with
`StringDataRightTruncation` on upgrade.
"""

from alembic import op
import sqlalchemy as sa

revision = "0037_so_cancel_reason"
down_revision = "0036_tenant_code"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sales_order", sa.Column("cancellation_reason", sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_column("sales_order", "cancellation_reason")
