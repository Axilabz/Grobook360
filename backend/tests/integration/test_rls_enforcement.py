"""Phase 1C: database-enforced tenant isolation, exercised through the REAL
restricted runtime role (the role in DATABASE_URL - grobook_app).

These tests are meaningful only when the API connects as a non-owner role with
migration 0038 applied; `test_runtime_role_is_restricted` fails loudly if the
suite is pointed at an owner/superuser by mistake, instead of passing vacuously.

Layers:
  * catalogue checks   - every table is classified, FORCEd, has USING + WITH CHECK
  * behaviour matrix   - cross-tenant SELECT / INSERT / UPDATE / DELETE per table
  * privilege checks   - the role cannot weaken RLS, change DDL, or touch audit rows
  * pre-login functions- narrow SECURITY DEFINER surface
  * pool safety        - tenant context never survives a transaction / leaks across requests
"""

import asyncio
import json
import uuid
from contextlib import asynccontextmanager

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

from app.db.session import AsyncSessionLocal, _connect_args, engine
from app.db.tenant_context import set_tenant_context
from tests.integration.test_tenant_isolation import _reset_state, two_orgs  # noqa: F401  (fixtures)
from tests.integration.test_customers import _valid_customer_payload
from tests.integration.test_suppliers import _valid_supplier_payload

NO_RLS_TABLES = {"alembic_version", "permission"}
APPEND_ONLY = ("audit_log", "stock_ledger_entry")
FUNCTIONS = {
    "auth_find_login_tenant": "user_id,tenant_id",
    "auth_find_reset_user": "user_id,tenant_id",
    "auth_find_reset_token": "token_id,user_id,tenant_id",
}


@asynccontextmanager
async def scoped(tenant_id=None):
    """A session on the runtime role; always rolled back, never committed."""
    async with AsyncSessionLocal() as session:
        try:
            if tenant_id is not None:
                await set_tenant_context(session, tenant_id)
            yield session
        finally:
            await session.rollback()


async def _all(session, sql, **params):
    return (await session.execute(text(sql), params)).all()


async def _scalar(session, sql, **params):
    return (await session.execute(text(sql), params)).scalar_one()


async def _tenant_tables():
    """(table, key_column): 'tenant' is keyed by id, everything else by tenant_id."""
    async with scoped() as s:
        rows = await _all(
            s,
            """SELECT c.relname, EXISTS (SELECT 1 FROM information_schema.columns i
                        WHERE i.table_schema='public' AND i.table_name=c.relname AND i.column_name='tenant_id')
               FROM pg_class c WHERE c.relnamespace='public'::regnamespace AND c.relkind='r'
               ORDER BY 1""",
        )
    return [(name, "tenant_id" if has_tid else "id") for name, has_tid in rows if name not in NO_RLS_TABLES]


async def _expect_denied(sql: str, **params) -> str:
    """Run `sql` as the runtime role; it must raise. Returns the error text."""
    async with scoped() as s:
        with pytest.raises(DBAPIError) as exc:
            await s.execute(text(sql), params)
    return str(exc.value.orig)


# --- catalogue ---------------------------------------------------------------


async def test_runtime_role_is_restricted():
    async with scoped() as s:
        sup, byp, crr, crd = (await _all(s, "SELECT rolsuper, rolbypassrls, rolcreaterole, rolcreatedb FROM pg_roles WHERE rolname = current_user"))[0]
        assert not (sup or byp or crr or crd), "runtime role must be NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOCREATEDB"
        owned = await _scalar(
            s, "SELECT count(*) FROM pg_class WHERE relnamespace='public'::regnamespace AND relkind IN ('r','S','v') AND pg_has_role(current_user, relowner, 'USAGE')"
        )
        assert owned == 0, "runtime role owns (or is a member of the owner of) database objects: RLS would be bypassed"


