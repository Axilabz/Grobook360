"""Phase 1C: enforce tenant isolation in the database (restricted runtime role + forced RLS).

Revision ID: 0038_rls_enforcement
Revises: 0037_so_cancel_reason
Create Date: 2026-11-02

Why: until now RLS was ENABLED but the runtime role OWNED every table, so
PostgreSQL exempted it from every policy (verified: with one tenant's context
set, `SELECT` on `customer` returned all 5,079 rows of 4,951 tenants). See
database/documentation/rls-status.md and docs/architecture/phase-1c-rls-plan.md.

What this migration does (run as the OWNER/migration role - never as the app):
  1. Requires the roles created by infrastructure/scripts/rls_bootstrap_roles.sql:
       grobook_app     runtime role: non-owner, NOBYPASSRLS, DML grants only
       grobook_definer NOLOGIN owner of the narrow pre-login functions
  2. ENABLE + FORCE row level security on every tenant table and replace the
     policies with explicit USING + WITH CHECK (cross-tenant INSERT/UPDATE is
     rejected, not merely hidden). Missing/empty `app.tenant_id` => zero rows.
     The comparison is a typed uuid equality (index-friendly), not a text cast.
  3. Adds the policies that were missing: tenant, auth_session,
     password_reset_token, idempotency_key.
  4. Creates 6 SECURITY DEFINER functions for the flows that run BEFORE a tenant
     is known (login, sign-up, password reset). Each is owned by the
     column-restricted grobook_definer role, has a fixed search_path, no dynamic
     SQL, validated input, EXECUTE revoked from PUBLIC and granted only to
     grobook_app, and returns identifiers only (never password hashes, reset
     tokens or other personal data).
  5. Grants grobook_app least-privilege DML. audit_log and stock_ledger_entry
     are INSERT/SELECT only (append-only at the permission level, on top of the
     existing triggers); permission is SELECT/INSERT; alembic_version none.

Every table must be classified here. An unclassified table aborts the migration,
so a new table can never silently skip RLS.

Data: no row is read, changed or deleted. No table or column is dropped.
Rollback: downgrade() restores the previous policies, un-forces RLS, removes the
functions, definer policies and app grants. Roles are left in place (drop them
with infrastructure/scripts/rls_rollback_roles.sql if desired).
"""

from alembic import op
import sqlalchemy as sa

revision = "0038_rls_enforcement"
down_revision = "0037_so_cancel_reason"
branch_labels = None
depends_on = None

APP_ROLE = "grobook_app"
DEFINER_ROLE = "grobook_definer"

# Tables that had NO policy before this migration and get one now.
NEWLY_PROTECTED = ("tenant", "auth_session", "password_reset_token", "idempotency_key")
# Reference / system tables: deliberately no RLS (documented in the policy map).
NO_RLS_TABLES = {"permission": ("SELECT", "INSERT"), "alembic_version": ()}
# Append-only at the privilege level.
APPEND_ONLY = ("audit_log", "stock_ledger_entry")

_CTX = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
_OLD_USING = "tenant_id::text = current_setting('app.tenant_id', true)"

SIGNUP_ENDPOINT = "POST /api/v1/auth/sign-up"

