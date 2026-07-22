# Adding an instrumentor

**The short version:** you do not write an instrumentor. You add one JSON fixture proving
ProveKit maps your framework's spans correctly, and — if it doesn't — you fix
`backend/provekit/services/otel.py::map_span` until the fixture passes.

This is the best first contribution in the repo. The fixture is a file, the test suite tells
you exactly which field is wrong, and you can do the whole thing without running an LLM.

---

## Why it works this way

ProveKit doesn't instrument frameworks itself. `provekit/trace.py` activates whatever
[OpenInference](https://github.com/Arize-ai/openinference) and
`opentelemetry-instrumentation-*` packages you have installed (`_INSTRUMENTORS` and
`_HTTP_INSTRUMENTORS`), those emit OTel spans, and ProveKit's job starts at ingest:
`map_span` turns each span into a run the portal can show.

So "support CrewAI" is not a feature you build — it's a mapping you prove. `map_span` is the
widest-contract function in the backend: ~20 instrumentor families, three attribute dialects,
one classification ladder deciding what the reviewer actually sees. Every genericness bug the
project has shipped was a span that mapped wrong, and each was invisible to a suite that only
tested the shape ProveKit's own SDK emits.

That's what `backend/tests/test_dialects.py` exists for. **Read its module docstring before you
start** — it is the spec; this guide is the on-ramp to it.

### The three dialects

| Dialect | Looks like | Emitted by |
|---|---|---|
| `genai_current` | `gen_ai.input.messages`, `gen_ai.provider.name`, `gen_ai.request.model`, `gen_ai.usage.input_tokens` | OTel GenAI semconv v1.37+ (ADK, Strands, Pydantic AI, newer OTel instrumentors) |
| `genai_legacy` | `gen_ai.prompt`, `gen_ai.completion`, `gen_ai.system`, and the flattened `gen_ai.prompt.{i}.role` form | OpenLLMetry / Traceloop, older OTel releases |
| `openinference` | `llm.model_name`, `llm.provider`, `input.value`, `output.value`, `llm.input_messages.{i}.message.content`, `openinference.span.kind` | every `openinference-instrumentation-*` package |

A fourth value, `http`, is not a GenAI dialect: it's the no-`gen_ai.*` case (an outbound tool
API call from `requests`/`httpx`/`urllib`). Those spans must still produce a usable **step**.

The same provider emits **all three** depending on which instrumentor is installed, and that is
exactly where the mapping drifts — which is why `openai`, `anthropic` and `bedrock` are each
pinned in all three by `test_each_provider_family_covers_every_genai_dialect`.

---

## Add a fixture in four steps

### 1. Capture a real span

Fixtures are pinned against **realistic payloads, not hand-made ones** — a mapping asserted
against a toy span proves nothing. Point the SDK at a local recorder instead of a portal and run
your agent once:

```python
# sink.py — writes every OTLP batch the SDK exports to ./captured/
import http.server, itertools, pathlib

out, n = pathlib.Path("captured"), itertools.count()
out.mkdir(exist_ok=True)

class H(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"] or 0))
        (out / f"batch{next(n)}.json").write_bytes(body)
        self.send_response(200); self.end_headers(); self.wfile.write(b"{}")

http.server.HTTPServer(("127.0.0.1", 4318), H).serve_forever()
```

```bash
python sink.py &
PROVEKIT_ENDPOINT=http://127.0.0.1:4318 PROVEKIT_API_KEY=pk_local python your_agent.py
```

Each file is an OTLP `ExportTraceServiceRequest`; your spans are at
`resourceSpans[].scopeSpans[].spans[]`. Pick the **one** span that shows the thing you're
proving — a fixture is one span, not a trace.

> No agent handy? Copy the closest file in `backend/tests/fixtures/otlp/` and edit the
> attributes to match what your instrumentor's source says it emits. That is how several of the
> existing fixtures were built. Say so in the `note` — an attribute set read off the
> instrumentor's source is honest; one invented to make a test pass is not.

