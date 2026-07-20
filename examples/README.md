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

## `complex_demo.py` — a deep multi-agent research orchestrator

A much larger flow for stress-testing the viewer: one run is a **37-span, 4-level-deep** trace
— an orchestrator that fans out to nested research **sub-agents**, each doing **RAG retrieval**
(a retriever with per-doc spans), analysis, a **flaky tool that fails then retries** (a red span
inside a successful run), a **critique → revise** reflection loop, and guardrail checks — then a
final synthesis across 3 models. Also emits a multi-turn session and a **fully failed run** whose
error bubbles up the tree.

```bash
python examples/complex_demo.py     # same PROVEKIT_API_KEY / PROVEKIT_ENDPOINT as above
```

Verified end-to-end: 4 traces, ~80 spans total, 25% error rate, ~4k tokens across
gpt-4o / gpt-4o-mini / claude-sonnet-5, with feedback scores and deep span metadata
(temperature, max_tokens, finish_reason). Great for showing off the Flow graph and Waterfall.

## `langgraph_demo.py` — a real LangGraph agent, auto-traced

Shows ProveKit's **zero-code auto-capture** with a real framework: a two-node LangGraph
(`retrieve` → `generate`) wrapped in a single `@pk.trace`. The graph nodes and the LangChain
LLM call nest underneath automatically via the OpenInference LangChain instrumentor — no manual
spans. Runs **fully offline** by default (a canned chat model stands in for the LLM, so no
OpenAI/Anthropic key is needed); set `OPENAI_API_KEY` to use `gpt-4o-mini` instead.

```bash
pip install "provekit[trace-all]" langgraph langchain-core
python examples/langgraph_demo.py     # same PROVEKIT_API_KEY / PROVEKIT_ENDPOINT as above
```

Verified end-to-end: one trace per question, each a `langgraph-agent → LangGraph → {retrieve,
generate → LLM}` flow with token usage on the model span — captured from the one decorator.

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
