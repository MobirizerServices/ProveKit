# Changelog

All notable changes to ProveKit. This project is pre-1.0; expect breaking changes.

## 0.7.0 — Evaluation you can gate on, and a console that shows the whole run

The hundred-point wave: 85 of the 100 tracked items in
[docs/ROADMAP_100.md](docs/ROADMAP_100.md) are shipped. The remaining fifteen are blocked on
things that are not code — an auditor, a hosting account, a pricing decision — and each says so
on its own line rather than being marked done.

### Breaking

- **The Mock provider is gone.** Playground, replay and flows shipped with a `Mock` provider
  selected by default, returning canned text without a key. It made every surface look like it
  worked before anything was configured — in a tool whose entire job is telling you what your
  model actually did, a convincing fake is the one thing that must not be there. Configure a
  real provider connection under Settings; the surfaces now say plainly when none exists rather
  than answering anyway.

- **Fresh workspaces start empty.** Sign-up seeded a sample project with fabricated traces. In
  a product for reading your own production data, demo rows make "is this mine or the sample?"
  a question that has to be asked of every screen. New workspaces contain nothing until you send
  something.

### Evaluation & CI gates

- **Gate CI on whether a regression is real, not on a threshold.** `provekit eval run --baseline
  <experiment>` runs a paired permutation test against the previous run and fails only on a
  *significant* drop, reporting a dip within noise instead of blocking on it. A fixed threshold
  fails on chance about as often as on real regressions, so it gets loosened until it stops
  blocking anything — the gate is still green and no longer means anything. It exits `3`, not
  `1`, when the two runs were measured over different dataset versions: no p-value rescues a
  delta computed over different material, and "I refuse to judge this" is a different answer
  from "this failed". See [docs/CI_GATE.md](docs/CI_GATE.md).

- **Alert when the judge itself drifts.** Calibration told you the judge agreed with your
  humans *that day*. A judge that drifts afterwards silently invalidates every online score
  underneath it, and nothing would have noticed — the scores keep arriving and keep looking like
  numbers. `judge_kappa`, `judge_agreement`, `eval_mean_score` and `human_mean_score` are now
  watchable alert metrics. An unmeasurable metric never fires: calibration withholds a kappa
  below 20 paired labels, and an alert that read "withheld" as `0.0` would page someone at 3am
  about a number the portal declines to show.

- **Scorers a project defines, that online eval can actually run.** Built-in scorers run from
  your code, which leaves online eval — grading live traces server-side, where there is no SDK —
  unable to run them at all. Projects can now define scorers server-side, referenced by name
  exactly as a built-in is: `contains`, `not_contains`, `equals`, `regex`, `json_path`,
  `length_between`. They are rules, not uploaded code, deliberately: "upload a Python function"
  is remote code execution wearing a feature's clothes, and a 95%-correct sandbox is a hole.
  Patterns are compiled and **rejected at creation time**, so a broken rule fails while you are
  looking at it instead of scoring 0.0 for a month. A rule that cannot apply returns nothing
  rather than zero — an ungradeable row scored 0.0 drags an experiment mean exactly as hard as a
  real failure while looking identical to one.

- **A human labelling queue that feeds calibration.** Judge calibration needed paired
  human labels and there was no way to produce them without writing scripts. Reviewers get a
  queue, label, and those labels become the ground truth kappa is computed against.

- **Scoring more than the final string.** An agent that reaches the right answer through four
  wrong tool calls is not a passing run. Trajectory scorers grade the path, RAG scorers grade
  retrieval against what was actually retrieved, and cost/latency become first-class eval axes —
  a 12% quality gain for 3× the spend is a decision, not a win, and it should be visible as one
  at review time.

- **Datasets are versioned, fingerprinted and splittable.** An experiment used to record which
  dataset it ran on but not what that dataset *contained*, so editing a dataset silently
  rewrote the meaning of every historical result. Every version now stores its contents and a
  fingerprint, experiments pin the version they measured, and comparisons across a changed
  dataset refuse rather than quietly mislead. Splits are deterministic, so a train/test boundary
  survives a re-run.

- **Production feeds back into evaluation.** Sampled live traces can be scored online, promoted
  into datasets, and triggered on — automations close the loop from "something looks wrong in
  production" to "there is now a regression test for it". Multi-turn conversations evaluate as
  conversations rather than as a bag of disconnected turns.

