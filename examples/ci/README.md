# CI gate examples

Copy-paste workflows for the [`provekit-eval` action](../../.github/actions/provekit-eval/),
which runs `pk.evaluate()` on a pull request, fails the build on a score regression, and
posts the per-scorer deltas as one sticky comment. Full reference:
[docs/CI_GATE.md](../../docs/CI_GATE.md).

| File | What it shows |
|---|---|
| `eval-gate.yml` | the minimum gate: evaluate on every PR, fail below a threshold, comment |
| `eval-gate-baseline.yml` | the same, plus deltas against the last run on `main` (cached baseline) and a `max-regression` limit |
| `eval_target.py` | the target function the action calls, and a custom scorer |

These are `.yml` files under `examples/`, not `.github/workflows/`, so they don't run in
this repo — they're templates. Copy one to `.github/workflows/eval-gate.yml` in yours.

## Before it works

1. A dataset in the portal with `{input, expected}` items — see
   [docs/EVALUATION.md](../../docs/EVALUATION.md). The examples use `qa-golden`.
2. Two repository secrets: `PROVEKIT_API_KEY` (a project key) and `PROVEKIT_ENDPOINT`
   (your ProveKit URL).
3. A target: any `fn(input) -> output`. `eval_target.py` is a stand-in that answers from a
   dict, so you can watch the gate work before pointing it at a real agent.

Secrets aren't available to workflows triggered by a pull request from a fork, so the eval
can only run on branches in your own repository.
