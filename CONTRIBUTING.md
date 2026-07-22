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

## The contribution ladder

Four rungs, smallest first. Each one is a complete contribution — you don't have to climb.

### 1. Add a dialect fixture (the best first PR here)

ProveKit doesn't instrument frameworks itself; it maps the OpenTelemetry spans your
instrumentor already emits. So "support framework X" is one JSON file in
`backend/tests/fixtures/otlp/` pinning what `services/otel.py::map_span` must produce — and
if the mapping is wrong, the fixture is the bug report that fixes it.

No LLM key, no Docker, no account. The suite names the exact field that's wrong.

**Start here → [docs/CONTRIBUTING_INSTRUMENTORS.md](docs/CONTRIBUTING_INSTRUMENTORS.md)**, then
read the module docstring of `backend/tests/test_dialects.py` — it is the spec.

Thirteen instrumentor families ProveKit activates have **no fixture at all** today. Each is
its own starter task, none of them blocked on anything:

`agno` · `aiohttp_client` · `autogen` · `dspy` · `groq` · `guardrails` · `haystack` ·
`instructor` · `mistralai` · `openai_agents` · `pydantic_ai` · `smolagents` · `vertexai`

Regenerate that list any time — it is just the gap between `trace.py`'s instrumentor lists and
the corpus:

```bash
cd backend && ./venv/bin/python -c "
import json, pathlib
from provekit import trace as t
mods = {m.rsplit('.',1)[-1] for m,_ in t._INSTRUMENTORS + t._HTTP_INSTRUMENTORS}
have = {json.loads(p.read_text())['instrumentor']
        for p in pathlib.Path('tests/fixtures/otlp').glob('*.json')}
print(*sorted(mods - have))"
```

### 2. Fix a doc

The docs are the markdown in `docs/`, rendered in place — there is no second copy to keep in
sync. If a command in a guide fails for you, that's a one-file PR. Two are waiting right now:
`docs/ADMIN.md` links `#revoking-actually-revoking` and
`#impersonation--read-only-view-as-tenant`, both renamed headings. Fix them and flip
`validation.links.anchors` to `warn` in `docs/site/mkdocs.yml` so the next one gets caught.

### 3. Fix a bug with a failing test first

`backend/tests/` has ~60 modules to copy a shape from. Get a workspace from `conftest.py`'s
`ingest_workspace_id()` rather than querying for one. Write the test that fails, then make it
pass — a PR whose test fails on `main` and passes on the branch reviews itself.

### 4. Build a roadmap item

[docs/ROADMAP_100.md](docs/ROADMAP_100.md) is the live plan, numbered and prioritized. Comment
on the item before you start so two people don't build it twice.

## Template gallery

Copy-paste starting points, so nothing begins from a blank file:

| You're… | Start from |
|---|---|
| reporting or fixing a mapping | `.github/ISSUE_TEMPLATE/1_instrumentor_coverage.yml` (the form asks for the span, which is the whole fix) |
| writing a dialect fixture | the closest file in `backend/tests/fixtures/otlp/` — 29 of them, each one span; the annotated skeleton is in the [instrumentor guide](docs/CONTRIBUTING_INSTRUMENTORS.md) |
| reporting a bug | `.github/ISSUE_TEMPLATE/2_bug_report.yml` |
| proposing a feature | `.github/ISSUE_TEMPLATE/3_feature_request.yml` |
| reporting a docs problem | `.github/ISSUE_TEMPLATE/4_docs.yml` |
| filing a starter task (maintainers) | `.github/ISSUE_TEMPLATE/5_good_first_issue.yml` — it makes files, done-criteria, the verify command and a named mentor mandatory |
| opening a PR | `.github/PULL_REQUEST_TEMPLATE.md`, filled in automatically |
| writing a demo agent | `examples/demo_agent.py` (small) or `examples/complex_demo.py` (deep, 37-span) — see [examples/README.md](examples/README.md) |
| adding a framework quickstart | the LangGraph / CrewAI / LlamaIndex sections of [docs/QUICKSTARTS.md](docs/QUICKSTARTS.md) — same shape each time: install, code, resulting span tree |
| adding a scorer | `backend/provekit/scorers.py` alongside the existing ones; the [evaluation guide](docs/EVALUATION.md) covers the interface |

Issue forms apply labels (`good first issue`, `instrumentor`, `documentation`); GitHub only
attaches labels that already exist in the repo, so create any missing ones once in **Settings →
Labels**.

## The docs site

`docs/site/` is a MkDocs scaffold that renders the existing `docs/*.md` into a searchable site —
one copy of every guide, no rendered HTML in git. **Nothing is deployed**; CI builds it so a
broken build is caught. Preview locally:

```bash
python -m venv docs/site/.venv
docs/site/.venv/bin/pip install -r docs/site/requirements.txt
docs/site/.venv/bin/mkdocs serve -f docs/site/mkdocs.yml     # http://127.0.0.1:8000
```

Adding a page? Drop the `.md` in `docs/` and add it to `nav:` in `docs/site/mkdocs.yml`.
Details and the not-yet-done multi-version publishing story: [docs/site/README.md](docs/site/README.md).

## Notes

- The venv is git-ignored and machine-local; if `./venv/bin/uvicorn` ever fails with a bad
  interpreter (a moved venv), run `make clean && make setup`.
- Secrets are never sent by the tracing SDK — only the inputs/outputs of the traced
  function. Redact anything sensitive before returning it if you don't want it captured.
