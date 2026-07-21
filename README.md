<div align="center">

# ◇ ProveKit

### See exactly what your AI agent did.

**Drop-in tracing, evaluation, and observability for any AI agent.** Add one import and review
every run — the model calls, tools, retries, and failures — as a nested flow. Then evaluate it,
watch it on a dashboard, and gate your CI on it. Open source and self-hostable.

[![CI](https://github.com/MobirizerServices/ProveKit/actions/workflows/ci.yml/badge.svg)](https://github.com/MobirizerServices/ProveKit/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**🌐 Live:** [provekit.online](https://provekit.online) · [Quickstart](#quickstart) · [How it works](#how-it-works) · [Self-hosting](docs/DEPLOY_PROVEKIT_ONLINE.md)

<img src="docs/launch/demo.gif" alt="ProveKit: one decorator captures the whole agent flow — a nested waterfall of the entrypoint, an auto-instrumented OpenAI call with tokens, and tool/step spans" width="820">

</div>

---

Most tracing tools make you stand up a collector, wire an exporter, or learn their model
before you see a single span. ProveKit's whole thesis is **time-to-first-trace**: create a
project, drop a key in `.env`, `pip install`, add **one import** — and the full nested flow
is in your portal. It's OpenTelemetry underneath (so your data is portable and nothing is
locked in), but you never have to know that.

**More than tracing:** evaluation (build datasets from real traces, score with `pk.evaluate()`,
gate CI on regressions), dashboards + alerts, multi-project with members, and a debug-over-MCP
channel. All open source, all self-hostable.

## Quickstart

**1. Create a project** and copy its key from the portal (Project keys).

**2. Add the SDK — one line:**

```bash
pip install "provekit[trace]"
```

```python
# .env
#   PROVEKIT_API_KEY=pk_...
#   PROVEKIT_ENDPOINT=https://provekit.online   # or your self-hosted URL

import provekit.auto        # one import — captures everything below it

# optional: group a run under a named root
import provekit.trace as pk

@pk.trace(name="support-agent")
def run_agent(question: str) -> str:
    docs = retrieve(question)          # wrap sub-steps with `with pk.span("retrieve"):`
    return llm(question, docs)         # OpenAI / Anthropic calls are captured automatically
```

**3. Run your agent, then open Traces** — every run appears as a nested tree: the entrypoint,
the model calls beneath it, the tools, the steps, each with its input, output, and timing.

## How it works

You decorate the **entrypoint once**. The decorator opens an OpenTelemetry span and makes it
the current context, so everything that runs inside nests underneath it:

- **LLM calls capture themselves.** `pip install "provekit[trace]"` auto-instruments OpenAI
  and Anthropic — no per-call wiring. Any other OTel-instrumented library nests too.
- **Sub-steps, your call.** Wrap a retrieval, a tool, or a branch in `with pk.span("name"):`
  to see it in the tree. Everything else is captured for you.
- **The portal rebuilds the tree** from the span hierarchy and renders it — agent → llm ·
  tool · step — with per-span input/output.

Fail-open by design: if the key/endpoint are unset or the portal is unreachable, your app
runs completely unaffected.

## What it is

The **trace is the front door** — that's the part you have to get right, and it's why the
integration is one import. Everything else builds on the captured run rather than asking you to
maintain a second source of truth:

- **Debug it** — open any LLM call, edit the prompt with real data, and re-run it; or fork the
  whole trace at a step and replay it. See [docs/DEBUGGING.md](docs/DEBUGGING.md).
- **Evaluate it** — promote interesting traces into a dataset, score a version against it with
  `pk.evaluate()`, and gate CI on the result. See [docs/EVALUATION.md](docs/EVALUATION.md).
- **Watch it** — dashboards over volume, error rate, latency, tokens, and cost, with threshold
  alerts.

Open source (MIT), self-hostable, and OpenTelemetry-native so you're never locked in.

- **Framework/provider-agnostic** — any Python agent; any OTLP exporter can also POST to
  `/v1/traces` directly (other languages included).
- **Self-hosted** — run it next to your app; see [docs/DEPLOY.md](docs/DEPLOY.md).

## Docs

- [Features](FEATURES.md) — the full inventory of what's built
- [Tracing guide](docs/TRACING.md) — the decorator, `pk.span()`, configuration, what's captured
- [Debugging guide](docs/DEBUGGING.md) — edit & re-run a captured call, replay a flow
- [Evaluation guide](docs/EVALUATION.md) — datasets, scorers, `pk.evaluate()`, CI gates
- [MCP debug channel](docs/MCP.md) — reason over your traces from Claude Desktop / Cursor
- [Deployment](docs/DEPLOY.md) — local vs hosted · [Publishing](docs/PUBLISHING.md) — release to PyPI
- [Security](SECURITY.md) · [Contributing](CONTRIBUTING.md) · [All docs](docs/README.md)
