# ProveKit — notes for coding agents

ProveKit is drop-in tracing for AI agents: one import captures a run's whole nested flow (model
calls, tools, steps) and ships it to the portal, where you can review it, re-run parts of it, and
evaluate it. Monorepo:

- `backend/` — FastAPI over SQLAlchemy; dev defaults to SQLite (`provekit.db`), Docker/prod
  runs Postgres (`DATABASE_URL`), Redis for rate limits and spend counters. The schema is owned
  by Alembic and `alembic upgrade head` runs automatically on startup — add a migration for any
  model change. Migrations live *inside* the package (`backend/provekit/migrations/`) so an
  installed wheel can migrate its own database; keep them there. Package is `provekit`.
  Run the API with `make backend` (uvicorn on **:8000**).
- `frontend/` — Next.js (app router). `make frontend` (`npm run dev`) on **:3000**.

> Docker Compose publishes different host ports (backend 8100, frontend 3001) than the local
> dev flow. Use 8000/3000 when running from source.

## Architecture

- **The SDK** — `provekit/trace.py` (`@pk.trace`, `pk.span`, `pk.init`/`configure`, `pk.score`)
  plus `provekit/auto.py` (zero-code activation via a single import). It opens OpenTelemetry
  spans, makes them the current context (so instrumented libraries nest), and a minimal exporter
  ships them to `/v1/traces` as OTLP-JSON. It depends only on httpx + OTel; **never import server
  modules into it**. `provekit/eval.py` + `scorers.py` are also client-side (and shared with the
  server). `provekit/mcp.py` is the MCP debug server, `demo.py` the `provekit-demo` smoke test.
- **Ingest** — `routers/traces.py` accepts OTLP/JSON, authed by a bearer project key
  (`services/apikey.py`) or session cookie. `services/otel.py` maps each span to a `Run`
  (classified agent/llm/tool/step, with trace/span/parent ids). Every span is kept, so the
  full tree survives — not just LLM calls. `services/redact.py` optionally masks PII before
  storage; `services/limits.py` enforces ingest/login/playground rates and the spend cap.
  `services/spool.py` fsyncs each batch to disk *before* it's acknowledged and releases it once
  the rows commit, so a database blip can't destroy accepted data — a drain task in the lifespan
  replays whatever is left staged. Ingest stays synchronous; the spool is a net under the write,
  not a queue in front of it. Its depth also drives backpressure and the `/healthz` ingest block.
- **Read APIs** — `routers/traces.py` serves three routers: `/v1` (key-authed ingest + read),
  `/api` (cookie-authed runs, feedback, notes, share links), and `/api/workspace`. The frontend
  rebuilds the tree from `parent_span_id`.
- **Auth / tenancy** — `services/auth.py` (signed sessions), `services/workspace.py` (project
  resolution + `current_workspace` dependency). Everything is workspace-scoped; the client picks
  a project with `X-Project-Id`, validated against membership server-side.
- **Other routers** — `datasets`, `experiments` (both cookie + `/v1` key-authed), `metrics`,
  `alerts`, `projects` (members/roles/settings), `playground` (edit-and-re-run, replay, prompt
  versions), `apikeys`, `auth`, `admin` (platform superadmin).
- **Other services** — `pricing.py` (cost estimates), `sealing.py` (provider keys encrypted at
  rest), `replay.py` (trace forking), `share.py` (signed read-only links), `llm_client.py`,
  `email.py`, `netguard.py`, `deploy.py`.
- **Frontend** — `app/traces/page.tsx` (the flow waterfall) plus `dashboard`, `datasets`,
  `prompts`, `settings`, `admin`, `shared/[token]`, the auth pages, and a marketing surface
  (landing, `blog`, `community`, `feed.xml`). Shared UI in `components/` (`TraceDetail`,
  `TraceGraph`, `TraceCompare`, `Playground`, `AlertsPanel`, `ModelConnections`, charts).
  Match the terminal-dark styling in `app/globals.css`.

## Conventions

- Keep modules small and single-purpose. All outbound URLs (the OTLP re-emit path, replay
  webhooks, provider calls) go through `services/netguard.py`.
- No plaintext secrets at rest — password hashes (PBKDF2), key hashes (SHA-256), and sealed
  provider credentials only. Provider keys are never returned to the browser.
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
