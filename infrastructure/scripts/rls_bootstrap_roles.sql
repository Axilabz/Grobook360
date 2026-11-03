-- Phase 1C: database roles for enforced RLS.  Idempotent.  Contains NO secrets.
--
-- Run ONCE per database server (local dev, Supabase staging, later production)
-- as a role allowed to create roles (local: postgres; Supabase: the `postgres`
-- user via the SQL editor or psql).  Passwords come from psql variables so they
-- never appear in the repository:
--
--   psql "<admin connection>" -v ON_ERROR_STOP=1 \
--        -v owner_role=postgres -v app_pw='<strong random>' \
--        -f infrastructure/scripts/rls_bootstrap_roles.sql
--
--   owner_role : the role that runs Alembic and owns the tables
--                (Supabase: postgres;  local fresh DB: grobook_owner)
--
-- Roles:
--   grobook_app      runtime role used by the API (and, in Phase 1B, by services).
--                    LOGIN, NOSUPERUSER, NOBYPASSRLS, NOCREATEROLE, NOCREATEDB,
--                    owns nothing.  Table privileges are granted by migration 0038.
--   grobook_definer  NOLOGIN. Owns only the narrow SECURITY DEFINER pre-login
--                    functions created by migration 0038. Column-level SELECT only.

SELECT format('CREATE ROLE grobook_definer NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOCREATEDB')
 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'grobook_definer') \gexec

SELECT format('CREATE ROLE grobook_app LOGIN PASSWORD %L NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOCREATEDB NOREPLICATION', :'app_pw')
 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'grobook_app') \gexec

-- Re-running with a new password rotates it.
SELECT format('ALTER ROLE grobook_app PASSWORD %L NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOCREATEDB', :'app_pw') \gexec

-- The migration role must be able to hand function ownership to grobook_definer.
SELECT format('GRANT grobook_definer TO %I', :'owner_role') \gexec

-- Allow the app role to connect (Supabase / local databases grant CONNECT to PUBLIC by default; explicit is safer).
SELECT format('GRANT CONNECT ON DATABASE %I TO grobook_app', current_database()) \gexec

-- Verification (prints the final attributes; must show f,f,f,f for both roles).
SELECT rolname, rolsuper, rolbypassrls, rolcreaterole, rolcreatedb, rolcanlogin
  FROM pg_roles WHERE rolname IN ('grobook_app', 'grobook_definer') ORDER BY 1;
