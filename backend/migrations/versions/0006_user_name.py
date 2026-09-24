"""Proposed schema addition: user.name.

Revision ID: 0006_user_name
Revises: 0005_password_reset_token
Create Date: 2026-09-06

Data Dictionary v3.0's user table has no name column, and PROMPT-002's
sign-up form never captured one (flagged in PROMPT-003-NOTES.md). PROMPT-005
explicitly needs it for the user list/detail/create screens. Nullable because
existing sign-up-created Owner users have none. See PROMPT-005-NOTES.md.
"""

from alembic import op
import sqlalchemy as sa

revision = "0006_user_name"
down_revision = "0005_password_reset_token"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user", sa.Column("name", sa.String(200), nullable=True))


def downgrade() -> None:
    op.drop_column("user", "name")