async def test_every_table_is_classified_forced_and_has_using_and_with_check():
    tables = await _tenant_tables()
    assert len(tables) >= 55
    async with scoped() as s:
        for name, _ in tables:
            rls, force = (await _all(s, "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE oid = to_regclass(:t)", t=f'public."{name}"'))[0]
            assert rls and force, f"{name}: RLS must be ENABLED and FORCED"
            pol = await _all(s, "SELECT cmd, qual, with_check FROM pg_policies WHERE schemaname='public' AND tablename=:t", t=name)
            assert pol, f"{name}: no policy"
            assert any(cmd == "ALL" and "app.tenant_id" in (q or "") and "app.tenant_id" in (w or "") for cmd, q, w in pol), (
                f"{name}: needs a FOR ALL policy with both USING and WITH CHECK on app.tenant_id"
            )
        # documented exceptions: `permission` is global reference data the runtime role must READ, so RLS must be
        # off for it (Supabase's rls_auto_enable trigger would otherwise leave it enabled with no policy = invisible).
        assert not await _scalar(s, "SELECT relrowsecurity FROM pg_class WHERE oid = to_regclass('public.permission')")
        assert await _scalar(s, "SELECT count(*) FROM permission") >= 1, "runtime role cannot read the permission table"
        # alembic_version: no privilege at all for the runtime role (its RLS flag is irrelevant)
        assert not await _scalar(s, "SELECT has_table_privilege(current_user, 'alembic_version', 'SELECT')")
        for priv in ("UPDATE", "DELETE", "TRUNCATE"):
            assert not await _scalar(s, "SELECT has_table_privilege(current_user, 'permission', :p)", p=priv)


async def test_policies_use_typed_uuid_comparison_and_fail_closed():
    async with scoped() as s:
        rows = await _all(s, "SELECT tablename, qual FROM pg_policies WHERE schemaname='public' AND policyname LIKE 'tenant_isolation_%'")
    assert rows
    for table, qual in rows:
        assert "NULLIF" in qual.upper() and "uuid" in qual.lower(), f"{table}: policy must compare typed uuid and treat '' as no tenant"


# --- append-only ----------------------------------------------------------------


async def test_append_only_tables_cannot_be_changed_by_runtime_role():
    async with scoped() as s:
        for t in APPEND_ONLY:
            assert await _scalar(s, "SELECT has_table_privilege(current_user, :t, 'SELECT')", t=t)
            assert await _scalar(s, "SELECT has_table_privilege(current_user, :t, 'INSERT')", t=t)
            for p in ("UPDATE", "DELETE", "TRUNCATE"):
                assert not await _scalar(s, "SELECT has_table_privilege(current_user, :t, :p)", t=t, p=p), f"{t}: {p} must be denied"
    assert "permission denied" in await _expect_denied("UPDATE audit_log SET action = action")
    assert "permission denied" in await _expect_denied("DELETE FROM stock_ledger_entry")


# --- behaviour matrix --------------------------------------------------------------


async def test_without_tenant_context_every_table_is_empty():
    async with scoped() as s:  # no set_tenant_context at all
        for name, _ in await _tenant_tables():
            assert await _scalar(s, f'SELECT count(*) FROM "{name}"') == 0, f"{name} leaks rows without tenant context"
    async with scoped(None) as s:
        await s.execute(text("SELECT set_config('app.tenant_id', 'not-a-uuid', true)"))
        with pytest.raises(DBAPIError):  # malformed context fails closed (error, never rows)
            await s.execute(text('SELECT count(*) FROM "customer"'))


