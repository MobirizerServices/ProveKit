# ProveKit examples

Runnable demos for the tracing + evaluation SDK. They generate real data in your portal so a
fresh install has something to explore.

## `demo_agent.py` — populate a portal with realistic traces

A mock support agent (no LLM key needed — the model is stubbed) that produces a variety of
traces: nested agent → tool → LLM spans with token usage, app logs, a **multi-turn session**,
a **failed run**, and a **feedback score**. Great for a first look or a screen-share.

```bash
pip install "provekit[trace]"
export PROVEKIT_API_KEY=pk_...             # a project key from the portal (Project keys)
export PROVEKIT_ENDPOINT=https://your-provekit-host
python examples/demo_agent.py
```

Then open the portal:

- **Traces** — seven runs: standalone agent flows, a two-turn conversation grouped by
  `session_id`, and one red failed trace. Click any span for its input/output and logs.
- **Dashboard** — trace volume, an error rate (~14%), latency p50/p95, tokens, and a
  per-model breakdown (gpt-4o / gpt-4o-mini / claude-sonnet-5).

## Try evaluation

Once you have traces, use **"add to dataset"** on a trace (or the Datasets page) to build a
golden set, then score a version against it:

```python
import provekit as pk

def target(question: str) -> str:
    return my_agent(question)              # the thing you're evaluating

summary = pk.evaluate("qa-golden", target, scorers=["exact_match", "contains"])
assert summary["mean_score"] >= 0.8        # gate CI on regressions
```

See [../docs/EVALUATION.md](../docs/EVALUATION.md) for the full guide.
