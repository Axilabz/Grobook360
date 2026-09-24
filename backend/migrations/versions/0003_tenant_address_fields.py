"""Proposed schema addition: tenant address fields.

Revision ID: 0003_tenant_address_fields
Revises: 0002_idempotency_key
Create Date: 2026-09-05

Database Design & Data Dictionary v3.0's tenant table has no address columns.
PROMPT-002 S7 explicitly requires capturing organization Address/City/PIN Code
at sign-up. Added as nullable columns rather than silently collecting and
discarding this data. See PROMPT-002-NOTES.md for the proposed-change record.
"""

from alembic import op
import sqlalchemy as sa

revision = "0003_tenant_address_fields"
down_revision = "0002_idempotency_key"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tenant", sa.Column("address_line1", sa.String(255), nullable=True))
    op.add_column("tenant", sa.Column("city", sa.String(100), nullable=True))
    op.add_column("tenant", sa.Column("pin_code", sa.CHAR(6), nullable=True))


def downgrade() -> None:
    op.drop_column("tenant", "pin_code")
    op.drop_column("tenant", "city")
    op.drop_column("tenant", "address_line1")
