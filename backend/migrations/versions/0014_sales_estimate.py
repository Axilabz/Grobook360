"""Sales Estimate (PROMPT-012) + sales_estimate.* permission catalogue.

Revision ID: 0014_sales_estimate
Revises: 0013_document_number_sequence
Create Date: 2026-09-12

The first concrete Sales document type, built on PROMPT-011's foundation
(GST calc service, document numbering service, sales validation service,
Inventory integration contract — none of which needed changes).

Data Dictionary v3.0 already fully specifies `estimate`/`estimate_line`
(SALES domain) — reused verbatim for: id, tenant_id, estimate_number,
customer_id, document_date, status, subtotal, discount_total,
taxable_total, tax_total, grand_total (header); line_no, product_id,
description, quantity, uom_id, unit_price, discount_amount,
taxable_amount, gst_rate, cgst_amount, sgst_amount, igst_amount,
cess_amount, line_total (line). Renamed to `sales_estimate`/
`sales_estimate_line` only to avoid a bare `estimate` table name colliding
with the generic English word across the growing schema — same table
shape and column set the DD defines, not a redesign.

Proposed schema additions (documented, same "propose, document, implement"
pattern as every prior prompt):

- `sales_estimate.valid_until_date` (DATE, nullable): the prompt's own
  §7/§13 require estimate validity/expiry — the DD has `document_date`
  only, no expiry column at all.
- `sales_estimate.customer_gstin`, `.billing_address`,
  `.place_of_supply_state_code` (all nullable): §7 lists these as minimum
  header fields, but no header snapshot columns exist in the DD. Captured
  from the Customer record AT ESTIMATE CREATION TIME and frozen
  thereafter — the same snapshot principle PROMPT-011 established for
  price/GST (§20/§21), applied to customer identity data too, since an
  Estimate is exactly the kind of document a later Customer Master edit
  must not silently rewrite. No separate shipping-address snapshot is
  added: Customer Master (PROMPT-007) itself has only one address field,
  no billing/shipping split — nothing to snapshot that doesn't already
  collapse into `billing_address`.
- `sales_estimate.cgst_total`, `.sgst_total`, `.igst_total` (all
  NUMERIC(15,2), default 0): the DD's header only has a single generic
  `tax_total`, but §7/§17 explicitly require the CGST/SGST/IGST split at
  document level (not just per line) for display. `tax_total` is kept and
  computed as their sum, preserving the approved column's meaning exactly.
- `sales_estimate.notes` (VARCHAR(1000), nullable): covers both "Notes"
  and "Terms and Conditions" from §7/§17 as one free-text field — the DD
  has neither, and adding two near-duplicate free-text columns for one
  need would be over-engineering the gap rather than filling it minimally.
- `sales_estimate.converted_at` (TIMESTAMPTZ, nullable): part of the
  conversion *architecture* this prompt is explicitly scoped to build
  (§21/§46) without the real Sales Order table existing yet (that's
  PROMPT-013). No `converted_sales_order_id` FK is added — there is
  nothing yet to point it at. `status='CONVERTED'` plus `converted_at`
  is the complete, honest signal this prompt can give; PROMPT-013 is
  expected to add its own `sales_order.source_estimate_id` (UNIQUE, per
  the Constraints & Indexes sheet's already-documented "one estimate
  converts at most once" rule) and reconcile the two records.
- `sales_estimate_line.hsn_code` (VARCHAR(8), nullable): §7/§17 require
  HSN per line; the DD's `estimate_line` has no HSN column. Snapshotted
  from `product.hsn_code` at line-creation time.

`sales_estimate_line.cess_amount` (from the DD) is created but always 0 —
no cess rate exists anywhere in Product Master to compute it from; this
is the same "reserved but inert column" treatment already used for
`product.reorder_level`/`batch_no` (PROMPT-009/010).

Status model: the DD only says `status` is a "Controlled lifecycle" with
default DRAFT, without enumerating values. Adopted this prompt's own
recommended baseline verbatim (§12), plus CANCELLED (needed for the
`.../cancel` endpoint §25 itself suggests): DRAFT, SENT, ACCEPTED,
REJECTED, EXPIRED, CANCELLED, CONVERTED.

Numbering: reuses `document_number_sequence`/`DocumentNumberingService`
from PROMPT-011 with document_type="ESTIMATE" — no separate numbering
mechanism was built (§11 explicitly forbids one).
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0014_sales_estimate"
down_revision = "0013_document_number_sequence"
branch_labels = None
depends_on = None

_ESTIMATE_PERMISSIONS = {
    "sales_estimate.view": "View tenant sales estimates",
    "sales_estimate.create": "Create a sales estimate",
    "sales_estimate.edit": "Edit a draft sales estimate",
    "sales_estimate.send": "Mark an estimate as sent to the customer",
    "sales_estimate.accept": "Record customer acceptance of an estimate",
    "sales_estimate.reject": "Record customer rejection of an estimate",
    "sales_estimate.cancel": "Cancel a draft/sent estimate",
    "sales_estimate.convert": "Convert an eligible estimate to a Sales Order",
}

# No approved source defines exact per-role Estimate permissions (§29/§44
# Q16 — open decision). Table 58/Table 7 (FRD) confirm Owner/Manager/
# Salesperson all get Estimate access "per entitlement" without granular
# detail. Resolved by mirroring the established Customer/Supplier shape
# (FR-CUST-07/FR-SUPP-05): Salesperson gets the full day-to-day lifecycle
# EXCEPT the higher-commitment "convert to Sales Order" action, which is
# Owner/Manager only — the same create/edit-but-not-the-big-action split
# already used elsewhere, not a new pattern invented for this prompt.
_ROLE_DEFAULT_PERMISSIONS = {
    "OWNER": [
        "sales_estimate.view", "sales_estimate.create", "sales_estimate.edit", "sales_estimate.send",
        "sales_estimate.accept", "sales_estimate.reject", "sales_estimate.cancel", "sales_estimate.convert",
    ],
    "MANAGER": [
        "sales_estimate.view", "sales_estimate.create", "sales_estimate.edit", "sales_estimate.send",
        "sales_estimate.accept", "sales_estimate.reject", "sales_estimate.cancel", "sales_estimate.convert",
    ],
    "SALESPERSON": [
        "sales_estimate.view", "sales_estimate.create", "sales_estimate.edit", "sales_estimate.send",
        "sales_estimate.accept", "sales_estimate.reject", "sales_estimate.cancel",
    ],
}


def upgrade() -> None:
    op.create_table(
        "sales_estimate",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("estimate_number", sa.String(50), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("customer.id"), nullable=False),
        sa.Column("document_date", sa.Date, nullable=False, server_default=sa.text("CURRENT_DATE")),
        # Proposed addition — see module docstring.
        sa.Column("valid_until_date", sa.Date, nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="DRAFT"),
        # Proposed snapshot additions — captured at creation, frozen after.
        sa.Column("customer_gstin", sa.CHAR(15), nullable=True),
        sa.Column("billing_address", sa.String(500), nullable=True),
        sa.Column("place_of_supply_state_code", sa.CHAR(2), nullable=True),
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
        sa.Column("converted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("row_version", sa.BigInteger, nullable=False, server_default="1"),
        sa.UniqueConstraint("tenant_id", "estimate_number", name="uq_sales_estimate_number"),
        sa.CheckConstraint(
            "status IN ('DRAFT','SENT','ACCEPTED','REJECTED','EXPIRED','CANCELLED','CONVERTED')",
            name="ck_sales_estimate_status",
        ),
        sa.CheckConstraint(
            "valid_until_date IS NULL OR valid_until_date >= document_date", name="ck_sales_estimate_validity"
        ),
        sa.CheckConstraint("subtotal >= 0", name="ck_sales_estimate_subtotal"),
        sa.CheckConstraint("discount_total >= 0", name="ck_sales_estimate_discount_total"),
        sa.CheckConstraint("grand_total >= 0", name="ck_sales_estimate_grand_total"),
    )
    op.create_index("idx_sales_estimate_tenant", "sales_estimate", ["tenant_id"])
    op.create_index("idx_sales_estimate_customer", "sales_estimate", ["tenant_id", "customer_id"])
    op.create_index("idx_sales_estimate_status", "sales_estimate", ["status"])

    op.create_table(
        "sales_estimate_line",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("estimate_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sales_estimate.id"), nullable=False),
        sa.Column("line_no", sa.Integer, nullable=False),
        # Nullable per the DD (a non-product line is schema-legal), but
        # this module always requires a product at the application layer —
        # no approved requirement asks for a free-text-only line, so none
        # is implemented.
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
        # Reserved, always 0 — no cess rate exists anywhere in Product
        # Master to compute it from (see module docstring).
        sa.Column("cess_amount", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("line_total", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("row_version", sa.BigInteger, nullable=False, server_default="1"),
        sa.UniqueConstraint("estimate_id", "line_no", name="uq_sales_estimate_line_no"),
        sa.CheckConstraint("quantity > 0", name="ck_sales_estimate_line_quantity"),
        sa.CheckConstraint("unit_price >= 0", name="ck_sales_estimate_line_unit_price"),
        sa.CheckConstraint("discount_amount >= 0", name="ck_sales_estimate_line_discount"),
        sa.CheckConstraint("gst_rate >= 0 AND gst_rate <= 100", name="ck_sales_estimate_line_gst_rate"),
    )
    op.create_index("idx_sales_estimate_line_tenant", "sales_estimate_line", ["tenant_id"])
    op.create_index("idx_sales_estimate_line_estimate", "sales_estimate_line", ["estimate_id"])

    for table in ("sales_estimate", "sales_estimate_line"):
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY tenant_isolation_{table} ON "{table}" '
            f"USING (tenant_id::text = current_setting('app.tenant_id', true))"
        )

    connection = op.get_bind()

    permission_ids: dict[str, str] = {}
    for code, description in _ESTIMATE_PERMISSIONS.items():
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
    for table in ("sales_estimate_line", "sales_estimate"):
        op.execute(f'DROP POLICY IF EXISTS tenant_isolation_{table} ON "{table}"')
    op.drop_table("sales_estimate_line")
    op.drop_table("sales_estimate")
    # Permission/role_permission seed rows left in place, matching precedent.
