# Features

ProveKit is drop-in tracing for AI agents: add one import, get a project key, and review every
run as a nested flow in the portal — then evaluate it, debug it by re-running it, and watch it
on a dashboard. This is the full feature inventory.

## Tracing SDK (`provekit.trace`)

- **`import provekit.auto`** — zero-code activation; one import at your entrypoint captures
  everything below it. The decorator is optional.
- **`@pk.trace` decorator** — groups a run under a single named root span.
- **`pk.span()` context manager** — capture custom sub-steps (retrieval, tools, branches).
- **`pk.init()` / `pk.configure()`** — from the environment (`PROVEKIT_API_KEY` /
  `PROVEKIT_ENDPOINT`) or explicit; `batch=False` exports synchronously for short scripts.
- **`pk.score()`** — attach a feedback score (numeric or categorical, with a comment) to the
  current trace from code — a heuristic, a guardrail, an LLM judge.
- **Sessions** — `@pk.trace(session_id=…)` groups multi-turn runs into a conversation.
- **Auto-instrumentation** of OpenAI & Anthropic with `[trace]`; `[trace-all]` adds LangChain,
  LlamaIndex, CrewAI, Bedrock, LiteLLM, Groq, Mistral, DSPy, and Haystack. Each instrumentor is
  dormant unless its library is installed.
- **Outbound HTTP capture** — `[http]` (folded into `[trace-all]`) turns every `httpx` /
  `requests` / `urllib` call into a child span, so tool APIs and vector DBs show up too.
- **Log capture** — your `logging.*` calls become events on the active span (INFO+, transport
  noise filtered). Disable with `pk.configure(capture_logs=False)`.
- **OpenTelemetry-native** — any OTel-instrumented library nests under the entrypoint.
- **Span-hierarchy capture** (trace / span / parent ids) so the tree can be rebuilt.
- **Fail-open by design** — no key, no OTel, or an unreachable portal degrades to a no-op;
  your app is never affected.
- Captures input, output, status, timing, and token usage.
- **`provekit-demo`** — a console command that ships a gallery of traces to your portal to
  verify a fresh key end-to-end in ~10 seconds. No LLM key needed.
- **`provekit-doctor`** — says *why* no traces are arriving. Fail-open means a wrong key, an
  unset endpoint, a missing extra, and a firewalled portal all look identical to "working";
  this checks each in turn and names the fix. `--send` posts one probe span; exits non-zero on
  a real failure so setup scripts and CI can gate on it.

## Ingest

- **OTLP/HTTP JSON ingest** at `/v1/traces` — accepts any OpenTelemetry exporter, any language.
- **Bearer-key auth** (named `pk_` project keys + a legacy per-workspace ingest key).
- **Span classification** — agent · llm · tool · step.
- **Multi-dialect gen_ai mapping** (current OTel conventions, legacy, OpenInference).
- Token-usage extraction and cost estimation; each span persisted for review.
- **Per-project ingest rate-limiting** and **trace retention** (old spans pruned to a cap) —
  so a key can't fill the database.

## Read APIs

- **Cookie-authed portal APIs** — `/api/traces` (roots) and `/api/traces/{id}` (all spans).
- **Key-authed read API** — `GET /v1/traces` and `/v1/traces/{id}` with a Bearer project key,
  supporting `status=failed`, `window_hours=N`, and `q=` full-text search. Script it or wire it
  into CI without MCP.
- **MCP debug channel** — `provekit-mcp` (`pip install "provekit[mcp]"`) lets Claude Desktop /
  Cursor / any MCP client reason over your traces, authed by project key. Tools:
  `provekit_list_traces`, `provekit_list_failures`, `provekit_get_trace`. See [docs/MCP.md](docs/MCP.md).

## Trace review (portal)

- **Traces list** — one row per trace (root span, span count, duration, status, tokens, cost),
  sortable, with model filter, status filter, time-window selector, full-text search, and
  **cursor paging** (`cursor=<last id>`) so history past the first page stays reachable.
- **Incomplete-run detection** — a trace whose root span never arrived (the process died
  mid-run) is still listed, badged **partial** rather than silently dropped.
- **Nested flow tree** — the agent's full flow, indented by hierarchy, with node status glyphs.
- **Time-proportional waterfall** — bars positioned by start-offset and sized by duration.
- **Type-colored badges** and **expandable per-span input / output / error**; failed-span errors
  surface prominently; large payloads collapse.
- **Chat-transcript view** — LLM input/output render as role-labelled messages, not raw JSON.
- **LLM parameter chips** — temperature, max_tokens, finish_reason on LLM spans.
- **Token counts and estimated cost** per span and per trace.
- **Session grouping** — multi-turn runs badged and grouped.
- **Span notes** and **human feedback** (👍/👎 + comment); external evaluators can `POST`
  `/v1/traces/{id}/feedback` by key. Sources tracked (human · sdk · eval).
- **Shareable trace links** — signed, read-only `/shared/{token}` links with expiry, viewable
  without an account.
- **Trace compare** — two runs side by side.
- **Live refresh** (5s poll) and loading skeletons.
- **Onboarding empty state** — "listening for your first trace…" with a copy-paste snippet
  pre-filled with this instance's endpoint.

## Evaluation

- **Datasets** — named `{input, expected}` collections; curate by hand or seed an item straight
  from a trace. Portal **Datasets** page + API (cookie + project key).
