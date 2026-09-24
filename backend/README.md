# SaaS MVP — Backend

Foundation (PROMPT-001) + tenant onboarding (PROMPT-002) + sign-in/session
management (PROMPT-003) + forgot/reset password (PROMPT-004) + user management
(PROMPT-005) + role & permission management (PROMPT-006). No other business
modules are implemented here — see [`PROMPT-001-NOTES.md`](../PROMPT-001-NOTES.md),
[`PROMPT-002-NOTES.md`](../PROMPT-002-NOTES.md), [`PROMPT-003-NOTES.md`](../PROMPT-003-NOTES.md),
[`PROMPT-004-NOTES.md`](../PROMPT-004-NOTES.md), [`PROMPT-005-NOTES.md`](../PROMPT-005-NOTES.md),
and [`PROMPT-006-NOTES.md`](../PROMPT-006-NOTES.md) at the repo root for the
full design records, conflicts found in the baseline documents, and open decisions.

## Stack

FastAPI + SQLAlchemy 2.0 (async, asyncpg) + Alembic + PostgreSQL 16.

## Local setup

```bash
cd backend
python -m venv .venv
./.venv/Scripts/activate        # Windows; use `source .venv/bin/activate` on macOS/Linux
pip install -r requirements/dev.txt
cp .env.example .env             # then fill in real values — never commit .env
```

Required `.env` values: `DATABASE_URL`, `JWT_SECRET_KEY` (32+ chars). The app fails
to start if either is missing — there is no insecure default.

## Database migration

```bash
alembic upgrade head
```

Creates the platform/security foundation tables (`tenant`, `user`, `role`,
`permission`, `user_role`, `role_permission`, `audit_log`) plus proposed
additions not in the Database Design baseline: `idempotency_key` (PROMPT-002),
`auth_session` (PROMPT-003, backs real logout/revocation for the otherwise-
stateless JWT), `password_reset_token` (PROMPT-004), `user.name` (PROMPT-005),
and a `role_permission` backfill + tightened `user_role` unique constraint
(PROMPT-006 — one role per user, now schema-enforced). No business tables.

To roll back: `alembic downgrade base`. To create a new migration:
`alembic revision -m "description"` (write it by hand — autogenerate won't produce
RLS policies or the audit_log immutability grant, which need explicit `op.execute`).

## Running the backend

```bash
uvicorn app.main:app --reload --port 8000
```

- `GET /api/v1/health` — app liveness
- `GET /api/v1/health/db` — DB connectivity
- `GET /api/v1/version` — API version
- `POST /api/v1/auth/sign-up` — tenant + owner registration (requires `Idempotency-Key` header)
- `POST /api/v1/auth/login` — phone + password; sets an httpOnly session cookie
- `POST /api/v1/auth/logout` — revokes the current session server-side
- `GET /api/v1/auth/me` / `GET /api/v1/auth/session-status` — protected, require the session cookie
- `POST /api/v1/auth/forgot-password` — always returns a generic response (anti-enumeration); logs the reset link to stdout in dev (no real email provider — see PROMPT-004-NOTES.md)
- `POST /api/v1/auth/reset-password/validate` / `POST /api/v1/auth/reset-password`
- `GET/POST /api/v1/users`, `GET/PATCH /api/v1/users/{id}`, `POST /api/v1/users/{id}/activate`, `POST /api/v1/users/{id}/deactivate` — permission-gated (`users.view/create/update/activate/deactivate`), see PROMPT-006-NOTES.md
- `GET /api/v1/roles`, `GET /api/v1/roles/{id}`, `GET /api/v1/roles/{id}/permissions`, `GET /api/v1/permissions` — read-only RBAC catalogue (no custom roles/permissions in MVP)
- `GET /docs` — OpenAPI/Swagger UI (disabled when `ENVIRONMENT=production`)

No `/auth/refresh` — see PROMPT-003-NOTES.md for the session/token architecture
decision (single 60-min JWT, no refresh token in this MVP).

CORS: `CORS_ALLOW_ORIGINS` in `.env` must include whatever origin the frontend
dev server actually runs on (Vite's configured port is 3000 here, not the
5173 default — check `vite.config.ts`).

## Running tests

```bash
pytest tests/ -v
```

Requires a real reachable PostgreSQL (`DATABASE_URL` in `.env`) — these are
integration tests against the live schema, not mocks. Setting `ENVIRONMENT=testing`
(done automatically by `tests/conftest.py`) switches the DB engine to `NullPool`,
which is required on Windows because asyncpg connections cannot be reused across
the separate event loop each test gets.

## Project structure

```
app/
  api/v1/        # routers — only system/health routes exist so far
  core/          # config, security, exceptions, correlation-id, concurrency
  db/            # session, declarative base + mixins, tenant-context (RLS)
  middleware/    # correlation-id middleware
  models/        # SQLAlchemy models: Tenant, User, Role, Permission, UserRole,
                 # RolePermission, AuditLog
  repositories/  # generic tenant-scoped repository base
  services/audit/ # AuditService — the only way future code writes to audit_log
  logging/       # structured JSON logging config
migrations/      # Alembic
tests/
  unit/          # no DB/HTTP required
  integration/   # real DB + HTTP via httpx ASGI transport
```

## What's deliberately NOT here

Login/session issuance (PROMPT-002), any business module (customer, product,
sales invoice, etc.), RLS `FORCE` (left open per the baseline's own open decisions).
