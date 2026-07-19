# Changelog

All notable changes to ProveKit. This project is pre-1.0; expect breaking changes.

## 0.5.0 — Multiple projects, admin console, and a real landing page

### Projects (multi-tenant)
- **Create, switch, rename, and delete projects** — each an isolated workspace with its own
  keys, traces, datasets, experiments, and members. A project picker lives in the nav; the
  client sends the selection as `X-Project-Id` (membership-validated server-side).
- **Members & roles** — invite teammates by email, set owner/member, remove (with last-owner
  protection). A **/settings** page manages name, members, and per-project data settings.
- **Per-project data settings** — span **retention** and **PII masking** overrides per project
  (fall back to the global defaults).

### Admin
- **Platform superadmin console** (`/admin`) — a global operator view of every user and
  project: counts, a users table (grant/revoke superuser), and an all-projects table. Gated by
  a superuser flag or a bootstrap `SUPERUSER_EMAILS` config entry.

### Landing
- A **world-class landing page** — hero with a live trace-preview card, feature grid, quickstart
  steps, and CTAs. Theme-aware, responsive, self-contained.

## 0.4.0 — Evaluation, dashboards, alerts, PII redaction

ProveKit grows from tracing into the full loop: capture → curate → **evaluate**, plus
operational monitoring and a production-safety net.

### Evaluation
- **Datasets** — named `{input, expected}` collections; curate by hand or **seed an item
  straight from a trace**. Portal **Datasets** page + API (cookie + project key).
- **Scorers** — `provekit.scorers`: `exact_match`, `contains`, `regex_match`, `json_valid`,
  or your own `fn(output, expected) -> float`. Shared by client and server.
- **`pk.evaluate(dataset, target, scorers)`** — runs a target over a dataset, scores each
  output, records an **experiment**, and returns a summary. `assert summary["mean_score"] >= …`
  to gate CI on regressions. See [docs/EVALUATION.md](docs/EVALUATION.md).
- **Experiments** — per-scorer means and side-by-side comparison of runs on the same dataset.

### Monitoring
- **Dashboard** — trace volume, error rate, latency p50/p95, tokens, a traffic chart, and a
  per-model breakdown over a window (`GET /api/metrics` + portal **Dashboard**).
- **Alerts** — threshold rules over those metrics (error rate, latency, volume, tokens) with a
  cooldown; `POST /api/alerts/check` evaluates them and emails on a breach (wire to a cron).

### Security
- **PII redaction** — optional server-side masking of emails / cards / SSNs / phones / secret
  keys in captured input/output/error before storage (`PROVEKIT_REDACT_PII=true`).

## 0.3.0 — Capture everything from one SDK; debug over MCP

The client stays a single SDK, but it now captures more with less code, and the portal gains
a read-side debug channel so assistants can reason over your traces.

### SDK — one SDK, less code
- **`import provekit.auto`** — zero-code activation: one import at your entrypoint turns
  tracing on. The `@pk.trace` decorator is now optional (it just groups a run under a root).
- **`pk.init()`** — a one-line alias for `configure()` for explicit setup.
- **Outbound HTTP capture** — `pip install "provekit[http]"` captures every `httpx` /
  `requests` / `aiohttp` / `urllib` call as a child span, so non-LLM calls (tool APIs, vector
  DBs, webhooks) show up too. Folded into `[trace-all]`.

### Debug channels — on the portal, not the client
- **ProveKit MCP server** (`provekit-mcp`, `pip install "provekit[mcp]"`) — debug traces from
  Claude Desktop / Cursor / any MCP client, authenticated by your project key. Tools:
  `provekit_list_traces`, `provekit_list_failures`, `provekit_get_trace`. See [docs/MCP.md](docs/MCP.md).
- **Key-authed read API** — `GET /v1/traces` and `GET /v1/traces/{id}` (Bearer project key),
  with `status=failed` and `window_hours=N` filters. Same data as the cookie-authed portal
  view, a different door; script it or wire it into CI without MCP.

### Evaluation & collaboration
- **Feedback / scoring** — `pk.score(name, score=/value=/comment=)` attaches a score to the
  current trace; humans score a run in the portal (👍/👎 + comment); external evaluators
  `POST /v1/traces/{id}/feedback` by key. Sources are tracked (human · sdk · eval).
- **Sessions** — `@pk.trace(session_id=…)` (or a `session.id` span attribute) groups multi-turn
  runs; the portal shows a session badge on the list and the trace.
- **Shareable trace links** — mint a signed, read-only link (`/shared/{token}`) anyone can
  view without an account; backed by a public `GET /v1/share/{token}`.

### Portal
- **Chat-transcript view** — LLM input/output render as role-labelled messages, not raw JSON.
- **Deep span metadata** — temperature, max_tokens, and finish_reason shown on LLM spans.
- **Trace-list filters** — "Failures only" toggle and a time-window selector.

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
