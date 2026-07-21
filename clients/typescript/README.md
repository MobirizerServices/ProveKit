# ProveKit for TypeScript

Drop-in tracing for TypeScript/JavaScript agents. One import, and every run shows up in your
portal as a nested flow.

```bash
npm install provekit
```

```ts
import * as pk from "provekit";

pk.init();                       // reads PROVEKIT_API_KEY / PROVEKIT_ENDPOINT

const runAgent = pk.trace("support-agent", async (question: string) => {
  const docs = await pk.span("retrieve", () => search(question));
  return await pk.span("generate", () => llm(question, docs));
});

await runAgent("how do refunds work?");
await pk.flush();                // before a short-lived process exits
```

That produces one trace with three nested spans, timings, inputs/outputs, and failure status.

## Why it looks like this

- **Fail-open.** No key, no endpoint, or an unreachable portal degrades to a no-op. Your agent
  is never the thing that breaks because tracing did. The wrapped function runs untouched, and
  a thrown error propagates unchanged — the tracer records it and rethrows.
- **Zero runtime dependencies.** Node 18+ ships `fetch`, `AsyncLocalStorage` and `randomBytes`.
  An observability client that pulls in a tree of transitive packages is a liability in exactly
  the place you can least afford one.
- **Same wire format as the Python SDK** (OTLP/JSON to `/v1/traces`), so one ingest path and one
  span mapper serve both, and a mixed-language team sees one consistent trace.

## Provider auto-instrumentation

Wrap your client once and every completion becomes an LLM span with model, messages, tokens,
finish reason, and cost:

```ts
const openai = pk.observeOpenAI(new OpenAI());
const anthropic = pk.observeAnthropic(new Anthropic());
```

Streaming is handled: the span stays open until you finish draining the iterator, accumulating
the text and both token counts — and it closes even if you `break` early or the stream fails
mid-flight, so a trace is never left hanging.

This wraps rather than monkey-patching your imports. In ESM there is no interceptable `require`,
and a loader hook has to be installed before everything else and breaks under bundlers. One
visible line at the call site works identically in ESM, CJS, bundled and serverless — and when
the alternative failure mode is a silently untraced app, visible is the right trade. The wrapper
is a `Proxy`: your client isn't mutated, and methods we don't know about pass straight through.

## API

| | |
|---|---|
| `init(options?)` | Configure; returns whether tracing is active. Reads env by default. |
| `trace(name, fn, options?)` | Wrap an entrypoint — one call, one trace. |
| `observeOpenAI(client)` / `observeAnthropic(client)` | Capture every completion as an LLM span. |
| `startSpan(name, options?)` | A leaf span you end yourself (for work that outlives the call). |
| `span(name, fn, options?)` | Capture a sub-step; nests under the active trace. |
| `score(name, {score, value, comment})` | Attach feedback to the current trace. |
| `currentTraceId()` | Correlate your own logs with the trace. |
| `flush()` / `shutdown()` | Ship queued spans; call before exit. |
| `diagnose()` | Why nothing is being captured. |
| `isActive()` / `stats()` | Active state; queue depth and drop count. |

`options` accepts `sessionId` (groups multi-turn runs into a conversation), `attributes`, and
`operation`.

## Diagnosing silence

Fail-open means a missing key and a working setup look identical from the outside. `diagnose()`
says which you have — the counterpart of `provekit-doctor` on the Python side:

```ts
pk.init();
console.log(pk.diagnose());
// { active: false, problems: ["PROVEKIT_API_KEY is not set — create a project key in the portal."] }
```

It also catches the most common mistake: pointing `PROVEKIT_ENDPOINT` at `/v1/traces` instead of
the base URL, which otherwise produces a silent 404.

## Delivery behaviour

Spans are queued and flushed on a batch size (50) or interval (5s), whichever comes first.

- A **network failure** re-queues the batch for the next attempt.
- A **5xx** re-queues too — ingest is idempotent, so a replay can't duplicate spans.
- A **4xx** is dropped. A rejected batch will never succeed on replay, and retrying it would
  grow the queue forever.
- The queue is **bounded** (2048 by default). Past that the oldest spans are dropped and counted
  in `stats().dropped`, because a portal outage must not become your process's memory problem.

## Serverless

There is no background flush you can rely on when the runtime freezes between invocations.
`await pk.flush()` before returning from the handler.

## Not yet

Framework-level instrumentation (LangChain.js, the Vercel AI SDK, Mastra) — the Python SDK
auto-instruments around twenty libraries; here it's OpenAI and Anthropic, and everything else is
`pk.span()`. Browser support is out of scope while context propagation depends on
`AsyncLocalStorage`.

## Development

From this directory: `npm install && npm run build && npm test`.

Inside this monorepo you can skip the install and use the frontend's compiler:

```bash
../../frontend/node_modules/.bin/tsc -p tsconfig.test.json && node --test dist-test/test/*.test.js
```
