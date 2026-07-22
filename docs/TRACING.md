# Tracing guide

Add one decorator at your agent's entrypoint and review the whole nested flow — model
calls, tools, and steps — in the portal. This is the entire product.

```
  @pk.trace          nested spans           the portal
  your entrypoint ──▶ ship to /v1/traces ──▶ rebuilds the agent-flow tree
```

## Setup

1. **Create a project** in the portal and copy its key (Project keys). It's shown once.
2. Put it in your agent's environment:

```bash
# .env
PROVEKIT_API_KEY=pk_...
PROVEKIT_ENDPOINT=https://provekit.your-company.com   # your ProveKit URL
```

3. Install and turn it on. Two ways, both one line at the client:

```bash
pip install "provekit[trace]"
```

```python
# Zero-code: one import at your program's entrypoint captures everything below it.
import provekit.auto

# ...or, if you want one run grouped under a named root, add the decorator:
import provekit.trace as pk

@pk.trace(name="support-agent")
def run_agent(question: str) -> str:
    ...
```

Run your agent, then open **Traces**. Each call is one trace; expand any span for its
input and output.

> **One SDK, nothing else at the client.** `import provekit.auto` (or `pk.init()`) is the
> whole integration — the decorator is optional sugar for grouping a run. You never add MCP,
> connectors, or per-call wiring in your app. Debugging *over* the captured data (MCP, REST)
> happens on the portal side — see [MCP debug channel](MCP.md).

## What gets captured

You decorate the **entrypoint once**. The decorator opens an OpenTelemetry span and makes
it the current context, so everything beneath it nests automatically:

| Source | Captured |
|---|---|
| **LLM & framework calls** | automatically — see the auto-instrumented list below |
| **Outbound HTTP** (tool APIs, vector DBs, webhooks) | automatically with `provekit[http]` — every `httpx`/`requests`/`urllib` call becomes a child span |
| Any OTel-instrumented library | automatically — it nests under the current span |
| Your own sub-steps (tools, retrieval, branches) | wrap them in `with pk.span("name"):` |
| Your `logging.*` calls | captured as **events** on the active span (INFO+; transport noise filtered). Disable with `pk.configure(capture_logs=False)`. |
| The decorated call | its input (args) and output (return), timing, and status |

Every span becomes a node in the trace, classified **agent · llm · tool · step**, with the
model, provider, token usage, and input/output captured.

### Auto-instrumented out of the box

`pip install "provekit[trace]"` auto-captures **OpenAI** and **Anthropic**. For the full set,
`pip install "provekit[trace-all]"` — one decorator then captures calls from any of these that
your project uses (each instrumentor is dormant unless its library is installed):

- **Providers:** OpenAI · Anthropic · Bedrock · Mistral · Groq · Google GenAI · Vertex AI · LiteLLM
- **Frameworks:** LangChain · LlamaIndex · CrewAI · AutoGen · OpenAI Agents · smolagents · DSPy · Haystack · Guardrails · Instructor · Agno · Pydantic AI
- **HTTP** (with `provekit[http]` or `[trace-all]`): `httpx` · `requests` · `aiohttp` · `urllib`

Anything else — your own tools, retrieval, business logic — you capture with `pk.span()`
(below). That's the honest split: **LLM/framework calls and outbound HTTP are automatic; your
own in-process steps are one line each.**

## Sub-steps with `pk.span()`

Wrap a retrieval, a tool call, or a branch to see it in the tree:

```python
@pk.trace(name="support-agent")
def run_agent(question: str) -> str:
    with pk.span("retrieve") as s:
        docs = search(question)
        s and s.set_attribute("gen_ai.output.messages", str(docs))
    return answer(question, docs)
```

`pk.span()` yields the OpenTelemetry span (or `None` when tracing is disabled — hence the
`s and ...` guard). Set `gen_ai.input.messages` / `gen_ai.output.messages` to show a step's
input/output in the portal.

## API

### `import provekit.auto`
Zero-code activation: importing this once at your entrypoint calls `pk.init()` for you.
Everything instrumented below it is then captured — no decorator required.

### `pk.init(api_key=None, endpoint=None, **kwargs)`
The one-line setup. Configures the tracer and turns on auto-instrumentation. Same as
`configure()`; returns `True` if active, `False` if a no-op.

### `@pk.trace(name=None, *, operation="invoke_agent")`
Decorate an entrypoint (or any function). `name` is the span label (defaults to the
function name). Optional — use it only to group one run under a single named root.

### `@pk.trace(..., session_id="conv-123")`
Pass `session_id` to group multi-turn runs (a conversation/thread) so the portal shows
them together.

### `with pk.span(name, **attributes)`
Capture a sub-step as a child span. Keyword attributes are attached to the span.

### `pk.score(name, *, score=None, value=None, comment=None, trace_id=None)`
Attach a feedback score to a trace from code — a heuristic, a guardrail, an LLM-judge:

```python
@pk.trace(name="support-agent")
def run_agent(q):
    answer = ...
    pk.score("relevance", score=0.9)              # numeric
    pk.score("thumbs", value="up", comment="ok")  # categorical + note
    return answer
```

