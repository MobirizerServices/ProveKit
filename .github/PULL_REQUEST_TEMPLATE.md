<!--
Short PRs get reviewed. If this is your first one: thank you — the checklist below is the same
one maintainers use, not a hazing ritual.
-->

## What this changes

<!-- One or two sentences. What can a user do after this that they couldn't before, or what
     stops being broken? -->

Fixes #

## Why

<!-- The reason, not the diff. This is the comment that belongs next to the code in six months —
     ProveKit's house style is comments explaining WHY, and a PR body is where that starts. -->

## How you know it works

<!-- Name the test or the command, and what you actually saw. "Should work" and a test count you
     didn't just run are the two things that make a reviewer re-do your work. If you couldn't run
     something (no Docker, no API key, no LLM access), say so plainly — that is always fine. -->

```
```

## Checks

- [ ] `cd backend && ./venv/bin/python -m ruff check provekit`
- [ ] `cd backend && ./venv/bin/python -m pytest tests/ -q` (coverage gate included)
- [ ] `cd frontend && ./node_modules/.bin/tsc --noEmit` — if you touched `frontend/`
- [ ] `cd frontend && npm run build` — if you touched `frontend/`

<!-- `make lint && make test && make build` runs the same set. -->

- [ ] A test covers the behaviour I changed (a fixture in `backend/tests/fixtures/otlp/` counts).
- [ ] Any model change ships with an Alembic migration in `backend/provekit/migrations/`.
- [ ] No secrets in the diff — no keys, no `.env`, no payloads with real customer text.
- [ ] Docs updated if behaviour changed. They live in `docs/*.md`; the site renders those files
      in place, so there is no second copy to update.

## Anything you're unsure about

<!-- Ask here. A question in the PR body is cheaper than a round trip after review. -->
