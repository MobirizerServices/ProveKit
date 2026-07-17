# Changelog

All notable changes to AgentMan. This project is pre-1.0; expect breaking changes.

## Unreleased

### Product
- **Universal agent client** — connect and test LLM providers, MCP servers, HTTP agents,
  and A2A agents from one console with live streaming and structured output.
- **Assertions & evals** — contains / equals / regex / json_path / json_schema /
  tool_called / latency / llm_judge; one-click "assert from this run"; dataset test suites.
- **`.agentman` file format + `agentman` CLI** — git-diffable tests/flows, run headless in
  CI (JUnit/JSON output), plus a promptfoo importer.
- **Visual flows** — build prompt/tool/condition/agent graphs, step-debug with breakpoints,
  and **deploy a flow as a versioned hosted API** (`POST /v1/d/{slug}`) with logs & metrics.
- **Protocols** — OpenAI Chat Completions + Responses/Open Responses, Anthropic Messages
  (tool-use, stop reasons), MCP (stdio + Streamable HTTP, OAuth 2.1, dual 2025/2026 spec
  generations), A2A agent cards, OpenTelemetry GenAI trace ingest + emit.

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

### Known gaps
- No third-party pen-test or real-provider load test yet; no email verification provider
  bundled (SMTP configurable, else links are logged); deployment key rotation is manual.
