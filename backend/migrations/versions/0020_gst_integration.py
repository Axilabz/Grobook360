"""E-Invoice / E-Way Bill integration (PROMPT-018) + einvoice.*/eway_bill.*
permission catalogue.

Revision ID: 0020_gst_integration
Revises: 0019_credit_debit_note
Create Date: 2026-09-06

The FIRST prompt in this codebase that integrates with an EXTERNAL
government/GSP system rather than a purely internal business document.
No approved Database Design/Data Dictionary baseline covers this area at
all (it postdates the v3.0 dictionary's own scope) — every table here is
a "propose, document, implement" addition, not a reuse of an existing
baseline table, unlike every prior Sales-document migration.

Four new tables:

- `integration_configuration`: ONE ROW PER TENANT (§7 — M1: one tenant =
  one business = one GSTIN), holding provider/environment/timeout/retry
  settings and an ENCRYPTED credentials blob (`credentials_encrypted`,
  Fernet symmetric encryption via `app.services.gst_integration.crypto`
  — never plaintext, never logged, never returned by any API). GSTIN
  itself is NOT duplicated here — always read live from `tenant.gstin`
  (§7/§28 "do not create redundant copies... unless required").
  `einvoice_enabled`/`eway_bill_enabled` are the pragmatic, HONEST
  resolution of §8/§18's "applicability" requirement: no approved legal
  turnover threshold or transaction-type rule exists anywhere in this
  codebase's source documents, so applicability is a tenant-level
  opt-in toggle plus a data-completeness readiness check — NOT invented
  legal thresholds (§53 Open Decision #4/#5, see PROMPT-018-NOTES.md).

- `einvoice`: one row per Sales Invoice that has been evaluated for
  e-invoicing (`sales_invoice_id` UNIQUE FK — a Sales Invoice gets AT
  MOST one e-invoice record, matching real-world GST e-invoicing: a
  cancelled IRN's invoice cannot get a second IRN; a correction requires
  a new invoice entirely, per §17). Holds the full authoritative
  provider response (IRN, ack number/date, signed invoice/QR payloads,
  provider reference) — §13/§14 explicit requirements. `sales_invoice`'s
  own reserved `irn`/`ack_number`/`ack_date`/`einvoice_status`/
  `qr_code_data` columns (added back in migration 0017, PROMPT-015,
  explicitly "reserved for PROMPT-018") are kept in sync as a fast-read
  DENORMALIZED SNAPSHOT for list-screen display — this table is the
  authoritative, audit-grade record.

- `eway_bill`: one row per Sales Invoice's E-Way Bill (`sales_invoice_id`
  UNIQUE FK — this MVP scopes E-Way Bill generation to Sales-Invoice-
  sourced transactions only, per this prompt's own dependency chain;
  multi-document/multi-vehicle consolidated E-Way Bills are explicitly
  NOT supported — §53 Open Decision #27 analog, "consolidated
  adjustments" restated for E-Way Bill).

- `integration_operation`: the operational history/idempotency-tracking
  log (§29) for every GENERATE/CANCEL/STATUS_CHECK attempt against
  either entity type. `entity_type`+`entity_id` link back to the
  `einvoice`/`eway_bill` row. This table is NOT the idempotency
  mechanism itself (the existing `idempotency_key` table +
  `IdempotencyService` already handles "same HTTP request retried with
  the same client-supplied Idempotency-Key" — reused verbatim, no new
  mechanism invented) — it is the audit/reconciliation trail plus the
  concurrency guard's evidence: `einvoice.status`/`eway_bill.status`
  being PROCESSING (checked under a row lock, exactly the same
  `SELECT ... FOR UPDATE` pattern every prior Sales document's
  confirm/post action already uses) is what actually prevents two
  concurrent Generate requests from racing (§11/§38).

Status model (§15, adopted verbatim for both `einvoice.status` and
`eway_bill.status`): NOT_APPLICABLE, READY, QUEUED, PROCESSING,
GENERATED, FAILED, CANCEL_REQUESTED, CANCELLED, STATUS_UNKNOWN.

No background-worker/queue infrastructure exists anywhere in this
17-prompt codebase (every prior "post"/"confirm" action is a single
synchronous request-response, same as every other FastAPI endpoint
here) — §53 Open Decision #8 ("background worker technology") is
EXPLICITLY UNRESOLVED. This migration/prompt implements GENERATE/CANCEL
synchronously within the HTTP request (same architecture as every prior
prompt), with the idempotency/concurrency/reconciliation safeguards
described above substituting for a queue. See PROMPT-018-NOTES.md.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0020_gst_integration"
down_revision = "0019_credit_debit_note"
branch_labels = None
depends_on = None

_GST_INTEGRATION_PERMISSIONS = {
    "einvoice.view": "View tenant e-invoice status and details",
    "einvoice.generate": "Generate an e-invoice (IRN) for a posted sales invoice",
    "einvoice.cancel": "Cancel a generated e-invoice (IRN)",
    "eway_bill.view": "View tenant e-way bill status and details",
    "eway_bill.generate": "Generate an e-way bill for a posted sales invoice",
    "eway_bill.cancel": "Cancel a generated e-way bill",
}

# No approved source defines exact per-role E-Invoice/E-Way Bill
# permissions (§4/§53 open decision — see PROMPT-018-NOTES.md). Resolved
# conservatively: Owner/Manager get full operational control; Salesperson
# gets VIEW ONLY for both — submitting/cancelling a document against a
# government system is a higher-commitment action than any prior
# Sales-document "post"/"confirm", so the established "Salesperson keeps
# everything except the one high-commitment action" pattern is tightened
# here to "view only", not "generate but not cancel". Documented judgment
# call, not a settled business rule.
_ROLE_DEFAULT_PERMISSIONS = {
    "OWNER": [
        "einvoice.view", "einvoice.generate", "einvoice.cancel",
        "eway_bill.view", "eway_bill.generate", "eway_bill.cancel",
    ],
    "MANAGER": [
        "einvoice.view", "einvoice.generate", "einvoice.cancel",
        "eway_bill.view", "eway_bill.generate", "eway_bill.cancel",
    ],
    "SALESPERSON": [
        "einvoice.view", "eway_bill.view",
    ],
}


def upgrade() -> None:
    # --- Tenant-scoped integration configuration (§6/§7) ---
    op.create_table(
        "integration_configuration",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False, server_default="SANDBOX_SIMULATOR"),
        sa.Column("environment", sa.String(20), nullable=False, server_default="SANDBOX"),
        sa.Column("api_base_url", sa.String(500), nullable=True),
        sa.Column("client_id", sa.String(200), nullable=True),
        # Fernet-encrypted JSON blob (client_secret/api_key/etc.) — see
        # app/services/gst_integration/crypto.py. Never plaintext.
        sa.Column("credentials_encrypted", sa.Text, nullable=True),
        sa.Column("timeout_seconds", sa.Integer, nullable=False, server_default="30"),
        sa.Column("max_retry_attempts", sa.Integer, nullable=False, server_default="3"),
        sa.Column("retry_backoff_seconds", sa.Integer, nullable=False, server_default="5"),
        sa.Column("rate_limit_per_minute", sa.Integer, nullable=False, server_default="60"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("einvoice_enabled", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("eway_bill_enabled", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("row_version", sa.BigInteger, nullable=False, server_default="1"),
        sa.UniqueConstraint("tenant_id", name="uq_integration_configuration_tenant"),
        sa.CheckConstraint("environment IN ('SANDBOX','PRODUCTION')", name="ck_integration_configuration_environment"),
        sa.CheckConstraint("timeout_seconds > 0", name="ck_integration_configuration_timeout"),
        sa.CheckConstraint("max_retry_attempts >= 0", name="ck_integration_configuration_max_retry"),
    )

    _status_check = "status IN ('NOT_APPLICABLE','READY','QUEUED','PROCESSING','GENERATED','FAILED','CANCEL_REQUESTED','CANCELLED','STATUS_UNKNOWN')"

    # --- E-Invoice (§13/§15) ---
    op.create_table(
        "einvoice",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("sales_invoice_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sales_invoice.id"), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="READY"),
        sa.Column("applicability_result", postgresql.JSONB, nullable=True),
        sa.Column("irn", sa.String(100), nullable=True),
        sa.Column("ack_number", sa.String(50), nullable=True),
        sa.Column("ack_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("signed_invoice_data", sa.Text, nullable=True),
        sa.Column("signed_qr_data", sa.Text, nullable=True),
        sa.Column("provider", sa.String(50), nullable=True),
        sa.Column("provider_reference", sa.String(100), nullable=True),
        sa.Column("provider_response_code", sa.String(50), nullable=True),
        sa.Column("provider_response_message", sa.String(500), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancellation_reason", sa.String(500), nullable=True),
        sa.Column("last_operation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("row_version", sa.BigInteger, nullable=False, server_default="1"),
        sa.UniqueConstraint("tenant_id", "sales_invoice_id", name="uq_einvoice_invoice"),
        sa.CheckConstraint(_status_check, name="ck_einvoice_status"),
    )
    op.create_index("idx_einvoice_tenant", "einvoice", ["tenant_id"])
    op.create_index("idx_einvoice_invoice", "einvoice", ["sales_invoice_id"])
    op.create_index("idx_einvoice_status", "einvoice", ["status"])

    # --- E-Way Bill (§21) ---
    op.create_table(
        "eway_bill",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("source_type", sa.String(30), nullable=False, server_default="SALES_INVOICE"),
        sa.Column("sales_invoice_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sales_invoice.id"), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="READY"),
        sa.Column("applicability_result", postgresql.JSONB, nullable=True),
        sa.Column("eway_bill_number", sa.String(50), nullable=True),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("transport_mode", sa.String(20), nullable=True),
        sa.Column("vehicle_number", sa.String(20), nullable=True),
        sa.Column("transporter_id", sa.String(20), nullable=True),
        sa.Column("transporter_name", sa.String(200), nullable=True),
        sa.Column("distance_km", sa.Numeric(8, 2), nullable=True),
        sa.Column("provider", sa.String(50), nullable=True),
        sa.Column("provider_reference", sa.String(100), nullable=True),
        sa.Column("provider_response_code", sa.String(50), nullable=True),
        sa.Column("provider_response_message", sa.String(500), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancellation_reason", sa.String(500), nullable=True),
        sa.Column("last_operation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("row_version", sa.BigInteger, nullable=False, server_default="1"),
        sa.UniqueConstraint("tenant_id", "sales_invoice_id", name="uq_eway_bill_invoice"),
        sa.CheckConstraint(_status_check, name="ck_eway_bill_status"),
        sa.CheckConstraint("source_type IN ('SALES_INVOICE')", name="ck_eway_bill_source_type"),
    )
    op.create_index("idx_eway_bill_tenant", "eway_bill", ["tenant_id"])
    op.create_index("idx_eway_bill_invoice", "eway_bill", ["sales_invoice_id"])
    op.create_index("idx_eway_bill_status", "eway_bill", ["status"])

    # --- Integration operation log (§29/§11 concurrency evidence) ---
    op.create_table(
        "integration_operation",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("entity_type", sa.String(20), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("operation_type", sa.String(30), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("attempt_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("provider", sa.String(50), nullable=True),
        sa.Column("provider_reference", sa.String(100), nullable=True),
        sa.Column("response_code", sa.String(50), nullable=True),
        sa.Column("error_code", sa.String(50), nullable=True),
        sa.Column("error_message", sa.String(500), nullable=True),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("row_version", sa.BigInteger, nullable=False, server_default="1"),
        sa.CheckConstraint("entity_type IN ('EINVOICE','EWAY_BILL')", name="ck_integration_operation_entity_type"),
        sa.CheckConstraint("operation_type IN ('GENERATE','CANCEL','STATUS_CHECK')", name="ck_integration_operation_type"),
        sa.CheckConstraint("status IN ('PENDING','IN_PROGRESS','SUCCEEDED','FAILED','UNKNOWN')", name="ck_integration_operation_status"),
    )
    op.create_index("idx_integration_operation_tenant", "integration_operation", ["tenant_id"])
    op.create_index("idx_integration_operation_entity", "integration_operation", ["entity_type", "entity_id"])
    op.create_index("idx_integration_operation_status", "integration_operation", ["status"])

    for table in ("integration_configuration", "einvoice", "eway_bill", "integration_operation"):
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY tenant_isolation_{table} ON "{table}" '
            f"USING (tenant_id::text = current_setting('app.tenant_id', true))"
        )

    connection = op.get_bind()

    permission_ids: dict[str, str] = {}
    for code, description in _GST_INTEGRATION_PERMISSIONS.items():
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
    for table in ("integration_operation", "eway_bill", "einvoice", "integration_configuration"):
        op.execute(f'DROP POLICY IF EXISTS tenant_isolation_{table} ON "{table}"')
    op.drop_table("integration_operation")
    op.drop_table("eway_bill")
    op.drop_table("einvoice")
    op.drop_table("integration_configuration")
    # Permission/role_permission seed rows left in place, matching precedent.