- **Experiment comparisons say whether a difference is real.** Two means and no uncertainty
  invites shipping on noise — 0.82 vs 0.79 is nothing over 20 examples and may be decisive over
  2,000, and the numbers alone don't say which you have. Every scorer now reports n, standard
  deviation and a 95% interval, and `GET /api/experiments/{a}/compare/{b}` runs a seeded
  permutation test, **paired on dataset item** where both runs scored the same examples (which
  removes item difficulty and detects far smaller real differences). Below 8 paired items it
  refuses to call anything significant and says why, and a non-significant result is labelled
  as *not distinguishable from chance* rather than as equivalence.

### Tracing & capture

- **Auto-instrumentation covers 37 libraries, and the catalogue can no longer lie.** It was 10
  claimed and 24 actually wired, because the list users read and the list the SDK ran were two
  hand-maintained copies. There is now one catalogue, derived from the runtime and served at
  `GET /api/coverage`, with a test that fails if they ever diverge. The new `provekit[data]`
  group covers the calls agents make *around* the model — vector stores, caches, databases —
  which is the group people forget to install and then can't explain the latency, because a
  900ms retrieval is invisible without it and is very often what made the run slow.

- **Protobuf OTLP is accepted.** A protobuf body used to return `200 {"errorMessage": "invalid
  JSON"}`. OTLP defines `200` as success, so Go's protobuf-only exporter — and every client
  left on the `http/protobuf` default — had its spans acknowledged and discarded. `/v1/traces`
  now decodes `application/x-protobuf` through the same spool, quota and dedupe path, and an
  undecodable body is a loud `400`.

- **A published, self-verifying OTel conformance matrix.** "OpenTelemetry-compatible" was a
  claim nobody could check, and the first `gen_ai` attribute that quietly stopped being read
  would have looked like a data bug. 34 attributes across the `gen_ai` conventions and the
  OpenInference dialect are now published with the suite that proves each one — which is how
  seven real mapping bugs were found and fixed.

- **A span whose parent never arrived is marked, not re-rooted.** Late and orphaned spans were
  silently re-parented to make the tree render, which invented structure: the resulting trace
  looked complete and was wrong. They are now shown as detached, because a visibly incomplete
  trace is honest and a plausible fabricated one is not.

- **Client clock skew is detected instead of poisoning the spool.** A machine with a bad clock
  submitted spans dated next week, which sorted to the top of every list forever.

- **Large payloads move out of the row**, span content is indexed for search rather than
  scanned as JSON, and the cost rate table is versioned so historical spend stays derivable
  after a provider changes its prices. Redaction was measured against a corpus rather than
  assumed, which found two defects.

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

- **fix: a retried OTLP export duplicated every span in the batch.** Exporters retry on `5xx` by
  replaying the whole batch, and ingest inserted each span again — silently inflating span
  counts, tokens, and cost, with no way to tell a real repeat from a retry. Ingest is now
  idempotent on `(project, trace_id, span_id)`, enforced by a unique index; the migration
  collapses existing duplicates to the earliest copy. Scoped by `trace_id` because OpenTelemetry
  only guarantees span-id uniqueness *within* a trace — two traces may legitimately reuse one.

### The console

- **Every section of the console is built.** Traces, flows, playground, datasets, prompts,
  sessions, evaluations, evaluators, automations, admin and settings — rebuilt on one design
  system rather than the handful of screens that existed with the rest advertised on the landing
  page. Phone-width overflows fixed.

- **Flow runs are recorded as real traces**, so a flow is debugged with the same tools as
  anything else instead of having a private half-instrumented view of itself.

- **Prompts and sessions.** Prompts are fetched at runtime and A/B tested live, so changing one
  does not require a deploy; sessions group a conversation's runs so a multi-turn failure is
  read as one thing.

- **Saved views, side-by-side trace comparison, structural diff, and a virtualized list** that
  stays responsive on long traces.

- **fix: reconstructed replay presented a wrong run as a faithful one.** Divergence was
  detected but not propagated: a tool whose input changed was correctly badged **DIVERGED**, yet
  the next LLM call — reading that tool's now-impossible output — was badged **RECORDED**, and
  everything after it inherited the same false confidence. Change the city and you'd get the old
  city's weather advice, presented as what the agent would do. Divergence now cascades through
  outputs and child spans, a diverged LLM call is no longer re-run (answering from inputs that
  no longer hold spends your budget to produce a confidently wrong result), and the replay
  reports `reliable: false` with a `fidelity` breakdown plus a banner on the trace.

