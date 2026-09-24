"""Proposed schema addition: idempotency_key table.

Revision ID: 0002_idempotency_key
Revises: 0001_foundation_schema
Create Date: 2026-09-04

Not present in Database Design & Data Dictionary v3.0. Added because API
Contract Specification v1.0 S10.1 requires idempotent-request storage that no
approved table covers. See backend/README.md / PROMPT-002 notes for the
proposed-change rationale (PROMPT-002 S31 process).
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002_idempotency_key"
down_revision = "0001_foundation_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "idempotency_key",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenant.id"), nullable=True),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("endpoint", sa.String(255), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("response_status", sa.Integer, nullable=False),
        sa.Column("response_body", postgresql.JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("idempotency_key", "endpoint", name="uq_idempotency_key_endpoint"),
    )
    op.create_index("idx_idempotency_key_tenant", "idempotency_key", ["tenant_id"])


def downgrade() -> None:
    op.drop_table("idempotency_key")
