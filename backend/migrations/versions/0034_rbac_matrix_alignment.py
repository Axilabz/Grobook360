"""RBAC Alignment Phase: tighten Manager/Salesperson defaults to match the
new target Role/Module access matrix.

Revision ID: 0034_rbac_matrix_alignment
Revises: 0033_tenant_profile_fields
Create Date: 2026-10-23

Data-only migration (no schema change) — removes `role_permission` rows
for codes that `ROLE_DEFAULT_PERMISSIONS` (app/core/permissions.py) no
longer grants to MANAGER/SALESPERSON, mirroring the "backfill every
EXISTING tenant's roles" precedent of migrations 0021/0025/0026/0028/0031,
but as a removal rather than an addition:

- MANAGER loses `accounting.reverse_journal`, `accounting.manage_account_
  mappings` (Accounting & Ledgers: "Limited"), `gst.export` (GST &
  Compliance: "Limited"), and `roles.view`/`permissions.view" (Role &
  Permission Configuration: "No Access" for Manager, Owner-only).
- SALESPERSON loses `suppliers.view`/`suppliers.create`/`suppliers.update`
  (Supplier Management: "No Access" — a deliberate tightening from the
  prior FR-SUPP-05-derived "Limited" resolution, not an oversight).

No permission rows are deleted from the global `permission` catalogue —
only the per-tenant `role_permission` grants naming MANAGER/SALESPERSON
are removed. OWNER is untouched. See the RBAC Alignment plan for the
full matrix comparison and the explicitly-deferred items (true per-tenant
configurable permissions, Purchase Quotation, data scope).
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0034_rbac_matrix_alignment"
down_revision = "0033_tenant_profile_fields"
branch_labels = None
depends_on = None

_REMOVALS: dict[str, list[str]] = {
    "MANAGER": [
        "accounting.reverse_journal",
        "accounting.manage_account_mappings",
        "gst.export",
        "roles.view",
        "permissions.view",
    ],
    "SALESPERSON": [
        "suppliers.view",
        "suppliers.create",
        "suppliers.update",
    ],
}


def upgrade() -> None:
    connection = op.get_bind()

    for role_name, codes in _REMOVALS.items():
        connection.execute(
            sa.text(
                """
                DELETE FROM role_permission
                WHERE role_id IN (SELECT id FROM role WHERE name = :role_name)
                  AND permission_id IN (
                      SELECT id FROM permission WHERE code = ANY(:codes)
                  )
                """
            ),
            {"role_name": role_name, "codes": codes},
        )


def downgrade() -> None:
    connection = op.get_bind()

    for role_name, codes in _REMOVALS.items():
        permission_ids: dict[str, str] = {}
        for code in codes:
            row = connection.execute(
                sa.text("SELECT id FROM permission WHERE code = :code"), {"code": code}
            ).fetchone()
            if row is not None:
                permission_ids[code] = str(row[0])

        roles = connection.execute(
            sa.text("SELECT id, tenant_id FROM role WHERE name = :role_name"),
            {"role_name": role_name},
        ).fetchall()
        for role_id, tenant_id in roles:
            for code, permission_id in permission_ids.items():
                existing = connection.execute(
                    sa.text(
                        "SELECT 1 FROM role_permission WHERE role_id = :role_id AND permission_id = :permission_id"
                    ),
                    {"role_id": str(role_id), "permission_id": permission_id},
                ).fetchone()
                if existing is None:
                    connection.execute(
                        sa.text(
                            "INSERT INTO role_permission (id, tenant_id, role_id, permission_id, created_at, updated_at, row_version) "
                            "VALUES (gen_random_uuid(), :tenant_id, :role_id, :permission_id, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 1)"
                        ),
                        {"tenant_id": str(tenant_id), "role_id": role_id, "permission_id": permission_id},
                    )