- **The trace list updates over SSE instead of polling.** Every viewer refetched the entire
  trace list every 5 seconds, so the cost scaled with viewers and a live run still felt laggy.
  `GET /api/traces/stream` now announces new traces. It's a *notification* channel — it sends
  the newest root-span id and the client refetches through its normal path, so paging and
  merging stay in one place rather than being reimplemented over the wire. The watcher runs its
  query in a threadpool (a synchronous driver called inline from an async generator would block
  the event loop for every other request on the worker), doesn't replay history on connect, and
  keeps a 30s poll as a fallback for when a proxy eats the stream.

- **The trace list pages back through history.** `limit` was capped at 200 with no cursor, so
  the 201st-oldest trace was simply unreachable — the failure arriving exactly when a project
  starts producing real volume. `/api/traces` and `/v1/traces` now take `cursor=<id of the last
  row you got>`. Paging is keyset rather than offset because traces land continuously and an
  offset would repeat or skip rows as the window shifts; the response stays a plain list, so
  the documented key-authed API that MCP and scripts consume is unchanged. The portal gets a
  **Load 50 more** button whose pages survive the 5s live refresh.

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

- **Portal polish (top-20 UI roadmap, all shipped):** real dashboard charts + 1h–90d ranges,
  alerts management UI, sessions grouping, sortable/model-filtered trace list with status +
  relative time, chat-transcript span view, LLM parameter chips, collapsible payloads, prominent
  failed-span errors, node status glyphs, share-link expiry, loading skeletons, and the
  `~$0.0000`/minimap bug fixes.

### Operating an instance

- **Retention is a `DROP TABLE`, not a delete storm.** Pruning competed with ingest for the same
  table, so the cleanup made the instance slow exactly when it was busiest. `runs` converts to
  monthly Postgres partitions (opt-in), verified end to end against postgres:17.

- **Bulk and scheduled export.** Data leaves on a schedule with a cursor that advances only
  after delivery is accepted, so a failed upload re-sends rather than skipping a window, and a
  restart mid-run does not lose or duplicate a slice.

- **Outbound webhooks** push events into your systems — with the SSRF gap that opened closed in
  the same change, since a user-supplied URL that the server fetches is an internal-network probe
  unless something stops it.

- **Published load numbers, measured rather than estimated**, plus restore drills, fleet health,
  weekly digests that say what *changed* rather than only what is broken now, and server-side
  masking on shared traces — masking done in the browser is a decoration, since the data was
  already sent.

- **Account quotas, so an instance can safely take sign-ups.** Rate limits bounded bursts but
  nothing bounded totals: 600 requests/minute forever is still unbounded storage, and a
  per-project cap is escaped by making another project. `MONTHLY_SPAN_QUOTA` and
  `MAX_PROJECTS_PER_ACCOUNT` add per-*account* ceilings, enforced before the write so an
  over-quota account stops consuming storage rather than being told afterwards. Over quota
  returns `402`, not `429` — the condition clears next month, not in a moment, so telling a
  client to retry shortly would be a lie. A retried (deduped) batch isn't charged twice. Both
  default to **off**, so a self-hosted upgrade never starts refusing its owner's own data. Usage
  is visible — `GET /api/projects/usage` plus meters in Settings — because a quota you can't see
  is indistinguishable from a bug, and it reports `approximate: true` without Redis rather than
  presenting a per-worker counter as a hard ceiling.

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

