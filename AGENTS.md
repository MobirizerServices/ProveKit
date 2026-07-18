# ProveKit — notes for coding agents

ProveKit is drop-in tracing for AI agents: one `@pk.trace` decorator captures a run's whole
nested flow (model calls, tools, steps) and ships it to the portal to review. Monorepo:

- `backend/` — FastAPI over SQLAlchemy; dev defaults to SQLite (`provekit.db`), Docker/prod
  runs Postgres (`DATABASE_URL`). The schema is owned by Alembic and `alembic upgrade head`
  runs automatically on startup — add a migration for any model change. Migrations live
  *inside* the package (`backend/provekit/migrations/`) so an installed wheel can migrate its
  own database; keep them there. Package is `provekit`. Run the API with
  `uvicorn provekit.main:app --port 8100`.
- `frontend/` — Next.js (app router). `npm run dev` on port 3001.

## Architecture

- **The SDK** — `provekit/trace.py` (`@pk.trace`, `pk.span`, `pk.configure`). It opens
  OpenTelemetry spans, makes them the current context (so instrumented libraries nest), and a
  minimal exporter ships them to `/v1/traces` as OTLP-JSON. It depends only on httpx + OTel;
  never import server modules into it.
- **Ingest** — `routers/traces.py` accepts OTLP/JSON, authed by a bearer project key
  (`services/apikey.py`) or session cookie. `services/otel.py` maps each span to a `Run`
  (classified agent/llm/tool/step, with trace/span/parent ids). Every span is kept, so the
  full tree survives — not just LLM calls.
- **Read APIs** — `routers/traces.py` also serves `/api/traces` (roots) and
  `/api/traces/{id}` (all spans of a trace); the frontend rebuilds the tree from
  `parent_span_id`.
- **Auth / tenancy** — `services/auth.py` (signed sessions), `services/workspace.py`
  (project resolution + `current_workspace` dependency). Everything is workspace-scoped.
- **Frontend** — `app/traces/page.tsx` (the flow waterfall), `app/api-keys/page.tsx`, and the
  auth pages. Match the terminal-dark styling in `app/globals.css`.

## Conventions

- Keep modules small and single-purpose. All outbound URLs (the OTLP re-emit path) go through
  `services/netguard.py`.
- No plaintext secrets at rest — password hashes (PBKDF2) and key hashes (SHA-256) only.
- Add a test for behavior changes; the coverage gate lives in `pyproject.toml`.

## Checks before committing

```bash
cd backend  && ./venv/bin/python -m ruff check provekit   # lint — CI gates on this
cd backend  && ./venv/bin/python -m pytest tests/ -q      # backend tests + coverage gate
cd frontend && ./node_modules/.bin/tsc --noEmit           # typecheck
cd frontend && npm run build                              # production build
```

Or `make lint && make test && make build`. CI additionally builds both Docker images, so keep
`backend/Dockerfile` and `frontend/Dockerfile` working.
