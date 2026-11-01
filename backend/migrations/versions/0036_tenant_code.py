"""Human-readable Tenant code — a display identifier alongside the UUID id.

Revision ID: 0036_tenant_code
Revises: 0035_inventory_accounting
Create Date: 2026-10-24

Proposed schema addition (the usual "propose, document, implement"
pattern — see CLAUDE.md S3): the baseline `tenant` table has no
human-readable code at all, unlike `customer`/`supplier` (both already
have a system-generated `*_code` column, migrations 0008/0030) and
`employee` (`employee_code`, migration 0029). This closes that one real
gap — the internal `id` stays a UUID everywhere (tenant isolation / FK
safety is unchanged), `tenant_code` is purely a user-facing label, format
"TEN-0001" (platform-wide, never resets — `tenant` has no FY concept of
its own, unlike a Sales/Purchase document).

Existing tenants are backfilled in `created_at` order so the codes read
as a stable, meaningful sequence rather than an arbitrary one. The column
starts nullable, is backfilled, then set NOT NULL + UNIQUE in the same
migration (no new tenant can be created mid-migration in this offline
step, so this ordering is safe).
"""

from alembic import op
import sqlalchemy as sa

revision = "0036_tenant_code"
down_revision = "0035_inventory_accounting"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tenant", sa.Column("tenant_code", sa.String(20), nullable=True))

    connection = op.get_bind()
    rows = connection.execute(sa.text("SELECT id FROM tenant ORDER BY created_at, id")).fetchall()
    for index, row in enumerate(rows, start=1):
        connection.execute(
            sa.text("UPDATE tenant SET tenant_code = :code WHERE id = :id"),
            {"code": f"TEN-{index:04d}", "id": row.id},
        )

    op.alter_column("tenant", "tenant_code", nullable=False)
    op.create_unique_constraint("uq_tenant_code", "tenant", ["tenant_code"])


def downgrade() -> None:
    op.drop_constraint("uq_tenant_code", "tenant", type_="unique")
    op.drop_column("tenant", "tenant_code")