- **Scorers** — `provekit.scorers`: `exact_match`, `contains`, `regex_match`, `json_valid`, or
  your own `fn(output, expected) -> float`. Shared by client and server.
- **`pk.evaluate(dataset, target, scorers)`** — runs a target over a dataset, scores each output,
  records an experiment, returns a summary you can assert on to **gate CI on regressions**.
- **Experiments** — per-scorer means and side-by-side comparison of runs on the same dataset.
- See [docs/EVALUATION.md](docs/EVALUATION.md).

## Interactive debugging

- **Prompt playground** — *Edit & re-run* any LLM span, seeded from the captured call (messages,
  model, params, auto-detected `{{variables}}`). The new output is **diffed** against the original
  with tokens / cost / latency; each run is kept as an **A/B** column.
- **Prompt versions** — save an edited prompt under a name (auto-versioned) and restore it later.
- **Trace replay** — *Replay flow* forks the whole trace at a span. **Reconstructed** mode
  (framework-agnostic) re-runs the fork live and threads its new output through downstream calls,
  badging each node LIVE / SAME / RECORDED / DIVERGED; **webhook** mode POSTs the override to your
  agent's replay URL for an exact re-run (SSRF-guarded, returns OTLP).
- **Run over dataset** — score an edited prompt against a golden set and save a real experiment.
- **Model connections** — per-project BYO keys (OpenAI / Anthropic / OpenAI-compatible), stored
  **sealed** and never returned to the browser; a keyless **Mock** provider works out of the box.
- Guarded by per-project rate limits, a max-tokens ceiling, and a **monthly spend cap**.
- See [docs/DEBUGGING.md](docs/DEBUGGING.md).

## Monitoring

- **Dashboard** — trace volume, error rate, latency p50/p95, tokens, cost, a traffic chart, and a
  per-model breakdown over a selectable 1h–90d window (`GET /api/metrics`).
- **Alerts** — threshold rules over those metrics (error rate, latency, volume, tokens) with a
  cooldown and a management UI; `POST /api/alerts/check` evaluates them and, on a breach,
  emails and/or posts to a **Slack / Discord incoming webhook** (SSRF-guarded, validated when
  you save the rule rather than when it fires).

## Accounts, projects & keys

- Sign up / sign in / sign out; signed session cookies; PBKDF2 password hashing.
- Email verification + password-reset flows (needs SMTP configured to send).
- Token versioning (revoke sessions on reset); login rate-limiting.
- Hosted vs. local mode (local skips login and lands you in a default project).
- **Multiple projects** — create, switch, rename, delete; each an isolated workspace with its own
  keys, traces, datasets, experiments, and members. The client sends `X-Project-Id`, validated
  against membership server-side.
- **Members & roles** — invite by email, owner/member, remove (with last-owner protection).
- **Per-project data settings** — span retention and PII masking overrides.
- **Project keys** — create, list, revoke; shown once, stored hashed; last-used tracking.
- **Admin console** (`/admin`) — a platform-superadmin view of every user and project, gated by a
  superuser flag or a bootstrap `SUPERUSER_EMAILS` entry. Paged and searchable, with an
  **audit log** of privileged changes. See [docs/ADMIN.md](docs/ADMIN.md).
- **Audit trail** — superuser grants/revocations, project deletion and settings changes,
  membership changes, and key create/revoke, each with actor, target, IP and timestamp. Actor
  and target are snapshotted so a record outlives the user or project it describes.

## Marketing site

- Landing page with a live trace-preview card, feature grid, and quickstart steps.
- Blog with RSS feed and per-post OG images; community, privacy, and terms pages.
- `sitemap.xml`, `robots.txt`, and generated OpenGraph images.

## Platform / ops

- 15-table schema, 9 Alembic migrations that run on boot. SQLite (local) / Postgres (prod),
  Redis for rate limits and spend counters.
- **PII redaction** — optional server-side masking of emails / cards / SSNs / phones / secret keys
  before storage (`PROVEKIT_REDACT_PII=true`).
- Security headers, request-id, and body-size-limit middleware; SSRF guard on every outbound URL;
  sealed provider keys; optional Sentry; health check.
- **Docker** images (backend + frontend), Compose, and a Caddy reverse-proxy config.

## Packaging

- pip package **`provekit`** with a tiny core (httpx only). Extras: `[trace]` (OTel + OpenAI /
  Anthropic instrumentors), `[trace-all]` (the full provider/framework set + HTTP), `[http]`,
  `[mcp]` (the debug server), `[server]` (the web app / ingest server).
- Console entry points: `provekit-demo`, `provekit-doctor`, `provekit-mcp`.
- Trusted-publishing workflow (tag → PyPI, no token).

## Testing & CI

- ~28 backend test modules with a coverage gate, including an auto-instrumentation regression test
  (a real OpenAI SDK call nests under the decorator) and trace-tree tests.
- CI: backend (Python matrix), frontend (build + `npm audit`), and Docker image builds.

## Not yet

**Streaming** trace updates
(the portal polls every 5s rather than pushing) · **per-seat billing**. Email verification and
password reset are wired — they just need SMTP configured to actually send.

See the [launch checklist](docs/launch/LAUNCH.md) and [publishing guide](docs/PUBLISHING.md).
