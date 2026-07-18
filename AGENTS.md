# AgentMan — notes for coding agents

AgentMan is the open-source universal agent client: test, debug, and evaluate any AI
agent (LLM API, MCP server, HTTP agent, A2A agent) with no SDK. Monorepo:

- `backend/` — FastAPI over SQLAlchemy; local/dev defaults to SQLite (`agentman.db`), while
  the Docker/prod stacks run Postgres (`DATABASE_URL`) + Redis (`REDIS_URL`). The schema is
  owned by Alembic and `alembic upgrade head` runs automatically on startup — add a
  migration for any model change. Migrations live *inside* the package
  (`backend/agentman/migrations/`) so an installed wheel can migrate its own database;
  keep them there. Python package is `agentman` (installable;
  provides the `agentman` CLI). Run the API with `uvicorn agentman.main:app --port 8100`.
- `frontend/` — Next.js 14 (app router) + React Flow. `npm run dev` on port 3001.

## Conventions

- Backend: keep modules small and single-purpose. Providers live in
  `agentman/services/providers/` and yield the unified event schema in
  `services/dispatch.py` (`start`/`delta`/`node`/`result`/`done`/`error`). Never send a
  stored connection's credentials to a caller-supplied URL — connections are authoritative
  for both destination and secrets (see `services/dispatch.py`). All outbound URLs go
  through `services/netguard.py`.
- Tool calling: `llm.astream` takes provider-agnostic messages (`user`/`assistant` with
  `tool_calls`/`tool`) and each provider translates them — a tool round looks different on
  every API, so keep that divergence inside `providers/llm.py`. It yields `tool_call` for a
  requested tool; the loop that executes it and decides whether to continue lives in
  `dispatch._run_prompt`, and MCP resolution/translation in `services/tooling.py`. Anything
  a `tool_called` assertion must see has to be emitted as a `node` event.
- MCP is synchronous and may spawn a process, so anything touching it from the async path
  (`tooling.discover`, `tooling.call`) goes through `anyio.to_thread.run_sync` — one slow
  MCP server must never stall the event loop. `tooling.plan` is the DB-only half and is
  safe to call inline.
- Secrets: masked in API responses (`services/masking.py`) and encrypted at rest
  (`services/sealing.py`). Never write a credential into an `.agentman` file
  (`services/testfile.py` strips and rejects them).
- Frontend: match the existing terminal-dark styling in `app/globals.css`; components are
  small and colocated under `components/`.

## Checks before committing

```bash
cd backend  && ./venv/bin/python -m ruff check agentman  # lint — CI gates on this
cd backend  && ./venv/bin/python -m pytest tests/ -q     # backend + CLI + protocol tests
cd frontend && ./node_modules/.bin/tsc --noEmit          # typecheck
cd frontend && npm run build                             # production build
```

Or `make lint && make test && make build`. CI additionally builds both Docker images, so
keep `backend/Dockerfile` and `frontend/Dockerfile` working.

## The `.agentman` file format

Plain-text, git-diffable tests/flows; connections referenced by name, never by id or key.
Spec in `docs/FILE_FORMAT.md`; runnable examples in `examples/.agentman/`. The `agentman`
CLI (`backend/agentman/cli.py`) runs them headless for CI.
