"""Foundation schema: tenant, user, role, permission, user_role, role_permission, audit_log.

Revision ID: 0001_foundation_schema
Revises:
Create Date: 2026-09-04

Scope note: this migration creates ONLY the platform/security foundation tables
(Table Register domains TENANCY, SECURITY). No business-module tables (customer,
product, sales_invoice, etc.) are created here — those belong to future module
prompts, per PROMPT-001's explicit scope boundary.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_foundation_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')

    op.create_table(
        "tenant",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("business_name", sa.String(200), nullable=False),
        sa.Column("gstin", sa.CHAR(15), nullable=True),
        sa.Column("state_code", sa.CHAR(2), nullable=True),
        sa.Column("financial_year_start_month", sa.SmallInteger, nullable=False, server_default="4"),
        sa.Column("status", sa.String(20), nullable=False, server_default="ACTIVE"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("row_version", sa.BigInteger, nullable=False, server_default="1"),
        sa.CheckConstraint("financial_year_start_month BETWEEN 1 AND 12", name="ck_tenant_fy_month"),
        sa.CheckConstraint("status IN ('ACTIVE','INACTIVE')", name="ck_tenant_status"),
    )

    op.create_table(
        "user",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenant.id"), nullable=True),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("phone", sa.String(20), nullable=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="ACTIVE"),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("row_version", sa.BigInteger, nullable=False, server_default="1"),
        sa.CheckConstraint("status IN ('ACTIVE','INACTIVE','LOCKED')", name="ck_user_status"),
    )
    op.create_index("idx_user_tenant", "user", ["tenant_id"])
    # FKs from tenant -> user (created_by/updated_by) added after user exists, to avoid
    # a create-order cycle between tenant and user.
    op.create_foreign_key("fk_tenant_created_by_user", "tenant", "user", ["created_by"], ["id"])
    op.create_foreign_key("fk_tenant_updated_by_user", "tenant", "user", ["updated_by"], ["id"])
    op.create_foreign_key("fk_user_created_by_user", "user", "user", ["created_by"], ["id"])
    op.create_foreign_key("fk_user_updated_by_user", "user", "user", ["updated_by"], ["id"])

    op.create_table(
        "role",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("name", sa.String(50), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("row_version", sa.BigInteger, nullable=False, server_default="1"),
        sa.UniqueConstraint("tenant_id", "name", name="uq_role_tenant_name"),
    )
    op.create_index("idx_role_tenant", "role", ["tenant_id"])

    op.create_table(
        "permission",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("code", sa.String(100), nullable=False, unique=True),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("row_version", sa.BigInteger, nullable=False, server_default="1"),
    )

    op.create_table(
        "user_role",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("role_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("role.id"), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("row_version", sa.BigInteger, nullable=False, server_default="1"),
        sa.UniqueConstraint("tenant_id", "user_id", "role_id", name="uq_user_role_assignment"),
    )
    op.create_index("idx_user_role_tenant", "user_role", ["tenant_id"])
    op.create_index("idx_user_role_user", "user_role", ["user_id"])
    op.create_index("idx_user_role_role", "user_role", ["role_id"])

    op.create_table(
        "role_permission",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        # tenant_id included per Table Register + Constraints&Indexes despite the
        # Data Dictionary column list omitting it — see app/models/role_permission.py.
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("role_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("role.id"), nullable=False),
        sa.Column("permission_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("permission.id"), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("row_version", sa.BigInteger, nullable=False, server_default="1"),
        sa.UniqueConstraint("role_id", "permission_id", name="uq_role_permission_assignment"),
    )
    op.create_index("idx_role_permission_tenant", "role_permission", ["tenant_id"])

    op.create_table(
        "audit_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("entity_type", sa.String(100), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("before_json", postgresql.JSONB, nullable=True),
        sa.Column("after_json", postgresql.JSONB, nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("ip_address", postgresql.INET, nullable=True),
        sa.Column("device_info", sa.String(1000), nullable=True),
        # Not in the Data Dictionary; added to satisfy PROMPT-001 S10's own
        # requirement that audit records carry a correlation ID "where applicable".
        # Flagged as a deviation requiring a Database Design v3.0 change record.
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index("idx_audit_log_tenant", "audit_log", ["tenant_id"])
    op.create_index("idx_audit_log_entity", "audit_log", ["entity_type", "entity_id"])

    # --- Row-Level Security scaffolding (ERD v2.0 S4; ERD-DEC-01 left open) ---
    # RLS is ENABLED (so policies exist and are ready) but NOT FORCED, so the
    # "mandatory in production" question stays open rather than silently decided.
    for table in ("user", "role", "user_role", "role_permission", "audit_log"):
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY tenant_isolation_{table} ON "{table}" '
            f"USING (tenant_id::text = current_setting('app.tenant_id', true))"
        )

    # --- Audit log immutability: no UPDATE/DELETE at the database role level ---
    op.execute("REVOKE UPDATE, DELETE ON audit_log FROM PUBLIC")


def downgrade() -> None:
    op.execute("GRANT UPDATE, DELETE ON audit_log TO PUBLIC")
    for table in ("audit_log", "role_permission", "user_role", "role", "user"):
        op.execute(f'DROP POLICY IF EXISTS tenant_isolation_{table} ON "{table}"')
    op.drop_table("audit_log")
    op.drop_table("role_permission")
    op.drop_table("user_role")
    op.drop_table("permission")
    op.drop_table("role")
    op.drop_constraint("fk_tenant_created_by_user", "tenant", type_="foreignkey")
    op.drop_constraint("fk_tenant_updated_by_user", "tenant", type_="foreignkey")
    op.drop_table("user")
    op.drop_table("tenant")
