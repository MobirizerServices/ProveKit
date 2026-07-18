# Changelog

All notable changes to ProveKit. This project is pre-1.0; expect breaking changes.

## Unreleased

### Product
- **Universal agent client** — connect and test LLM providers, MCP servers, HTTP agents,
  and A2A agents from one console with live streaming and structured output.
- **Assertions & evals** — contains / equals / regex / json_path / json_schema /
  tool_called / latency / llm_judge; one-click "assert from this run"; dataset test suites.
- **`.provekit` file format + `provekit` CLI** — git-diffable tests/flows, run headless in
  CI (JUnit/JSON output), plus a promptfoo importer.
- **Visual flows** — build prompt/tool/condition/agent graphs, step-debug with breakpoints,
  and **deploy a flow as a versioned hosted API** (`POST /v1/d/{slug}`) with logs & metrics.
- **Protocols** — OpenAI Chat Completions + Responses/Open Responses, Anthropic Messages
  (tool-use, stop reasons), MCP (stdio + Streamable HTTP, OAuth 2.1, dual 2025/2026 spec
  generations), A2A agent cards, OpenTelemetry GenAI trace ingest + emit.

- **MCP tools for the agent under test** — attach MCP servers to a prompt (console or flow
  node) and the model can call them: it picks a tool, ProveKit executes it over MCP, feeds
  the result back, and the loop continues to a `max_tool_rounds` cap. Works on OpenAI Chat
  Completions, Responses/Open Responses, Anthropic, and the keyless mock agent (so the whole
  loop is demoable offline). Expose all discovered tools or an allowlist; **dry run** records
  the tool the model picked without executing it, for asserting routing without side effects.
  This is what makes the `tool_called` assertion meaningful for an LLM connection — nothing
  previously sent tools to a model, so it could never fire. Tools attach to **prompt**
  requests (LLM connections) only; `agent`/`a2a` endpoints bring their own tools and are
  observed as before.

### Platform
- Auth (email/password), password reset + optional email verification, workspaces with
  full tenant isolation, Postgres + Alembic migrations, Redis-backed debug state, rate
  limits & quotas, per-workspace token usage.
- **Async I/O** across providers/dispatch/flow engine/streaming endpoints — a stream no
  longer holds a thread; ~35× concurrency over the previous serial ceiling in local tests.
- Production stack: Caddy/TLS, same-origin API, healthchecks, structured logs, request
  IDs, optional Sentry.

### Security
- Credentials encrypted at rest; secrets masked in responses and run history; SSRF guard
  on all outbound paths (strict in hosted mode); stored-connection credential-override
  protection; login/reset brute-force throttling; hosted-mode `SECRET_KEY` boot guard.
  See `SECURITY.md`.
- **stdio MCP connections are blocked in hosted mode** — a tenant can no longer make the
  server spawn a local process (remote code execution). Local mode is unaffected.
- **A password reset now revokes every existing session**, via a `token_version` claim
  bound to the user; the reset link itself is single-use.
- Security response headers (`X-Content-Type-Options`, `X-Frame-Options`,
  `Referrer-Policy`, HSTS in hosted mode) from backend middleware and the Caddy proxy.

### Quality
- Backend test suite at 500 tests / 99% line coverage; `ruff` lint gate and Docker image
  builds enforced in CI (`.github/workflows/ci.yml`).
- `make setup` now selects the newest Python on PATH and refuses to build a venv on
  anything below 3.11 (a bare `python3` silently produced a broken env before).
- Hardened the scenarios line-coverage missed: the MCP tool loop is now driven end-to-end
  with realistic OpenAI / Anthropic / Responses SSE — asserting round 2's request body
  carries the correctly-translated tool-call and tool-result turns per provider (the shape
  a live API rejects); deployment rollback/redeploy is verified to actually serve the live
  version's output (not just return 200); dataset runs are tested with a mixed pass/fail
  batch so the "which rows failed" half is exercised.

### Fixed
- **A password reset no longer locks an unverified account out permanently.** The verify
  link is only ever minted at registration, so bumping `token_version` on reset killed the
  user's one link with no way to reissue it — with `REQUIRE_EMAIL_VERIFICATION` they could
  neither verify nor log in. A completed reset now proves the mailbox and verifies the email.
- **`pip install`ed wheels can boot.** Migrations moved into the package
  (`provekit/migrations/`) and are resolved from `__file__`, so a non-editable install no
  longer fails `alembic upgrade head` at startup for want of `alembic.ini`.
- **Rolled-back deployments report the version that is actually serving.** The list endpoint
  showed the newest version, so a rolled-back slug read as "inactive" while an older version
  kept answering — and the UI hid Deactivate, leaving no way to switch off a live endpoint.
  Rollback now steps back from the live version instead of always retargeting latest-minus-one.
- **A `%` in `DATABASE_URL` no longer breaks startup.** The password was passed through
  Alembic's ConfigParser, which read it as interpolation syntax and raised before any
  migration ran; the URL now goes straight to `create_engine`.
- Masked secrets can no longer be saved as credentials: renaming an env var/header key, or
  duplicating a connection, dropped the mask instead of sealing `••••3456` as the token.
- 413 and error responses now carry the security headers and `X-Request-ID` (the body-size
  middleware short-circuited outside them). A client that disconnects mid-upload still ends
  the exchange quietly (499) rather than raising through to a 500 + error report.
- `run_collect` no longer drops `node` events, so a `tool_called` assertion works inside a
  flow instead of silently never matching.
- Stopping a stream mid-run keeps the assertion shortcuts (`interrupted` counted as unfinished).

### Known gaps
- No third-party pen-test or real-provider load test yet; no email verification provider
  bundled (SMTP configurable, else links are logged); deployment key rotation is manual.
- No Content-Security-Policy yet; the other security headers ship.
- Coverage is measured but not gated in CI, so it can regress silently.