Uses the current trace when `trace_id` is omitted. Fail-open (returns `False` if tracing
is off or there's no active trace). Humans can also score a run from the portal, and
external evaluators can `POST` to `/v1/traces/{trace_id}/feedback` with the project key.

### `pk.configure(api_key=None, endpoint=None, *, batch=True)`
Wire up tracing explicitly instead of via the environment. Called automatically on first
use; returns `True` if active, `False` if a no-op. Idempotent. `batch=False` exports each
span synchronously (handy in short scripts).

### Environment

| variable | meaning |
|---|---|
| `PROVEKIT_API_KEY` | the `pk_` project key from the portal |
| `PROVEKIT_ENDPOINT` | your ProveKit URL; traces ship to `${PROVEKIT_ENDPOINT}/v1/traces` |

## What gets stored, exactly

Two things happen to a payload between your agent and the portal, and both are recorded on
the span rather than applied silently.

**Truncation.** Captured input and output are stored up to **8,000 characters each**
(`MAX_PAYLOAD_CHARS` in `backend/provekit/services/otel.py`). Past that the tail is dropped —
not stored elsewhere, not recoverable; ProveKit keeps no copy you can't see. When it happens
the span carries a marker:

```json
"meta": { "truncation": { "input": { "stored_chars": 8000, "original_chars": 41233 } } }
```

So a cut answer is never rendered as if it were the whole one. If your payloads are routinely
larger, raise the constant and make sure your database can carry it.

**Redaction.** With PII redaction on (`REDACT_PII`, or per-project in Settings), matched
emails, cards, SSNs, keys and phone numbers are replaced with `[REDACTED_<TYPE>]` before
storage. The masking is regex-based, so it has false positives — the phone pattern will eat
any long digit run, including order and invoice numbers. Every masked span therefore records
what was touched:

```json
"meta": { "redaction": { "fields": ["input"], "counts": { "input": { "EMAIL": 2 } } } }
```

That marker is what makes a mangled output traceable to the masker instead of blamed on the
model.

**Measured quality.** Regex redaction has two failure modes and both are measured against a
labelled corpus (`backend/tests/fixtures/redaction_corpus.json`), re-run on every CI build:

| | rate |
|---|---|
| Recall (labelled PII that gets masked) | **100% recall** |
| False positives (clean text that gets mangled) | **18% false-positive rate** |

The false positives are all the same shape: long digit runs — ISBNs, order numbers, invoice
ids — are indistinguishable from a card number to a regex. They are listed explicitly in the
corpus rather than removed from it, so the published number stays honest and a future fix has
a target. Recall is measured over the patterns the corpus covers (emails, cards, SSNs,
provider keys, phone numbers); it is not a claim that nothing else is sensitive.

This is a safety net, not a guarantee. Don't put secrets in agent output and rely on this to
remove them.

## Fail-open

Tracing never takes your agent down. If the key/endpoint are unset, OpenTelemetry isn't
installed, or the portal is unreachable, tracing degrades to a transparent no-op — your
function runs exactly as it would without the decorator.

## Other languages / stock OpenTelemetry

ProveKit is OTel-native: the ingest endpoint accepts OTLP/JSON, so any OpenTelemetry
exporter (any language) can `POST` gen_ai spans to `${PROVEKIT_ENDPOINT}/v1/traces` with
your project key as a bearer token — the Python decorator is the batteries-included path,
not the only one.

## Notes

- Secrets are never sent by the decorator — only the inputs/outputs of the traced
  function. Redact anything sensitive before returning it if you don't want it captured.
- Self-hosters set `PROVEKIT_ENDPOINT` to their instance; there is no default hosted
  endpoint.

## OTLP protobuf (`Content-Type: application/x-protobuf`)

`/v1/traces` accepts the OTLP `ExportTraceServiceRequest` in **protobuf** as well as JSON.
The transport is chosen by the request's content type; everything after the decode — the
project key, the rate limit, the per-account span quota, the ingest spool, the
`(trace_id, span_id)` dedupe, retention — is the same code path either encoding takes.

```bash
curl -X POST "$PROVEKIT_ENDPOINT/v1/traces" \
  -H "Authorization: Bearer $PROVEKIT_API_KEY" \
  -H "Content-Type: application/x-protobuf" \
  --data-binary @batch.pb
```

The reply is a protobuf `ExportTraceServiceResponse` — **an empty body is a full success**,
which is what "no fields set" encodes to, not a stub.

This matters because protobuf is the default in most of the ecosystem, and until now the
server read every body as JSON:

| exporter | what it sends |
|---|---|
| Go `otlptracehttp` | protobuf; there is no JSON encoding option |
| Java / JS / .NET autoconfigure | `http/protobuf` is the default protocol |
| OpenTelemetry Collector `otlphttp` | `encoding: proto` by default |

A protobuf body used to come back `200 {"partialSuccess": {"rejectedSpans": 0,
"errorMessage": "invalid JSON"}}`. OTLP defines a 200 with zero rejected spans as success,
so exporters logged a warning at most, dropped the batch and never retried — the pipeline
looked healthy and the spans were gone. If you were told to route around this (see
[SDK_OTHER_LANGUAGES.md](SDK_OTHER_LANGUAGES.md)), you no longer have to.

A body that cannot be decoded now answers **400** with the reason in the response's
`error_message`, so a broken exporter is visible instead of silently discarded.

### Still missing: OTLP/gRPC on :4317

`OTEL_EXPORTER_OTLP_PROTOCOL=grpc` is **not** served. gRPC needs an HTTP/2 listener on its
own port, which the ASGI app cannot host — uvicorn serves HTTP/1.1 — so it means a second
server process, a second published port, and `grpcio` as a dependency. The payload itself is
already handled: gRPC carries the byte-identical `ExportTraceServiceRequest` this endpoint
now decodes.

Until it ships, put a collector in front and let it change transports for you — receive
OTLP/gRPC on 4317, export `otlphttp` to ProveKit:

```yaml
receivers:
  otlp:
    protocols:
      grpc: { endpoint: 0.0.0.0:4317 }
exporters:
  otlphttp:
    endpoint: https://provekit.your-company.com
    headers: { authorization: "Bearer pk_..." }
service:
  pipelines:
    traces: { receivers: [otlp], exporters: [otlphttp] }
```

The collector's `otlphttp` exporter posts protobuf, which is exactly the hop that used to
lose the batch.