# (function signature, body). All: STABLE, SECURITY DEFINER, fixed search_path,
# schema-qualified objects, no dynamic SQL.
_FUNCTIONS = {
    "auth_find_login_tenant(p_phone text)": """
        CREATE FUNCTION public.auth_find_login_tenant(p_phone text)
        RETURNS TABLE(user_id uuid, tenant_id uuid)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $f$
          SELECT u.id, u.tenant_id FROM public."user" u
          WHERE p_phone IS NOT NULL AND length(p_phone) BETWEEN 1 AND 20
            AND u.phone = p_phone AND u.tenant_id IS NOT NULL
            AND (SELECT count(*) FROM public."user" u2 WHERE u2.phone = p_phone) = 1
        $f$""",
    "auth_find_reset_user(p_email text)": """
        CREATE FUNCTION public.auth_find_reset_user(p_email text)
        RETURNS TABLE(user_id uuid, tenant_id uuid)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $f$
          SELECT u.id, u.tenant_id FROM public."user" u
          WHERE p_email IS NOT NULL AND length(p_email) BETWEEN 3 AND 254
            AND u.email = p_email AND u.tenant_id IS NOT NULL
            AND (SELECT count(*) FROM public."user" u2 WHERE u2.email = p_email) = 1
        $f$""",
    "auth_find_reset_token(p_token_hash text)": """
        CREATE FUNCTION public.auth_find_reset_token(p_token_hash text)
        RETURNS TABLE(token_id uuid, user_id uuid, tenant_id uuid)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $f$
          SELECT t.id, t.user_id, t.tenant_id FROM public.password_reset_token t
          WHERE p_token_hash IS NOT NULL AND length(p_token_hash) = 64
            AND t.token_hash = p_token_hash AND t.tenant_id IS NOT NULL
        $f$""",
    "signup_tenant_count()": """
        CREATE FUNCTION public.signup_tenant_count()
        RETURNS bigint
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $f$
          SELECT count(*) FROM public.tenant
        $f$""",
    "signup_phone_in_use(p_phone text)": """
        CREATE FUNCTION public.signup_phone_in_use(p_phone text)
        RETURNS boolean
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $f$
          SELECT p_phone IS NOT NULL AND length(p_phone) BETWEEN 1 AND 20
             AND EXISTS (SELECT 1 FROM public."user" u WHERE u.phone = p_phone)
        $f$""",
    "signup_idempotency_lookup(p_key text)": f"""
        CREATE FUNCTION public.signup_idempotency_lookup(p_key text)
        RETURNS TABLE(request_fingerprint text, response_status integer, response_body jsonb)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $f$
          SELECT k.request_fingerprint::text, k.response_status, k.response_body
          FROM public.idempotency_key k
          WHERE p_key IS NOT NULL AND length(p_key) BETWEEN 1 AND 255
            AND k.idempotency_key = p_key AND k.endpoint = '{SIGNUP_ENDPOINT}'
          LIMIT 1
        $f$""",
}

# Column-restricted read access for the definer role (and the RLS policy that
# lets ONLY that role read them across tenants).
_DEFINER_READS = {
    '"user"': "id, tenant_id, phone, email",
    "password_reset_token": "id, user_id, tenant_id, token_hash",
    "tenant": "id",
    "idempotency_key": "idempotency_key, endpoint, request_fingerprint, response_status, response_body",
}


def _require_roles(bind) -> None:
    present = {r[0] for r in bind.execute(sa.text("SELECT rolname FROM pg_roles WHERE rolname IN (:a, :d)"), {"a": APP_ROLE, "d": DEFINER_ROLE})}
    missing = {APP_ROLE, DEFINER_ROLE} - present
    if missing:
        raise RuntimeError(
            f"Missing database role(s) {sorted(missing)}. Run infrastructure/scripts/rls_bootstrap_roles.sql "
            "as a role allowed to create roles BEFORE this migration (see docs/architecture/phase-1c-rls-plan.md)."
        )
    attrs = bind.execute(
        sa.text("SELECT rolname, rolsuper, rolbypassrls, rolcreaterole, rolcreatedb FROM pg_roles WHERE rolname IN (:a, :d)"),
        {"a": APP_ROLE, "d": DEFINER_ROLE},
    ).all()
    for name, sup, byp, crr, crd in attrs:
        if sup or byp or crr or crd:
            raise RuntimeError(f"Role {name} must be NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOCREATEDB")


def _classify(bind) -> tuple[list[str], list[str]]:
    """Return (tenant_id tables, id-keyed tables). Abort on any unclassified table."""
    tables = [r[0] for r in bind.execute(sa.text("SELECT relname FROM pg_class WHERE relnamespace = 'public'::regnamespace AND relkind = 'r' ORDER BY 1"))]
    with_tenant_id = {
        r[0] for r in bind.execute(sa.text("SELECT table_name FROM information_schema.columns WHERE table_schema='public' AND column_name='tenant_id'"))
    }
    tenant_tables, id_tables = [], []
    for t in tables:
        if t in NO_RLS_TABLES:
            continue
        if t == "tenant":
            id_tables.append(t)
        elif t in with_tenant_id:
            tenant_tables.append(t)
        else:
            raise RuntimeError(f"Table {t!r} has no tenant_id and is not classified in migration 0038; classify it before migrating.")
    return tenant_tables, id_tables


