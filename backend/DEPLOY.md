# Deploying the backend

1. **Build & run** (any container host — Render, Railway, Fly, a VPS):
   `docker build -t grobook-api backend/` then run with the env vars from
   `.env.production.example` and port 8000 exposed (hosts that set `$PORT` are honoured).
2. **Database**: the Supabase DB already has the schema (alembic head). For a fresh DB run
   `alembic upgrade head` once per release (uses `DATABASE_URL`, or `MIGRATION_DATABASE_URL` if set).
3. **Route the frontend to it** — pick ONE:
   - *Same origin*: proxy `https://grobook360np.axilabz.com/api/*` to the backend, e.g. nginx:
     ```
     location /api/ {
         proxy_pass http://<backend-host>:8000;
         proxy_set_header Host $host;
         proxy_set_header X-Forwarded-Proto $scheme;
     }
     ```
     Frontend keeps `VITE_API_BASE_URL=https://grobook360np.axilabz.com/api/v1` (`.env.production`).
   - *Separate API domain* (e.g. `https://api-np.axilabz.com`): set
     `VITE_API_BASE_URL=https://api-np.axilabz.com/api/v1` at frontend build, and
     `CORS_ALLOW_ORIGINS` on the backend. Keep both under `*.axilabz.com` so the login cookie
     (SameSite=Lax) is sent.
4. **Verify**: `curl https://<api>/api/v1/health` must return JSON `{"data":{"status":"ok"}}`, not HTML.

Known production limits: forgot-password has no real email provider and raises in production
mode (open decision in CLAUDE.md); GST e-Invoice uses the sandbox simulator only.
