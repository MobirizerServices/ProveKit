# CI gate — the GitHub Action

`pk.evaluate()` already returns a summary you can assert on, so a regression gate is a
`pytest` away ([EVALUATION.md](EVALUATION.md#4-gate-ci-on-regressions)). What every team then
writes by hand is the same forty lines of workflow YAML around it: install the SDK, thread
two secrets through, decide what "worse" means, and put the numbers somewhere a reviewer
will actually see them. This action is that part.

```
  pull request      provekit-eval action            the PR
  your target ────▶ pk.evaluate() → threshold ────▶ one sticky comment, per-scorer deltas
                                   → exit 1
```

## Quick start

```yaml
# .github/workflows/eval-gate.yml
name: Eval gate
on: pull_request

permissions:
  contents: read
  pull-requests: write        # so the action can post the score table

jobs:
  eval:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - uses: MobirizerServices/ProveKit/.github/actions/provekit-eval@main
        with:
          api-key: ${{ secrets.PROVEKIT_API_KEY }}
          endpoint: ${{ secrets.PROVEKIT_ENDPOINT }}
          dataset: qa-golden
          target: eval/targets.py:answer
          scorers: exact_match,contains
          threshold: "0.8"
```

You need three things first: a dataset with `{input, expected}` items in the portal, a
project key and endpoint as repository secrets, and a target — any `fn(input) -> output`.
Runnable templates live in [`examples/ci/`](../examples/ci/), including a target you can
point the action at before you have a real agent wired up.

The action lives in this repository at `.github/actions/provekit-eval`, so `uses:` names the
path. Pin it to a tag (`@v0.7.0`) rather than `@main` once you depend on it.

## What it does

1. `pip install provekit[trace]` on the runner (pin with `provekit-version`), plus your own
   `requirements` file if the target needs one.
2. Imports `target` and any custom scorers by `module:function` — or
   `path/to/file.py:function`, because an eval target in CI is as often a loose script as an
   installed package.
3. Calls `pk.evaluate(dataset, target, scorers=…, name=…)`. That's the same client-side
   entry point as a local run: it pulls the dataset by project key, runs the target per item,
   scores each output, and records an experiment in your portal.
4. Diffs the returned summary against a baseline, if you supplied one.
5. Writes the table to the job summary, posts it as a PR comment, **then** fails the job —
   in that order, so a failing gate never hides its own explanation.

## Gating

Two independent checks, both off by default — the action reports until you tell it what
"worse" means:

| Input | Fails the build when |
|---|---|
| `threshold` | `mean_score` is below this absolute floor |
| `max-regression` | `mean_score` fell more than this far below the baseline |

Set both. A floor alone can't see a slow slide down toward it; a tolerance alone can't see a
first run that was bad from the start. With neither, the job always passes and the comment
says so — useful for a week of watching the numbers before you commit to a number.

`soft-fail: "true"` keeps the report and drops the failure, for rolling the gate out on a
repo whose scores you don't trust yet.

Nothing scored is never a pass: an empty dataset, or scorers that produced no values, fails
the gate rather than sailing through on a `None` mean. Unknown scorer names are rejected up
front for the same reason — `run_scorers` skips a name it doesn't recognise, so a typo would
otherwise green-light a build that scored nothing.

## Baselines and deltas

The comment always shows this run's per-scorer means, n, and 95% interval. The **Δ** column
needs a baseline, and the project-key API can read one experiment by id but cannot list
experiments — so "the previous run" has to be handed to the action:

- **`baseline-experiment: "42"`** — a fixed reference run, fetched with the same project key.
  Good when you have a known-good experiment (the one you last shipped) to hold the line at.
- **`baseline-file: .provekit-baseline.json`** — a summary JSON an earlier run wrote. The
  action writes one every time (`summary-file`), so cache it on the default branch and
  restore it in pull requests. A missing file is a first run, not an error.

[`examples/ci/eval-gate-baseline.yml`](../examples/ci/eval-gate-baseline.yml) wires the cache
version end to end. It's safe to point `baseline-file` and `summary-file` at the same path:
the baseline is read before the eval runs, and overwritten after.

Deltas are a comparison, not a verdict. The interval in the comment is there to stop a team
shipping on noise — 0.82 vs 0.79 over 20 examples is nothing.

You no longer have to open the portal to get a p-value. See the next section.

## Gate on significance, not on a threshold

A threshold gate has one failure mode, and it is fatal to the gate itself: it fails on noise.
Run the same unchanged model over twenty examples twice and the mean moves a couple of points
either way. A gate that blocks on that blocks good changes, so somebody loosens the threshold,
and after two or three loosenings it blocks nothing at all.

`--baseline` asks the question a reviewer actually has — *did the score move more than chance
explains* — using the same paired permutation test the portal shows:

```bash
provekit eval run \
  --dataset regression-set \
  --command "python agent.py" \
  --baseline 196            # a known-good experiment id
```

```text
acc moved -0.040 — within noise (p=0.420, n=20); not blocking
provekit: no significant regression against experiment 196.
```

```text
provekit: acc regressed -1.000 and the move is real (p=0.000, n=20)
provekit: blocking — 1 scorer(s) regressed significantly against experiment 196.
```

An improvement never blocks, whatever its size.

### Exit codes

| Code | Meaning |
|-----:|---------|
| `0` | No significant regression. A dip within noise lands here, and says so. |
| `1` | A regression that is statistically real, or `--fail-under` was breached. |
| `3` | **Refused to judge** — the dataset changed between the two runs. |

`3` is deliberately not `1`. "Your change made it worse" and "I can't tell, and won't pretend
to" call for different reactions, and a pipeline that conflates them teaches people to ignore
the gate. If the dataset was edited between the baseline and this run, the delta is an artefact
of the edit and no p-value rescues it — re-run the baseline against the current dataset, or pass
`--allow-incomparable` to gate anyway.

### Which to use

`--fail-under` and `--baseline` answer different questions and compose:

- **`--fail-under 0.8`** — an absolute floor. *Never ship below this*, regardless of history.
- **`--baseline 196`** — a relative guard. *Don't ship a real regression*, however good the
  absolute number is.

Using both is normal: the floor catches a collapse with no baseline to compare against, and the
baseline catches a slow slide that never crosses the floor.

## The comment

> ### ProveKit eval — **FAIL**
>
> `qa-golden` · experiment **#128** (ci a1b2c3d) · 40 results
>
> | scorer | baseline | this run | Δ | n | 95% CI |
> |---|---|---|---|---|---|
> | `contains` | 0.900 | 0.850 | -0.050 | 40 | 0.738 – 0.962 |
> | `exact_match` | 0.750 | 0.750 | ±0.000 | 40 | 0.612 – 0.888 |
> | **mean** | 0.825 | 0.800 | -0.025 | 40 | — |
>
> Baseline: `.provekit-baseline.json` (experiment #121).
>
> ✔ mean **0.800** ≥ threshold 0.750
> ✘ mean moved **-0.025** vs baseline (allowed −0.020)

One comment per gate, updated in place: a hidden `<!-- provekit-eval:KEY -->` marker
identifies the comment the action owns, so a ten-commit PR ends with one current table
instead of ten stale ones. `KEY` defaults to the dataset name; set `comment-key` when a
single workflow gates several datasets.

Posting is best-effort. A read-only token or a missing `pull-requests: write` produces a
warning, not a failed job — the gate's verdict is decided by the scores, not by whether
GitHub accepted a comment. The table is always in the job summary either way.

## Inputs

| Input | Default | |
|---|---|---|
| `api-key` | — | **required.** Project key. Pass a secret. |
| `endpoint` | — | **required.** Your ProveKit URL. |
| `dataset` | — | **required.** Dataset name or id. |
| `target` | — | **required.** `module:function` or `file.py:function`. |
| `scorers` | `exact_match` | comma-separated built-in names and/or `module:function` |
| `threshold` | — | minimum mean score |
| `max-regression` | — | allowed drop vs baseline |
| `baseline-experiment` | — | experiment id to diff against |
| `baseline-file` | — | summary JSON to diff against |
| `experiment-name` | `ci <short sha>` | name recorded in the portal |
| `working-directory` | `.` | where to run and import from |
| `requirements` | — | pip requirements file for the target's deps |
| `provekit-version` | `provekit[trace]` | pip spec; pin for a reproducible gate |
| `comment` | `true` | post the PR comment |
| `comment-key` | the dataset | sticky-comment identity |
| `github-token` | `github.token` | token used to comment |
| `summary-file` | `provekit-eval-summary.json` | where the summary JSON is written |
| `soft-fail` | `false` | report without failing |

Outputs: `passed`, `mean-score`, `experiment-id`, `result-count`, `summary-file`,
`comment-file`. Use them to fan out — upload the summary as an artifact, or add a second
step that only runs when `passed == 'true'`.

Built-in scorers are `exact_match`, `contains`, `regex_match`, `json_valid`
([EVALUATION.md](EVALUATION.md#3-scorers)). Custom scorers are ordinary functions:

```python
# eval/scorers.py
def not_empty(output, expected):
    return 1.0 if output.strip() else 0.0
```

```yaml
scorers: contains,eval/scorers.py:not_empty
```

## Notes and limits

- **Fork pull requests can't run this.** GitHub withholds secrets from fork PRs, so there's
  no project key and no eval. That's a property of the trigger, not of the action; `pull_request_target`
  can work around it but hands untrusted code your key, so don't.
- **The eval calls your target for real.** Every item is a live run of your agent — model
  spend, rate limits and flakiness all apply on every push. Keep CI datasets small and
  deterministic, and put the 2,000-item set behind a nightly `schedule:` trigger.
- **Tracing covers what your target does, not the eval itself.** `pk.evaluate()` calls the
  target directly and does not wrap it in a span (`backend/provekit/eval.py`), so a target
  that only does a dict lookup produces no trace. `provekit[trace]` installs the
  auto-instrumentors, so a target that calls a model *is* captured — which is what makes a
  dropped score debuggable in the portal. Set `provekit-version: provekit` for scores only.
- **The runner's Python is used as-is.** The action doesn't install one — add
  `actions/setup-python` before it if the version matters.
- **Untested against a hosted portal from CI.** The action's logic is exercised locally, but
  no GitHub-hosted run against a live ProveKit instance is recorded in this repo. Expect to
  shake out endpoint/secret wiring on your first PR.
