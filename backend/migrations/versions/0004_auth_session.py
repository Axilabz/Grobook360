"""Proposed schema addition: auth_session table (server-side JWT revocation).

Revision ID: 0004_auth_session
Revises: 0003_tenant_address_fields
Create Date: 2026-09-05

Not present in Database Design & Data Dictionary v3.0. PROMPT-001's JWT access
token is stateless; without a server-side record, logout cannot invalidate a
token before its natural 60-minute expiry. See PROMPT-003-NOTES.md.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0004_auth_session"
down_revision = "0003_tenant_address_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "auth_session",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenant.id"), nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("token_jti", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("device_info", sa.String(500), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("row_version", sa.BigInteger, nullable=False, server_default="1"),
        sa.UniqueConstraint("token_jti", name="uq_auth_session_token_jti"),
    )
    op.create_index("idx_auth_session_tenant", "auth_session", ["tenant_id"])
    op.create_index("idx_auth_session_user", "auth_session", ["user_id"])
    op.create_index("idx_auth_session_expires_at", "auth_session", ["expires_at"])
    op.create_index("idx_auth_session_revoked_at", "auth_session", ["revoked_at"])


def downgrade() -> None:
    op.drop_table("auth_session")
