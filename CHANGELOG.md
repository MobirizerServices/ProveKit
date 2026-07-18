# Changelog

All notable changes to ProveKit. This project is pre-1.0; expect breaking changes.

## 0.2.0 — Drop-in agent tracing

ProveKit is now a **tracing** product: add one decorator, get a project key, and review every
run your agent makes as a nested flow. (This supersedes the 0.1.0 "universal agent test
client"; see below.)

### SDK
- **`@pk.trace`** — one decorator at your agent's entrypoint captures the whole run.
- **`pk.span()`** — capture custom sub-steps (retrieval, tools, branches).
- **Auto-instrumentation** of OpenAI & Anthropic — LLM calls nest under the entrypoint with
  zero extra code. OpenTelemetry-native, so any OTel-instrumented library nests too.
- **Fail-open by design** — no key/endpoint, missing OTel, or an unreachable portal degrades
  to a transparent no-op.

### Portal
- **Traces** view — the agent's nested flow as a **time-proportional waterfall**, with
  type-colored spans (agent · llm · tool · step), per-span input/output, and token usage.
- **Project keys** — named `pk_` keys, created/revoked in the portal, shown once, stored hashed.
- **Onboarding** — a "listening for your first trace…" empty state with a copy-paste snippet.

### Platform
- OTLP/HTTP JSON ingest at `/v1/traces` (accepts any OpenTelemetry exporter).
- Accounts, projects (workspaces) with tenant isolation, Postgres + a single Alembic baseline.
- Docker images (backend + frontend), Compose, Caddy/TLS, health checks, request IDs, Sentry hook.

### Packaging
- Lean install: `pip install "provekit[trace]"` pulls only httpx + OpenTelemetry + the
  instrumentors. `[server]` adds the web app / ingest server.

### Security
- No plaintext secrets at rest (password + key hashes only); signed session tokens with
  reset-revocation; SSRF guard on outbound emit; hosted-mode `SECRET_KEY` boot guard;
  login/reset rate limiting; security response headers. See `SECURITY.md`.

## 0.1.0 — Universal agent test client (superseded)

The initial release was a "test any agent (LLM/MCP/HTTP/A2A) from the outside" client with a
console, visual flows, deployments, and a `.provekit` CI test runner. 0.2.0 repurposes the
project around agent tracing; the test-client surfaces were removed.
