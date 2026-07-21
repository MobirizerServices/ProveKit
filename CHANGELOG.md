# Changelog

All notable changes to ProveKit. This project is pre-1.0; expect breaking changes.

## Unreleased — Interactive debugging + live in production

- **fix: a run that crashed mid-flight was invisible.** Spans are exported when they *end*, so
  a process killed by an OOM, a timeout, or a `SIGKILL` never emits its root span — and the
  trace list, which selected only root spans, dropped the whole trace. The run that crashed was
  precisely the one you couldn't see. Rootless traces are now listed by promoting their earliest
  span to stand in, flagged `incomplete` in the API and badged **partial** in the portal —
  distinct from **failed**, because the run didn't report an error, it stopped reporting at all.

- **fix: cost was priced from a fabricated 50/50 token split.** The dashboard only received a
  *total* token count per model, so it assumed half input and half output — but output tokens
  cost 3–5x more, which makes the estimate badly wrong on anything input-heavy like RAG, and it
  rendered exactly like a measured number. `/api/metrics` now reports `input_tokens` and
  `output_tokens` separately (per model and per time bucket) and the three places that guessed
  now price the real split. It also reports `usage_coverage`, and the cost tile says *"N% of
  calls reported usage"* when some didn't — a total built partly from silence is a floor, not
  an estimate.

- **The trace list pages back through history.** `limit` was capped at 200 with no cursor, so
  the 201st-oldest trace was simply unreachable — the failure arriving exactly when a project
  starts producing real volume. `/api/traces` and `/v1/traces` now take `cursor=<id of the last
  row you got>`. Paging is keyset rather than offset because traces land continuously and an
  offset would repeat or skip rows as the window shifts; the response stays a plain list, so
  the documented key-authed API that MCP and scripts consume is unchanged. The portal gets a
  **Load 50 more** button whose pages survive the 5s live refresh.

- **The admin tables are paged and searchable.** `GET /api/admin/users` and `/projects` returned
  every row in one response. Both now take `limit` (default 50, capped at 200), `offset`, and a
  `q` substring search — users by email/name, projects by name or owner email — returning
  `{total, limit, offset, …}` so the console can page. Per-page member and span counts are
  scoped to the rows on the page rather than grouping over the whole table on every request.

- **Alerts reach Slack and Discord, not just email.** A breach can now POST to an incoming
  webhook alongside the email. The URL is SSRF-guarded and validated when you save the rule —
  discovering a typo at 3am via a breach that notified nobody is the failure this fixes. The
  payload shape is chosen per host (Slack reads `text`, Discord `content`), a dead webhook is
  reported rather than raised so it can't abort the alert run, and `/api/alerts/check` returns
  `webhook_delivered` so a cron caller can tell a delivery failure from a rule with no webhook.

- **fix: a retried OTLP export duplicated every span in the batch.** Exporters retry on `5xx` by
  replaying the whole batch, and ingest inserted each span again — silently inflating span
  counts, tokens, and cost, with no way to tell a real repeat from a retry. Ingest is now
  idempotent on `(project, trace_id, span_id)`, enforced by a unique index; the migration
  collapses existing duplicates to the earliest copy. Scoped by `trace_id` because OpenTelemetry
  only guarantees span-id uniqueness *within* a trace — two traces may legitimately reuse one.

- **fix: revoking a superuser could silently do nothing.** `SUPERUSER_EMAILS` overrides the
  database flag, so clearing the flag on a listed account left it a full operator — and the users
  table, computing the same `or`, still rendered **✓ Superuser**, so the revoke looked like it had
  worked. The API now refuses that revoke with a `409` naming the config, `GET /api/admin/users`
  returns `is_bootstrap` alongside `is_superuser`, and the console shows config-granted accounts
  as **✓ Superuser · config** instead of a toggle that can't fire. Admin errors are surfaced in
  the UI rather than swallowed. New [operator guide](docs/ADMIN.md).

- **Interactive debugging — edit a captured run and re-run it with real data.** Turns the trace
  view from a log viewer into a debugger ([design](docs/design/INTERACTIVE_DEBUGGING.md),
  [guide](docs/DEBUGGING.md)):
  - **Prompt playground** — an *Edit & re-run* action on any LLM span opens an editor seeded from
    the captured call (messages, model, params, and auto-detected `{{variables}}`). Run it against
    a provider connection and the new output is **diffed** against the original with tokens / cost /
    latency; each run is kept as an **A/B** column. Save/restore **prompt versions**.
  - **Trace replay harness** — *Replay flow* forks the whole trace at a span. **Reconstructed**
    mode (framework-agnostic) re-runs the fork live and threads its new output through downstream
    calls that consumed it, badging each node LIVE / SAME / DIVERGED; **webhook** mode POSTs the
    override to your agent's `replay_url` for an exact re-run (SSRF-guarded, returns OTLP).
  - **Evaluate an edit** — *Run over dataset* scores an edited prompt against a golden set
    (`{{input}}`/`{{expected}}`) and saves a real experiment.
  - **Model connections** — per-project BYO keys (OpenAI / Anthropic / OpenAI-compatible), stored
    **sealed** and never returned to the browser; a keyless **Mock** provider works out of the box.

## Live in production + portal polish

- **Live at [provekit.online](https://provekit.online)** — deployed on a dedicated VPS with its
  own Caddy (auto-HTTPS), Postgres, Redis; `HOSTED` login gate on; verified end-to-end (signup →
  project → key → live trace → dashboard → admin).
- **Ops:** daily automated DB backups (`deploy/backup.sh`), security hardening (`deploy/harden.sh`
  — updates, unattended-upgrades, fail2ban, firewall), one-shot `deploy/vps-deploy.sh`. Standard
  ports are now **3000 (frontend) / 8000 (backend)** to match common gateways.
- **Portal polish (top-20 UI roadmap, all shipped):** real dashboard charts + 1h–90d ranges,
  alerts management UI, sessions grouping, sortable/model-filtered trace list with status +
  relative time, chat-transcript span view, LLM parameter chips, collapsible payloads, prominent
  failed-span errors, node status glyphs, share-link expiry, loading skeletons, and the
  `~$0.0000`/minimap bug fixes.

## 0.6.0 — `provekit-demo` smoke test + LangGraph examples

- **`provekit-demo` console command** — after `pip install "provekit[trace]"`, run `provekit-demo`
  to send a small gallery of traces (nested spans, a multi-turn session, a failed run, a feedback
  score) to your portal and verify a fresh key end-to-end in ~10 seconds. No LLM key needed.
- **LangGraph examples** — `examples/langgraph_demo.py` (a two-node graph) and
  `examples/langgraph_complex_demo.py` (a ~70-span multi-agent orchestrator: parallel map-reduce
  fan-out, a compiled sub-graph, a reflection cycle, a flaky-retry tool, five models) — each
  captured from one `@pk.trace`, offline by default.
- **SDK:** quiet the benign `DependencyConflict` errors auto-instrumentation logged when a
  provider library (openai/anthropic) isn't installed — they alarmed first-time users.

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
