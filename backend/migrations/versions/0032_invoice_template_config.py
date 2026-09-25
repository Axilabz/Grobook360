"""Invoice Template Configuration (Configuration Center prompt) +
configuration.* permission catalogue.

Revision ID: 0032_invoice_template_config
Revises: 0031_export_permissions
Create Date: 2026-09-25

Scope note (this migration deliberately does NOT implement the full
44-section source prompt): only ONE new table is added,
`invoice_template_configuration` — a tenant-scoped, lazily-provisioned
(one row per tenant, same pattern as `integration_configuration`,
migration 0020) appearance/display-settings row for the Sales Invoice
print/preview view. There is no separate system-template catalog table
— "template" is a small, fixed, code-level set of layout ids
(CLASSIC/MODERN/COMPACT) rendered by the frontend, not an
extensible/DB-driven template library, since no template-authoring
workflow was requested or exists. There is no template-versioning or
document-snapshot table either — an already-issued invoice's PDF/print
view re-renders using the tenant's CURRENT configuration, not a
snapshot taken at issue time. This is a real, documented gap against
the source prompt's own §18 "CRITICAL REQUIREMENT" (historical invoice
immutability) — flagged here and in the session's own summary to the
user, not silently resolved.

The business logo is stored as a data-URI directly on this row
(`logo_data_uri`, nullable Text) rather than a filesystem/object-storage
pipeline with signed URLs — no file-upload/static-serving
infrastructure exists anywhere else in this codebase to extend, and
building one is out of scope for this pass. Size is capped
server-side (see app/services/configuration/configuration_service.py)
to keep this reasonable for a DB TEXT column.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0032_invoice_template_config"
down_revision = "0031_export_permissions"
branch_labels = None
depends_on = None

_CONFIGURATION_PERMISSIONS = {
    "configuration.view": "View tenant configuration (invoice template/appearance settings)",
    "configuration.manage": "Change tenant configuration (invoice template/appearance settings, logo)",
}

_ROLE_DEFAULT_PERMISSIONS = {
    "OWNER": ["configuration.view", "configuration.manage"],
    "MANAGER": ["configuration.view"],
    # SALESPERSON gets neither — tenant-level configuration has no
    # plausible Salesperson use case, mirrors Purchase/Accounting/GST's
    # own identical "no ambiguity" precedent.
}


def upgrade() -> None:
    op.create_table(
        "invoice_template_configuration",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("template_id", sa.String(20), nullable=False, server_default="CLASSIC"),
        sa.Column("primary_color", sa.String(7), nullable=False, server_default="#2563EB"),
        sa.Column("secondary_color", sa.String(7), nullable=False, server_default="#0F172A"),
        sa.Column("accent_color", sa.String(7), nullable=False, server_default="#10B981"),
        sa.Column("text_color", sa.String(7), nullable=False, server_default="#111827"),
        sa.Column("table_header_color", sa.String(7), nullable=False, server_default="#E5E7EB"),
        sa.Column("logo_data_uri", sa.Text, nullable=True),
        sa.Column("show_logo", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("show_business_address", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("show_gstin", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("show_customer_gstin", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("show_hsn", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("show_discount", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("show_tax_breakup", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("show_bank_details", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("show_terms", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("show_amount_in_words", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("show_round_off", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("terms_text", sa.Text, nullable=True),
        sa.Column("bank_name", sa.String(200), nullable=True),
        sa.Column("bank_account_name", sa.String(200), nullable=True),
        sa.Column("bank_account_number", sa.String(50), nullable=True),
        sa.Column("bank_ifsc", sa.String(20), nullable=True),
        sa.Column("bank_upi_id", sa.String(100), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("row_version", sa.BigInteger, nullable=False, server_default="1"),
        sa.UniqueConstraint("tenant_id", name="uq_invoice_template_configuration_tenant"),
        sa.CheckConstraint("template_id IN ('CLASSIC','MODERN','COMPACT')", name="ck_invoice_template_configuration_template_id"),
        sa.CheckConstraint(
            "primary_color ~ '^#[0-9A-Fa-f]{6}$' AND secondary_color ~ '^#[0-9A-Fa-f]{6}$' "
            "AND accent_color ~ '^#[0-9A-Fa-f]{6}$' AND text_color ~ '^#[0-9A-Fa-f]{6}$' "
            "AND table_header_color ~ '^#[0-9A-Fa-f]{6}$'",
            name="ck_invoice_template_configuration_hex_colors",
        ),
    )
    op.create_index("idx_invoice_template_configuration_tenant", "invoice_template_configuration", ["tenant_id"])

    op.execute('ALTER TABLE "invoice_template_configuration" ENABLE ROW LEVEL SECURITY')
    op.execute(
        "CREATE POLICY tenant_isolation_invoice_template_configuration ON \"invoice_template_configuration\" "
        "USING (tenant_id::text = current_setting('app.tenant_id', true))"
    )

    connection = op.get_bind()

    permission_ids: dict[str, str] = {}
    for code, description in _CONFIGURATION_PERMISSIONS.items():
        row = connection.execute(sa.text("SELECT id FROM permission WHERE code = :code"), {"code": code}).fetchone()
        if row is None:
            new_id = connection.execute(
                sa.text(
                    "INSERT INTO permission (id, code, description, created_at, updated_at, row_version) "
                    "VALUES (gen_random_uuid(), :code, :description, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 1) "
                    "RETURNING id"
                ),
                {"code": code, "description": description},
            ).fetchone()
            permission_ids[code] = str(new_id[0])
        else:
            permission_ids[code] = str(row[0])

    roles = connection.execute(sa.text("SELECT id, tenant_id, name FROM role")).fetchall()
    for role_id, tenant_id, role_name in roles:
        for code in _ROLE_DEFAULT_PERMISSIONS.get(role_name, []):
            permission_id = permission_ids[code]
            existing = connection.execute(
                sa.text("SELECT 1 FROM role_permission WHERE role_id = :role_id AND permission_id = :permission_id"),
                {"role_id": str(role_id), "permission_id": permission_id},
            ).fetchone()
            if existing is None:
                connection.execute(
                    sa.text(
                        "INSERT INTO role_permission (id, tenant_id, role_id, permission_id, created_at, updated_at, row_version) "
                        "VALUES (gen_random_uuid(), :tenant_id, :role_id, :permission_id, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 1)"
                    ),
                    {"tenant_id": str(tenant_id), "role_id": str(role_id), "permission_id": permission_id},
                )


def downgrade() -> None:
    op.execute('DROP POLICY IF EXISTS tenant_isolation_invoice_template_configuration ON "invoice_template_configuration"')
    op.drop_table("invoice_template_configuration")
    # Permission/role_permission seed rows left in place, matching precedent.
