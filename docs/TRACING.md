# Tracing → tests

Capture what your agent actually did in the real world, then turn any run into a
regression test in one click. This is the **trace → test bridge**: point the decorator at
your agent, run it, and its inputs and outputs flow to ProveKit as *traces*; pick a trace
you care about and **Save as test** turns it into a runnable `.provekit` test you commit and
run in CI.

```
  @pk.trace          runs land as        Save as test        provekit run
  your agent  ──────▶  Traces in the ──────▶  a .provekit  ──────▶  green/red in CI
  (real runs)          portal               regression test
```

Unlike testing an agent from the outside (see the [LangGraph starter](../examples/langgraph-starter/)),
tracing observes your agent *from the inside* — so a test is seeded from a genuine
production interaction, not a hand-written guess.

---

## Quickstart

### 1. Get an API key

In the portal, open **API Keys** → name a key → **Create**. The `pk_…` value is shown
once; copy it. Put it in your agent's environment:

```bash
# .env
PROVEKIT_API_KEY=pk_...
PROVEKIT_ENDPOINT=https://provekit.your-company.com   # your ProveKit URL
```

`PROVEKIT_ENDPOINT` is wherever your ProveKit server is reachable (for local dev, the same
origin you open the portal on). Traces are shipped to `${PROVEKIT_ENDPOINT}/v1/traces`.

### 2. Decorate your agent

```bash
pip install "provekit[trace]"
```

```python
import provekit.trace as pk

@pk.trace(name="support-agent")
def run_agent(question: str) -> str:
    # ...your agent: LLM calls, tools, whatever...
    return answer
```

That's it. Every call to `run_agent` is captured as a run carrying its input and output.
Configuration is read from the environment automatically on first use.

### 3. See your runs

Run your agent as usual, then open **Traces** in the portal. Each captured run shows its
input, output, model, and status. (Runs also appear in the console's history.)

### 4. Save a run as a test

On a trace, click **Save as test**:

- It creates a **prompt** test whose input is the captured input.
- It seeds an **`llm_judge`** assertion — "the response should convey the same answer as
  this reference from the captured run, even if worded differently" — so the test passes on
  a correct answer even if the wording changes (far more robust than a substring match).
- Pick a **connection** in the dialog; it's wired to both the prompt target and the judge,
  so the test runs as-is. (Choose *Attach later* to set it in the console instead.)

The saved test is immediately runnable in the console, and exportable to a `.provekit`
file (see [the file format](FILE_FORMAT.md)).

### 5. Run it in CI

Export the saved test to a `.provekit` file, commit it under `.provekit/tests/`, and run
the suite headless — the same runner the rest of your tests use:

```bash
provekit run .provekit/tests/          # exit code is non-zero if any assertion fails
```

See [CONTRIBUTING](../CONTRIBUTING.md) and the [LangGraph starter](../examples/langgraph-starter/)
for a full CI workflow (`provekit run` + a connections file with `${ENV}` secrets).

---

## What gets captured

The decorator emits an OpenTelemetry span per call, tagged with the
[GenAI semantic conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/):

| what | captured as |
|---|---|
| the decorated call's inputs | `gen_ai.input.messages` (function args, JSON) |
| its return value | `gen_ai.output.messages` |
| success / failure | span status (an exception marks the run failed and re-raises) |
| duration | span timing |

Because it's **real OpenTelemetry**, any LLM instrumentation you already have installed —
e.g. OpenInference or OpenLLMetry for OpenAI/Anthropic — emits its own `gen_ai` spans into
the same trace, and those are captured too. You don't have to hand-annotate each model
call; decorate the entrypoint and the nested calls come along.

Every `gen_ai` span becomes a **run** (`type="trace"`) in your workspace. The same ingest
endpoint accepts OTLP from *any* exporter, so you can also point a stock OpenTelemetry
collector at `${PROVEKIT_ENDPOINT}/v1/traces` instead of using the decorator.

---

## API reference

### `@pk.trace(name=None, *, operation="invoke_agent")`

Wrap a function so each call is captured.

- `name` — the span/run label (defaults to the function name).
- `operation` — the `gen_ai.operation.name` tag (defaults to `"invoke_agent"`).

### `pk.configure(api_key=None, endpoint=None, *, batch=True)`

Wire up tracing explicitly instead of via the environment. Called automatically on first
use; call it yourself only to pass values in code or to change batching. Returns `True` if
tracing is active, `False` if it's a no-op. Idempotent.

- `api_key` / `endpoint` — default to `PROVEKIT_API_KEY` / `PROVEKIT_ENDPOINT`.
- `batch` — `True` batches exports in the background (default); `False` exports each span
  synchronously (useful in short-lived scripts and tests).

### Environment

| variable | meaning |
|---|---|
| `PROVEKIT_API_KEY` | a `pk_` key from **API Keys** in the portal |
| `PROVEKIT_ENDPOINT` | your ProveKit URL; traces ship to `${PROVEKIT_ENDPOINT}/v1/traces` |

---

## Fail-open by design

Tracing must never take your agent down. If `PROVEKIT_API_KEY`/`PROVEKIT_ENDPOINT` are
unset, the OpenTelemetry SDK isn't installed, or the portal is unreachable, tracing
degrades to a transparent no-op — your function runs exactly as it would without the
decorator. Export failures are swallowed and logged at debug level, never raised.

---

## How it works

The decorator uses the OpenTelemetry SDK to create spans and a minimal exporter that ships
them to `${PROVEKIT_ENDPOINT}/v1/traces` as OTLP-JSON, authenticated with your `pk_` key as
a bearer token. The server maps `gen_ai` spans into runs; **Save as test** maps a run into
a saved request plus an `llm_judge` assertion, which serializes to a `.provekit` file via
the same exporter the console uses. Nothing about your model calls is intercepted or
proxied — the decorator only observes.

---

## Notes & limits

- The seeded `llm_judge` needs an LLM connection to run (the one you pick, or one you
  attach later). Refine the criteria or swap assertion types in the console.
- The Traces view lists each captured span as its own run (a flat list, newest first),
  not yet a nested waterfall.
- Self-hosters set `PROVEKIT_ENDPOINT` to their instance; there is no default hosted
  endpoint.
- Secrets are never sent by the decorator — only the inputs/outputs you pass through the
  traced function. Redact anything sensitive before returning it if you don't want it
  captured.
