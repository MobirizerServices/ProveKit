# Publishing `provekit` to PyPI

`provekit` publishes via **Trusted Publishing** (OIDC) — **no token, no manual upload**. The
`0.1.0` release already shipped this way, so the publisher is configured; releasing is just a
git tag.

## Pre-flight (already green)

- ✅ Version bumped in `backend/pyproject.toml` (PyPI versions are immutable — each release
  needs a new number; `0.1.0` is taken).
- ✅ `python -m build` + `twine check` **PASSED**; a fresh `pip install "provekit[trace]"`
  installs lean (httpx + OpenTelemetry + instrumentors), imports, and the decorator works.

## Release (Trusted Publishing — the normal path)

The repo has `.github/workflows/publish.yml`: on a `v*` tag it runs the tests, checks the tag
matches the packaged version, and publishes over OIDC. **No token anywhere.**

```bash
# the tag must sit on a commit that has the target version in pyproject + publish.yml
git tag v0.2.0
git push origin v0.2.0
```

Watch it under the repo's **Actions** tab. When it's green, verify:

```bash
pip install "provekit[trace]"
python -c "import provekit.trace as pk; print('ok')"
```

**One-time PyPI setup** (already done for `0.1.0`, shown for reference): pypi.org → the
**provekit** project → *Settings* → *Publishing* → *Add a trusted publisher* with owner
`MobirizerServices`, repo `ProveKit`, workflow `publish.yml`, environment blank.

## Fallback: manual upload with a token

Only if you ever need to publish outside CI. Create a PyPI API token scoped to `provekit`,
then:

```bash
cd backend && rm -rf dist && python -m build
python -m twine upload dist/*      # username: __token__   password: <pypi-… token>
```

## Future releases

Bump `version` in `backend/pyproject.toml`, then `git tag vX.Y.Z && git push origin vX.Y.Z`.
The version-check gate refuses to publish if the tag and the pyproject version disagree.
