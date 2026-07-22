# `provekit-eval` action

Runs `pk.evaluate()` on a pull request, fails the build on a score regression, and posts the
per-scorer deltas as one sticky comment.

```yaml
- uses: MobirizerServices/ProveKit/.github/actions/provekit-eval@main
  with:
    api-key: ${{ secrets.PROVEKIT_API_KEY }}
    endpoint: ${{ secrets.PROVEKIT_ENDPOINT }}
    dataset: qa-golden
    target: eval/targets.py:answer
    scorers: exact_match,contains
    threshold: "0.8"
```

**Usage and every input: [docs/CI_GATE.md](../../../docs/CI_GATE.md).** Copy-paste workflows:
[examples/ci/](../../../examples/ci/).

## Layout

| File | |
|---|---|
| `action.yml` | the composite action — install, evaluate, comment, then fail |
| `gate.py` | calls `pk.evaluate()`, diffs against the baseline, renders the report |
| `comment.py` | creates or updates the sticky PR comment (standard library only) |

The logic lives in Python files rather than inline `run:` blocks so it can be read and fixed
without hunting through YAML escaping, and so the gate's rules are reviewable in one place.
Inputs reach those scripts as `INPUT_*` environment variables — never interpolated into a
shell command, where a crafted dataset name would be an injection.

This is an action *inside* a product repo, not a repo that is an action: `action.yml` sits
here rather than at the root so the root stays ProveKit's. The path form of `uses:` works the
same for consumers; only a GitHub Marketplace listing would require the root.
