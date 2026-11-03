-- OPTIONAL, after `alembic downgrade 0037_so_cancel_reason`: remove the Phase 1C roles.
-- Run as the role that created them. Fails (safely) if the roles still own or hold privileges on objects.
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM grobook_app;
REVOKE ALL ON SCHEMA public FROM grobook_app, grobook_definer;
DROP OWNED BY grobook_app;
DROP OWNED BY grobook_definer;
DROP ROLE IF EXISTS grobook_app;
DROP ROLE IF EXISTS grobook_definer;
