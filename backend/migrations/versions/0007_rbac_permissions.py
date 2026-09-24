"""RBAC: seed permission catalogue, backfill role_permission for pre-existing
roles, and tighten user_role to one role per user (PROMPT-006).

Revision ID: 0007_rbac_permissions
Revises: 0006_user_name
Create Date: 2026-09-07

Data migration: any Role row created before this migration (by PROMPT-002
sign-up or PROMPT-005 user creation) had zero role_permission rows, since no
default set existed yet. This backfills them using the exact same
ROLE_DEFAULT_PERMISSIONS mapping app.core.permissions defines, so existing
tenants get correct effective permissions without needing to recreate
anything. See PROMPT-006-NOTES.md.

Schema tightening: user_role's unique constraint was (tenant_id, user_id,
role_id), which never actually prevented a user from holding two roles
simultaneously. PROMPT-006 S36 formalizes the "one user -> one primary role"
recommendation PROMPT-002/005 already behaved as if true; this migration
enforces it structurally. No existing data violates it in practice, since
app code has only ever created one user_role row per user.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0007_rbac_permissions"
down_revision = "0006_user_name"
branch_labels = None
depends_on = None

_ROLE_DEFAULT_PERMISSIONS = {
    "OWNER": ["users.view", "users.create", "users.update", "users.activate", "users.deactivate", "roles.view", "permissions.view"],
    "MANAGER": ["users.view", "roles.view", "permissions.view"],
    "SALESPERSON": [],
}

_PERMISSION_DESCRIPTIONS = {
    "users.view": "View tenant users",
    "users.create": "Create tenant users",
    "users.update": "Edit tenant user details and role",
    "users.activate": "Reactivate a deactivated user",
    "users.deactivate": "Deactivate a user",
    "roles.view": "View the tenant's roles and their permissions",
    "permissions.view": "View the global permission catalogue",
}


def upgrade() -> None:
    connection = op.get_bind()

    # 1. Seed the global permission catalogue (idempotent).
    permission_ids: dict[str, str] = {}
    for code, description in _PERMISSION_DESCRIPTIONS.items():
        row = connection.execute(
            sa.text('SELECT id FROM permission WHERE code = :code'), {"code": code}
        ).fetchone()
        if row is None:
            new_id = connection.execute(
                sa.text(
                    'INSERT INTO permission (id, code, description, created_at, updated_at, row_version) '
                    "VALUES (gen_random_uuid(), :code, :description, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 1) "
                    "RETURNING id"
                ),
                {"code": code, "description": description},
            ).fetchone()
            permission_ids[code] = str(new_id[0])
        else:
            permission_ids[code] = str(row[0])

    # 2. Backfill role_permission for every existing role, per its name.
    roles = connection.execute(sa.text('SELECT id, tenant_id, name FROM role')).fetchall()
    for role_id, tenant_id, role_name in roles:
        for code in _ROLE_DEFAULT_PERMISSIONS.get(role_name, []):
            permission_id = permission_ids[code]
            existing = connection.execute(
                sa.text(
                    'SELECT 1 FROM role_permission WHERE role_id = :role_id AND permission_id = :permission_id'
                ),
                {"role_id": str(role_id), "permission_id": permission_id},
            ).fetchone()
            if existing is None:
                connection.execute(
                    sa.text(
                        'INSERT INTO role_permission (id, tenant_id, role_id, permission_id, created_at, updated_at, row_version) '
                        "VALUES (gen_random_uuid(), :tenant_id, :role_id, :permission_id, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 1)"
                    ),
                    {"tenant_id": str(tenant_id), "role_id": str(role_id), "permission_id": permission_id},
                )

    # 3. Tighten user_role: one role per user.
    op.drop_constraint("uq_user_role_assignment", "user_role", type_="unique")
    op.create_unique_constraint("uq_user_role_one_role_per_user", "user_role", ["tenant_id", "user_id"])


def downgrade() -> None:
    op.drop_constraint("uq_user_role_one_role_per_user", "user_role", type_="unique")
    op.create_unique_constraint("uq_user_role_assignment", "user_role", ["tenant_id", "user_id", "role_id"])
    # Permission/role_permission seed data is left in place on downgrade —
    # removing it could delete permissions a later migration also depends on.
