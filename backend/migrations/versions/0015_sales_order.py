"""Sales Order (PROMPT-013) + sales_order.* permission catalogue.

Revision ID: 0015_sales_order
Revises: 0014_sales_estimate
Create Date: 2026-09-19

The second concrete Sales document type, built directly on PROMPT-011's
foundation (GST calc, document numbering, sales validation) and mirroring
PROMPT-012's `sales_estimate`/`sales_estimate_line` shape almost exactly.

Data Dictionary v3.0 fully specifies `sales_order`/`sales_order_item`
(SALES domain) for: id, tenant_id, order_number, customer_id, order_date,
status, subtotal, discount_total, taxable_total, tax_total, grand_total
(header); line_no, product_id, description, quantity, uom_id, unit_price,
discount_amount, taxable_amount, gst_rate, cgst_amount, sgst_amount,
igst_amount, cess_amount, line_total (line). Renamed the line table to
`sales_order_line` only for naming consistency with `sales_estimate_line`
(the DD's own `sales_order_item` name is preserved as this migration's
documentation reference, not a schema divergence in shape).

Proposed schema additions (same "propose, document, implement" pattern as
every prior prompt):

- `sales_order.customer_gstin`, `.billing_address`, `.shipping_address`,
  `.place_of_supply_state_code` (all nullable): §8 lists these as minimum
  header fields; the DD has no snapshot columns at all. Captured from the
  Customer record AT ORDER CREATION TIME and frozen thereafter — same
  snapshot principle as `sales_estimate`. `shipping_address` has no
  separate Customer Master source field (Customer has one `address`
  column, no billing/shipping split) — it defaults to the same address as
  billing but is a distinct, independently-editable column so a caller
  *can* diverge them per order if the business needs that later.
- `sales_order.source_estimate_id` (nullable FK to `sales_estimate.id`,
  UNIQUE): §16 conversion-integrity requirement — one Estimate converts to
  at most ONE Sales Order, enforced by a real UNIQUE constraint, not only
  frontend button disabling (§16's own explicit instruction).
- `sales_order.cgst_total`, `.sgst_total`, `.igst_total` (NUMERIC(15,2),
  default 0): the DD's header only has generic `tax_total`; §8/§22 require
  the CGST/SGST/IGST split at document level. `tax_total` remains their
  sum, preserving the approved column's meaning.
- `sales_order.notes` (VARCHAR(1000), nullable): covers both "Notes" and
  "Terms and Conditions" (§8) as one free-text field, mirroring
  `sales_estimate.notes`'s identical resolution.
- `sales_order_line.hsn_code` (VARCHAR(8), nullable): §8/§22 require HSN
  per line; snapshotted from `product.hsn_code` at line-creation time.

No `round_off` column: §17/§45 open decision #17, no approved source
defines a round-off rule — not silently invented.

`sales_order_line.cess_amount` (from the DD) is created but always 0, the
same "reserved but inert column" treatment as `sales_estimate_line`.

Status model (§13, explicit open decision #1/#2): the prompt's own
recommended baseline is DRAFT -> CONFIRMED -> PARTIALLY_FULFILLED ->
FULFILLED -> CANCELLED, but §13 itself says "For the current prompt,
implement only the statuses required for Sales Order functionality" and
"Do not implement the full fulfillment engine in this prompt." This
migration's CHECK constraint therefore only allows DRAFT, CONFIRMED,
CANCELLED — PARTIALLY_FULFILLED/FULFILLED are deliberately NOT added yet.
Whichever future prompt builds Delivery Challan is expected to ALTER this
CHECK constraint to add them once it actually implements the fulfillment
calculation those statuses represent.

Numbering: reuses `document_number_sequence`/`DocumentNumberingService`
from PROMPT-011 with document_type="SALES_ORDER" (already defined in
`app.core.sales_constants`) — no separate numbering mechanism.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0015_sales_order"
down_revision = "0014_sales_estimate"
branch_labels = None
depends_on = None

_SALES_ORDER_PERMISSIONS = {
    "sales_order.view": "View tenant sales orders",
    "sales_order.create": "Create a sales order",
    "sales_order.edit": "Edit a draft sales order",
    "sales_order.confirm": "Confirm a sales order for fulfillment",
    "sales_order.cancel": "Cancel a sales order",
}

# No approved source defines exact per-role Sales Order permissions (§31/
# §45 Q4 — open decision, documented in PROMPT-013-NOTES.md). Resolved by
# mirroring Estimate's established shape, but with CONFIRM (not a convert
# action — see below) as Salesperson's excluded higher-commitment action —
# User Story 3 explicitly names "Manager/Owner" as the actor who reviews
# and confirms a Sales Order, a stronger signal than anything Estimate had.
# No "convert_from_estimate" permission code is created: conversion is
# exposed via the EXISTING POST /sales/estimates/{id}/convert-to-sales-order
# endpoint (PROMPT-012), already gated by sales_estimate.convert
# (Owner/Manager-only since that prompt) — see PROMPT-013-NOTES.md.
_ROLE_DEFAULT_PERMISSIONS = {
    "OWNER": [
        "sales_order.view", "sales_order.create", "sales_order.edit",
        "sales_order.confirm", "sales_order.cancel",
    ],
    "MANAGER": [
        "sales_order.view", "sales_order.create", "sales_order.edit",
        "sales_order.confirm", "sales_order.cancel",
    ],
    "SALESPERSON": [
        "sales_order.view", "sales_order.create", "sales_order.edit", "sales_order.cancel",
    ],
}


def upgrade() -> None:
    op.create_table(
        "sales_order",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("order_number", sa.String(50), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("customer.id"), nullable=False),
        sa.Column("order_date", sa.Date, nullable=False, server_default=sa.text("CURRENT_DATE")),
        sa.Column("status", sa.String(30), nullable=False, server_default="DRAFT"),
        # Proposed snapshot additions — captured at creation, frozen after.
        sa.Column("customer_gstin", sa.CHAR(15), nullable=True),
        sa.Column("billing_address", sa.String(500), nullable=True),
        sa.Column("shipping_address", sa.String(500), nullable=True),
        sa.Column("place_of_supply_state_code", sa.CHAR(2), nullable=True),
        # Proposed addition — conversion-integrity (§16): UNIQUE below.
        sa.Column("source_estimate_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sales_estimate.id"), nullable=True),
        sa.Column("subtotal", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("discount_total", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("taxable_total", sa.Numeric(15, 2), nullable=False, server_default="0"),
        # Proposed additions — see module docstring.
        sa.Column("cgst_total", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("sgst_total", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("igst_total", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("tax_total", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("grand_total", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("notes", sa.String(1000), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("row_version", sa.BigInteger, nullable=False, server_default="1"),
        sa.UniqueConstraint("tenant_id", "order_number", name="uq_sales_order_number"),
        # §16: one Estimate converts to at most one Sales Order, enforced
        # at the DB level (recommended by §16 itself), not only by the
        # frontend disabling a button.
        sa.UniqueConstraint("source_estimate_id", name="uq_sales_order_source_estimate"),
        sa.CheckConstraint(
            "status IN ('DRAFT','CONFIRMED','CANCELLED')",
            name="ck_sales_order_status",
        ),
        sa.CheckConstraint("subtotal >= 0", name="ck_sales_order_subtotal"),
        sa.CheckConstraint("discount_total >= 0", name="ck_sales_order_discount_total"),
        sa.CheckConstraint("grand_total >= 0", name="ck_sales_order_grand_total"),
    )
    op.create_index("idx_sales_order_tenant", "sales_order", ["tenant_id"])
    op.create_index("idx_sales_order_customer", "sales_order", ["tenant_id", "customer_id"])
    op.create_index("idx_sales_order_status", "sales_order", ["status"])

    op.create_table(
        "sales_order_line",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sales_order.id"), nullable=False),
        sa.Column("line_no", sa.Integer, nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("product.id"), nullable=True),
        sa.Column("description", sa.String(500), nullable=True),
        # Proposed addition — see module docstring.
        sa.Column("hsn_code", sa.String(8), nullable=True),
        sa.Column("quantity", sa.Numeric(18, 3), nullable=False),
        sa.Column("uom_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("unit_of_measure.id"), nullable=False),
        sa.Column("unit_price", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("discount_amount", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("taxable_amount", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("gst_rate", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column("cgst_amount", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("sgst_amount", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("igst_amount", sa.Numeric(15, 2), nullable=False, server_default="0"),
        # Reserved, always 0 — same treatment as sales_estimate_line.
        sa.Column("cess_amount", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("line_total", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("row_version", sa.BigInteger, nullable=False, server_default="1"),
        sa.UniqueConstraint("order_id", "line_no", name="uq_sales_order_line_no"),
        sa.CheckConstraint("quantity > 0", name="ck_sales_order_line_quantity"),
        sa.CheckConstraint("unit_price >= 0", name="ck_sales_order_line_unit_price"),
        sa.CheckConstraint("discount_amount >= 0", name="ck_sales_order_line_discount"),
        sa.CheckConstraint("gst_rate >= 0 AND gst_rate <= 100", name="ck_sales_order_line_gst_rate"),
    )
    op.create_index("idx_sales_order_line_tenant", "sales_order_line", ["tenant_id"])
    op.create_index("idx_sales_order_line_order", "sales_order_line", ["order_id"])

    for table in ("sales_order", "sales_order_line"):
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY tenant_isolation_{table} ON "{table}" '
            f"USING (tenant_id::text = current_setting('app.tenant_id', true))"
        )

    connection = op.get_bind()

    permission_ids: dict[str, str] = {}
    for code, description in _SALES_ORDER_PERMISSIONS.items():
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
    for table in ("sales_order_line", "sales_order"):
        op.execute(f'DROP POLICY IF EXISTS tenant_isolation_{table} ON "{table}"')
    op.drop_table("sales_order_line")
    op.drop_table("sales_order")
    # Permission/role_permission seed rows left in place, matching precedent.
