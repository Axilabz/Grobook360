-- LEVEL 1 ROLLBACK (seconds, no code deploy, no data change).
-- Restores the pre-Phase-1C isolation posture (RLS present but not enforced for the owner)
-- WITHOUT removing anything the new application code depends on (policies and the pre-login
-- functions stay). Run as the OWNER/migration role, then point DATABASE_URL at the owner login.
-- This WEAKENS tenant isolation: use only to restore service while a defect is investigated.
--
--   psql "<owner connection>" -v ON_ERROR_STOP=1 -f infrastructure/scripts/rls_emergency_relax.sql
--
-- Re-enforce afterwards with rls_reenforce.sql (or `alembic upgrade head` after a downgrade).

DO $$
DECLARE t text;
BEGIN
  FOR t IN SELECT relname FROM pg_class
           WHERE relnamespace = 'public'::regnamespace AND relkind = 'r' AND relforcerowsecurity
  LOOP
    EXECUTE format('ALTER TABLE public.%I NO FORCE ROW LEVEL SECURITY', t);
  END LOOP;
END $$;