async def test_cross_tenant_select_update_delete_matrix(two_orgs):
    a, b, org_a, org_b = two_orgs
    A, B = uuid.UUID(org_a["tenant_id"]), uuid.UUID(org_b["tenant_id"])
    assert (await a.post("/api/v1/customers", json=_valid_customer_payload())).status_code == 201
    assert (await b.post("/api/v1/suppliers", json=_valid_supplier_payload())).status_code == 201

    populated = 0
    for name, key in await _tenant_tables():
        for me, other in ((A, B), (B, A)):
            async with scoped(me) as s:
                assert await _scalar(s, f'SELECT count(*) FROM "{name}" WHERE {key} <> :me', me=me) == 0, f"{name}: SELECT leaks other tenants"
                assert await _scalar(s, f'SELECT count(*) FROM "{name}" WHERE {key} = :o', o=other) == 0, f"{name}: other tenant visible"
                if await _scalar(s, f'SELECT count(*) FROM "{name}"'):
                    populated += 1
            async with scoped(me) as s:
                upd = await s.execute(text(f'UPDATE "{name}" SET {key} = {key} WHERE {key} = :o'), {"o": other}) if name not in APPEND_ONLY else None
                assert upd is None or upd.rowcount == 0, f"{name}: UPDATE reached another tenant"
            if name not in APPEND_ONLY:
                async with scoped(me) as s:
                    assert (await s.execute(text(f'DELETE FROM "{name}" WHERE {key} = :o'), {"o": other})).rowcount == 0, f"{name}: DELETE reached another tenant"
    assert populated >= 8, f"matrix exercised only {populated} populated tables; seed more data"


async def test_cross_tenant_insert_and_update_are_rejected_by_with_check(two_orgs):
    a, b, org_a, org_b = two_orgs
    A, B = uuid.UUID(org_a["tenant_id"]), uuid.UUID(org_b["tenant_id"])
    assert (await a.post("/api/v1/customers", json=_valid_customer_payload())).status_code == 201

    checked = 0
    for name, key in await _tenant_tables():
        if key != "tenant_id":
            continue
        async with scoped(A) as s:
            if not await _scalar(s, f'SELECT count(*) FROM "{name}"'):
                continue
            has_id = await _scalar(s, "SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name=:t AND column_name='id')", t=name)
        override = "jsonb_build_object('tenant_id', CAST(:b AS text))" + (" || jsonb_build_object('id', gen_random_uuid()::text)" if has_id else "")
        clone = (
            f'INSERT INTO "{name}" SELECT (jsonb_populate_record(NULL::"{name}", to_jsonb(s) || {override})).* '
            f'FROM "{name}" s WHERE s.tenant_id = :a LIMIT 1'
        )
        async with scoped(A) as s:
            with pytest.raises(DBAPIError) as exc:
                await s.execute(text(clone), {"a": A, "b": str(B)})
            assert "row-level security" in str(exc.value.orig), f"{name}: cross-tenant INSERT not rejected by policy: {exc.value.orig}"
        if name not in APPEND_ONLY:
            async with scoped(A) as s:
                with pytest.raises(DBAPIError) as exc:
                    await s.execute(text(f'UPDATE "{name}" SET tenant_id = :b WHERE tenant_id = :a'), {"a": A, "b": B})
                assert "row-level security" in str(exc.value.orig), f"{name}: moving a row to another tenant not rejected"
        checked += 1
    assert checked >= 6, f"only {checked} populated tables exercised"


async def test_tenant_table_cannot_be_read_or_forged_across_tenants(two_orgs):
    _, _, org_a, org_b = two_orgs
    A, B = uuid.UUID(org_a["tenant_id"]), uuid.UUID(org_b["tenant_id"])
    async with scoped(A) as s:
        assert [r[0] for r in await _all(s, "SELECT id FROM tenant")] == [A]
    async with scoped(A) as s:
        with pytest.raises(DBAPIError) as exc:
            await s.execute(text("INSERT INTO tenant (id, tenant_code, business_name, status, financial_year_start_month, row_version) VALUES (:id, 'TEN-X', 'x', 'ACTIVE', 4, 1)"), {"id": uuid.uuid4()})
        assert "row-level security" in str(exc.value.orig)


