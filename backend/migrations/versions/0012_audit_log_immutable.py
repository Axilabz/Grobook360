"""Audit log immutability: enforce with a trigger, not just REVOKE.

Revision ID: 0012_audit_log_immutability_trigger
Revises: 0011_inventory_foundation
Create Date: 2026-09-05

Migration 0001 tried to make `audit_log` append-only with
`REVOKE UPDATE, DELETE ON audit_log FROM PUBLIC`. That revoke has never
actually enforced anything: the application's own Postgres role
(`saas_app`) is the *owner* of `audit_log` (it created the table via
Alembic), and table ownership in PostgreSQL bypasses the owner's own
GRANT/REVOKE restrictions entirely — an owner can always UPDATE/DELETE its
own table regardless of REVOKE. This was flagged as a known limitation in
PROMPT-001-NOTES.md at the time, and empirically confirmed while building
PROMPT-010's `stock_ledger_entry` table, which needed the same
append-only guarantee and used a BEFORE UPDATE/DELETE trigger instead
(see 0011_inventory_foundation.py) — a trigger fires regardless of table
ownership and is the only mechanism that actually works without moving
the app to a separate non-owning DB role.

This migration applies that same trigger pattern to `audit_log`. The
REVOKE from migration 0001 is left in place for defense-in-depth
documentation (it still matters if a future non-owning role is ever
introduced), but the trigger is what actually enforces immutability now.
"""

from alembic import op

revision = "0012_audit_log_immutable"
down_revision = "0011_inventory_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_audit_log_mutation()
        RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION 'audit_log is append-only: % not permitted', TG_OP;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_audit_log_immutable
        BEFORE UPDATE OR DELETE ON audit_log
        FOR EACH ROW EXECUTE FUNCTION prevent_audit_log_mutation();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_audit_log_immutable ON audit_log")
    op.execute("DROP FUNCTION IF EXISTS prevent_audit_log_mutation()")
