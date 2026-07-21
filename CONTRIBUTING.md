# Contributing to ProveKit

## Quickstart (clone → running in ~2 minutes)

Requirements: Python 3.11+ (3.13 recommended), Node 20 (`.nvmrc`).

```bash
make setup        # backend venv + deps, frontend deps
make backend      # terminal 1 → API on http://localhost:8000
make frontend     # terminal 2 → web app on http://localhost:3000
```

Open http://localhost:3000. In local mode there's no login — you land in a default project.
To see traces, add `@pk.trace` to an agent (see the **Project keys** page for the snippet)
and run it, or `POST` an OTLP payload to `/v1/traces`.

## Common commands

```bash
make lint         # ruff check on the backend
make test         # backend pytest + frontend typecheck
make build        # frontend production build
make clean        # remove venv, node_modules, local db (re-run make setup afterwards)
```

Run `make lint && make test && make build` before opening a PR. CI
(`.github/workflows/ci.yml`) runs those same gates and also builds the backend and frontend
Docker images, so a Dockerfile break fails the build too.

## Layout

- `backend/` — FastAPI, package `provekit`.
  - `provekit/trace.py` — the tracing SDK (`@pk.trace`, `pk.span`, `pk.score`); `auto.py` is the
    one-import activation. `eval.py` + `scorers.py` are the evaluation client.
  - `provekit/routers/` — `traces` (ingest + read APIs), `auth`, `apikeys`, `projects`,
    `datasets`, `experiments`, `metrics`, `alerts`, `playground`, `admin`.
  - `provekit/services/` — `otel` (span→run mapping), `auth`, `workspace`, `apikey`, `netguard`,
    `sealing`, `redact`, `limits`, `pricing`, `replay`, `share`, `llm_client`, `email`.
  - `provekit/models.py` — 15 tables; `provekit/migrations/` — Alembic, run on boot.
- `frontend/` — Next.js (app router): `app/traces` (the flow view), `app/dashboard`,
  `app/datasets`, `app/prompts`, `app/settings`, `app/admin`, auth pages, and the marketing
  surface (landing, `app/blog`). Shared UI in `components/`.
- `docs/` — start at [docs/README.md](docs/README.md); the [tracing guide](docs/TRACING.md),
  [debugging](docs/DEBUGGING.md), [evaluation](docs/EVALUATION.md),
  [deployment](docs/DEPLOY.md), [publishing](docs/PUBLISHING.md).

## Notes

- The venv is git-ignored and machine-local; if `./venv/bin/uvicorn` ever fails with a bad
  interpreter (a moved venv), run `make clean && make setup`.
- Secrets are never sent by the tracing SDK — only the inputs/outputs of the traced
  function. Redact anything sensitive before returning it if you don't want it captured.