async def test_row_security_off_does_not_expose_other_tenants(two_orgs):
    _, _, org_a, _ = two_orgs
    async with scoped(uuid.UUID(org_a["tenant_id"])) as s:
        await s.execute(text("SET LOCAL row_security = off"))
        try:
            rows = await _all(s, 'SELECT DISTINCT tenant_id FROM "customer"')
        except DBAPIError:
            return  # PostgreSQL refuses the query outright for a non-bypass role: also safe
        assert {r[0] for r in rows} <= {uuid.UUID(org_a["tenant_id"])}


# --- privilege escalation -------------------------------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        'ALTER TABLE "customer" DISABLE ROW LEVEL SECURITY',
        'ALTER TABLE "customer" NO FORCE ROW LEVEL SECURITY',
        'DROP POLICY tenant_isolation_customer ON "customer"',
        'CREATE POLICY open_all ON "customer" USING (true)',
        'TRUNCATE "customer"',
        'DROP TABLE "customer"',
        'ALTER TABLE "customer" ADD COLUMN evil int',
        "CREATE TABLE public.evil_table (x int)",
        "CREATE FUNCTION public.evil() RETURNS int LANGUAGE sql AS 'SELECT 1'",
        "ALTER ROLE CURRENT_USER BYPASSRLS",
        "CREATE ROLE evil_role",
        "SELECT * FROM alembic_version",
        "DROP FUNCTION public.auth_find_login_tenant(text)",
        "CREATE OR REPLACE FUNCTION public.auth_find_login_tenant(p_phone text) RETURNS TABLE(user_id uuid, tenant_id uuid) LANGUAGE sql AS 'SELECT id, tenant_id FROM public.\"user\"'",
    ],
)
async def test_runtime_role_cannot_weaken_security_or_change_schema(sql):
    await _expect_denied(sql)


async def test_runtime_role_cannot_grant_privileges_to_public():
    # PostgreSQL only WARNS ("no privileges were granted") for a non-owner; the
    # real check is that nothing changed.
    async with scoped() as s:
        before = await _scalar(s, "SELECT relacl::text FROM pg_class WHERE oid = to_regclass('public.\"customer\"')")
        await s.execute(text('GRANT ALL ON "customer" TO PUBLIC'))
        after = await _scalar(s, "SELECT relacl::text FROM pg_class WHERE oid = to_regclass('public.\"customer\"')")
        assert before == after
        assert not any(part.startswith("=") for part in (after or "").strip("{}").split(","))


async def test_runtime_role_cannot_assume_the_owner_role():
    async with scoped() as s:
        owner = await _scalar(s, "SELECT pg_get_userbyid(relowner) FROM pg_class WHERE oid = to_regclass('public.\"customer\"')")
    err = await _expect_denied(f'SET ROLE "{owner}"')
    assert "permission denied" in err or "must be member" in err or "not permitted" in err


# --- pre-login SECURITY DEFINER surface ----------------------------------------------------


async def test_definer_functions_are_locked_down():
    async with scoped() as s:
        names = [
            r[0]
            for r in await _all(
                s,
                "SELECT proname FROM pg_proc WHERE pronamespace='public'::regnamespace AND prosecdef ORDER BY 1",
            )
        ]
        # `rls_auto_enable` is a Supabase-managed event-trigger function (not ours); nothing else may be SECURITY DEFINER.
        names = [n for n in names if n != "rls_auto_enable"]
        assert set(names) == {
            "auth_find_login_tenant", "auth_find_reset_user", "auth_find_reset_token",
            "signup_tenant_count", "signup_phone_in_use", "signup_idempotency_lookup",
        }, f"unexpected SECURITY DEFINER set: {names}"
        for row in await _all(
            s,
            """SELECT p.proname, pg_get_userbyid(p.proowner), p.proconfig, p.proacl::text, l.lanname,
                      has_function_privilege(current_user, p.oid, 'EXECUTE')
               FROM pg_proc p JOIN pg_language l ON l.oid = p.prolang
               WHERE p.pronamespace='public'::regnamespace AND p.prosecdef AND p.proname <> 'rls_auto_enable'""",
        ):
            name, owner, config, acl, lang, can_exec = row
            assert owner == "grobook_definer", f"{name} must be owned by the column-restricted definer role, not {owner}"
            assert config and any("search_path=pg_catalog, pg_temp" in c for c in config), f"{name}: fixed search_path required"
            assert lang == "sql", f"{name}: no procedural/dynamic SQL"
            assert not any(part.startswith("=") for part in (acl or "").strip("{}").split(",")), f"{name}: EXECUTE must be revoked from PUBLIC (acl={acl})"
            assert can_exec, f"{name}: runtime role must be able to execute"


