# ProveKit Test Kit

A self-contained folder for evaluating **ProveKit** — a drop-in tracing/observability layer for
AI agents. Add one `@pk.trace` decorator and every run your agent makes (model calls, tool calls,
nested steps) is captured and shown in a portal, exactly as it executed.

You can be looking at your first trace in **under a minute**. No LLM key required — the demos run
fully offline against a mocked model.

---

## What's in this folder

| File | What it is |
|------|-----------|
| `README.md` | This guide. |
| `requirements.txt` | Everything to install (`provekit`, LangGraph, and helpers). |
| `.env.example` | Template for your project key + portal URL. Copy to `.env`. |
| `run_langgraph.py` | A **simple** LangGraph agent (retrieve → generate), auto-traced. |
| `run_langgraph_complex.py` | A **deep** multi-agent LangGraph orchestrator (~70 spans). |

There's also a built-in command, `provekit-demo`, that ships a gallery of traces with **zero
code** — great as a first smoke test (see Step 4).

---

## Prerequisites

- **Python 3.11+**
- A **ProveKit account + project key** (free — see Step 1). No OpenAI/Anthropic key needed.

---

## Step 1 — Get a project key

1. Sign up at **https://provekit.online**.
2. Create a project (or use the default one).
3. Go to **Project keys → Create key**, and copy the `pk_...` value (shown once).

That key is how the SDK ships traces to your portal.

---

## Step 2 — Install

```bash
# from inside this folder
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

This installs `provekit` from PyPI (with the tracing + framework instrumentors), plus LangGraph
for the framework demos.

---

## Step 3 — Configure

```bash
cp .env.example .env
```

Open `.env` and fill in the key from Step 1:

```env
PROVEKIT_API_KEY=pk_your_key_here
PROVEKIT_ENDPOINT=https://provekit.online
```

The demo scripts load `.env` automatically.

---

## Step 4 — Run a demo

Pick any of these — each sends traces to your portal, then prints a link.

**a) The zero-code smoke test** (installed with the package):
```bash
provekit-demo
```
Ships 7 traces: nested agent → tool → LLM flows, a two-turn session, a failed run, and a
feedback score. The fastest way to confirm your key works.

**b) A simple LangGraph agent:**
```bash
python run_langgraph.py
```
A two-node graph (`retrieve → generate`). One trace per question, each showing the graph nodes
and the LLM call nested automatically.

**c) A deep, multi-agent LangGraph orchestrator:**
```bash
python run_langgraph_complex.py
```
One run → a **~70-span** trace: a planner that fans out to **parallel** research sub-agents
(map-reduce via LangGraph's `Send`), each doing retrieval (with a flaky-then-retried fetch),
analysis, and a **critique → revise** reflection loop, then a final synthesis across five models.
Built to stress-test the viewer.

> Want a real model instead of the offline canned one? Set `OPENAI_API_KEY` in `.env` and the
> LangGraph demos will use `gpt-4o-mini`.

---

## What to look at in the portal

Open **https://provekit.online/traces** and click a trace:

- **Flow graph** — the whole run as a node graph. Try **Collapse all** to fold subtrees, the
  node **search** box, and **Heat** to colour nodes green→red by latency so the slow ones pop.
- **Waterfall** — the same run as a timeline, with a per-span duration bar and a **Heat** toggle.
- **Inspector** (right panel) — click any node for its input/output, raw JSON, parameters, and logs.
- **Dashboard** — trace volume, error rate, latency p50/p95, tokens, a **per-model + cost**
  breakdown, latency/token/cost **trends over time**, and a **failures** panel (each failure
  deep-links to its trace). The complex demo lights all of this up.

---

## Using ProveKit in your own agent

Once the demos look right, wiring up your real agent is three lines:

```bash
pip install "provekit[trace-all]"
export PROVEKIT_API_KEY=pk_...  PROVEKIT_ENDPOINT=https://provekit.online
```

```python
import provekit.trace as pk

@pk.trace(name="my-agent")           # wrap your entrypoint
def run_agent(question: str) -> str:
    ...                              # your agent; LLM/tool calls are captured automatically
```

Any OpenAI / Anthropic / LangChain / LangGraph calls inside are auto-instrumented and nest under
the trace — no per-call code. Add manual spans with `with pk.span("step"): ...` and scores with
`pk.score("quality", score=0.9)`.

The `[trace-all]` extra pulls in the framework instrumentors (LangChain/LangGraph, LlamaIndex,
CrewAI, etc.). If you only use OpenAI/Anthropic, `pip install "provekit[trace]"` is leaner.

---

## Troubleshooting

- **"Set PROVEKIT_API_KEY and PROVEKIT_ENDPOINT first"** — your `.env` isn't filled in, or you're
  running outside this folder. Confirm `.env` exists here with both values.
- **No traces in the portal** — double-check the key is a **project key** (`pk_...`) from the
  right project, and that `PROVEKIT_ENDPOINT` is `https://provekit.online` (no trailing path).
- **`ModuleNotFoundError: langgraph`** — run `pip install -r requirements.txt` inside the
  activated virtualenv.
- **Traces are delayed** — spans are batched and flushed on exit; the demos flush before printing
  "Done". Give the portal a couple of seconds and refresh.

---

## Links

- **Portal:** https://provekit.online
- **Source & more examples:** https://github.com/MobirizerServices/ProveKit
- **PyPI:** https://pypi.org/project/provekit/
