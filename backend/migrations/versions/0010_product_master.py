"""Product master, Unit of Measure, Product Unit Conversion (PROMPT-009) +
products.* permission catalogue.

Revision ID: 0010_product_master
Revises: 0009_supplier_master
Create Date: 2026-09-09

Unlike `customer`/`supplier` (PROMPT-007/008), Data Dictionary v3.0's
`product` table is already fully specified for this prompt's scope — no
proposed field additions were needed. FR-PROD-01 (Confirmed) lists exactly
the same fields the baseline already has: name, SKU, HSN, GST rate, Cost
Price, Selling Price, MRP, UOM. Notably absent from BOTH the baseline and
FR-PROD-01: category, subcategory, brand, product_type, description — none
exist here, by design (§11/§12 forbid inventing them merely because FMCG
products commonly have them).

`unit_of_measure` and `product_unit_conversion` are created here too —
Table Register lists both as MASTER-domain tables, and `product.base_uom_id`
is a mandatory (NOT NULL) FK to `unit_of_measure`, so Product Master cannot
function without them. No prior prompt created either table.

Reserved-but-inert columns, created exactly as the approved baseline
defines them but given NO write path anywhere in this module (see
app/services/products/product_service.py):
- `stock_qty_cache`: FR-STK-05/ASM-004 (Confirmed) — "Product stock quantity
  is a cache over Stock Ledger" and "must not be treated as source of
  truth." The future Stock Ledger module owns writes to it.
- `reorder_level`: tied to the same future Inventory/reorder-alert
  functionality (FR-DASH-05) — explicitly out of scope here.
- `batch_no`, `expiry_date`: the FRD's own Scope Matrix marks
  "Batch / Expiry" as **OPEN** — "Schema reserved; exact product behavior
  not confirmed." Creating the columns matches the approved schema;
  implementing any batch/expiry business rule would not, since the FRD
  itself hasn't confirmed one.

Proposed addition beyond the Data Dictionary: a UNIQUE constraint on
`product_unit_conversion (tenant_id, product_id, from_uom_id, to_uom_id)`
and a CHECK preventing `from_uom_id = to_uom_id`. Neither exists in the
Constraints & Indexes sheet, but both are straightforward data-integrity
rules the prompt itself asks for (S19: "prevent duplicate conversion
definitions", "prevent invalid circular/self-conversion") — the same class
of low-risk schema tightening PROMPT-006 did for `user_role`'s uniqueness.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0010_product_master"
down_revision = "0009_supplier_master"
branch_labels = None
depends_on = None

_PRODUCT_PERMISSIONS = {
    "products.view": "View tenant products",
    "products.create": "Create tenant products",
    "products.update": "Edit tenant product details",
    "products.activate": "Reactivate a deactivated product",
    "products.deactivate": "Deactivate a product",
}

# FR-PROD-04 (Confirmed): "Owner and Manager may create/edit/deactivate;
# Salesperson has read-only visibility." Table 7 confirms "View" (not
# "Limited") for Salesperson on Products — stricter than Customer/Supplier.
_ROLE_DEFAULT_PERMISSIONS = {
    "OWNER": ["products.view", "products.create", "products.update", "products.activate", "products.deactivate"],
    "MANAGER": ["products.view", "products.create", "products.update", "products.activate", "products.deactivate"],
    "SALESPERSON": ["products.view"],
}


def upgrade() -> None:
    op.create_table(
        "unit_of_measure",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("code", sa.String(20), nullable=False),
        sa.Column("name", sa.String(50), nullable=False),
        sa.Column("precision", sa.SmallInteger, nullable=False, server_default="2"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("row_version", sa.BigInteger, nullable=False, server_default="1"),
        sa.UniqueConstraint("tenant_id", "code", name="uq_unit_of_measure_code"),
        sa.CheckConstraint("precision BETWEEN 0 AND 6", name="ck_unit_of_measure_precision"),
    )
    op.create_index("idx_unit_of_measure_tenant", "unit_of_measure", ["tenant_id"])

    op.create_table(
        "product",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("sku", sa.String(50), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("hsn_code", sa.String(8), nullable=True),
        sa.Column("gst_rate", sa.Numeric(5, 2), nullable=True),
        sa.Column("base_uom_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("unit_of_measure.id"), nullable=False),
        sa.Column("cost_price", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("selling_price", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("mrp", sa.Numeric(15, 2), nullable=False, server_default="0"),
        # Reserved, no write path in this module — see module docstring.
        sa.Column("reorder_level", sa.Numeric(18, 3), nullable=False, server_default="0"),
        sa.Column("stock_qty_cache", sa.Numeric(18, 3), nullable=False, server_default="0"),
        sa.Column("batch_no", sa.String(50), nullable=True),
        sa.Column("expiry_date", sa.Date, nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="ACTIVE"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("row_version", sa.BigInteger, nullable=False, server_default="1"),
        sa.UniqueConstraint("tenant_id", "sku", name="uq_product_sku"),
        sa.CheckConstraint("status IN ('ACTIVE','INACTIVE')", name="ck_product_status"),
        sa.CheckConstraint("cost_price >= 0", name="ck_product_cost_price"),
        sa.CheckConstraint("selling_price >= 0", name="ck_product_selling_price"),
        sa.CheckConstraint("mrp >= 0", name="ck_product_mrp"),
        sa.CheckConstraint("gst_rate IS NULL OR (gst_rate >= 0 AND gst_rate <= 100)", name="ck_product_gst_rate"),
        sa.CheckConstraint("reorder_level >= 0", name="ck_product_reorder_level"),
        sa.CheckConstraint("stock_qty_cache >= 0", name="ck_product_stock_qty_cache"),
    )
    op.create_index("idx_product_tenant", "product", ["tenant_id"])
    op.create_index("idx_product_hsn", "product", ["hsn_code"])
    op.create_index("idx_product_name", "product", ["name"])

    op.create_table(
        "product_unit_conversion",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("product.id"), nullable=False),
        sa.Column("from_uom_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("unit_of_measure.id"), nullable=False),
        sa.Column("to_uom_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("unit_of_measure.id"), nullable=False),
        sa.Column("conversion_factor", sa.Numeric(18, 6), nullable=False, server_default="1"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("row_version", sa.BigInteger, nullable=False, server_default="1"),
        # Proposed additions beyond the Data Dictionary — see module docstring.
        sa.UniqueConstraint(
            "tenant_id", "product_id", "from_uom_id", "to_uom_id", name="uq_product_unit_conversion_pair"
        ),
        sa.CheckConstraint("from_uom_id <> to_uom_id", name="ck_product_unit_conversion_distinct"),
        sa.CheckConstraint("conversion_factor > 0", name="ck_product_unit_conversion_factor_positive"),
    )
    op.create_index("idx_product_unit_conversion_tenant", "product_unit_conversion", ["tenant_id"])
    op.create_index("idx_product_unit_conversion_product", "product_unit_conversion", ["product_id"])

    for table in ("unit_of_measure", "product", "product_unit_conversion"):
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY tenant_isolation_{table} ON "{table}" '
            f"USING (tenant_id::text = current_setting('app.tenant_id', true))"
        )

    connection = op.get_bind()

    permission_ids: dict[str, str] = {}
    for code, description in _PRODUCT_PERMISSIONS.items():
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
    for table in ("product_unit_conversion", "product", "unit_of_measure"):
        op.execute(f'DROP POLICY IF EXISTS tenant_isolation_{table} ON "{table}"')
    op.drop_table("product_unit_conversion")
    op.drop_table("product")
    op.drop_table("unit_of_measure")
    # Permission/role_permission seed rows are left in place on downgrade,
    # matching migrations 0007/0008/0009's precedent.
