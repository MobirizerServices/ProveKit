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

3. Install and decorate:

```bash
pip install "provekit[trace]"
```

```python
import provekit.trace as pk

@pk.trace(name="support-agent")
def run_agent(question: str) -> str:
    ...
```

Run your agent, then open **Traces**. Each call is one trace; expand any span for its
input and output.

## What gets captured

You decorate the **entrypoint once**. The decorator opens an OpenTelemetry span and makes
it the current context, so everything beneath it nests automatically:

| Source | Captured |
|---|---|
| OpenAI / Anthropic calls | automatically — the `[trace]` extra auto-instruments them |
| Any OTel-instrumented library | automatically — it nests under the current span |
| Your own sub-steps | wrap them in `with pk.span("name"):` |
| The decorated call | its input (args) and output (return), timing, and status |

Every span becomes a node in the trace, classified **agent · llm · tool · step**.

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

### `@pk.trace(name=None, *, operation="invoke_agent")`
Decorate an entrypoint (or any function). `name` is the span label (defaults to the
function name).

### `with pk.span(name, **attributes)`
Capture a sub-step as a child span. Keyword attributes are attached to the span.

### `pk.configure(api_key=None, endpoint=None, *, batch=True)`
Wire up tracing explicitly instead of via the environment. Called automatically on first
use; returns `True` if active, `False` if a no-op. Idempotent. `batch=False` exports each
span synchronously (handy in short scripts).

### Environment

| variable | meaning |
|---|---|
| `PROVEKIT_API_KEY` | the `pk_` project key from the portal |
| `PROVEKIT_ENDPOINT` | your ProveKit URL; traces ship to `${PROVEKIT_ENDPOINT}/v1/traces` |

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
