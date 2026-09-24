"""Credit Note / Debit Note (PROMPT-017) + credit_note.*/debit_note.*
permission catalogue + Sales Invoice credited/debited-quantity tracking.

Revision ID: 0019_credit_debit_note
Revises: 0018_sales_return
Create Date: 2026-09-06

The sixth Sales document type, and the first that is a PURE FINANCIAL
ADJUSTMENT with NO inventory effect whatsoever (§2/§3/§22 — the single
most safety-critical rule in this prompt: neither note type ever calls
`InventoryService`/`post_movement`, structurally, not just by omission —
verified by a dedicated test asserting zero new `stock_ledger_entry`
rows for both note types).

Data Dictionary v3.0 specifies one shared table pair —
`credit_debit_note`/`credit_debit_note_line` (SALES domain) — for BOTH
note types, distinguished by `note_type`. Reused verbatim for the exact
minimal field set the baseline defines (id, tenant_id, note_number,
customer_id, document_date, status, subtotal/discount_total/
taxable_total/tax_total/grand_total, note_type, source_invoice_id at the
header; id/tenant_id/credit_debit_note_id/line_no/product_id/
description/quantity/uom_id/unit_price/discount_amount/taxable_amount/
gst_rate/cgst_amount/sgst_amount/igst_amount/cess_amount/line_total at
the line).

Proposed schema additions (same "propose, document, implement" pattern
every prior prompt has used):

- `credit_debit_note.note_type` is widened to VARCHAR(20) (from the
  baseline's VARCHAR(10)): the baseline's own CHECK-constraint wording
  ("CREDIT/DEBIT") implies 6/5-character values, but §8 of this prompt
  explicitly instructs implementing the self-describing document types
  `CREDIT_NOTE`/`DEBIT_NOTE` (11/10 characters) — matching the identical
  vocabulary already reserved in `app.core.sales_constants` since
  PROMPT-011. Resolved in favor of the more specific, more recent prompt
  instruction (the same resolution precedent as PROMPT-004's FR-SI-07-vs-
  no-OTP conflict) — documented here, not silently changed.
- `credit_debit_note.note_date` (this migration's name for the baseline's
  `document_date`, matching every sibling document's own `<type>_date`
  naming convention — `invoice_date`/`challan_date`/`return_date`).
- `credit_debit_note.customer_gstin`, `.billing_address`,
  `.shipping_address`, `.place_of_supply_state_code` (snapshots — same
  principle as every prior Sales document; needed to recompute GST
  treatment consistently with the source invoice at post time).
- `credit_debit_note.reason` (NOT NULL, free-text VARCHAR — §4/§53 open
  decision #20 explicitly instructs NOT inventing a controlled reason
  taxonomy "unless supported by approved requirements", unlike Sales
  Return's own prompt which explicitly suggested one. A free-text reason
  is still captured for audit/traceability, just not CHECK-constrained
  to an enum).
- `credit_debit_note.notes` (nullable): identical resolution to every
  prior Sales document.
- `credit_debit_note.cgst_total` / `.sgst_total` / `.igst_total`:
  header-level GST split, consistent with every prior Sales document's
  own proposed addition over the baseline's `tax_total`-only shape.
- `credit_debit_note.accounting_posting_reference` / `.gst_transaction_
  reference` (both nullable VARCHAR): §20/§21's integration-boundary
  contract, identical pattern to `sales_invoice`/`sales_return`'s own
  reference columns. Neither is a foreign key: no real ledger/GST
  transaction table exists yet.
- `credit_debit_note_line.hsn_code`: line-level HSN snapshot, same as
  every prior Sales document line.
- `credit_debit_note_line.source_invoice_line_id` (NOT NULL FK ->
  sales_invoice_line.id): §17/§18's core eligibility/pricing requirement
  — every note line MUST reference the specific Sales Invoice line it
  adjusts, so eligible remaining quantity/value can be computed and
  historical pricing can be preserved. Resolves Open Decision #22
  ("quantity-based vs value-based") as quantity-based, mirroring Sales
  Return's identical line model — see PROMPT-017-NOTES.md §9 for the
  full rationale and the documented Open Decision this judgment call
  still leaves for Debit Note's true eligibility rule.

No `credit_note_source_return_id` column: Credit-Note-from-Sales-Return
(§14, explicit "if approved") is NOT implemented — the baseline schema
itself has no such column, and no approved requirement confirms this
path (Open Decision #5, see PROMPT-017-NOTES.md). Only Sales-Invoice-
sourced notes are supported in this prompt.

Sales Invoice changes (this same migration, since neither note type can
enforce §17's eligibility-limit rule without it):

- `sales_invoice_line.credited_quantity` (NUMERIC(18,3), default 0):
  cumulative quantity already credited via POSTED Credit Notes against
  this invoice line. Only ever incremented by
  `CreditDebitNoteService.post_note` when `note_type='CREDIT_NOTE'`.
  `CHECK (credited_quantity >= 0 AND credited_quantity <= quantity)` is
  the DB-level backstop, the same class of constraint as
  `sales_invoice_line.returned_quantity`'s own CHECK from migration 0018.
- `sales_invoice_line.debited_quantity` (NUMERIC(18,3), default 0): the
  same running-total pattern for Debit Notes. Its cap-at-`quantity`
  CHECK is a deliberately CONSERVATIVE placeholder (§53 open decision
  #10/#28, explicitly flagged unresolved by this prompt itself) — a real
  Debit Note (e.g. a short-billing correction) may not naturally need to
  be bounded by the ORIGINAL invoiced quantity at all. This constraint
  prevents unbounded/unsafe adjustment values in this MVP without
  claiming to have resolved the true business rule.

Status model (§9, explicit open decision #1... actually not numbered as
open in this prompt, but resolved the same way as every prior document):
adopted the prompt's own recommended baseline verbatim — DRAFT, POSTED,
CANCELLED.

Cancellation-after-posting (§30/§53 open decisions #15-17): NOT
implemented — mirrors Sales Return/Sales Invoice/Delivery Challan's own
identical resolution for the identical reason (no approved reversal
mechanism for the accounting/GST effect exists). `ck_credit_debit_note_
status` still allows CANCELLED (for a DRAFT to be cancelled); the
application layer restricts POSTED -> CANCELLED until reversal design is
approved.

Numbering: reuses `document_number_sequence`/`DocumentNumberingService`
with document_type="CREDIT_NOTE"/"DEBIT_NOTE" (already reserved in
`app.core.sales_constants` since PROMPT-011) — no separate numbering
mechanism, per §23's explicit instruction to reuse existing numbering.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0019_credit_debit_note"
down_revision = "0018_sales_return"
branch_labels = None
depends_on = None

_CREDIT_DEBIT_NOTE_PERMISSIONS = {
    "credit_note.view": "View tenant credit notes",
    "credit_note.create": "Create a credit note against a posted sales invoice",
    "credit_note.edit": "Edit a draft credit note",
    "credit_note.post": "Post a credit note (accounting/GST impact)",
    "credit_note.cancel": "Cancel a draft credit note",
    "debit_note.view": "View tenant debit notes",
    "debit_note.create": "Create a debit note against a posted sales invoice",
    "debit_note.edit": "Edit a draft debit note",
    "debit_note.post": "Post a debit note (accounting/GST impact)",
    "debit_note.cancel": "Cancel a draft debit note",
}

# No approved source defines exact per-role Credit/Debit Note permissions
# (§42/§53 open decision #24 — explicitly flagged unresolved, see
# PROMPT-017-NOTES.md). Resolved by mirroring the established shape from
# every prior Sales document type: Salesperson gets the full day-to-day
# lifecycle except POST, the accounting/GST-impacting action.
_ROLE_DEFAULT_PERMISSIONS = {
    "OWNER": [
        "credit_note.view", "credit_note.create", "credit_note.edit", "credit_note.post", "credit_note.cancel",
        "debit_note.view", "debit_note.create", "debit_note.edit", "debit_note.post", "debit_note.cancel",
    ],
    "MANAGER": [
        "credit_note.view", "credit_note.create", "credit_note.edit", "credit_note.post", "credit_note.cancel",
        "debit_note.view", "debit_note.create", "debit_note.edit", "debit_note.post", "debit_note.cancel",
    ],
    "SALESPERSON": [
        "credit_note.view", "credit_note.create", "credit_note.edit", "credit_note.cancel",
        "debit_note.view", "debit_note.create", "debit_note.edit", "debit_note.cancel",
    ],
}


def upgrade() -> None:
    # --- Sales Invoice credited/debited-quantity tracking ---
    op.add_column(
        "sales_invoice_line",
        sa.Column("credited_quantity", sa.Numeric(18, 3), nullable=False, server_default="0"),
    )
    op.add_column(
        "sales_invoice_line",
        sa.Column("debited_quantity", sa.Numeric(18, 3), nullable=False, server_default="0"),
    )
    op.create_check_constraint(
        "ck_sales_invoice_line_credited_quantity",
        "sales_invoice_line",
        "credited_quantity >= 0 AND credited_quantity <= quantity",
    )
    op.create_check_constraint(
        "ck_sales_invoice_line_debited_quantity",
        "sales_invoice_line",
        "debited_quantity >= 0 AND debited_quantity <= quantity",
    )

    # --- Credit/Debit Note tables ---
    op.create_table(
        "credit_debit_note",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("note_number", sa.String(50), nullable=False),
        sa.Column("note_type", sa.String(20), nullable=False),
        sa.Column("note_date", sa.Date, nullable=False, server_default=sa.text("CURRENT_DATE")),
        sa.Column("source_invoice_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sales_invoice.id"), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("customer.id"), nullable=False),
        sa.Column("customer_gstin", sa.CHAR(15), nullable=True),
        sa.Column("billing_address", sa.String(500), nullable=True),
        sa.Column("shipping_address", sa.String(500), nullable=True),
        sa.Column("place_of_supply_state_code", sa.CHAR(2), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="DRAFT"),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("notes", sa.String(1000), nullable=True),
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
        sa.UniqueConstraint("tenant_id", "note_number", name="uq_credit_debit_note_number"),
        sa.CheckConstraint("status IN ('DRAFT','POSTED','CANCELLED')", name="ck_credit_debit_note_status"),
        sa.CheckConstraint("note_type IN ('CREDIT_NOTE','DEBIT_NOTE')", name="ck_credit_debit_note_type"),
        sa.CheckConstraint("subtotal >= 0", name="ck_credit_debit_note_subtotal"),
        sa.CheckConstraint("discount_total >= 0", name="ck_credit_debit_note_discount_total"),
        sa.CheckConstraint("grand_total >= 0", name="ck_credit_debit_note_grand_total"),
    )
    op.create_index("idx_credit_debit_note_tenant", "credit_debit_note", ["tenant_id"])
    op.create_index("idx_credit_debit_note_customer", "credit_debit_note", ["tenant_id", "customer_id"])
    op.create_index("idx_credit_debit_note_source_invoice", "credit_debit_note", ["tenant_id", "source_invoice_id"])
    op.create_index("idx_credit_debit_note_status", "credit_debit_note", ["status"])
    op.create_index("idx_credit_debit_note_type", "credit_debit_note", ["note_type"])

    op.create_table(
        "credit_debit_note_line",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("credit_debit_note_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("credit_debit_note.id"), nullable=False),
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
        sa.UniqueConstraint("credit_debit_note_id", "line_no", name="uq_credit_debit_note_line_no"),
        sa.CheckConstraint("quantity > 0", name="ck_credit_debit_note_line_quantity"),
        sa.CheckConstraint("unit_price >= 0", name="ck_credit_debit_note_line_unit_price"),
        sa.CheckConstraint("discount_amount >= 0", name="ck_credit_debit_note_line_discount"),
        sa.CheckConstraint("gst_rate >= 0 AND gst_rate <= 100", name="ck_credit_debit_note_line_gst_rate"),
    )
    op.create_index("idx_credit_debit_note_line_tenant", "credit_debit_note_line", ["tenant_id"])
    op.create_index("idx_credit_debit_note_line_note", "credit_debit_note_line", ["credit_debit_note_id"])
    op.create_index("idx_credit_debit_note_line_source_invoice_line", "credit_debit_note_line", ["source_invoice_line_id"])

    for table in ("credit_debit_note", "credit_debit_note_line"):
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY tenant_isolation_{table} ON "{table}" '
            f"USING (tenant_id::text = current_setting('app.tenant_id', true))"
        )

    connection = op.get_bind()

    permission_ids: dict[str, str] = {}
    for code, description in _CREDIT_DEBIT_NOTE_PERMISSIONS.items():
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
    for table in ("credit_debit_note_line", "credit_debit_note"):
        op.execute(f'DROP POLICY IF EXISTS tenant_isolation_{table} ON "{table}"')
    op.drop_table("credit_debit_note_line")
    op.drop_table("credit_debit_note")

    op.drop_constraint("ck_sales_invoice_line_debited_quantity", "sales_invoice_line", type_="check")
    op.drop_constraint("ck_sales_invoice_line_credited_quantity", "sales_invoice_line", type_="check")
    op.drop_column("sales_invoice_line", "debited_quantity")
    op.drop_column("sales_invoice_line", "credited_quantity")
    # Permission/role_permission seed rows left in place, matching precedent.