async def test_definer_role_can_read_only_identifier_columns():
    async with scoped() as s:
        # information_schema.column_privileges hides other roles' grants from a
        # non-owner, so ask the catalogue directly, column by column.
        rows = await _all(
            s,
            """SELECT c.table_name, c.column_name FROM information_schema.columns c
               WHERE c.table_schema = 'public'
                 AND has_column_privilege('grobook_definer', format('public.%I', c.table_name), c.column_name, 'SELECT')""",
        )
        writes = await _all(
            s,
            """SELECT c.relname FROM pg_class c WHERE c.relnamespace='public'::regnamespace AND c.relkind='r'
                 AND (has_table_privilege('grobook_definer', c.oid, 'INSERT') OR has_table_privilege('grobook_definer', c.oid, 'UPDATE')
                      OR has_table_privilege('grobook_definer', c.oid, 'DELETE'))""",
        )
    assert writes == [], "the definer role must be read-only"
    granted = {(t, c) for t, c in rows}
    assert {t for t, _ in granted} == {"user", "password_reset_token", "tenant", "idempotency_key"}
    forbidden = {("user", "password_hash"), ("password_reset_token", "request_ip"), ("user", "name")}
    assert not (granted & forbidden)
    assert {c for t, c in granted if t == "user"} == {"id", "tenant_id", "phone", "email"}
    assert {c for t, c in granted if t == "password_reset_token"} == {"id", "user_id", "tenant_id", "token_hash"}
    assert {c for t, c in granted if t == "tenant"} == {"id"}


async def test_login_lookup_function_returns_identifiers_only_and_resists_abuse(two_orgs):
    _, _, org_a, org_b = two_orgs
    A = uuid.UUID(org_a["tenant_id"])
    async with scoped(A) as s:
        phone = await _scalar(s, 'SELECT phone FROM "user" WHERE id = :u', u=uuid.UUID(org_a["owner_user_id"]))
    async with scoped() as s:  # NO tenant context - the function is what makes this work
        row = (await s.execute(text("SELECT * FROM public.auth_find_login_tenant(:p)"), {"p": phone})).first()
        assert row is not None and list(row._mapping.keys()) == ["user_id", "tenant_id"]
        assert row.tenant_id == A and str(row.user_id) == org_a["owner_user_id"]
        for bad in ("0000000000", "' OR '1'='1", "x" * 21, "", "%", "9%"):
            assert (await s.execute(text("SELECT * FROM public.auth_find_login_tenant(:p)"), {"p": bad})).first() is None
        assert (await s.execute(text("SELECT * FROM public.auth_find_login_tenant(NULL)"))).first() is None
        assert await _scalar(s, 'SELECT count(*) FROM "user"') == 0  # the function is not a table-wide hole
        assert await _scalar(s, "SELECT public.signup_phone_in_use(:p)", p=phone) is True
        assert await _scalar(s, "SELECT public.signup_phone_in_use(:p)", p="0000000000") is False
        assert await _scalar(s, "SELECT public.signup_tenant_count()") >= 2


async def test_reset_token_lookup_never_returns_the_token_or_hash(two_orgs):
    async with scoped() as s:
        assert (await s.execute(text("SELECT * FROM public.auth_find_reset_token(:h)"), {"h": "a" * 64})).first() is None
        assert (await s.execute(text("SELECT * FROM public.auth_find_reset_token(:h)"), {"h": "short"})).first() is None
        cols = (await s.execute(text("SELECT * FROM public.auth_find_reset_token(:h)"), {"h": "a" * 64})).keys()
        assert list(cols) == ["token_id", "user_id", "tenant_id"]


