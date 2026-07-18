<div align="center">

# ◇ ProveKit

### The open-source universal agent client

**Test, debug, and evaluate any AI agent — any provider, any protocol, no SDK.**
Point it at an LLM API, an MCP server, an HTTP agent, or an A2A agent; run it with live
streaming; turn a run into a regression test in one click; run the suite in CI.

[![CI](https://github.com/MobirizerServices/ProveKit/actions/workflows/ci.yml/badge.svg)](https://github.com/MobirizerServices/ProveKit/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Python 3.13](https://img.shields.io/badge/python-3.13-3776ab.svg)
![Next.js 15](https://img.shields.io/badge/next.js-15-black.svg)

[Quickstart](#quickstart) · [Docs](docs/README.md) · [Security](SECURITY.md) · [Contributing](CONTRIBUTING.md)

<!-- Demo GIF placeholder — export it first (see docs/launch/DEMO_SCRIPT.md), drop it at
     docs/launch/demo.gif, then uncomment the <img> below. The 15s run → +assert → ✓ passed
     loop is the whole value prop.
<img src="docs/launch/demo.gif" alt="ProveKit: run an agent, turn the run into a test, run it in CI" width="760">
-->

</div>

---

Unlike the observability platforms, ProveKit is a **client** you point at a deployed
endpoint — no SDK to instrument, no code to change. Unlike the visual builders, it doesn't
ask you to rebuild your agent in its canvas; it tests the agent you already have, wherever
it runs.

> **Open source, local-first, forever.** Every product feature is MIT-licensed and runs
> fully offline on your machine — no account, no cloud, no telemetry. That's a promise in
> writing, not a trial.

**Speaks:** OpenAI Chat Completions · OpenAI Responses / Open Responses (vLLM · Ollama ·
OpenRouter) · Anthropic Messages · MCP (stdio + Streamable HTTP, OAuth 2.1, both the
2025-11-25 and 2026-07-28 spec generations) · A2A agent cards · OpenTelemetry GenAI
trace ingest.

## Quickstart

```bash
git clone https://github.com/MobirizerServices/ProveKit && cd ProveKit
make setup      # backend venv + deps, frontend deps  (needs Python 3.13, Node 20)
make backend    # API on :8100     (terminal 1)
make frontend   # web app on :3001 (terminal 2)
```

Open http://localhost:3001 — **no login, no API key needed**; the seeded mock agent runs
offline. Then: hit **Run**, click **+ contains** on the result, hit **Run** again to see
the assertion pass. That's the loop.

Run your tests headless in CI:

```bash
provekit run .provekit/tests/     # plain-text, git-diffable, no secrets in the files
```

Full docs: [docs/](docs/README.md) · [contributing](CONTRIBUTING.md) · [security](SECURITY.md).

> ⭐ If this is useful, a star helps other agent builders find it — and tells me to keep going.

Three surfaces, one nav:

```
Console ─ single-shot runner    Flows ─ visual node canvas     Prompts ─ registry
┌──────────────┬──────────────┐  ┌────────┬───────────┬──────┐  ┌────────────────────┐
│ Connections  │ Prompt·Tool· │  │ flows  │  canvas   │ node │  │ key · name · body  │
│ + History    │ Agent stream │  │ list   │ + run/dbg │ insp │  │ edit · save        │
└──────────────┴──────────────┘  └────────┴───────────┴──────┘  └────────────────────┘
```

## What works

### Console — single-shot runner

- **Connections** — LLM (openai/anthropic/compatible), MCP server (by URL), agent API
  (base URL + headers). Secrets are masked in responses.
- **Prompt** — pick model + system/user, stream tokens live, see usage/latency.
- **Tool** — pick an MCP connection → tools are **auto-discovered**; the argument form is
  **generated from each tool's JSON input-schema**; results render as a JSON tree.
- **Give the agent tools (MCP)** — attach one or more MCP servers to a **Prompt** and the
  model under test can actually call them: it picks a tool, ProveKit runs it over MCP, feeds
  the result back, and the model continues. That makes `tool_called` an assertion about the
  agent's *decision*, not about a call you wired by hand. Narrow which tools are exposed, cap
  the call→result loop (`max_tool_rounds`), or flip **dry run** to record the tool it picks
  **without** executing it — so you can test routing without firing real side effects.
- **Agent** — call any HTTP endpoint (method/path/headers/body), buffered or SSE-streamed.
  Optional **auth helper**: log in once (login path + credentials → token path) and the
  bearer token is attached to every call — credentials are never stored, only the token.
- **Collections** — save/organize requests; click to reload.
- **Environments + `{{variables}}`** — named variable sets; the active one interpolates
  into any field, server-side.
- **Assertions** — turn any request into a test: `contains` · `equals` · `regex` ·
  `json_path` · `json_schema` · `tool_called` · `latency_lt` · `llm_judge`. Pass/fail shown
  per assertion.
- **Datasets** — run one request over N input rows (each with its own variables) → a
  pass/fail table. Save reusable datasets, and **export a self-contained HTML eval report**
  to share.
- **Compare** — same prompt, two models, side by side.
- **History** — every run is persisted; click to reload request + result.

### Flows — visual agent builder

- **Node canvas** (React Flow) — drag nodes from the palette (**input · prompt · tool ·
  agent · condition · output**), wire them together, and `{{ref}}` any upstream value
  (`{{input.x}}`, `{{nodeId.field}}`) into a later node's fields.
- **Branching** — condition nodes (`== · != · contains · > · < · exists`) fork the graph
  down `true`/`false` edges.
- **Run + step-debug** — Run streams per-node events so nodes light up as they execute
  (status + timing). Toggle **Debug** to set breakpoints on any node, then
  **Continue / Step** through — an in-engine context store keeps the run paused between calls.
- **Node inspector** — per-type config forms + the node's last-run input/output. A prompt
  node can **pull its system prompt from the Prompt Registry by key**, so the registry stays
  the single source of truth, and can **attach MCP servers** so its model calls tools itself
  rather than following a hand-wired tool node.

- **Deploy** — publish a flow as a versioned hosted API (`POST /v1/d/{slug}`). You get a
  URL, a one-time key, and a ready `curl`; invocations show up with logs and metrics.

### Prompts — registry

- **Prompt Registry** — versionable prompts keyed by slug (`assistant.system`,
  `extract.json`, …) with name/description/body. Edit once; every flow prompt node bound to
  that key uses the new content on its next run.

### Traces — capture real runs, turn one into a test

- **`@pk.trace` decorator** — `pip install "provekit[trace]"`, add a decorator to your
  agent's entrypoint, and every real call is captured as a run. It's OpenTelemetry-native,
  so any OpenAI/Anthropic instrumentation you already have is captured too — and fail-open,
  so it never affects your app. Or point any OTLP exporter at `/v1/traces`.
- **Save as test** — pick a captured run and turn it into a runnable `.provekit` regression
  test in one click, seeded with an `llm_judge` assertion against the captured output. The
  bridge from a real production run to a committed CI test. See [docs/TRACING.md](docs/TRACING.md).

## CLI — run tests in CI

Export any saved request or flow to a plain-text, git-diffable `.provekit` file
(see [docs/FILE_FORMAT.md](docs/FILE_FORMAT.md)), commit it, and run the whole suite
headless — locally or in CI:

```bash
pip install -e backend            # provides the `provekit` command
provekit run .provekit/tests/                     # pretty output, non-zero exit on failure
provekit run .provekit/tests/ --format junit -o results.xml
provekit import-promptfoo promptfooconfig.yaml -o .provekit/tests/   # migrate from promptfoo
```

Connections resolve by name from `.provekit/connections.yaml` (secrets via `${ENV_VAR}`),
so credentials never touch the test files:

```yaml
connections:
  OpenAI (prod):
    provider: openai
    api_key: ${OPENAI_API_KEY}
    models: [gpt-4o-mini]
```

**Testing a framework agent (LangGraph, CrewAI, …)?** Serve it behind an endpoint and point
ProveKit at it — no SDK, no changes to your agent code. Copy-and-run example:
[`examples/langgraph-starter/`](examples/langgraph-starter/) (serve wrapper + `.provekit/`
tests + a GitHub Actions workflow).

## Run it

### Docker (both services)

```bash
OPENAI_API_KEY=sk-… docker compose up --build
# open http://localhost:3001
```

The Postgres db persists in the `provekit-pg` volume. The seeded **Demo Assistant (mock)**
connection works in-container with no key; to reach an agent running on your host, point
the connection at `host.docker.internal` rather than `127.0.0.1`.

This stack is **for local use only** — it ships a default `SECRET_KEY`, so stored
credentials are encrypted under a publicly-known constant and the backend says so in its
logs. For anything reachable from a network, use the hosted stack (`HOSTED=true`, a real
`SECRET_KEY`, TLS) — see [docs/DEPLOY.md](docs/DEPLOY.md).

### Local dev (two processes)

```bash
# backend (port 8100)
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # optional: set OPENAI_API_KEY to prefill the example
uvicorn provekit.main:app --port 8100

# frontend (port 3001)
cd frontend
npm install
npm run dev                    # http://localhost:3001
```

On first run each workspace is seeded with a **Demo Assistant (mock)** connection that
streams a canned answer with no API key, plus (unless `SEED_EXAMPLES=false`) empty
**OpenAI** and **Anthropic** connections to drop your own keys into (pencil ✎ in the
sidebar). You also get two registry **prompts** and a **"Demo · Ask the agent"** flow
(input → prompt → output), so `/flows` and `/prompts` are populated on first load.

## Architecture

- **backend/** — FastAPI over SQLAlchemy; local/dev defaults to SQLite (`provekit.db`),
  while the Docker/prod compose stacks run Postgres (set via `DATABASE_URL`).
  `services/dispatch.py` routes a request by type to
  `providers/llm.py` (httpx streaming, provider-agnostic), `providers/mcp_client.py`
  (MCP JSON-RPC over Streamable-HTTP), or `providers/agent_http.py`. Everything is
  normalized to one event schema (`start / delta / node / result / assert / done / error`) streamed
  as SSE from `/api/run/stream`. `services/flow.py` walks a node graph over the same
  providers (via `dispatch.run_collect`), streaming a flow event schema
  (`start / node / pause / done / error`) with breakpoint + single-step support, from
  `/api/flows/{id}/run|continue/stream`. Connections, collections, requests, environments,
  run history, **prompts**, and **flows** persist in the configured database
  (`provekit.db` locally, Postgres under Docker/prod).
- **frontend/** — Next.js app with a shared `TopNav` over three routes: **`/`** console
  (`RequestEditor` + `ResponsePanel`), **`/flows`** visual builder (`FlowNode` +
  `NodeInspector` on a React Flow canvas), and **`/prompts`** registry.

## Status

Shipped: the console runner (prompt/tool/agent) · collections · environments +
`{{variables}}` · assertions · datasets + **saved datasets** · **A/B compare** · the agent
**auth helper** · run history · **exportable HTML eval reports** · Docker packaging ·
the **visual Flow builder** (node canvas + branching + run/step-debug + inspector) ·
the **Prompt Registry** (with flow prompt nodes bound by key) · the **`.provekit` format +
`provekit` CLI** (JUnit/JSON output, promptfoo importer) · **flow deployments** as a
versioned hosted API · **A2A** agent cards · **OpenTelemetry** GenAI trace ingest + emit ·
**auth + workspaces** with tenant isolation, Postgres + Alembic, rate limits and usage
metering.

Next ideas: team **export/import** of collections + flows, streaming dataset progress, and
a **prompt node inside flows that streams tokens** on the canvas.
