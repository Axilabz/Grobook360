"""Supplier master (PROMPT-008) + suppliers.* permission catalogue.

Revision ID: 0009_supplier_master
Revises: 0008_customer_master
Create Date: 2026-09-08

Schema note: Data Dictionary v3.0's `supplier` table defines id, tenant_id,
supplier_code, name, gstin, state_code, address, phone, credit_terms_days,
balance, status + audit/row_version columns. FR-SUPP-01 (Confirmed)
additionally requires an owner/contact person, optional email, city and pin
code on the same screen — the same class of documented gap PROMPT-007 hit
for `customer` (and PROMPT-005 for `user.name`). This migration adds those
FR-SUPP-01 fields on top of the approved baseline, following the identical
"propose, document, implement" pattern.

Deliberately NOT added — because FR-SUPP-02 explicitly forbids them for
Supplier ("Do not capture Customer-only Region/Beat, GPS or Credit Limit
fields for Supplier"): a region/beat column, a gps_location column, and a
credit_limit column. This is a direct textual instruction, not an inference
— Supplier's proposed additions are deliberately a strict subset of
Customer's (see migration 0008).

Also deliberately NOT added: any bank-account fields. Data Dictionary
v3.0's own Open Decisions sheet (ERD-DEC-04) says a BankAccount master "is
required by bank transaction/reconciliation" but is "not fully specified in
current ERD" — i.e. explicitly unresolved upstream, not something this
module has grounds to invent. See PROMPT-008-NOTES.md.

`balance` is created exactly as the approved cache column it is (default 0)
but is never a create/update input of this module — see
app/services/suppliers/supplier_service.py. Mutating it is
Payments/Accounting's job (FR-PINV-02 references it explicitly as a
Purchase Invoice side effect).
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0009_supplier_master"
down_revision = "0008_customer_master"
branch_labels = None
depends_on = None

_SUPPLIER_PERMISSIONS = {
    "suppliers.view": "View tenant suppliers",
    "suppliers.create": "Create tenant suppliers",
    "suppliers.update": "Edit tenant supplier details",
    "suppliers.activate": "Reactivate a deactivated supplier",
    "suppliers.deactivate": "Deactivate a supplier",
}

# FR-SUPP-05 (Confirmed): Owner, Manager and Salesperson may create/edit;
# deactivation is Owner/Manager controlled. Activate is granted
# symmetrically with deactivate for the same reason documented in migration
# 0008 for Customers — leaving reactivation off both roles that can
# deactivate would make deactivation effectively permanent.
_ROLE_DEFAULT_PERMISSIONS = {
    "OWNER": ["suppliers.view", "suppliers.create", "suppliers.update", "suppliers.activate", "suppliers.deactivate"],
    "MANAGER": ["suppliers.view", "suppliers.create", "suppliers.update", "suppliers.activate", "suppliers.deactivate"],
    "SALESPERSON": ["suppliers.view", "suppliers.create", "suppliers.update"],
}


def upgrade() -> None:
    op.create_table(
        "supplier",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("supplier_code", sa.String(50), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        # Proposed addition (FR-SUPP-01): "owner/contact" person.
        sa.Column("contact_person", sa.String(200), nullable=False),
        sa.Column("phone", sa.String(20), nullable=True),
        # Proposed addition (FR-SUPP-01: "optional email").
        sa.Column("email", sa.String(254), nullable=True),
        sa.Column("gstin", sa.CHAR(15), nullable=True),
        sa.Column("state_code", sa.CHAR(2), nullable=True),
        sa.Column("address", sa.String(500), nullable=True),
        # Proposed additions (FR-SUPP-01: city, pin code).
        sa.Column("city", sa.String(100), nullable=True),
        sa.Column("pincode", sa.String(6), nullable=True),
        sa.Column("credit_terms_days", sa.Integer, nullable=False, server_default="0"),
        # Balance cache — read-only from this module; see module docstring.
        sa.Column("balance", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="ACTIVE"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("row_version", sa.BigInteger, nullable=False, server_default="1"),
        sa.UniqueConstraint("tenant_id", "supplier_code", name="uq_supplier_code"),
        sa.CheckConstraint("status IN ('ACTIVE','INACTIVE')", name="ck_supplier_status"),
        sa.CheckConstraint("credit_terms_days >= 0", name="ck_supplier_credit_terms_days"),
    )
    op.create_index("idx_supplier_tenant", "supplier", ["tenant_id"])
    op.create_index("idx_supplier_gstin", "supplier", ["gstin"])
    op.create_index("idx_supplier_phone", "supplier", ["phone"])

    # RLS scaffolding — enabled but not forced, matching migrations 0001/0008.
    op.execute('ALTER TABLE "supplier" ENABLE ROW LEVEL SECURITY')
    op.execute(
        'CREATE POLICY tenant_isolation_supplier ON "supplier" '
        "USING (tenant_id::text = current_setting('app.tenant_id', true))"
    )

    connection = op.get_bind()

    permission_ids: dict[str, str] = {}
    for code, description in _SUPPLIER_PERMISSIONS.items():
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
    op.execute('DROP POLICY IF EXISTS tenant_isolation_supplier ON "supplier"')
    op.drop_table("supplier")
    # Permission/role_permission seed rows are left in place on downgrade,
    # matching migrations 0007/0008's precedent.
