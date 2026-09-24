"""Delivery Challan (PROMPT-014) + delivery_challan.* permission catalogue
+ Sales Order fulfillment tracking.

Revision ID: 0016_delivery_challan
Revises: 0015_sales_order
Create Date: 2026-09-26

The third concrete Sales document type — and the FIRST one that actually
moves stock (§3: "Delivery Challan = STOCK OUT", unlike Estimate/Sales
Order which never touch inventory). Built on PROMPT-011's foundation
(document numbering only — no GST calc service is used here, since §9's
own header/line field list has no pricing/GST columns at all) and
PROMPT-013's Sales Order.

Data Dictionary v3.0 specifies `delivery_challan`/`delivery_challan_item`
(SALES domain) for the core identity/traceability columns. Proposed
schema additions (same "propose, document, implement" pattern as every
prior prompt):

- `delivery_challan.shipping_address`, `.place_of_supply_state_code`
  (nullable): §9 lists these as minimum header fields; snapshotted from
  the source Sales Order at creation time, independently editable
  thereafter (open decision #17, resolved as yes).
- `delivery_challan.total_quantity` (NUMERIC(18,3), default 0): §9 lists
  it as a minimum header field — sum of line `current_delivery_quantity`,
  informational/display-only, always recomputed server-side.
- `delivery_challan_line.previously_delivered_quantity`,
  `.remaining_quantity` (both NUMERIC(18,3)): §9 explicitly lists these as
  minimum line fields for traceability; snapshotted from the live
  `sales_order_line.delivered_quantity` at CONFIRM time (the moment they
  become historically true — see `delivery_challan_service.py`).

No pricing/GST/HSN-amount columns anywhere on either table — genuinely
absent from §9's field list, unlike Estimate/Sales Order which do carry
them. `hsn_code` IS kept (line-level, per §9) purely for display/print
traceability, snapshotted from Product Master.

Sales Order changes (this same migration, since Delivery Challan cannot
function without them):

- `sales_order_line.delivered_quantity` (NUMERIC(18,3), default 0): new
  column, incremented only by `SalesOrderService.apply_delivery` as
  Delivery Challans are confirmed. `CHECK (delivered_quantity >= 0 AND
  delivered_quantity <= quantity)` is the DB-level backstop for "delivered
  quantity must never exceed ordered quantity" (§5/§23) — a coarse single-
  row check; the real remaining-vs-requested-delivery validation still
  happens in application code under a row lock (see §19/§20 concurrency
  notes in `delivery_challan_service.py`), since that comparison spans
  the (mutable) current DC's requested quantity too, not just this column.
- `sales_order.ck_sales_order_status` widened to also allow
  `PARTIALLY_FULFILLED` and `FULFILLED` — exactly the two statuses
  PROMPT-013's own migration (0015) deliberately withheld pending this
  prompt. Set only by `SalesOrderService.apply_delivery`, never by any
  Sales Order endpoint directly.

Status model (§11, explicit open decision #2 in the prompt's own list):
adopted the prompt's own recommended baseline verbatim — DRAFT, CONFIRMED,
CANCELLED. No PARTIALLY_DELIVERED-style Delivery-Challan-side status:
§11 itself says "Additional fulfillment information should be represented
through the source Sales Order status" — partial/full fulfillment is
purely a Sales Order-side concept, one Delivery Challan is just one
dispatch event and is always either not-yet-dispatched (DRAFT),
dispatched (CONFIRMED), or voided (CANCELLED).

Cancellation-after-confirmation (§11/§45 open decision #3/#4): NOT
implemented. `ck_delivery_challan_status` still allows CANCELLED (for a
DRAFT to be cancelled), but the application layer (not this migration)
restricts the CONFIRMED -> CANCELLED transition until a compensating
stock-reversal design is approved — see PROMPT-014-NOTES.md.

Numbering: reuses `document_number_sequence`/`DocumentNumberingService`
from PROMPT-011 with document_type="DELIVERY_CHALLAN" (already defined in
`app.core.sales_constants`) — no separate numbering mechanism.

Stock Ledger: no schema change needed. `stock_ledger_entry`'s existing
`uq_stock_ledger_entry_source (tenant_id, source_type, source_id)`
constraint (migration 0011) already gives Delivery Challan the exact
duplicate-movement protection §18/§34 ask for, PROVIDED `source_id` is
set to the delivery_challan_LINE's id (not the header's) for each STOCK
OUT movement — see `delivery_challan_service.py`'s module docstring.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0016_delivery_challan"
down_revision = "0015_sales_order"
branch_labels = None
depends_on = None

_DELIVERY_CHALLAN_PERMISSIONS = {
    "delivery_challan.view": "View tenant delivery challans",
    "delivery_challan.create": "Create a delivery challan against a sales order",
    "delivery_challan.edit": "Edit a draft delivery challan",
    "delivery_challan.confirm": "Confirm a delivery challan and dispatch stock",
    "delivery_challan.cancel": "Cancel a draft delivery challan",
}

# No approved source defines exact per-role Delivery Challan permissions
# (§35/§45 Q5 — open decision, documented in PROMPT-014-NOTES.md). Resolved
# by mirroring Sales Order's established shape: Salesperson gets the full
# day-to-day lifecycle except CONFIRM — User Story 3 again explicitly names
# "Owner/Manager" as the actor confirming the stock-reducing action.
_ROLE_DEFAULT_PERMISSIONS = {
    "OWNER": [
        "delivery_challan.view", "delivery_challan.create", "delivery_challan.edit",
        "delivery_challan.confirm", "delivery_challan.cancel",
    ],
    "MANAGER": [
        "delivery_challan.view", "delivery_challan.create", "delivery_challan.edit",
        "delivery_challan.confirm", "delivery_challan.cancel",
    ],
    "SALESPERSON": [
        "delivery_challan.view", "delivery_challan.create", "delivery_challan.edit", "delivery_challan.cancel",
    ],
}


def upgrade() -> None:
    # --- Sales Order fulfillment tracking (needed by Delivery Challan) ---
    op.add_column(
        "sales_order_line",
        sa.Column("delivered_quantity", sa.Numeric(18, 3), nullable=False, server_default="0"),
    )
    op.create_check_constraint(
        "ck_sales_order_line_delivered_quantity",
        "sales_order_line",
        "delivered_quantity >= 0 AND delivered_quantity <= quantity",
    )
    op.drop_constraint("ck_sales_order_status", "sales_order", type_="check")
    op.create_check_constraint(
        "ck_sales_order_status",
        "sales_order",
        "status IN ('DRAFT','CONFIRMED','PARTIALLY_FULFILLED','FULFILLED','CANCELLED')",
    )

    # --- Delivery Challan tables ---
    op.create_table(
        "delivery_challan",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("challan_number", sa.String(50), nullable=False),
        sa.Column("challan_date", sa.Date, nullable=False, server_default=sa.text("CURRENT_DATE")),
        sa.Column("source_sales_order_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sales_order.id"), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("customer.id"), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="DRAFT"),
        sa.Column("billing_address", sa.String(500), nullable=True),
        # Proposed additions — see module docstring.
        sa.Column("shipping_address", sa.String(500), nullable=True),
        sa.Column("place_of_supply_state_code", sa.CHAR(2), nullable=True),
        sa.Column("total_quantity", sa.Numeric(18, 3), nullable=False, server_default="0"),
        sa.Column("notes", sa.String(1000), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("row_version", sa.BigInteger, nullable=False, server_default="1"),
        sa.UniqueConstraint("tenant_id", "challan_number", name="uq_delivery_challan_number"),
        sa.CheckConstraint("status IN ('DRAFT','CONFIRMED','CANCELLED')", name="ck_delivery_challan_status"),
        sa.CheckConstraint("total_quantity >= 0", name="ck_delivery_challan_total_quantity"),
    )
    op.create_index("idx_delivery_challan_tenant", "delivery_challan", ["tenant_id"])
    op.create_index("idx_delivery_challan_source_order", "delivery_challan", ["tenant_id", "source_sales_order_id"])
    op.create_index("idx_delivery_challan_customer", "delivery_challan", ["tenant_id", "customer_id"])
    op.create_index("idx_delivery_challan_status", "delivery_challan", ["status"])

    op.create_table(
        "delivery_challan_line",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("challan_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("delivery_challan.id"), nullable=False),
        sa.Column("line_no", sa.Integer, nullable=False),
        sa.Column("source_sales_order_line_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sales_order_line.id"), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("product.id"), nullable=True),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("hsn_code", sa.String(8), nullable=True),
        sa.Column("uom_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("unit_of_measure.id"), nullable=False),
        sa.Column("ordered_quantity", sa.Numeric(18, 3), nullable=False),
        sa.Column("previously_delivered_quantity", sa.Numeric(18, 3), nullable=False, server_default="0"),
        sa.Column("current_delivery_quantity", sa.Numeric(18, 3), nullable=False),
        sa.Column("remaining_quantity", sa.Numeric(18, 3), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("row_version", sa.BigInteger, nullable=False, server_default="1"),
        sa.CheckConstraint("current_delivery_quantity > 0", name="ck_delivery_challan_line_current_qty"),
        sa.CheckConstraint("current_delivery_quantity <= ordered_quantity", name="ck_delivery_challan_line_qty_le_ordered"),
        sa.CheckConstraint("previously_delivered_quantity >= 0", name="ck_delivery_challan_line_prev_qty"),
        sa.CheckConstraint("remaining_quantity >= 0", name="ck_delivery_challan_line_remaining_qty"),
    )
    op.create_index("idx_delivery_challan_line_tenant", "delivery_challan_line", ["tenant_id"])
    op.create_index("idx_delivery_challan_line_challan", "delivery_challan_line", ["challan_id"])
    op.create_index("idx_delivery_challan_line_source", "delivery_challan_line", ["source_sales_order_line_id"])

    for table in ("delivery_challan", "delivery_challan_line"):
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY tenant_isolation_{table} ON "{table}" '
            f"USING (tenant_id::text = current_setting('app.tenant_id', true))"
        )

    connection = op.get_bind()

    permission_ids: dict[str, str] = {}
    for code, description in _DELIVERY_CHALLAN_PERMISSIONS.items():
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
    for table in ("delivery_challan_line", "delivery_challan"):
        op.execute(f'DROP POLICY IF EXISTS tenant_isolation_{table} ON "{table}"')
    op.drop_table("delivery_challan_line")
    op.drop_table("delivery_challan")

    op.drop_constraint("ck_sales_order_status", "sales_order", type_="check")
    op.create_check_constraint(
        "ck_sales_order_status", "sales_order", "status IN ('DRAFT','CONFIRMED','CANCELLED')"
    )
    op.drop_constraint("ck_sales_order_line_delivered_quantity", "sales_order_line", type_="check")
    op.drop_column("sales_order_line", "delivered_quantity")
    # Permission/role_permission seed rows left in place, matching precedent.
