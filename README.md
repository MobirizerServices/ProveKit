# AgentMan — Postman for agents

A generic workspace to **create, run, and debug** prompts, MCP tools, agent APIs, and
multi-step **agent flows** across **any provider** — OpenAI, Anthropic, any
OpenAI-compatible base URL, any MCP server URL, any HTTP agent endpoint. Standalone (not
tied to any one app); Magari ships as an example connection set.

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
  the single source of truth.

### Prompts — registry

- **Prompt Registry** — versionable prompts keyed by slug (`assistant.system`,
  `extract.json`, …) with name/description/body. Edit once; every flow prompt node bound to
  that key uses the new content on its next run.

## Run it

### Docker (both services)

```bash
OPENAI_API_KEY=sk-… docker compose up --build
# open http://localhost:3001
```

The db persists in the `agentman-data` volume. In-container, the seeded Magari example
connections point at `host.docker.internal` so they reach services on your host.

### Local dev (two processes)

```bash
# backend (port 8100)
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # optional: set OPENAI_API_KEY to prefill the example
uvicorn app.main:app --port 8100

# frontend (port 3001)
cd frontend
npm install
npm run dev                    # http://localhost:3001
```

On first run the backend seeds example connections: **OpenAI**, **Anthropic**,
**Magari · catalog (MCP)** (`http://127.0.0.1:8765/mcp`), and **Magari · backend (agent)** —
plus three registry **prompts** and an **"Inventory check" flow** (input → MCP tool →
condition → branch) so `/flows` and `/prompts` are populated on first load. Add your API
key to the OpenAI connection (pencil ✎ in the sidebar) to run prompts.

## Architecture

- **backend/** — FastAPI + SQLite. `services/dispatch.py` routes a request by type to
  `providers/llm.py` (httpx streaming, provider-agnostic), `providers/mcp_client.py`
  (MCP JSON-RPC over Streamable-HTTP), or `providers/agent_http.py`. Everything is
  normalized to one event schema (`start / delta / node / result / assert / done / error`) streamed
  as SSE from `/api/run/stream`. `services/flow.py` walks a node graph over the same
  providers (via `dispatch.run_collect`), streaming a flow event schema
  (`start / node / pause / done / error`) with breakpoint + single-step support, from
  `/api/flows/{id}/run|continue/stream`. Connections, collections, requests, environments,
  run history, **prompts**, and **flows** persist in `agentman.db`.
- **frontend/** — Next.js app with a shared `TopNav` over three routes: **`/`** console
  (`RequestEditor` + `ResponsePanel`), **`/flows`** visual builder (`FlowNode` +
  `NodeInspector` on a React Flow canvas), and **`/prompts`** registry.

## Status

Shipped: the console runner (prompt/tool/agent) · collections · environments +
`{{variables}}` · assertions · datasets + **saved datasets** · **A/B compare** · the agent
**auth helper** · run history · **exportable HTML eval reports** · Docker packaging ·
the **visual Flow builder** (node canvas + branching + run/step-debug + inspector) ·
the **Prompt Registry** (with flow prompt nodes bound by key).

Next ideas: **CI mode** (run a saved dataset from the CLI as a regression gate), team
**export/import** of collections + flows, streaming dataset progress, and a **prompt node
inside flows that streams tokens** on the canvas.
