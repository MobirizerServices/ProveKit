# Features

ProveKit is drop-in tracing for AI agents: add one decorator, get a project key, and review
every run as a nested flow in the portal. This is the full feature inventory.

## Tracing SDK (`provekit.trace`)

- **`@pk.trace` decorator** — one at your agent's entrypoint captures the whole run.
- **`pk.span()` context manager** — capture custom sub-steps (retrieval, tools, branches).
- **`pk.configure()`** — from the environment (`PROVEKIT_API_KEY` / `PROVEKIT_ENDPOINT`) or explicit.
- **Auto-instrumentation** of OpenAI & Anthropic — LLM calls nest with zero extra code.
- **OpenTelemetry-native** — any OTel-instrumented library nests under the entrypoint too.
- **Span-hierarchy capture** (trace / span / parent ids) so the tree can be rebuilt.
- **Fail-open by design** — no key, no OTel, or an unreachable portal degrades to a no-op;
  your app is never affected.
- Captures input, output, status, timing, and token usage.

## Ingest

- **OTLP/HTTP JSON ingest** at `/v1/traces` — accepts any OpenTelemetry exporter, not just the SDK.
- **Bearer-key auth** (named `pk_` project keys + a legacy per-workspace ingest key).
- **Span classification** — agent · llm · tool · step.
- **Multi-dialect gen_ai mapping** (current OTel conventions, legacy, OpenInference).
- Token-usage extraction; each span persisted for review.

## Trace review (portal)

- **Traces list** — one row per trace (root span, span count, duration, status, total tokens).
- **Nested flow tree** — the agent's full flow, indented by hierarchy.
- **Time-proportional waterfall** — bars positioned by start-offset and sized by duration.
- **Type-colored badges** and **expandable per-span input / output / error**.
- **Token counts** per span and per trace.
- **Live refresh** — the view updates as runs arrive.
- **Onboarding empty state** — "listening for your first trace…" with a copy-paste snippet
  pre-filled with this instance's endpoint.

## Accounts, projects & keys

- Sign up / sign in / sign out; signed session cookies; PBKDF2 password hashing.
- Email verification + password-reset flows (needs SMTP configured to send).
- Token versioning (revoke sessions on reset); login rate-limiting.
- Hosted vs. local mode.
- A **project** per account with tenant isolation.
- **Project keys** — create, list, revoke; shown once, stored hashed; last-used tracking.

## Platform / ops

- 5-table schema (users, workspaces, members, api_keys, runs); a single Alembic baseline that
  runs on boot. SQLite (local) / Postgres (prod).
- Security headers, request-id, and body-size-limit middleware; SSRF guard; Fernet
  secret-sealing; optional Sentry; health check.
- **Docker** images (backend + frontend), Compose, and a Caddy reverse-proxy config.

## Packaging

- pip package **`provekit`** with a lean install: `pip install "provekit[trace]"` pulls only
  httpx + OpenTelemetry + the instrumentors. `[server]` adds the web app / ingest server.
- Trusted-publishing workflow (tag → PyPI, no token).

## Testing & CI

- Backend test suite with a coverage gate, including an auto-instrumentation regression test
  (a real OpenAI SDK call nests under the decorator) and trace-tree tests.
- CI: backend (Python matrix), frontend (build + `npm audit`), and Docker image builds.

## Not yet

Multi-project UI (one project per account today) · cost estimates (tokens shown, not $) ·
trace search / filter / pagination · SMTP wiring for email verification · a hosted instance.
See the [launch checklist](docs/launch/LAUNCH.md) and [publishing guide](docs/PUBLISHING.md).
