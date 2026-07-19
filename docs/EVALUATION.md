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

## 4. Gate CI on regressions

`pk.evaluate` returns the summary, so a failing score fails the build:

```python
def test_agent_quality():
    summary = pk.evaluate("qa-golden", target, scorers=["exact_match", "contains"])
    assert summary["mean_score"] >= 0.8       # block the merge on a regression
```

Compare runs over time in the portal: **Datasets → your set → Experiments** lists each run
with its per-scorer means side by side.

## Feedback vs. evaluation

- **Feedback** (`pk.score`, or 👍/👎 in the portal) attaches a score to a *single production
  trace* — see [TRACING.md](TRACING.md).
- **Evaluation** (this page) scores a *version against a dataset* — an offline experiment you
  can gate on. Together they close the loop: capture production traces → curate the
  interesting ones into a dataset → evaluate the next version against it.
