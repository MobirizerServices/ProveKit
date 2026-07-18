# Publishing `provekit` to PyPI

This is what makes `pip install "provekit[trace]"` work for the world. **You run one command
with your own token — this repo never stores or sees credentials.**

## Pre-flight (already green)

These were verified when this guide was written:

- ✅ Version bumped to **0.2.0** in `backend/pyproject.toml` (PyPI already has `0.1.0` — the
  old build — and a version can never be re-uploaded, so each release needs a new number).
- ✅ `python -m build` produces a valid wheel + sdist; `twine check` **PASSED**.
- ✅ A fresh `pip install "provekit[trace]"` pulls a lean tree (httpx + OpenTelemetry +
  instrumentors — no server bloat), `import provekit.trace` works, the decorator is a no-op
  when unconfigured. Tests are excluded from the wheel; migrations are included.

> Note: `provekit` on PyPI already exists (your `0.1.0`, the old test-client). Publishing
> `0.2.0` continues that same package as the pivoted tracing product. That's intentional —
> you own the name.

---

## Path A — Publish now, with an API token (fastest, ~2 min)

Best when you want it live immediately from this branch, before merging.

1. **Create a PyPI API token:** pypi.org → your account → *Account settings* → *API tokens*
   → *Add API token*. Scope it to the **provekit** project. Copy it (starts with `pypi-…`).

2. **Build and upload** (from the repo root):

   ```bash
   cd backend
   rm -rf dist && python -m build            # writes dist/provekit-0.2.0*
   python -m pip install --upgrade twine     # if you don't have it
   python -m twine upload dist/*
   ```

   When prompted:
   - **username:** `__token__`
   - **password:** paste the `pypi-…` token

   (Or set `TWINE_USERNAME=__token__` and `TWINE_PASSWORD=<token>` to skip the prompts.)

3. **Verify** (in a fresh virtualenv):

   ```bash
   pip install "provekit[trace]"
   python -c "import provekit.trace as pk; print('ok')"
   ```

That's it — `pip install "provekit[trace]"` now works everywhere.

---

## Path B — Automated, no token (Trusted Publishing)

The repo already has `.github/workflows/publish.yml`: on a `v*` tag it runs the tests, checks
the tag matches the packaged version, and publishes via OIDC — **no token anywhere**. Use this
for every release after the first.

**One-time PyPI setup** (probably already done for `0.1.0`): pypi.org → the **provekit**
project → *Settings* → *Publishing* → *Add a trusted publisher*:

| Field | Value |
|---|---|
| Owner | `MobirizerServices` |
| Repository name | `ProveKit` |
| Workflow name | `publish.yml` |
| Environment name | *(leave blank)* |

**Release:**

```bash
# after the pivot is merged to main (publish.yml + the 0.2.0 code must be on the tagged commit)
git tag v0.2.0
git push origin v0.2.0
```

The workflow builds, tests, verifies `v0.2.0` == pyproject `0.2.0`, and publishes. Watch it
under the repo's *Actions* tab.

---

## Future releases

For each new release: bump `version` in `backend/pyproject.toml`, then either re-run Path A,
or (Path B) `git tag vX.Y.Z && git push origin vX.Y.Z`. The version-check gate refuses to
publish if the tag and the pyproject version disagree.
