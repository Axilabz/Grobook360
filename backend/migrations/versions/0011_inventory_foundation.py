"""Inventory foundation: Location, Stock Ledger, Stock Adjustment (PROMPT-010)
+ inventory.* permission catalogue.

Revision ID: 0011_inventory_foundation
Revises: 0010_product_master
Create Date: 2026-09-10

Three MASTER/INVENTORY-domain tables Table Register already lists but no
prior prompt created:

- `location`: exactly per Data Dictionary v3.0 (id, tenant_id, code, name,
  address, status, audit/row_version). §8 of this prompt: M1 supports only
  one active location. No Location management API/UI is built here — a
  single "MAIN" location is lazily get-or-created per tenant by
  `app/services/inventory/inventory_service.py` the first time that tenant
  posts any stock movement, rather than requiring a manual setup screen
  nothing in this prompt's scope asks for.

- `stock_ledger_entry`: per Data Dictionary v3.0 (id, tenant_id, product_id,
  location_id, source_type, source_id, movement_type, quantity, uom_id,
  batch_no, expiry_date, occurred_at, audit/row_version) **plus one
  proposed addition**: `base_quantity`. The DD's own field list for this
  table (§12 of the prompt) explicitly asks for "quantity, unit,
  normalized/base quantity where applicable" — normalized/base quantity is
  not a DD column, so this is the same "propose, document, implement"
  pattern used throughout this project. `quantity`/`uom_id` remain exactly
  what the caller entered (preserving the original entered value, per
  §27); `base_quantity` is that same movement expressed in the product's
  base UOM (via Product Master's own conversion table — no second
  conversion engine), making `SUM(base_quantity)`-style balance
  aggregation always correct without a per-row join at read time.

  `movement_type` is constrained to the five types this prompt actually
  implements: OPENING_STOCK, STOCK_IN, STOCK_OUT, ADJUSTMENT_IN,
  ADJUSTMENT_OUT. The DD's own constraint note ("IN/OUT/ADJUSTMENT") is a
  terse shorthand, not a literal 3-value enum — direction is deliberately
  folded into the type name (no separate ambiguous "direction" column,
  per §56: "do not allow contradictory states such as STOCK_OUT + IN
  direction"). SALES/PURCHASE/SALES_RETURN/PURCHASE_RETURN/
  DELIVERY_CHALLAN/TRANSFER (§13) are intentionally NOT added to the CHECK
  constraint yet — those belong to the Sales/Purchase modules that don't
  exist yet; extending this CHECK is exactly the kind of one-line migration
  those future prompts should make when they need a new type, not
  something to pre-guess now. TRANSFER specifically requires a second
  location, which is out of scope per §8 (single-location M1).

  Matches Table Register's IMMUTABLE/APPEND-ONLY = YES flag. Enforced with
  a BEFORE UPDATE/DELETE trigger that unconditionally raises, **not** just
  `REVOKE UPDATE, DELETE ... FROM PUBLIC` (audit_log's migration-0001
  precedent) — verified empirically while writing this prompt's own tests
  that REVOKE alone does nothing here: the application's DB role is the
  *owner* of these tables (created them via Alembic), and table ownership
  in PostgreSQL bypasses its own grant/revoke checks entirely, so
  `audit_log` has actually never been immutable against the app's own
  connection despite the comment there claiming so. A trigger fires
  regardless of ownership and is the only defense that actually works
  without switching the app to a separate non-owning DB role (a bigger,
  separately-scoped change). The REVOKE statement is kept alongside the
  trigger for defense-in-depth against any future non-owning role, but the
  trigger is what actually enforces this. Flagged as a pre-existing gap in
  `audit_log` for a follow-up fix — not corrected here since it's out of
  this prompt's scope.

- `stock_adjustment`: per Data Dictionary v3.0 (id, tenant_id,
  adjustment_number, location_id, reason, status, approved_by, approved_at,
  audit/row_version) — a header row per adjustment, referenced by exactly
  one `stock_ledger_entry` as `source_type='STOCK_ADJUSTMENT'`. The
  DRAFT/approved_by/approved_at columns exist per the approved schema, but
  no source names a distinct "approver" role separate from the
  "Owner/Manager may record manual stock movements" authority in FR-STK-04
  — so this MVP self-approves atomically (the creating Owner/Manager is
  also `approved_by`) rather than inventing a second reviewer role nobody
  defined. See PROMPT-010-NOTES.md.

`stock_qty_cache` on `product` (PROMPT-009, previously write-less) gets its
first writer here — transactionally updated alongside every ledger insert,
per FR-STK-05/BR-015 ("ledger is authoritative; cache must be
reconcilable").
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0011_inventory_foundation"
down_revision = "0010_product_master"
branch_labels = None
depends_on = None

_INVENTORY_PERMISSIONS = {
    "inventory.view": "View tenant inventory and stock movement history",
    "inventory.opening_stock": "Record opening stock for a product",
    "inventory.adjust": "Record a manual stock adjustment",
    "inventory.stock_in": "Record a manual stock-in movement",
    "inventory.stock_out": "Record a manual stock-out movement",
}

# FR-STK-04 (Confirmed): Owner/Manager may record manual stock movements;
# Salesperson may only cause stock movement through permitted sales
# workflows (none exist yet, so view-only for now).
_ROLE_DEFAULT_PERMISSIONS = {
    "OWNER": ["inventory.view", "inventory.opening_stock", "inventory.adjust", "inventory.stock_in", "inventory.stock_out"],
    "MANAGER": ["inventory.view", "inventory.opening_stock", "inventory.adjust", "inventory.stock_in", "inventory.stock_out"],
    "SALESPERSON": ["inventory.view"],
}


def upgrade() -> None:
    op.create_table(
        "location",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("code", sa.String(30), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("address", sa.String(500), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="ACTIVE"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("row_version", sa.BigInteger, nullable=False, server_default="1"),
        sa.UniqueConstraint("tenant_id", "code", name="uq_location_code"),
        sa.CheckConstraint("status IN ('ACTIVE','INACTIVE')", name="ck_location_status"),
    )
    op.create_index("idx_location_tenant", "location", ["tenant_id"])

    op.create_table(
        "stock_adjustment",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("adjustment_number", sa.String(50), nullable=False),
        sa.Column("location_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("location.id"), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="DRAFT"),
        sa.Column("approved_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("row_version", sa.BigInteger, nullable=False, server_default="1"),
        sa.UniqueConstraint("tenant_id", "adjustment_number", name="uq_stock_adjustment_number"),
        sa.CheckConstraint("status IN ('DRAFT','APPROVED')", name="ck_stock_adjustment_status"),
    )
    op.create_index("idx_stock_adjustment_tenant", "stock_adjustment", ["tenant_id"])

    op.create_table(
        "stock_ledger_entry",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("product.id"), nullable=False),
        sa.Column("location_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("location.id"), nullable=False),
        sa.Column("source_type", sa.String(50), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("movement_type", sa.String(20), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 3), nullable=False),
        sa.Column("uom_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("unit_of_measure.id"), nullable=False),
        # Proposed addition — see module docstring.
        sa.Column("base_quantity", sa.Numeric(18, 3), nullable=False),
        # Schema-reserved, unused (OQ-007 in the FRD is still open — "Is
        # batch/expiry in M1?"). No business logic reads/writes these.
        sa.Column("batch_no", sa.String(50), nullable=True),
        sa.Column("expiry_date", sa.Date, nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("row_version", sa.BigInteger, nullable=False, server_default="1"),
        sa.CheckConstraint(
            "movement_type IN ('OPENING_STOCK','STOCK_IN','STOCK_OUT','ADJUSTMENT_IN','ADJUSTMENT_OUT')",
            name="ck_stock_ledger_entry_movement_type",
        ),
        sa.CheckConstraint("quantity > 0", name="ck_stock_ledger_entry_quantity_positive"),
        sa.CheckConstraint("base_quantity > 0", name="ck_stock_ledger_entry_base_quantity_positive"),
        # Idempotency (§15/§41/§42): one ledger entry per source event.
        # Opening stock uses source_id = product_id, so this also enforces
        # "at most one opening stock entry per product" (§20 recommended
        # principle, §68 Q9 resolved: no, multiple opening-stock entries
        # per product are not allowed).
        sa.UniqueConstraint("tenant_id", "source_type", "source_id", name="uq_stock_ledger_entry_source"),
    )
    op.create_index("idx_stock_ledger_entry_tenant", "stock_ledger_entry", ["tenant_id"])
    op.create_index("idx_stock_ledger_entry_product", "stock_ledger_entry", ["tenant_id", "product_id"])
    op.create_index("idx_stock_ledger_entry_movement_type", "stock_ledger_entry", ["movement_type"])
    op.create_index("idx_stock_ledger_entry_occurred_at", "stock_ledger_entry", ["occurred_at"])

    for table in ("location", "stock_adjustment", "stock_ledger_entry"):
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY tenant_isolation_{table} ON "{table}" '
            f"USING (tenant_id::text = current_setting('app.tenant_id', true))"
        )

    # Ledger immutability (Table Register: IMMUTABLE/APPEND-ONLY = YES).
    # REVOKE alone (audit_log's migration-0001 approach) does not work
    # against the app's own DB role, which owns these tables — see module
    # docstring. A trigger fires regardless of ownership.
    op.execute("REVOKE UPDATE, DELETE ON stock_ledger_entry FROM PUBLIC")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_stock_ledger_entry_mutation()
        RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION 'stock_ledger_entry is append-only: % not permitted', TG_OP;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_stock_ledger_entry_immutable
        BEFORE UPDATE OR DELETE ON stock_ledger_entry
        FOR EACH ROW EXECUTE FUNCTION prevent_stock_ledger_entry_mutation();
        """
    )

    connection = op.get_bind()

    permission_ids: dict[str, str] = {}
    for code, description in _INVENTORY_PERMISSIONS.items():
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
    op.execute("DROP TRIGGER IF EXISTS trg_stock_ledger_entry_immutable ON stock_ledger_entry")
    op.execute("DROP FUNCTION IF EXISTS prevent_stock_ledger_entry_mutation()")
    op.execute("GRANT UPDATE, DELETE ON stock_ledger_entry TO PUBLIC")
    for table in ("stock_ledger_entry", "stock_adjustment", "location"):
        op.execute(f'DROP POLICY IF EXISTS tenant_isolation_{table} ON "{table}"')
    op.drop_table("stock_ledger_entry")
    op.drop_table("stock_adjustment")
    op.drop_table("location")
    # Permission/role_permission seed rows are left in place on downgrade,
    # matching migrations 0007/0008/0009/0010's precedent.
