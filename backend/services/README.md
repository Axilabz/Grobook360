# Services

Intentionally empty in Phase 1A: no service skeletons are generated until there is real code to put in them.

Phase 1B (awaiting approval) adds `identity-service/`, `tenant-service/`, `master-data-service/` — each a standalone FastAPI app (`app/api/v1`, `core`, `models`, `schemas`, `services`, `repositories`, `main.py`, `Dockerfile`, tests) that imports only `backend/shared`, never another service. See `docs/architecture/code-migration-mapping.md`.