### 2. Write the fixture

One standalone JSON document per span, in `backend/tests/fixtures/otlp/`, named
`{framework}_{operation}_{dialect}.json`:

```json
{
  "instrumentor": "crewai",
  "dialect": "openinference",
  "note": "why this payload looks like this — and what breaks if the mapping changes",
  "span": {
    "traceId": "32 hex chars",
    "spanId": "16 hex chars",
    "parentSpanId": "16 hex chars",
    "name": "Crew.kickoff",
    "startTimeUnixNano": "1753142900000000000",
    "endTimeUnixNano": "1753142901500000000",
    "status": {"code": 1},
    "attributes": [
      {"key": "openinference.span.kind", "value": {"stringValue": "AGENT"}}
    ]
  },
  "expect": {
    "type": "agent",
    "label": "Crew.kickoff",
    "duration_ms": 1500,
    "request.operation": "invoke_agent"
  },
  "expect_absent": ["result.meta.tool"]
}
```

- `instrumentor` — the **module tail** from `trace.py`'s instrumentor lists
  (`openinference.instrumentation.llama_index` → `llama_index`). An unknown value fails
  `test_fixture_is_wellformed`.
- `dialect` — `genai_current` | `genai_legacy` | `openinference` | `http`.
- `note` — required, and it is the point. Write *why the payload looks like this*, so the next
  person reading a failure knows whether the fixture or the mapping is wrong. The fixtures
  promoted from real bugs each keep the story of the bug they caught.
- `span` — exactly what the exporter sends. Real ids (`traceId` 32 hex, `spanId` 16 hex — the
  columns are `String(32)`/`String(16)`), real nanosecond timestamps with `end > start`.
- `expect` — dotted paths into the kwargs `map_span` returns, e.g. `request.model`,
  `result.meta.usage.input_tokens`. **Every key becomes its own test case**, so a failure names
  the exact field that moved. A list/dict expectation is compared against the *parsed* stored
  string, so you can write the message array a contributor would recognize instead of matching
  `json.dumps` spacing. `expect.type` is mandatory — pin the node type or a broken classification
  ladder slips past you.
- `expect_absent` — asserts a conditionally-written field was **not** set. It may only name
  paths in the suite's `OPTIONAL_FIELDS` set, so a typo can't silently "pass" by being absent
  from every run.

Give the span a **unique** `spanId` across the whole corpus: ingest dedupes on
`(trace_id, span_id)`, and a copy-pasted id makes the end-to-end test assert on one row twice.

### 3. Run the suite

```bash
cd backend && ./venv/bin/python -m pytest tests/test_dialects.py -q
```

Then the full gate before you open the PR:

```bash
cd backend && ./venv/bin/python -m ruff check provekit
cd backend && ./venv/bin/python -m pytest tests/ -q
```

### 4. If it fails, decide which side is wrong

Read the failure. It names a field: `request.model: expected 'gpt-4o', got None`.

- **Your expectation was wrong** → fix the fixture, and put what you learned in the `note`.
- **The mapping is wrong** → fix `map_span`, and leave a comment saying *why* the old behaviour
  was broken and what a user saw. That is the house style; `services/otel.py` is full of them.

**There is nowhere to park a known-broken mapping.** The `known_gaps/` directory that held
payloads ProveKit mapped wrong is intentionally gone: a slot for broken mappings invites adding
one instead of fixing it. A newly discovered gap is a **failing fixture, and it stays failing
until someone fixes the mapping.**

---

## What the mapping must satisfy

These are the invariants `map_span` is held to. If your framework needs one of them bent, that's
a design conversation in the issue, not a quiet edit.

**Every span is kept.** Not just the LLM calls — the full nested flow is the product. A span
with nothing recognizable still becomes a `step` labelled with its span name.

**The classification ladder, in order.** First rung that matches wins:

