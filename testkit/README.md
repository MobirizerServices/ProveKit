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
| `loadtest.py` | An **OTLP ingest load harness** — spans/sec, ingest latency, error/shed rates. |

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

## Load-testing your instance

`loadtest.py` answers the question the demos can't: **how many spans per second will my instance
take, and how slow does ingest get before it starts refusing?** It POSTs real OTLP batches to
`/v1/traces` with a real project key — same path an exporter uses, auth, spool fsync, database
write, retention pruning and all. It imports nothing from the server, so it works against a
remote instance too.

Stdlib only. No `pip install`, not even `provekit`:

```bash
# against a local dev server — mints its own throwaway account + key
python testkit/loadtest.py --endpoint http://localhost:8000 --bootstrap --duration 30

# against an instance you already have a key for
PROVEKIT_API_KEY=pk_... python testkit/loadtest.py \
    --endpoint https://provekit.example.com --concurrency 8 --duration 60 --json result.json
```

```
ProveKit ingest load test
  target        http://localhost:8011  [sqlite, 1 worker, M5 laptop]
  load          4 exporters x 100 spans/batch, 10 spans/trace, 400B payload attrs
  duration      20.005s wall (+5.0s warmup discarded)

  spans/sec     10325.3   (103.25 batches/sec, 206800 spans accepted, 204.81 MB sent)
  latency ms    p50 36.31  p95 49.08  p99 53.36  max 91.6  (accepted batches only, n=2068)
  requests      2068 total / 2068 ok / 0 429 / 0 503 / 0 other / 0 transport errors
  rates         error 0.00%  shed 0.00%  rate-limited 0.00%
  spool before  {'spool': True, 'queue_depth': 0, 'lag_seconds': 0.0, ...}
  spool after   {'spool': True, 'queue_depth': 0, 'lag_seconds': 0.0, ...}
```

### Flags

| Flag | Default | What it does |
|---|---|---|
| `--endpoint` | `$PROVEKIT_ENDPOINT` or `http://localhost:8000` | Instance base URL |
| `--key` | `$PROVEKIT_API_KEY` | Project key (`pk_…`) |
| `--bootstrap` | off | Register a throwaway account on the target and mint a key. **Local instances only — it creates a real account.** |
| `--concurrency` | 4 | Concurrent exporters (each one keep-alive connection, one batch in flight) |
| `--batch-size` | 100 | Spans per POST. The biggest lever on spans/sec. |
| `--spans-per-trace` | 10 | Shape of the synthetic traces |
| `--span-bytes` | 400 | Prompt/completion text per span — payload size is real work |
| `--duration` / `--warmup` | 30 / 5 | Measured seconds, and seconds discarded first |
| `--target-rps` | 0 (closed loop) | Pace batches/sec regardless of server speed, to watch latency degrade under fixed offered load |
| `--interval` | 60 | Width of the per-window drift breakdown printed on long runs — a soak's whole point |
| `--label` | — | What this run is. Copied into the report. |
| `--json` | — | Write the full result, including the `/healthz` spool state, to a file |

### Reading the result honestly

- **`429`s mean you measured the rate limiter, not ingest.** The default `INGEST_RATE_PER_MIN=600`
  caps one *project* at 600 requests/minute — at 100 spans/batch that is ~1,000 spans/sec, whatever
  the hardware. The harness says so in a NOTE when 429s appear. Set `INGEST_RATE_PER_MIN=0` on the
  server when you want capacity.
- **Latency is reported for accepted batches only.** A 429 or a backpressure 503 is refused before
  any work happens; folding those in makes an overloaded server look faster the more it rejects.
  The line below it (`incl. refused`) shows the mixed figure when the two differ.
- **The load generator competes with the server when both run on one box.** Check that the client
  isn't the bottleneck: watch CPU per process, or split the same total concurrency across two
  processes and confirm the aggregate doesn't rise.
- **Closed loop by default.** N exporters each wait for their ack, so latency is service time at
  that concurrency. Throughput that stays flat while latency grows with `--concurrency` means the
  server is saturated, not that the harness is.
- **A long run prints per-window throughput and latency.** An average over ten minutes cannot
  distinguish a steady 10k spans/sec from one that started at 15k and decayed to 5k; the
  `per 60s window` block can. Use it for soaks, and quote the shape, not just the mean.
- **A number without its conditions is unusable.** Always record hardware, database (SQLite and
  Postgres differ enormously), batch size, worker count, and the spool/rate-limit settings — that
  is what `--label` and `--json` are for.

Published results from a run on a laptop, with all of that spelled out, are in
[`docs/PERFORMANCE.md`](../docs/PERFORMANCE.md).

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
