-- LOCAL DEVELOPMENT ONLY. Creates a throwaway database for Phase 1C validation
-- with a dedicated owner role (so the owner/runtime split is exercised for real).
-- Do NOT run against Supabase (there the owner is the existing `postgres` user).
--
--   psql -h localhost -p 5433 -U postgres -v ON_ERROR_STOP=1 \
--        -v owner_pw='<random>' -f infrastructure/scripts/local_rls_database.sql
--
-- Afterwards run rls_bootstrap_roles.sql with -v owner_role=grobook_owner against
-- the NEW database (-d saas_rls_dev), then point Alembic at grobook_owner and the
-- API/tests at grobook_app.

SELECT format('CREATE ROLE grobook_owner LOGIN PASSWORD %L NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOCREATEDB', :'owner_pw')
 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'grobook_owner') \gexec
SELECT format('ALTER ROLE grobook_owner PASSWORD %L', :'owner_pw') \gexec

SELECT 'CREATE DATABASE saas_rls_dev OWNER grobook_owner'
 WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'saas_rls_dev') \gexec