1. `gen_ai.tool.name` or `tool.name` present, or `openinference.span.kind == "TOOL"` → **tool**.
   A tool call made by an agent also carries the agent's operation and the model that chose it;
   it is still a tool span, or the tool timeline loses the call.
2. `gen_ai.operation.name == "invoke_agent"`, or `openinference.span.kind == "AGENT"` → **agent**.
3. a model **or** provider attribute → **llm**.
4. otherwise → **step**.

A span carrying only GenAI *payload* attributes (`gen_ai.input.messages` on a guardrail or
chain span) is **not** an LLM call. Counting it as one inflates the model-call count and the
cost estimate.

**Aliases are ordered, and the order is load-bearing.** Instrumentors mix dialects on one span
— OpenInference emits `llm.*` alongside `session.id`, a proxy adds `gen_ai.*`. `map_span` reads
each field through a fixed key list (model, provider, session, input/output tokens, prompt,
completion, finish reason), and `test_alias_precedence` pins every position in every list. Adding
a key means adding it *in the right place*, and the empty string never wins a race: redaction and
some instrumentors write `""` instead of dropping the key, so an empty value falls through to the
next alias.

**Indexed message attributes are first-class.** OpenInference's
`llm.input_messages.{i}.message.content` and Traceloop's `gen_ai.prompt.{i}.content` are
reconstructed into a messages array *before* the flat keys are consulted, because they travel as
independent attribute sets — separate redaction config, and the OTel SDK's 128-attribute-per-span
cap can evict one while the other survives.

**Ids and time survive.** `trace_id`, `span_id`, `parent_span_id` are carried through so the
portal can rebuild the tree; `start_ns` is stored as a **string** because epoch nanoseconds
overflow JavaScript's 53-bit floats. A malformed timestamp costs its own span's duration, never
the batch — ingest retains what it fails to persist, so one bad span must not be retried forever.

**Payloads are truncated visibly.** Anything over `MAX_PAYLOAD_CHARS` (8000) is cut, and
`result.meta.truncation` records the original length. Nothing is stored where the user can't see
it, and a truncated answer must never read as a complete one.

**Coverage does not regress.** `REQUIRED_FAMILIES` (the providers and frameworks users actually
arrive with, plus the generic HTTP instrumentors) must stay covered, and `openai`/`anthropic`/
`bedrock` must each stay pinned in all three GenAI dialects.

**It has to survive the round trip.** `test_every_fixture_persists_through_the_ingest_endpoint`
posts the whole corpus to the real `/v1/traces` on the real app and reads the rows back, so a
fixture also proves the router, redaction and the spool didn't eat it. `map_span` returning the
right dict is only half the contract.

---

## Adding a genuinely new framework

If the framework has no instrumentor at all, the mapping still isn't the first question:

1. Check whether an `openinference-instrumentation-*` or `opentelemetry-instrumentation-*`
   package already exists upstream. If it does, the contribution is a fixture (above) plus a
   line in `_INSTRUMENTORS` in `backend/provekit/trace.py`, and it lights up for everyone.
2. If it doesn't, upstream is usually the right place to write it — a framework instrumented in
   OpenInference works with every OTel-based tool, not just this one.
3. If the framework emits OTel spans of its own, no instrumentor is needed at all: point its
   OTLP exporter at `/v1/traces` (see [Go & Java](SDK_OTHER_LANGUAGES.md)) and add a fixture for
   the dialect it emits.

---

## Where things live

| | |
|---|---|
| The mapping | `backend/provekit/services/otel.py` (`map_span`) |
| The conformance suite + its spec | `backend/tests/test_dialects.py` |
| The fixtures | `backend/tests/fixtures/otlp/*.json` |
| Which instrumentors are activated | `backend/provekit/trace.py` (`_INSTRUMENTORS`, `_HTTP_INSTRUMENTORS`) |
| Per-framework setup docs | [QUICKSTARTS.md](QUICKSTARTS.md) |
| Everything else about contributing | [CONTRIBUTING.md](../CONTRIBUTING.md) |
