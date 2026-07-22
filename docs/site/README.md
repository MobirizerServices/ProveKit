# The docs site

A MkDocs (Material) scaffold that renders **the markdown already in `docs/`** into a searchable
site. Roadmap item #33.

> **There is no hosted docs site.** Nothing here deploys. CI builds the site on every PR so a
> broken build is caught, and that is the whole of it — no domain, no GitHub Pages branch, no
> published URL. Anything you read below about publishing describes work that has *not* been
> done.

## Build it

```bash
python -m venv docs/site/.venv
docs/site/.venv/bin/pip install -r docs/site/requirements.txt
docs/site/.venv/bin/mkdocs build --strict -f docs/site/mkdocs.yml   # → build/docs-site/
docs/site/.venv/bin/mkdocs serve -f docs/site/mkdocs.yml            # → http://127.0.0.1:8000
```

`build/` is gitignored. **Rendered HTML is never committed** — a checked-in copy of the site is
a copy of the docs that starts drifting the moment someone edits a guide.

## How it avoids a second copy of the docs

`mkdocs.yml` sets `docs_dir: ..`, so the generator reads `docs/*.md` in place. There is one copy
of every guide, it is the one you edit, and GitHub and the site render the same bytes.

Consequences worth knowing:

- **Adding a page** — drop the `.md` in `docs/` as usual, then add it to `nav:` in
  `mkdocs.yml`. A page missing from the nav still builds and is still findable by search; it
  just has no sidebar entry. A nav entry pointing at a file that does *not* exist fails the
  build.
- **Links that leave `docs/`** (`../CONTRIBUTING.md`, `../examples/README.md`) resolve on
  GitHub but are outside `docs_dir`, so MkDocs cannot check them and is configured not to warn.
  In-page anchors *are* checked.
- **`docs/site/` itself** is excluded from the rendered site (`exclude_docs`); this file is
  meant to be read here, on GitHub.

## Search

Full-text search over every guide is the `search` plugin, built into MkDocs — the one thing a
markdown tree in a repo genuinely cannot do. It is a client-side index built at build time; no
service, no API key.

## Versioning — what exists and what does not

**Exists:** every build is stamped with the ProveKit version it was built from, read at build
time from `backend/pyproject.toml` by `hooks/version_stamp.py` and shown in the footer. If that
version cannot be read, `--strict` fails the build rather than shipping an unlabelled site.

**Does not exist:** serving `/0.6/` next to `/latest/` with a version switcher. That is
[`mike`](https://github.com/jimporter/mike), and it needs a publishing target to write to. Nobody
has picked one, so it is not configured — enabling `mike` without somewhere to deploy produces a
version selector that lists nothing.

Wiring it up later is roughly: add `mike` to `requirements.txt`, add
`extra: {version: {provider: mike, default: latest}}` to `mkdocs.yml`, and have a
**tag-triggered** workflow run `mike deploy --push --update-aliases <tag> latest`. Do not add the
`provider` line before the deploy step works — the selector is only correct once something has
actually been deployed.

## CI

`.github/workflows/docs.yml` runs `mkdocs build --strict` on pushes to `main` and on PRs. It
gates the *build*, not prose: bad YAML, a nav entry pointing at a deleted file, a broken anchor,
an unreadable version. It does not publish anything.
