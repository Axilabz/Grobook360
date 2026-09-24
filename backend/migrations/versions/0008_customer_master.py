"""Customer master (PROMPT-007) + customers.* permission catalogue.

Revision ID: 0008_customer_master
Revises: 0007_rbac_permissions
Create Date: 2026-09-08

Schema note: Data Dictionary v3.0's `customer` table only defines id,
tenant_id, customer_code, name, gstin, state_code, address, phone,
credit_limit, payment_terms_days, balance, status + audit/row_version
columns. FR-CUST-01 (legacy FRD, "Confirmed") additionally requires owner
name, optional email, region/beat, city, pin code and GPS location on the
same screen. Data Dictionary v3.0 simply predates that legacy requirement
being reconciled into it — the same class of gap PROMPT-005 hit for
user.name (migration 0006). Following the same established pattern, this
migration ADDS those FR-CUST-01 fields on top of the approved baseline
columns rather than dropping them or silently inventing something
different. See PROMPT-007-NOTES.md "Schema Assessment" for the full
per-field reconciliation table.

Deliberately NOT added: a customer_type/B2B-B2C column (FR-CUST-03 already
defines GST-registration status as *derived* from whether gstin is blank —
no separate classification column is specified anywhere), a
country column (BR-001/ASM-002: M1 is a single-tenant-business, one-GSTIN,
India-only model), and separate billing/shipping addresses (Data Dictionary
v3.0 has exactly one address; the prompt itself forbids inventing a
multi-address model the approved baseline doesn't support).

`balance` is created exactly as the approved cache column it is (default 0)
but this migration grants it no write path of its own — see
app/services/customers/customer_service.py, which never accepts it as
create/update input. Mutating it is Payments/Accounting's job, not
Customer Management's (PROMPT-007 S29).
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0008_customer_master"
down_revision = "0007_rbac_permissions"
branch_labels = None
depends_on = None

_CUSTOMER_PERMISSIONS = {
    "customers.view": "View tenant customers",
    "customers.create": "Create tenant customers",
    "customers.update": "Edit tenant customer details",
    "customers.activate": "Reactivate a deactivated customer",
    "customers.deactivate": "Deactivate a customer",
}

# FR-CUST-07 (Confirmed): Owner, Manager and Salesperson may create/edit;
# only Owner/Manager may deactivate. Activate is granted symmetrically with
# deactivate — FR-CUST-07 doesn't name it separately, but leaving reactivation
# authority off both roles that can deactivate would make deactivation
# effectively permanent, which nothing in the approved source intends. Table 7
# (Role x Module matrix) independently confirms Salesperson has only "Limited"
# access to Customers, consistent with create/edit-but-not-deactivate.
_ROLE_DEFAULT_PERMISSIONS = {
    "OWNER": ["customers.view", "customers.create", "customers.update", "customers.activate", "customers.deactivate"],
    "MANAGER": ["customers.view", "customers.create", "customers.update", "customers.activate", "customers.deactivate"],
    "SALESPERSON": ["customers.view", "customers.create", "customers.update"],
}


def upgrade() -> None:
    op.create_table(
        "customer",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("customer_code", sa.String(50), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        # Proposed addition (FR-CUST-01): business contact person.
        sa.Column("owner_name", sa.String(200), nullable=False),
        sa.Column("phone", sa.String(20), nullable=True),
        # Proposed addition (FR-CUST-01: "optional email").
        sa.Column("email", sa.String(254), nullable=True),
        sa.Column("gstin", sa.CHAR(15), nullable=True),
        sa.Column("state_code", sa.CHAR(2), nullable=True),
        sa.Column("address", sa.String(500), nullable=True),
        # Proposed additions (FR-CUST-01: city, pin code; FR-CUST-01 "region/beat").
        sa.Column("city", sa.String(100), nullable=True),
        sa.Column("pincode", sa.String(6), nullable=True),
        sa.Column("region", sa.String(100), nullable=True),
        # Proposed addition (FR-CUST-02: "Use Current Location" browser geolocation).
        sa.Column("gps_location", sa.String(500), nullable=True),
        sa.Column("credit_limit", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("payment_terms_days", sa.Integer, nullable=False, server_default="0"),
        # Balance cache — read-only from this module; see module docstring.
        sa.Column("balance", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="ACTIVE"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("row_version", sa.BigInteger, nullable=False, server_default="1"),
        sa.UniqueConstraint("tenant_id", "customer_code", name="uq_customer_code"),
        sa.CheckConstraint("status IN ('ACTIVE','INACTIVE')", name="ck_customer_status"),
        sa.CheckConstraint("credit_limit >= 0", name="ck_customer_credit_limit"),
        sa.CheckConstraint("payment_terms_days >= 0", name="ck_customer_payment_terms_days"),
    )
    op.create_index("idx_customer_tenant", "customer", ["tenant_id"])
    op.create_index("idx_customer_gstin", "customer", ["gstin"])
    op.create_index("idx_customer_phone", "customer", ["phone"])

    # RLS scaffolding — enabled but not forced, matching migration 0001's
    # documented pattern (ERD-DEC-01 stays open, not silently decided here).
    op.execute('ALTER TABLE "customer" ENABLE ROW LEVEL SECURITY')
    op.execute(
        'CREATE POLICY tenant_isolation_customer ON "customer" '
        "USING (tenant_id::text = current_setting('app.tenant_id', true))"
    )

    connection = op.get_bind()

    permission_ids: dict[str, str] = {}
    for code, description in _CUSTOMER_PERMISSIONS.items():
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
    op.execute('DROP POLICY IF EXISTS tenant_isolation_customer ON "customer"')
    op.drop_table("customer")
    # Permission/role_permission seed rows are left in place on downgrade,
    # matching migration 0007's precedent.
