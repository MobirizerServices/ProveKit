# Migrating from LangSmith or Langfuse

Nobody adopts a tracing tool on a blank page. You already have an agent, it already ships spans
somewhere, and the question is what breaks if you point it here instead. This is the concept
mapping and the import path — including the parts that don't come across, because a migration
guide that oversells gets found out on day one.

```
  your agent ──▶ OTLP/JSON ──▶ ${PROVEKIT_ENDPOINT}/v1/traces ──▶ Traces
                 (repoint the exporter, or swap the SDK)
```

## What actually moves

| | Moves? |
|---|---|
| **Traces from now on** | Yes — repoint the exporter (below) or swap the SDK. |
| **Your trace history** | No. There is no importer. Run both backends until your old retention window expires. |
| **Datasets** | By hand or by script. There's a create/append API, but it's session-authed — see [gaps](#what-does-not-come-across). |
| **Prompts (Langfuse prompt management)** | No. ProveKit has no runtime prompt registry. |
| **Metadata / tags / user ids** | No. Only `session.id` survives ingest. |

---

## Path 1 — repoint the OTLP exporter (fastest)

Both tools are OTel-capable, and ProveKit's ingest is a plain OTLP endpoint. If your spans
already reach LangSmith or Langfuse over OTLP, the migration is a URL and a header:

```bash
PROVEKIT_ENDPOINT=https://provekit.your-company.com   # spans go to ${...}/v1/traces
PROVEKIT_API_KEY=pk_...                               # Settings → Project keys
```

The endpoint accepts an OTLP `ExportTraceServiceRequest` at `POST /v1/traces`, authenticated by
`Authorization: Bearer <project key>`. A workspace ingest key (`POST /api/workspace/ingest-key`)
works too — the ingest path resolves either.

**The one caveat, and it matters: the endpoint reads JSON, not protobuf.** `ingest_traces` parses
the body as JSON; a protobuf body can't be parsed, and the handler answers `200` with
`{"partialSuccess": {"rejectedSpans": 0, "errorMessage": "invalid JSON"}}`. A standard exporter
reads that as *delivered* and moves on. You get silence, not an error — so **confirm a real trace
appears in the portal before you turn the old backend off.**

Practically:

- The OpenTelemetry **JS** OTLP/HTTP trace exporter serialises JSON, so it works as-is.
- The OpenTelemetry **Python** OTLP/HTTP exporter (`opentelemetry-exporter-otlp-proto-http`) is
  protobuf-only — there is no JSON mode to flip. Use the ProveKit SDK (Path 2) instead.
- An OpenTelemetry Collector in front, with the `otlphttp` exporter set to JSON encoding, is the
  general escape hatch for any language. **Untested against this repo** — no collector ships here
  and nothing in CI exercises that path. Verify it end to end before relying on it.

Stock OTLP-protobuf ingest is a known gap, tracked as item 49 in [ROADMAP.md](ROADMAP.md).

### Attribute dialects the mapper understands

`services/otel.py` reads three dialects, which is what makes a foreign exporter legible at all:

- **current** `gen_ai.*` (v1.37+) — `gen_ai.input.messages` / `gen_ai.output.messages`,
  `gen_ai.provider.name`, `gen_ai.request.model`, `gen_ai.usage.*`
- **legacy** — `gen_ai.prompt` / `gen_ai.completion` / `gen_ai.system`
- **OpenInference** — `llm.model_name`, `input.value` / `output.value`, and the flattened
  `llm.input_messages.{i}.message.{role,content}` form

Anything outside those keys is **discarded at ingest** — see [gaps](#what-does-not-come-across).

---

## Path 2 — swap the SDK

If you're on a native client (`langsmith`, `langfuse`) rather than raw OTel, the swap is small.
ProveKit's decorator goes on the **entrypoint only**; you don't annotate every function, because
the decorator opens an OTel span and makes it the current context, so instrumented libraries
below it nest by themselves.

```bash
pip install "provekit[trace]"        # or [trace-all] for ~20 instrumentors
```

```python
# before — a decorator per function
# @traceable                 (langsmith)
# @observe()                 (langfuse)

# after — one decorator at the top, plus pk.span() for your own steps
import provekit.trace as pk

@pk.trace(name="support-agent")
def run_agent(question: str) -> str:
    with pk.span("retrieve") as s:
        docs = search(question)
        s and s.set_attribute("gen_ai.output.messages", str(docs))
    answer = llm(question, docs)          # OpenAI/Anthropic calls captured automatically
    pk.score("relevance", score=0.9)      # was: create_feedback() / langfuse.score()
    return answer
```

Even shorter: `import provekit.auto` at your entrypoint calls `pk.init()` and captures everything
below it with no decorator at all. The decorator is only for grouping a run under one named root.

TypeScript is a separate client (`npm install provekit`, in `clients/typescript/`) with the same
shape: `pk.init()`, `pk.trace(name, fn)`, `pk.span(name, fn)`, `pk.score(...)`, and an explicit
`pk.flush()` before a short-lived process exits. It wraps provider clients rather than
monkey-patching — `pk.observeOpenAI(new OpenAI())` — and covers OpenAI and Anthropic only.

Full API: [TRACING.md](TRACING.md).

---

## Concept mapping — LangSmith

| LangSmith | ProveKit | Notes |
|---|---|---|
| **Run** | a **span** (one `Run` row) | Every span is stored and classified `agent · llm · tool · step`. LangSmith's run *types* are inferred here from attributes, not declared. |
| **Trace** (a run tree) | **trace** — spans sharing a `trace_id` | The tree is rebuilt client-side from `parent_span_id`. A trace whose root never arrived is still listed, badged **partial**. |
| **Project** | **project** (a workspace) | Selected by the project key on `/v1`, or `X-Project-Id` on `/api` (validated against membership). |
| **Dataset** / examples | **dataset** / items — `{input, expected}` | Seedable from a captured trace ("add to dataset"). Read by key at `GET /v1/datasets`; writes are session-authed. |
| **Evaluator** | **scorer** — `fn(output, expected) -> float` | Built-ins: `exact_match`, `contains`, `regex_match`, `json_valid`; custom scorers are plain functions passed to `pk.evaluate()`, and run **client-side**, in your process. An `llm_judge` scorer exists too, but only server-side in the portal's "run this prompt over a dataset" path. Either way it's offline, against a dataset — nothing scores your production traffic automatically. |
| **Experiment** (an eval run) | **experiment** | `pk.evaluate("qa-golden", target, scorers=[...])` returns `{id, result_count, scorer_means, mean_score}`; assert on it to gate CI. |
| **Feedback** | **feedback** | `pk.score(name, score=…, value=…, comment=…)`, the portal's 👍/👎, or `POST /v1/traces/{trace_id}/feedback`. Numeric *and* categorical, same as LangSmith. |
| **Annotation queue** | — | No queue. There is per-trace feedback and per-span notes, but no review workflow to route runs to a human. |
| **Thread** | **session** | `@pk.trace(session_id="conv-123")`, or a `session.id` / `gen_ai.conversation.id` / `thread.id` attribute on any span. |
| **Prompt hub** | — | See [gaps](#what-does-not-come-across). |

## Concept mapping — Langfuse

| Langfuse | ProveKit | Notes |
|---|---|---|
| **Trace** | **trace** | Same idea. Langfuse's trace-level `input`/`output` live on the root span here. |
| **Observation** | **span** | Every observation type lands as a span row; nothing is filtered out for not being an LLM call. |
| **Span** | **span**, classified `step` (or `tool` if it carries `gen_ai.tool.name`) | `with pk.span("retrieve"):`. |
| **Generation** | **span**, classified `llm` | Classification is by attribute: a span carrying a model or provider becomes an `llm` node, with model, token usage, temperature/top_p/max_tokens and finish reason surfaced. |
| **Event** (a point-in-time observation) | **span event** | Your `logging.*` calls (INFO+) attach to the active span as events and show up inline. No separate event object you create yourself. |
| **Score** | **feedback** | `pk.score()`. Numeric or categorical + comment; `source` distinguishes `sdk` from `human`. |
| **Session** | **session** | `session_id` on the decorator, or the `session.id` attribute. |
| **Prompt** (managed, fetched at runtime) | **saved prompt version** — *not equivalent* | See below. |
| **Dataset / dataset run** | **dataset / experiment** | Same shape: run a target over items, score, compare runs. |
| **`@observe()`** | `@pk.trace` at the entrypoint + `pk.span()` for sub-steps | You decorate once, not per function. |

---

## What does not come across

- **Metadata, tags, and user ids are dropped at ingest.** The span mapper keeps a fixed set of
  fields (type, label, model/provider, input, output, usage, params, finish reason, ids, session)
  and there is no raw-attribute column on the `runs` table. Everything else on the span is
  discarded. If you filter by `user_id` or a custom tag today, that workflow has no equivalent —
  `session.id` (and its aliases) is the only free-form grouping key that survives.
- **No prompt management.** Langfuse's `get_prompt()`-at-runtime pattern has no counterpart:
  prompt versions here are saved *from the playground* and served over `/api/prompts`, which is
  cookie-authed only. There is no key-authed route for an SDK to fetch a prompt by name, so
  prompts cannot be decoupled from your deploy.
- **Dataset writes need a session, not a project key.** `/v1/datasets` is read-only (list
  datasets, list items) — that's what `pk.evaluate()` uses. Creating a dataset and appending
  items is `POST /api/datasets` and `POST /api/datasets/{id}/items`, which authenticate with the
  portal session cookie. A bulk import script has to log in as a user; it can't use `pk_…`.
- **No historical backfill.** Nothing reads a LangSmith or Langfuse export. Plan on running both
  in parallel until your old data ages out.
- **No protobuf OTLP** — see Path 1.
- **No SQL or query API** over trace data. You get list/get/search over spans
  (`GET /v1/traces?q=…&status=failed&window_hours=…`), not arbitrary queries.
- **Costs are estimates** from a hardcoded price table that drifts as vendors reprice. If you
  reconcile spend against invoices today, don't switch that reporting over.
- **Retention is a span count, not a time window** — the newest N spans per project
  (`RUNS_RETENTION`, default 10000), pruned on write.

## What you get that they don't

Two honest tiers here.

**Table stakes, not a differentiator:** the single-call prompt playground — open an LLM span, edit
messages/model/params, re-run against your own provider key, diff the output. LangSmith, Langfuse,
Phoenix, Braintrust and most others have this. If it's why you're switching, you're switching for
the wrong reason.

**The actual difference — reconstructed replay.** ProveKit forks a whole trace at a chosen span
and re-runs the flow, not just the one call: the edited call runs live, its new output is threaded
into downstream calls that consumed it, and those re-run too. Steps before the fork are copied;
unrelated steps replay their recorded output. Whole-agent replay elsewhere is essentially
LangGraph-only, because it needs a resumable checkpoint; this is reconstructed from the trace, so
it works for any framework.

It is also honest about its own limits, which is the part that makes it usable. Every node is
badged **LIVE / SAME / RECORDED / DIVERGED**. Divergence propagates: a span whose input referenced
a changed value is diverged, anything reading its output is diverged too, and a diverged LLM call
is deliberately *not* re-run. A replay containing any diverged span returns `reliable: false` with
a fidelity breakdown and says so at the top of the trace view — it is a hypothesis, not a
reproduction. For an exact re-run, point ProveKit at a replay webhook and it ingests the real run
your own agent produces. Details: [DEBUGGING.md](DEBUGGING.md).

Two smaller things worth knowing: **every span is kept**, not just model calls (tools, retrieval,
your own steps and outbound HTTP all become nodes), and the whole thing is **self-hosted by
default** — there is no hosted endpoint, `PROVEKIT_ENDPOINT` is always your instance.

---

## Running both during the cutover

Tempting, and mostly fine at the *transport* level — but not by stacking two SDKs in one process.

`pk.configure()` builds its own `TracerProvider` and enables whichever instrumentors are installed
against it. An instrumentor that another vendor's SDK already instrumented is skipped silently
(the SDK treats "already instrumented" the same as "not installed" — both are non-fatal, by
design, so tracing never breaks your app). The result is a split: some spans go to the old
backend, some to ProveKit, and neither side has the whole tree. Context still propagates, so the
parent/child relationships look right in each half — which makes the loss easy to miss.

Safer parallel-run options, in order of preference:

1. **Duplicate at the collector.** Fan out one OTLP stream to both backends. Requires a collector
   and the JSON-encoding caveat above; untested here.
2. **Split by service or environment.** Point staging at ProveKit and production at the incumbent,
   then swap once you trust it.
3. **Just cut over** and keep the old backend readable until its retention expires. There's no
   backfill either way, so a clean cut costs you nothing you weren't already losing.

## Verify the switch

Fail-open means a misconfigured SDK and a working one look identical from the outside — nothing
throws, and your agent keeps running. So verify explicitly:

```bash
provekit-doctor          # walks the SDK's own path and reports the first thing that would stop a span
provekit-doctor --send   # posts one probe span end to end
provekit-demo            # fills a portal with a gallery of traces
```

In TypeScript the equivalent is `pk.diagnose()`, which returns `{active, problems}`.

Then open **Traces** and confirm you see a real run from your agent — with its children, its
inputs and outputs — before you decommission anything.
