"""Proposed schema addition: password_reset_token table.

Revision ID: 0005_password_reset_token
Revises: 0004_auth_session
Create Date: 2026-09-06

Not present in Database Design & Data Dictionary v3.0. See PROMPT-004-NOTES.md.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0005_password_reset_token"
down_revision = "0004_auth_session"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "password_reset_token",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenant.id"), nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("request_ip", sa.String(45), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("row_version", sa.BigInteger, nullable=False, server_default="1"),
        sa.UniqueConstraint("token_hash", name="uq_password_reset_token_hash"),
    )
    op.create_index("idx_password_reset_token_tenant", "password_reset_token", ["tenant_id"])
    op.create_index("idx_password_reset_token_user", "password_reset_token", ["user_id"])
    op.create_index("idx_password_reset_token_expires_at", "password_reset_token", ["expires_at"])
    op.create_index("idx_password_reset_token_consumed_at", "password_reset_token", ["consumed_at"])
    op.create_index("idx_password_reset_token_revoked_at", "password_reset_token", ["revoked_at"])


def downgrade() -> None:
    op.drop_table("password_reset_token")
