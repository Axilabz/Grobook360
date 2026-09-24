"""Sales Return (PROMPT-016) + sales_return.* permission catalogue +
Sales Invoice returned-quantity tracking.

Revision ID: 0018_sales_return
Revises: 0017_sales_invoice
Create Date: 2026-09-06

The fifth Sales document type, and the FIRST that reverses a prior
transaction rather than extending it. §2/§5/§6 are the critical rules
this file exists to serve:

- Sales Return ALWAYS references a source Sales Invoice
  (`sales_return.source_invoice_id` NOT NULL FK, per the Data Dictionary
  v3.0 baseline itself — §47 open decision #3 is answered by the approved
  schema, not invented: a standalone/ad-hoc return has no source line to
  validate quantities against, so it is not supported).
- Confirming a Sales Return creates STOCK IN (never STOCK OUT) — the
  mirror image of Delivery Challan/direct Sales Invoice's STOCK OUT.
- A Sales Return is NOT a Credit Note. No credit-note table/reference is
  created here (§22 explicit boundary) — PROMPT-017's own scope.

Data Dictionary v3.0 specifies `sales_return`/`sales_return_line` (SALES
domain) with a MINIMAL baseline field set (id, tenant_id, return_number,
customer_id, document_date, status, subtotal/discount_total/
taxable_total/tax_total/grand_total, source_invoice_id, audit columns,
row_version at the header; id/tenant_id/sales_return_id/line_no/
product_id/description/quantity/uom_id/unit_price/discount_amount/
taxable_amount/gst_rate/cgst_amount/sgst_amount/igst_amount/cess_amount/
line_total/audit columns/row_version at the line). Reused verbatim for
that exact field set.

Proposed schema additions (same "propose, document, implement" pattern
every prior prompt has used):

- `sales_return.return_date` (this migration's name for the baseline's
  `document_date`, matching every sibling document's own `<type>_date`
  naming convention — `invoice_date`/`challan_date`/`order_date` — a pure
  naming-consistency choice, not a field this prompt invented).
- `sales_return.customer_gstin`, `.billing_address`, `.shipping_address`,
  `.place_of_supply_state_code` (snapshots — same principle as every
  prior Sales document; needed to recompute GST treatment consistently
  with the source invoice at confirm time).
- `sales_return.return_reason` (NOT NULL) / `.reason_description`
  (nullable, required only when reason='OTHER' — enforced in the service
  layer): §8 explicit open decision #2 — no approved return-reason master
  exists in the FRD/Data Dictionary, so the prompt's OWN suggested
  baseline taxonomy (DAMAGED / WRONG_PRODUCT / EXCESS_QUANTITY /
  QUALITY_ISSUE / CUSTOMER_REJECTION / OTHER) is adopted, documented as a
  proposed taxonomy needing eventual sign-off (Open Decision #2, see
  PROMPT-016-NOTES.md) — not silently hard-coded as final.
- `sales_return.notes` (nullable): identical resolution to every prior
  Sales document.
- `sales_return.total_return_quantity`: mirrors `delivery_challan.
  total_quantity`'s identical header-level running total for display.
- `sales_return.cgst_total` / `.sgst_total` / `.igst_total`: header-level
  GST split, consistent with Estimate/Sales Order/Sales Invoice's own
  proposed additions over the same baseline `tax_total`-only shape
  (`tax_total` remains the combined total, per the Data Dictionary's own
  field name).
- `sales_return.accounting_posting_reference` / `.gst_transaction_
  reference` (both nullable VARCHAR): §21/§22's integration-boundary
  contract, identical pattern to `sales_invoice`'s own two reference
  columns — see `accounting_posting_service.py`'s new `post_sales_return`
  method and `gst_reporting_service.py`'s new `record_return_transaction`
  method. Neither is a foreign key: no real ledger/GST transaction table
  exists yet (Open Decision #11/#12).
- `sales_return_line.hsn_code`: line-level HSN snapshot, same as every
  prior Sales document line.
- `sales_return_line.source_invoice_line_id` (NOT NULL FK ->
  sales_invoice_line.id): §6/§12's core traceability requirement — a
  return line MUST reference the specific invoice line it is returning
  against so returnable quantity can be validated. This is the single
  most important proposed addition in this migration; without it the
  Returnable Quantity formula (§7) has nothing to compute against.

No `round_off`, no `credit_note_id` column: the former is the same
unresolved-rounding-policy open decision restated for the fifth
consecutive document type; the latter would be inventing a forward
reference to a table that does not exist yet (§22 explicit boundary —
Credit Note is PROMPT-017's own scope).

Sales Invoice changes (this same migration, since Sales Return cannot
enforce §7's "returnable = invoiced - previously returned" rule without
it):

- `sales_invoice_line.returned_quantity` (NUMERIC(18,3), default 0):
  cumulative quantity already returned via CONFIRMED Sales Returns
  against this invoice line. Only ever incremented by
  `SalesReturnService.confirm_return` — never written from anywhere in
  `sales_invoice_service.py`. `CHECK (returned_quantity >= 0 AND
  returned_quantity <= quantity)` is the DB-level backstop, the same
  class of constraint as `delivery_challan_line.invoiced_quantity`'s own
  CHECK from migration 0017. The real "does this specific new return
  request exceed the CURRENTLY remaining returnable amount" comparison
  still happens in application code under a row lock (§18's mandatory
  concurrency requirement — same reasoning as every prior migration's
  identical caveat).

Status model (§13, explicit open decision #1): adopted the prompt's own
recommended baseline verbatim — DRAFT, CONFIRMED, CANCELLED (not POSTED —
§13's own wording says "CONFIRMED", matching Delivery Challan's status
name rather than Sales Invoice's "POSTED", since a Sales Return is
inventory-only like a Delivery Challan, not a billing document).

Cancellation-after-confirmation (§25/§47 open decisions #9-10): NOT
implemented — mirrors Delivery Challan/Sales Invoice's own identical
resolution for the identical reason (no approved reversal mechanism for
the Stock IN this document created exists). `ck_sales_return_status`
still allows CANCELLED (for a DRAFT to be cancelled); the application
layer restricts CONFIRMED -> CANCELLED until a compensating-STOCK_OUT
reversal design is approved.

Multiple returns per invoice line (§19/§47 open decision #4): the Data
Dictionary places NO unique constraint on `source_invoice_id` (or on a
source-invoice-line reference), and §19 explicitly asks for this to be
supported — resolved as YES, tracked via the same per-line running-total
column pattern (`sales_invoice_line.returned_quantity`) already used
twice in this exact document chain.

Numbering: reuses `document_number_sequence`/`DocumentNumberingService`
with document_type="SALES_RETURN" (already reserved in
`app.core.sales_constants` since PROMPT-011) — no separate numbering
mechanism, per §20's explicit instruction to reuse existing numbering.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0018_sales_return"
down_revision = "0017_sales_invoice"
branch_labels = None
depends_on = None

_SALES_RETURN_PERMISSIONS = {
    "sales_return.view": "View tenant sales returns",
    "sales_return.create": "Create a sales return against a posted sales invoice",
    "sales_return.edit": "Edit a draft sales return",
    "sales_return.confirm": "Confirm a sales return (creates stock IN)",
    "sales_return.cancel": "Cancel a draft sales return",
}

# No approved source defines exact per-role Sales Return permissions
# (§36/§47 open decision #18 — Salesperson-confirm is explicitly flagged
# unresolved, see PROMPT-016-NOTES.md). Resolved by mirroring Sales
# Order/Delivery Challan/Sales Invoice's established shape: Salesperson
# gets the full day-to-day lifecycle except CONFIRM, the stock-impacting
# action — this is now the fourth consecutive Sales document type
# resolved with this exact shape, a consistent pattern rather than a new
# judgment call, though still explicitly flagged as open per this
# prompt's own weaker (generic "authorized user") User Story wording.
_ROLE_DEFAULT_PERMISSIONS = {
    "OWNER": [
        "sales_return.view", "sales_return.create", "sales_return.edit",
        "sales_return.confirm", "sales_return.cancel",
    ],
    "MANAGER": [
        "sales_return.view", "sales_return.create", "sales_return.edit",
        "sales_return.confirm", "sales_return.cancel",
    ],
    "SALESPERSON": [
        "sales_return.view", "sales_return.create", "sales_return.edit", "sales_return.cancel",
    ],
}


def upgrade() -> None:
    # --- Sales Invoice returned-quantity tracking (needed by Sales Return) ---
    op.add_column(
        "sales_invoice_line",
        sa.Column("returned_quantity", sa.Numeric(18, 3), nullable=False, server_default="0"),
    )
    op.create_check_constraint(
        "ck_sales_invoice_line_returned_quantity",
        "sales_invoice_line",
        "returned_quantity >= 0 AND returned_quantity <= quantity",
    )

    # --- Sales Return tables ---
    op.create_table(
        "sales_return",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("return_number", sa.String(50), nullable=False),
        sa.Column("return_date", sa.Date, nullable=False, server_default=sa.text("CURRENT_DATE")),
        sa.Column("source_invoice_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sales_invoice.id"), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("customer.id"), nullable=False),
        sa.Column("customer_gstin", sa.CHAR(15), nullable=True),
        sa.Column("billing_address", sa.String(500), nullable=True),
        sa.Column("shipping_address", sa.String(500), nullable=True),
        sa.Column("place_of_supply_state_code", sa.CHAR(2), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="DRAFT"),
        sa.Column("return_reason", sa.String(30), nullable=False),
        sa.Column("reason_description", sa.String(500), nullable=True),
        sa.Column("notes", sa.String(1000), nullable=True),
        sa.Column("total_return_quantity", sa.Numeric(18, 3), nullable=False, server_default="0"),
        sa.Column("subtotal", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("discount_total", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("taxable_total", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("cgst_total", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("sgst_total", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("igst_total", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("tax_total", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("grand_total", sa.Numeric(15, 2), nullable=False, server_default="0"),
        # Integration boundaries — see module docstring. Opaque references,
        # not foreign keys to tables that don't exist yet.
        sa.Column("accounting_posting_reference", sa.String(100), nullable=True),
        sa.Column("gst_transaction_reference", sa.String(100), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("row_version", sa.BigInteger, nullable=False, server_default="1"),
        sa.UniqueConstraint("tenant_id", "return_number", name="uq_sales_return_number"),
        sa.CheckConstraint("status IN ('DRAFT','CONFIRMED','CANCELLED')", name="ck_sales_return_status"),
        sa.CheckConstraint(
            "return_reason IN ('DAMAGED','WRONG_PRODUCT','EXCESS_QUANTITY','QUALITY_ISSUE',"
            "'CUSTOMER_REJECTION','OTHER')",
            name="ck_sales_return_reason",
        ),
        sa.CheckConstraint("subtotal >= 0", name="ck_sales_return_subtotal"),
        sa.CheckConstraint("discount_total >= 0", name="ck_sales_return_discount_total"),
        sa.CheckConstraint("grand_total >= 0", name="ck_sales_return_grand_total"),
        sa.CheckConstraint("total_return_quantity >= 0", name="ck_sales_return_total_quantity"),
    )
    op.create_index("idx_sales_return_tenant", "sales_return", ["tenant_id"])
    op.create_index("idx_sales_return_customer", "sales_return", ["tenant_id", "customer_id"])
    op.create_index("idx_sales_return_source_invoice", "sales_return", ["tenant_id", "source_invoice_id"])
    op.create_index("idx_sales_return_status", "sales_return", ["status"])

    op.create_table(
        "sales_return_line",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("sales_return_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sales_return.id"), nullable=False),
        sa.Column("line_no", sa.Integer, nullable=False),
        # Proposed addition — see module docstring; this is the critical link.
        sa.Column("source_invoice_line_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sales_invoice_line.id"), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("product.id"), nullable=True),
        sa.Column("description", sa.String(500), nullable=True),
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
        sa.Column("cess_amount", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("line_total", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("row_version", sa.BigInteger, nullable=False, server_default="1"),
        sa.UniqueConstraint("sales_return_id", "line_no", name="uq_sales_return_line_no"),
        sa.CheckConstraint("quantity > 0", name="ck_sales_return_line_quantity"),
        sa.CheckConstraint("unit_price >= 0", name="ck_sales_return_line_unit_price"),
        sa.CheckConstraint("discount_amount >= 0", name="ck_sales_return_line_discount"),
        sa.CheckConstraint("gst_rate >= 0 AND gst_rate <= 100", name="ck_sales_return_line_gst_rate"),
    )
    op.create_index("idx_sales_return_line_tenant", "sales_return_line", ["tenant_id"])
    op.create_index("idx_sales_return_line_return", "sales_return_line", ["sales_return_id"])
    op.create_index("idx_sales_return_line_source_invoice_line", "sales_return_line", ["source_invoice_line_id"])

    for table in ("sales_return", "sales_return_line"):
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY tenant_isolation_{table} ON "{table}" '
            f"USING (tenant_id::text = current_setting('app.tenant_id', true))"
        )

    connection = op.get_bind()

    permission_ids: dict[str, str] = {}
    for code, description in _SALES_RETURN_PERMISSIONS.items():
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
    for table in ("sales_return_line", "sales_return"):
        op.execute(f'DROP POLICY IF EXISTS tenant_isolation_{table} ON "{table}"')
    op.drop_table("sales_return_line")
    op.drop_table("sales_return")

    op.drop_constraint("ck_sales_invoice_line_returned_quantity", "sales_invoice_line", type_="check")
    op.drop_column("sales_invoice_line", "returned_quantity")
    # Permission/role_permission seed rows left in place, matching precedent.
