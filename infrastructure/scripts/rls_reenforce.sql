-- Reverse of rls_emergency_relax.sql: FORCE row level security on every table that has RLS enabled.
-- Run as the OWNER/migration role, then point DATABASE_URL back at grobook_app.
DO $$
DECLARE t text;
BEGIN
  FOR t IN SELECT relname FROM pg_class
           WHERE relnamespace = 'public'::regnamespace AND relkind = 'r' AND relrowsecurity AND NOT relforcerowsecurity
  LOOP
    EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY', t);
  END LOOP;
END $$;