- **Live at [provekit.online](https://provekit.online)** — deployed on a dedicated VPS with its
  own Caddy (auto-HTTPS), Postgres, Redis; `HOSTED` login gate on; verified end-to-end (signup →
  project → key → live trace → dashboard → admin).

- **Ops:** daily automated DB backups (`deploy/backup.sh`), security hardening (`deploy/harden.sh`
  — updates, unattended-upgrades, fail2ban, firewall), one-shot `deploy/vps-deploy.sh`. Standard
  ports are now **3000 (frontend) / 8000 (backend)** to match common gateways.

### Teams, access & tenancy

- **SSO (OIDC) and SCIM.** Authorization Code + PKCE issuing **the same** signed session as
  password login, so `token_version` revocation still applies and there is no second auth path
  to keep secure. The signing algorithm comes from an allowlist and never from the token header,
  so `alg:none` and key-confusion are refused before a key is loaded. SCIM's deprovisioning path
  is made exact: `active=false` bumps `token_version`, so issued sessions die immediately rather
  than the row merely being flagged inactive while the session keeps working.

- **A read-only viewer role**, enforced where the project is resolved rather than at each
  route, so a new endpoint is covered by default instead of being covered once someone
  remembers.

- **Invitations for people who do not have accounts yet**, support impersonation with an
  in-product banner and an audit record, and a tenant-visible activity feed built as a view over
  the audit log — not a second log to drift — gated by an allowlist, because impersonation rows
  are written against the tenant's own workspace and scoping alone would have shown a support
  session to the customer.

- **Deleting a project deletes everything scoped to it.** Thirteen tables were orphaned,
  including sealed provider credentials. The purge set is now discovered from the mapper, so a
  new workspace-scoped table opts into deletion by default rather than being remembered, with a
  test that fails if one is added and left behind.

- **A durable usage ledger** separate from the quota counters, note threads with @mentions and
  resolve, and a compliance posture document that leads with "ProveKit is not SOC 2 certified"
  and an explicit gap list.

- **An audit trail for privileged changes.** There was no record of who granted superuser,
  deleted a project, changed retention or PII masking, added a member, or revoked a key — the
  first thing any security review asks for. `audit_logs` now records actor, action, target, IP
  and timestamp, readable at `GET /api/admin/audit` and in the console. Actor email and target
  label are *snapshotted* rather than joined, so deleting a user or project can't erase the
  evidence that it happened; key events store the display prefix and never the secret; and
  `record()` never raises, because an audit write that can 500 a legitimate revoke would push
  operators toward unaudited workarounds.

- **fix: revoking a superuser could silently do nothing.** `SUPERUSER_EMAILS` overrides the
  database flag, so clearing the flag on a listed account left it a full operator — and the users
  table, computing the same `or`, still rendered **✓ Superuser**, so the revoke looked like it had
  worked. The API now refuses that revoke with a `409` naming the config, `GET /api/admin/users`
  returns `is_bootstrap` alongside `is_superuser`, and the console shows config-granted accounts
  as **✓ Superuser · config** instead of a toggle that can't fire. Admin errors are surfaced in
  the UI rather than swallowed. New [operator guide](docs/ADMIN.md).

### CLI & diagnostics

- **A real CLI.** `provekit up` starts backend, frontend and database locally in one command;
  eval runs, dataset writes and experiment comparison are all scriptable against a project key,
  so CI needs no browser session.

- **`provekit-doctor` — a diagnostic for the silence.** The SDK is fail-open by design, which
  is right in production and brutal on first run: a wrong key, an unset endpoint, a missing
  `[trace]` extra, an endpoint that already includes `/v1/traces`, and a firewalled portal all
  degrade to the same silent no-op. The doctor walks the same path the SDK takes and reports
  the first thing that would stop a span, with the fix — including which installed libraries
  have no instrumentor, so "why is my LangChain call missing?" has an answer. `--send` posts a
  probe span; the exit code is non-zero only on a real failure, so CI can gate on it.

### SDKs

- **TypeScript provider auto-instrumentation.** `pk.observeOpenAI(client)` and
  `pk.observeAnthropic(client)` make every completion an LLM span — model, messages, tokens,
  finish reason, cost — which is what turns the TS SDK from "wrap your own calls" into the
  one-line story the Python SDK has. Streaming is properly handled: the span stays open until
  the caller drains the iterator, accumulating text and both token counts, and closes on an
  early `break` or a mid-stream error so a trace is never left hanging. It wraps via `Proxy`
  rather than patching imports — ESM has no interceptable `require`, and a visible line at the
  call site beats a loader hook that silently stops working under a bundler.

- **A TypeScript SDK.** OTLP ingest always accepted any language, but there was no idiomatic
  client — a large share of agent code is TypeScript, and "point your exporter at this URL" is
  not an integration story. `clients/typescript` adds `pk.trace()` / `pk.span()` with context
  carried across `await` by `AsyncLocalStorage`, plus `score()`, `flush()`/`shutdown()` for
  serverless, and `diagnose()` as the counterpart of `provekit-doctor`. **Zero runtime
  dependencies** and the same OTLP/JSON wire format as the Python SDK, so one ingest path and
  one span mapper serve both. Delivery is deliberate about failure: a 5xx is retried because
  ingest is idempotent, a 4xx is dropped because replaying it can only fail again, and the queue
  is bounded so a portal outage can't become your process's memory problem.


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