async def test_signup_idempotency_function_is_limited_to_the_signup_endpoint(two_orgs):
    a, b, org_a, _ = two_orgs
    A = uuid.UUID(org_a["tenant_id"])
    key = f"phase1c-{uuid.uuid4()}"
    async with scoped(A) as s:
        await s.execute(
            text("INSERT INTO idempotency_key (id, tenant_id, idempotency_key, endpoint, request_fingerprint, response_status, response_body, created_at) "
                 "VALUES (gen_random_uuid(), :t, :k, 'POST /api/v1/customers', 'f', 201, CAST(:b AS jsonb), now())"),
            {"t": A, "k": key, "b": json.dumps({"secret": "x"})},
        )
        await s.flush()
        # other endpoints' stored responses are not reachable through the sign-up lookup
        assert (await s.execute(text("SELECT * FROM public.signup_idempotency_lookup(:k)"), {"k": key})).first() is None


# --- pool safety ---------------------------------------------------------------------------------


def _pooled_engine(size: int):
    return create_async_engine(engine.url, pool_size=size, max_overflow=0, connect_args=_connect_args)


async def test_tenant_context_does_not_survive_the_transaction_on_a_reused_connection(two_orgs):
    _, _, org_a, _ = two_orgs
    A = uuid.UUID(org_a["tenant_id"])
    eng = _pooled_engine(1)  # one physical connection => the next session MUST reuse it
    try:
        from sqlalchemy.ext.asyncio import async_sessionmaker

        maker = async_sessionmaker(eng, expire_on_commit=False)
        async with maker() as first:
            await set_tenant_context(first, A)
            assert await _scalar(first, 'SELECT count(*) FROM "user"') >= 1
            await first.commit()
            # same session, NEW transaction: context is re-applied from session.info, not from the connection
            assert await _scalar(first, "SELECT current_setting('app.tenant_id', true)") == str(A)
            await first.rollback()
        async with maker() as second:  # reuses the same pooled connection, no context set
            assert await _scalar(second, "SELECT coalesce(current_setting('app.tenant_id', true), '')") == ""
            assert await _scalar(second, 'SELECT count(*) FROM "user"') == 0
            assert await _scalar(second, 'SELECT count(*) FROM "customer"') == 0
    finally:
        await eng.dispose()


async def test_concurrent_requests_for_different_tenants_never_see_each_other(two_orgs):
    a, b, org_a, org_b = two_orgs
    A, B = uuid.UUID(org_a["tenant_id"]), uuid.UUID(org_b["tenant_id"])
    eng = _pooled_engine(4)
    from sqlalchemy.ext.asyncio import async_sessionmaker

    maker = async_sessionmaker(eng, expire_on_commit=False)

    async def worker(i: int) -> set:
        me = A if i % 2 == 0 else B
        async with maker() as s:
            await set_tenant_context(s, me)
            await s.execute(text("SELECT pg_sleep(:d)"), {"d": 0.01 * (i % 5)})
            seen = {r[0] for r in await _all(s, 'SELECT DISTINCT tenant_id FROM "user"')}
            await s.rollback()
        assert seen == {me}, f"worker {i} saw {seen}"
        return seen

    try:
        await asyncio.gather(*[worker(i) for i in range(60)])
    finally:
        await eng.dispose()


# --- every tenant table, including tables that are empty ---------------------------------------------------------
#
# The matrix above can only exercise tables that happen to hold rows. This test
# makes EVERY tenant table behavioural by seeding two minimal rows inside a
# transaction on the OWNER connection that is always rolled back: constraints
# that would stop a skeleton row (NOT NULL / CHECK / FOREIGN KEY) are dropped
# and the table briefly un-FORCEd - all transactional DDL, nothing persists.
# PostgreSQL evaluates the RLS WITH CHECK before those constraints, so the
# policy is what is under test, not the constraints.
#
# Queries then run with FORCE restored, as the runtime role when the owner may
# `SET ROLE` to it, otherwise as the owner itself (FORCE binds the owner too);
# the mode used per table is recorded and printed.