def upgrade() -> None:
    bind = op.get_bind()
    _require_roles(bind)
    tenant_tables, id_tables = _classify(bind)

    # --- 1. policies + FORCE -------------------------------------------------
    for t in tenant_tables:
        op.execute(f'ALTER TABLE "{t}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{t}" FORCE ROW LEVEL SECURITY')
        op.execute(f'DROP POLICY IF EXISTS tenant_isolation_{t} ON "{t}"')
        op.execute(
            f'CREATE POLICY tenant_isolation_{t} ON "{t}" FOR ALL '
            f"USING (tenant_id = {_CTX}) WITH CHECK (tenant_id = {_CTX})"
        )
    for t in id_tables:
        op.execute(f'ALTER TABLE "{t}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{t}" FORCE ROW LEVEL SECURITY')
        op.execute(f'DROP POLICY IF EXISTS tenant_isolation_{t} ON "{t}"')
        op.execute(f'CREATE POLICY tenant_isolation_{t} ON "{t}" FOR ALL USING (id = {_CTX}) WITH CHECK (id = {_CTX})')

    # --- 2. definer role: column-level reads + role-scoped read policy ---------
    op.execute(f"GRANT USAGE ON SCHEMA public TO {DEFINER_ROLE}")
    for table, cols in _DEFINER_READS.items():
        bare = table.strip('"')
        op.execute(f"GRANT SELECT ({cols}) ON {table} TO {DEFINER_ROLE}")
        op.execute(f"DROP POLICY IF EXISTS pre_auth_definer_select ON {table}")
        # `TO role` also matches every MEMBER of the role (the migration/owner role is one, so it
        # can hand function ownership over). current_user is the role actually executing: it is the
        # definer only inside the SECURITY DEFINER functions, never for a member's own session.
        op.execute(
            f"CREATE POLICY pre_auth_definer_select ON {table} FOR SELECT TO {DEFINER_ROLE} "
            f"USING (current_user = '{DEFINER_ROLE}')"
        )

    # --- 3. functions (created by the owner, then handed to the definer role) --
    op.execute(f"GRANT CREATE ON SCHEMA public TO {DEFINER_ROLE}")
    for signature, ddl in _FUNCTIONS.items():
        name = signature.split("(")[0]
        op.execute(f"DROP FUNCTION IF EXISTS public.{signature}")
        op.execute(ddl)
        op.execute(f"ALTER FUNCTION public.{signature} OWNER TO {DEFINER_ROLE}")
        op.execute(f"REVOKE ALL ON FUNCTION public.{signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION public.{signature} TO {APP_ROLE}")
    op.execute(f"REVOKE CREATE ON SCHEMA public FROM {DEFINER_ROLE}")

    # --- 4. runtime role grants (least privilege) --------------------------------
    op.execute(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}")
    for t in tenant_tables + id_tables:
        privs = "SELECT, INSERT" if t in APPEND_ONLY else "SELECT, INSERT, UPDATE, DELETE"
        op.execute(f'GRANT {privs} ON "{t}" TO {APP_ROLE}')
    for t, privs in NO_RLS_TABLES.items():
        if privs:
            op.execute(f'GRANT {", ".join(privs)} ON "{t}" TO {APP_ROLE}')


def downgrade() -> None:
    bind = op.get_bind()
    tenant_tables, id_tables = _classify(bind)

    for signature in _FUNCTIONS:
        op.execute(f"DROP FUNCTION IF EXISTS public.{signature}")
    for table in _DEFINER_READS:
        op.execute(f"DROP POLICY IF EXISTS pre_auth_definer_select ON {table}")
        op.execute(f"REVOKE SELECT ON {table} FROM {DEFINER_ROLE}")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {DEFINER_ROLE}")

    for t in tenant_tables + id_tables:
        op.execute(f'DROP POLICY IF EXISTS tenant_isolation_{t} ON "{t}"')
        op.execute(f'ALTER TABLE "{t}" NO FORCE ROW LEVEL SECURITY')
        if t in NEWLY_PROTECTED:
            op.execute(f'ALTER TABLE "{t}" DISABLE ROW LEVEL SECURITY')
        else:
            op.execute(f'CREATE POLICY tenant_isolation_{t} ON "{t}" USING ({_OLD_USING})')

    op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {APP_ROLE}")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {APP_ROLE}")
