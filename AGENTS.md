# AgentMan — notes for coding agents

AgentMan is the open-source universal agent client: test, debug, and evaluate any AI
agent (LLM API, MCP server, HTTP agent, A2A agent) with no SDK. Monorepo:

- `backend/` — FastAPI + SQLite. Python package is `agentman` (installable; provides the
  `agentman` CLI). Run the API with `uvicorn agentman.main:app --port 8100`.
- `frontend/` — Next.js 14 (app router) + React Flow. `npm run dev` on port 3001.

## Conventions

- Backend: keep modules small and single-purpose. Providers live in
  `agentman/services/providers/` and yield the unified event schema in
  `services/dispatch.py` (`start`/`delta`/`node`/`result`/`done`/`error`). Never send a
  stored connection's credentials to a caller-supplied URL — connections are authoritative
  for both destination and secrets (see `services/dispatch.py`). All outbound URLs go
  through `services/netguard.py`.
- Secrets: masked in API responses (`services/masking.py`) and encrypted at rest
  (`services/sealing.py`). Never write a credential into an `.agentman` file
  (`services/testfile.py` strips and rejects them).
- Frontend: match the existing terminal-dark styling in `app/globals.css`; components are
  small and colocated under `components/`.

## Checks before committing

```bash
cd backend  && ./venv/bin/python -m pytest tests/ -q     # backend + CLI + protocol tests
cd frontend && ./node_modules/.bin/tsc --noEmit          # typecheck
cd frontend && npm run build                             # production build
```

## The `.agentman` file format

Plain-text, git-diffable tests/flows; connections referenced by name, never by id or key.
Spec in `docs/FILE_FORMAT.md`; runnable examples in `examples/.agentman/`. The `agentman`
CLI (`backend/agentman/cli.py`) runs them headless for CI.
