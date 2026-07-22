# Evaluation guide

Beyond tracing, ProveKit can **grade** your agent: build datasets, run a version against
them, score the outputs, and compare runs to catch a regression before it ships.

```
  dataset            pk.evaluate(target, scorers)        experiments
  {input, expected} ─────────────────────────────────▶  per-scorer means, compared
```

## 1. Build a dataset

A dataset is a named set of `{input, expected}` examples. Create one in the portal
(**Datasets**), add items by hand, or seed them straight from a captured trace ("add to
dataset" uses the trace's input as the item input and its output as the expected).

Via the API:

```bash
curl -X POST $PROVEKIT_ENDPOINT/api/datasets -d '{"name":"qa-golden"}'
```

## 2. Score with `pk.evaluate()`

Run a target function over every item, score each output, and record an experiment:

```python
import provekit as pk

def target(question: str) -> str:
    return my_agent(question)          # the thing you're evaluating

summary = pk.evaluate(
    "qa-golden",                       # dataset name (or id)
    target,
    scorers=["exact_match", "contains"],
)
print(summary["mean_score"], summary["scorer_means"])
```

`pk.evaluate` pulls the dataset by project key, runs the target per item, applies the
scorers, posts the results as an experiment, and returns its summary.

## 3. Scorers

Built-in (from `provekit.scorers`), each returns a float in `[0, 1]`:

| Scorer | 1.0 when |
|---|---|
| `exact_match` | output equals expected (trimmed) |
| `contains` | expected appears in output (case-insensitive) |
| `regex_match` | the expected regex matches output |
| `json_valid` | output parses as JSON |

Bring your own — any `fn(output, expected) -> float`:

```python
def not_empty(output, expected):
    return 1.0 if output.strip() else 0.0

pk.evaluate("qa-golden", target, scorers=["exact_match", not_empty])
```

These all grade one string against another. For an agent that is rarely the whole question —
[§5](#5-scoring-more-than-the-final-string) grades the path it took, whether its answer is
grounded in what it retrieved, and what the run cost.

## 4. Gate CI on regressions

`pk.evaluate` returns the summary, so a failing score fails the build:

```python
def test_agent_quality():
    summary = pk.evaluate("qa-golden", target, scorers=["exact_match", "contains"])
    assert summary["mean_score"] >= 0.8       # block the merge on a regression
```

Compare runs over time in the portal: **Datasets → your set → Experiments** lists each run
with its per-scorer means side by side.

## 5. Scoring more than the final string

An agent's answer is not all of what it did. The scorers below grade the *path* it took, the
*context* it retrieved, and what the run *cost* — all of which ProveKit already captures per
span. They keep the same `fn(output, expected) -> float` contract, so they are just names in
the same list; what changes is that the target returns a payload instead of prose:

```python
def target(question: str):
    answer, trace_id = my_agent(question)
    spans = httpx.get(f"{PROVEKIT_ENDPOINT}/v1/traces/{trace_id}",
                      headers={"Authorization": f"Bearer {PROVEKIT_API_KEY}"}).json()
    return {
        "question": question,
        "answer":   answer,
        "context":  my_agent.last_chunks,   # retrieved chunks, for the RAG scorers
        "spans":    spans,                  # the captured span tree, for the trajectory ones
        "cost_usd": 0.004, "latency_ms": 1830,
    }
```

`pk.evaluate` json-dumps a non-string result, so nothing else changes. Every key is optional,
and the list `GET /api/traces/{trace_id}` returns is accepted as the payload on its own —
score a captured trace with no extra plumbing.

> **A scorer that can't grade a row is left out of that row, not scored 0.0.** `no_repeat` on
> an output with no spans, `cost_budget` on a run nothing priced — the key is simply absent,
> so the experiment mean stays over the rows the scorer could actually grade. Zero would be
> indistinguishable from a genuine failure and would move the mean by just as much.

Every scorer gets the same `expected` for an item, so when several of these run together the
item's `expected` is one JSON config object and each picks out its own key:

```json
{"tools": ["search", "summarize"], "max_steps": 12,
 "max_cost_usd": 0.02, "max_latency_ms": 2000, "max_tokens": 4000}
```

A bare value (`"search,summarize"`, `"12"`) still works when only one of them is in play. A
scorer whose key is missing or unusable scores `0.0` — a misconfigured budget is a mistake
worth seeing, not a row to skip.

### 5.1 Trajectory scorers

The trajectory is a pre-order walk of the span tree, siblings in start order — the portal's
waterfall read top to bottom. Spans are ordered by their captured start time, never by
arrival order, and a span whose parent never arrived is promoted to a root rather than
dropped, so a partial trace is still scoreable.

| Scorer | `expected` key | 1.0 when |
|---|---|---|
| `expected_tools_used` | `tools` | every named tool was called (order ignored) |
| `tool_order` | `tool_order`, else `tools` | those tools were called in that order, extra calls in between allowed |
| `no_repeat` | — | no tool was called twice with the *same* arguments |
| `step_budget` | `max_steps` | the run took ≤ that many steps (any span but the `agent` wrapper) |

Each degrades rather than flipping to zero: `expected_tools_used` is the share of the tools
found, `tool_order` the longest expected sequence that fits in order, `no_repeat` is
unique/total calls (five identical calls → `0.2`), `step_budget` is budget/steps (twice the
budget → `0.5`).

```python
pk.evaluate("agent-golden", target,
            scorers=["expected_tools_used", "tool_order", "no_repeat", "step_budget"])
```

A tool call is a span carrying `gen_ai.tool.name` (a plain `{"tool": ..., "args": {...}}`
works too), and its arguments are normalised — key order and whitespace don't make two
identical calls look like progress.

### 5.2 RAG scorers

| Scorer | Asks | Needs |
|---|---|---|
| `faithfulness` | is the answer supported by the retrieved context? | `context` + `answer` |
| `context_relevance` | was the retrieval any good? | `context` + `question` |
| `answer_relevance` | does the answer address the question asked? | `question` + `answer` |

Context comes from the payload (`context` / `contexts` / `retrieved` / `documents` /
`chunks`; strings, or dicts with a `text`/`page_content` field), and failing that from the
output of the trajectory's retrieval spans — a tool whose name mentions retrieve, search,
lookup, vector, index, query or embed.

**These are model-graded questions, and they work without a model.** `provekit.scorers` is
client-side and never imports a provider client, so out of the box each one is a lexical
estimate: `faithfulness` is the share of the answer's sentences whose content words appear in
the context (which catches an invented sentence among grounded ones), the other two are
question/answer word overlap. Install a judge to upgrade all three in place:

```python
from provekit import scorers

scorers.set_judge(lambda prompt: my_model(prompt))   # -> float in [0, 1], or None
```

The judge is asked for a single number. Returning `None` — or raising, which is what a
missing API key looks like — falls back to the lexical estimate for that row rather than
failing the eval run. That is the whole degrade path: no key costs you precision, not a
build.

### 5.3 Cost & latency as eval axes

Quality on its own can't decide anything. "3% better for 4x the cost" is the actual call, and
these put the second half of it on the same scale as the first:

| Scorer | `expected` key | Reads |
|---|---|---|
| `cost_budget` | `max_cost_usd` | `cost_usd` on the payload, or summed per span |
| `latency_budget` | `max_latency_ms` | `latency_ms`, else the trajectory's root duration |
| `token_budget` | `max_tokens` | `usage` on the spans — no price table needed |

Each scores 1.0 at or under budget and `budget / actual` above it, so **4x the budget reads
as `0.25`** rather than clipping every over-budget run to the same zero — the ratio is the
part you were trying to see. Compare two experiments and the trade-off is on the page:
`exact_match` +0.03, `cost_budget` 1.00 → 0.25.

Cost is never priced from tokens here: the price tables are versioned and server-side
(`services/pricing.py`), so a client-side scorer inventing its own would silently disagree
with the portal. Pass `cost_usd`, or use `token_budget`, which works on any captured trace.

## Feedback vs. evaluation

- **Feedback** (`pk.score`, or 👍/👎 in the portal) attaches a score to a *single production
  trace* — see [TRACING.md](TRACING.md).
- **Evaluation** (this page) scores a *version against a dataset* — an offline experiment you
  can gate on. Together they close the loop: capture production traces → curate the
  interesting ones into a dataset → evaluate the next version against it.