def _owner_engine():
    from app.core.config import get_settings

    url = get_settings().migration_database_url
    if not url:
        pytest.skip("MIGRATION_DATABASE_URL (owner role) is required for the synthetic per-table matrix")
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return create_async_engine(url, connect_args=_connect_args)


async def _seed_skeleton_rows(conn, table: str, key: str, tenants: tuple) -> None:
    await conn.execute(text(f'ALTER TABLE "{table}" NO FORCE ROW LEVEL SECURITY'))
    cons = (
        await conn.execute(
            text("SELECT conname FROM pg_constraint WHERE conrelid = to_regclass(:t) AND contype IN ('f','c')"),
            {"t": f'public."{table}"'},
        )
    ).scalars().all()
    for c in cons:
        await conn.execute(text(f'ALTER TABLE "{table}" DROP CONSTRAINT "{c}"'))
    notnull = (
        await conn.execute(
            text(
                """SELECT a.attname FROM pg_attribute a WHERE a.attrelid = to_regclass(:t) AND a.attnum > 0 AND NOT a.attisdropped
                   AND a.attnotnull AND a.attname <> :k AND a.attname <> 'id'
                   AND NOT EXISTS (SELECT 1 FROM pg_index i WHERE i.indrelid = a.attrelid AND i.indisprimary AND a.attnum = ANY (i.indkey))"""
            ),
            {"t": f'public."{table}"', "k": key},
        )
    ).scalars().all()
    for col in notnull:
        await conn.execute(text(f'ALTER TABLE "{table}" ALTER COLUMN "{col}" DROP NOT NULL'))
    has_id = (
        await conn.execute(
            text("SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name=:t AND column_name='id')"),
            {"t": table},
        )
    ).scalar_one()
    for tid in tenants:
        cols, vals = (f'"{key}", "id"', ":tid, gen_random_uuid()") if has_id and key != "id" else (f'"{key}"', ":tid")
        await conn.execute(text(f'INSERT INTO "{table}" ({cols}) VALUES ({vals})'), {"tid": tid})
    await conn.execute(text(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY'))


async def _in_savepoint(conn, sql: str, params: dict) -> str:
    """Run one statement in a savepoint. Returns 'rls', 'privilege', 'constraint' or 'ok'."""
    sp = await conn.begin_nested()
    try:
        await conn.execute(text(sql), params)
    except DBAPIError as exc:
        await sp.rollback()
        msg = str(exc.orig)
        if "row-level security" in msg:
            return "rls"
        if "permission denied" in msg:
            return "privilege"
        return "constraint"
    await sp.rollback()
    return "ok"


async def test_every_tenant_table_enforces_cross_tenant_writes_including_empty_tables(two_orgs):
    _, _, org_a, org_b = two_orgs
    A, B = uuid.UUID(org_a["tenant_id"]), uuid.UUID(org_b["tenant_id"])
    owner = _owner_engine()
    modes: dict[str, str] = {}
    try:
        tables = await _tenant_tables()
        assert len(tables) >= 55
        for table, key in tables:
            async with owner.connect() as conn:
                trans = await conn.begin()
                try:
                    if key == "tenant_id":
                        await _seed_skeleton_rows(conn, table, key, (A, B))
                    # run as the real runtime role when possible; else as the owner (still bound by FORCE)
                    sp = await conn.begin_nested()
                    try:
                        await conn.execute(text("SET LOCAL ROLE grobook_app"))
                        modes[table] = "grobook_app"
                        await sp.commit()
                    except DBAPIError:
                        await sp.rollback()
                        modes[table] = "owner-under-FORCE"
                    append_only = table in APPEND_ONLY

                    for me, other in ((A, B), (B, A)):
                        await conn.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(me)})
                        seen = (await conn.execute(text(f'SELECT DISTINCT "{key}" FROM "{table}"'))).scalars().all()
                        assert seen and set(seen) <= {me}, f"{table}: ctx {me} saw {seen}"
                        if key == "tenant_id":
                            assert len(seen) == 1
                            if not append_only:
                                upd = await conn.execute(text(f'UPDATE "{table}" SET "{key}" = "{key}" WHERE "{key}" = :o'), {"o": other})
                                assert upd.rowcount == 0, f"{table}: UPDATE reached another tenant"
                                dele = await conn.execute(text(f'DELETE FROM "{table}" WHERE "{key}" = :o'), {"o": other})
                                assert dele.rowcount == 0, f"{table}: DELETE reached another tenant"
                            assert await _in_savepoint(conn, f'INSERT INTO "{table}" ("{key}") VALUES (:o)', {"o": other}) == "rls", (
                                f"{table}: cross-tenant INSERT was not refused by the policy"
                            )
                            moved = await _in_savepoint(conn, f'UPDATE "{table}" SET "{key}" = :o WHERE "{key}" = :me', {"o": other, "me": me})
                            if append_only:  # refused by privilege (runtime role) or by the immutability trigger / policy (owner)
                                assert moved in ("privilege", "constraint", "rls"), f"{table}: append-only row was changed"
                            else:
                                assert moved == "rls", f"{table}: row-move gave {moved}"
                            own = await _in_savepoint(conn, f'INSERT INTO "{table}" ("{key}") VALUES (:me)', {"me": me})
                            assert own != "rls", f"{table}: own-tenant INSERT refused by the policy"
                        else:  # the tenant table itself, keyed by id
                            assert await _in_savepoint(conn, f'UPDATE "{table}" SET id = :o WHERE id = :me', {"o": other, "me": me}) == "rls"
                    await conn.execute(text("SELECT set_config('app.tenant_id', '', true)"))
                    assert (await conn.execute(text(f'SELECT count(*) FROM "{table}"'))).scalar_one() == 0, f"{table}: rows visible without context"
                finally:
                    await trans.rollback()
        print("per-table matrix modes:", {m: sum(1 for v in modes.values() if v == m) for m in set(modes.values())}, "tables:", len(tables))
    finally:
        await owner.dispose()


