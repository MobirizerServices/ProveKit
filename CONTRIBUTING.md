# Contributing to AgentMan

## Quickstart (clone → running in ~2 minutes)

Requirements: Python 3.13 (`.python-version`), Node 20 (`.nvmrc`).

```bash
make setup        # backend venv + deps, frontend deps
make backend      # terminal 1 → API on http://localhost:8100
make frontend     # terminal 2 → web app on http://localhost:3001
```

Open http://localhost:3001. Local mode needs no login and no API keys — the seeded
**Demo Assistant (mock)** connection runs offline. Add an OpenAI/Anthropic key from the
Connections tab for real models.

## Common commands

```bash
make test         # backend pytest + frontend typecheck
make build        # frontend production build
make clean        # remove venv, node_modules, local db, then re-run make setup
```

Run these before opening a PR; CI (`.github/workflows/ci.yml`) runs the same.

## Layout

- `backend/` — FastAPI, package `agentman`. Providers in `agentman/services/providers/`,
  the unified event schema in `services/dispatch.py`. See `AGENTS.md` for conventions.
- `frontend/` — Next.js 14 (app router) + React Flow.
- `docs/` — file format, deployment, product strategy.

## Notes

- The venv is git-ignored and machine-local; if `./venv/bin/uvicorn` ever fails with a
  bad interpreter (a moved venv), run `make clean && make setup`. The Makefile always
  invokes tools via `./venv/bin/python -m <tool>`, which is immune to stale shebangs.
- Never put secrets in `.agentman` files — connections are referenced by name and secrets
  come from the environment (`${VAR}`) at run time.