async def test_supabase_api_roles_have_no_access_to_application_objects():
    """Supabase's default privileges would hand anon/authenticated (the public Data API roles)
    ALL on every table and EXECUTE on every function. Migration 0038 revokes that; no-op elsewhere."""
    async with scoped() as s:
        roles = [r[0] for r in await _all(s, "SELECT rolname FROM pg_roles WHERE rolname IN ('anon', 'authenticated')")]
        if not roles:
            pytest.skip("no Supabase API roles on this server")
        for role in roles:
            tables = await _all(
                s,
                """SELECT c.relname FROM pg_class c WHERE c.relnamespace='public'::regnamespace AND c.relkind IN ('r','S')
                   AND (has_table_privilege(:r, c.oid, 'SELECT') OR has_table_privilege(:r, c.oid, 'INSERT')
                        OR has_table_privilege(:r, c.oid, 'UPDATE') OR has_table_privilege(:r, c.oid, 'DELETE')
                        OR has_table_privilege(:r, c.oid, 'TRUNCATE') OR has_table_privilege(:r, c.oid, 'REFERENCES')
                        OR has_table_privilege(:r, c.oid, 'TRIGGER'))""",
                r=role,
            )
            assert tables == [], f"{role} can touch {tables}"
            funcs = await _all(
                s,
                "SELECT p.proname FROM pg_proc p WHERE p.pronamespace='public'::regnamespace AND p.proname <> 'rls_auto_enable' "
                "AND has_function_privilege(:r, p.oid, 'EXECUTE')",
                r=role,
            )
            assert funcs == [], f"{role} can execute {funcs}"
