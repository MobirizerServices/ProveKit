# ProveKit — 100 points to a world-class product

Written against **what is actually shipped today** (see [FEATURES.md](../FEATURES.md)), not
against a blank page. The original [ROADMAP.md](ROADMAP.md) has largely been *delivered* — 8 of
its 10 "where I'd start" items are live: datasets, code + LLM-judge scorers, experiments,
dashboards, alerts, sessions, span search, side-by-side compare, `pk.score()`, PII redaction.
That roadmap asked *"does ProveKit have the features?"* — mostly, now, yes.

This one asks the harder question: **would a serious team bet their production agent on it?**
The gap is no longer feature count. It's the boring, unglamorous properties — data you can
trust, performance that holds at scale, an operator story, and an ecosystem — that separate a
capable tool from one people adopt.

**Legend** — Impact: 🔴 table-stakes · 🟡 differentiator · 🟢 nice-to-have.
Effort: S (days) · M (1–2 wk) · L (3–4 wk) · XL (>1 mo).
Status: ✅ present · ◑ partial · ✖ missing.

> **Honest note:** this is a *menu to prioritize from*, not a build-all list. The
> [top 10](#where-id-actually-start-the-top-10) at the bottom is where I'd start, and roughly
> half of that list is Section A — because a tracing tool that loses or mangles a span has no
> second feature worth discussing.

---

## A. Trust & correctness (1–14)

The category ProveKit is *judged* on. An observability tool that silently drops or duplicates
data is worse than none — it produces confident wrong answers.

1. **Idempotent ingest.** ~~A retried OTLP batch duplicated every span in it, inflating counts, tokens and cost.~~ Deduped on `(workspace, trace_id, span_id)` behind a partial unique index; keyed by trace because OTel scopes span-id uniqueness to a trace. 🔴 S ✅
2. **Durable accept.** ~~Ingest wrote straight through to the DB; a write failure lost the batch with no retry path.~~ Every batch is fsynced to an on-disk spool before it is acknowledged and released only once the rows commit; a background drainer replays whatever a failed write or a killed worker left behind. Ingest stays synchronous, so a trace is still queryable the moment the POST returns. 🔴 M ✅
3. **Orphan & late-span handling.** A child whose parent hasn't landed yet (or never will, if the process died) should render as a rooted partial tree with an explicit marker, not vanish from the flow. 🔴 M ◑
4. **Incomplete-trace indicator.** ~~A run whose root never arrived was missing from the list entirely, not merely unbadged.~~ Rootless traces are listed via a stand-in span and badged **partial**, distinct from *failed*. 🔴 S ✅
5. **Clock-skew defence.** ~~A skewed client produced a nonsensical chart with no warning.~~ A span that ended in the future relative to server receipt time, beyond a 60s tolerance, carries `meta.clock_skew_ms`. Only future timestamps count as evidence — exporters batch and networks are slow, so treating *old* as skew would flag every healthy deployment. 🟡 M ✅
6. **Documented truncation policy.** ~~What was actually *stored* vs. dropped was unstated.~~ `MAX_PAYLOAD_CHARS` (8,000 per field) is a named, documented boundary; anything longer is cut and the span carries `meta.truncation` with the stored and original lengths. Written up in [TRACING.md](TRACING.md). 🔴 S ✅
7. **Redaction test corpus.** ~~Neither failure rate was measured, so neither could be argued about.~~ A labelled corpus asserts both directions on every CI run — currently **100% recall, 18% false positives** (published in [TRACING.md](TRACING.md)). Building it found two real defects: `sk-proj-…` OpenAI keys passed through completely unmasked, and ISO dates were mangled as phone numbers. Both fixed. 🔴 M ✅
8. **Redaction provenance.** ~~A masked span looked identical to an untouched one.~~ `meta.redaction` records the fields touched and the per-type match counts, so a mangled output — the regex phone rule eats long order numbers — is traceable to the masker rather than blamed on the model. 🟡 S ✅
9. **Versioned price table.** ~~A single hardcoded table, so a vendor repricing silently restated every historical cost.~~ Tables are keyed by effective date, each captured LLM span is stamped with `meta.price_version`, and `estimate(..., version=)` re-derives a cost at the rates that applied then. Changing prices means adding a version, never editing one. `GET /api/pricing` serves the card so the frontend can stop keeping a second copy. 🔴 M ✅
10. **Estimated-vs-reported tokens.** ~~Cost was priced from a fabricated 50/50 input/output split, and a call reporting no usage looked like one reporting zero.~~ The real split now reaches the client, and `usage_coverage` labels a partial estimate. 🔴 S ✅
11. **Dialect conformance suite.** ~~~20 instrumentors across 3 dialects, one regression test.~~ 29 golden OTLP payloads across 4 dialects, each expected field asserted as its own case so a break names the exact attribute. It found **7 live mapping bugs** on the first run; all seven are fixed and their fixtures promoted to regression guards. 🔴 M ✅
12. **Migration integrity tests.** ~~Migrations run automatically on boot against production data; nothing tested upgrade (or downgrade) on a *populated* database.~~ The real Alembic chain is run over a throwaway database: upgrade from scratch, downgrade-and-back with rows present, a full round trip to `base`, and a stepwise application asserted to match a single jump to head. 🔴 M ✅
13. **Observable retention.** ~~Pruning silently deleted at a cap.~~ Deletions are tallied per hour in `retention_events`, and `GET /api/workspace/retention` reports the policy in force, how many spans are stored, the oldest one still retained, and recent prune history — so "my trace is missing" and "my trace never arrived" stop looking identical. 🟡 S ✅
14. **Self-observability.** ~~[observability.py](../backend/provekit/observability.py) reported liveness only.~~ `/healthz` carries an `ingest` block: queue depth, lag (age of the oldest un-drained batch), and counts of batches shed by backpressure or quarantined as corrupt. All zero on a healthy instance. 🟡 M ✅

## B. Scale & performance (15–26)

Everything here is fine on a demo instance and breaks on a real one.

15. **Cursor pagination on the trace list.** ~~Beyond 200 traces, older runs were unreachable.~~ `cursor=<last id>` on `/api/traces` and `/v1/traces`; keyset rather than offset so a continuously-filling list can't repeat or skip rows. 🔴 M ✅
16. **Pre-aggregated metric rollups.** ~~`/api/metrics` scanned raw `Run` rows per request, and capped the scan — so a wide window wasn't merely slow, it returned a truncated sample that rendered identically to a complete one.~~ Closed hours are folded into `metric_rollups` / `model_rollups` once and read thereafter; only the open hour (and the partial hour the cutoff lands in) is computed live, so a "last 48 hours" is exactly 48. Percentiles come from a mergeable latency histogram, because the p95 of a day is not the mean of 24 hourly p95s. 🔴 L ✅
17. **Indexed full-text search.** ~~`ILIKE '%term%'` over a JSON cast — unindexable, and it matched JSON *keys* as readily as content.~~ Each span carries a `search_text` column built once at write time (from the post-redaction row) and Postgres indexes `to_tsvector('english', …)` with GIN. History that predates the column stays findable through the old scan until `scripts/backfill_search.py` converts it. 🔴 M ✅
18. **Index audit.** ~~Several hot filters weren't covered.~~ Four composites on `runs` — root listing, the metrics window, the failures panel, session grouping — each traced to a predicate that actually appears in the code, with the plans asserted in `test_index_coverage.py` so a regression fails a test rather than a dashboard. The bare `span_id` index this item asked for was deliberately *not* added: nothing filters on it alone, and an unused index costs a write on every ingested span. 🔴 S ✅
19. **Time-partitioned span storage.** Spans grow without bound and dominate the schema. Partition by time so retention becomes a partition drop, not a delete storm. 🟡 L ✖
20. **Payload offload.** ~~Big inputs/outputs lived inline, so the table every hot index covers was mostly text nobody was reading.~~ Past a threshold a payload moves to a content-addressed blob store and the row keeps a reference plus a preview — so search, the label and the trace *list* never touch the store. A missing blob degrades to the preview **with an explicit marker**, never silently. Off unless a store is configured; the filesystem backend is the shape S3 slots into. 🟡 L ✅
21. **Streaming trace updates.** ~~Every viewer refetched the whole list every 5s.~~ `GET /api/traces/stream` (SSE) announces new traces and the client refetches through its normal path; a 30s poll remains as a fallback. 🔴 M ✅
22. **Large-trace virtualization.** ~~A 1000-span trace rendered every node.~~ A hand-rolled windowing hook (no new dependency) mounts ~29 rows whether the trace has 120 spans or 1000; below the threshold the markup is byte-identical to before. Keyboard navigation became a proper roving-tabindex tree and deep links still reveal an unmounted span. 🔴 M ✅
23. **Ingest backpressure.** ~~No queue between accept and write — a traffic spike became DB pressure and 5xx (which, per #1, then duplicated).~~ Once the spool backlog passes `SPOOL_MAX_DEPTH` the endpoint sheds with `503 + Retry-After` instead of taking work the database can't absorb; the depth check is TTL-cached so it costs no syscall per request. 🔴 M ✅
24. **SDK-side durable buffer.** ~~If the portal was unreachable the batch was dropped by design (fail-open).~~ A failed export is written to a bounded on-disk buffer and retried on the next export or flush, oldest evicted first. Still fail-open: an unwritable directory degrades to the old behaviour rather than raising. The TS SDK re-queues in memory (no disk in a browser). 🟡 M ✅
25. **Published load numbers.** ~~No soak test and no figures at all.~~ `testkit/loadtest.py` drives real `POST /v1/traces` and [PERFORMANCE.md](PERFORMANCE.md) publishes what was measured: ~10.3k spans/sec on SQLite on a *laptop*, a 10-minute 5.95M-span soak, and stock-config throughput showing the rate limit binds first. Postgres was measured and deliberately **not** published as a capability — too noisy on that hardware. Numbers from real server hardware are still missing, which is why this stays partial. 🔴 M ◑
26. **Frontend perf budget.** ~~Nothing gated bundle size.~~ `frontend/perf-budget.json` + a build-output checker, wired to CI, with budgets set from measured sizes plus headroom. Lighthouse still uncovered — it needs a browser in CI, and a step nobody has run is worse than an absent one. 🟢 S ◑

## C. Onboarding & time-to-first-trace (27–38)

The single strongest lever on adoption. ProveKit's pitch is "one import" — the surrounding path should be equally short.

27. **Hosted free tier.** Signup → key already works on a hosted instance, and the quota work (#79/#80) makes opening one up safe. What's left is the offer itself: plan tiers, and the billing hook to move off free. 🔴 L ◑
28. **`provekit doctor`.** ~~Every misconfiguration looked identical to "working".~~ `provekit-doctor` checks config, packages, instrumentation coverage, reachability and auth, naming the fix for each; non-zero exit on real failure. 🔴 S ✅
29. **Framework quickstarts.** ~~The examples existed; the docs didn't route people to them by framework.~~ [QUICKSTARTS.md](QUICKSTARTS.md) — install line, minimal traced program and the actual span tree for LangGraph, CrewAI and LlamaIndex, including which attributes `map_span` keeps and which it drops. 🔴 S ✅
30. **Instrumentation coverage report.** ~~No way to see which installed libraries aren't instrumented.~~ Reported by `provekit-doctor`; not yet surfaced in the portal. 🟡 S ◑
31. **Diagnostic empty state.** The "listening for your first trace…" state is good; make it say *why* nothing has arrived (no key seen, key seen but no spans, spans rejected). 🔴 S ◑
32. **Preloaded sample project.** ~~`provekit-demo` did this from the CLI only.~~ Registration seeds a "Sample data (demo)" project — 18 spans including a failure, a two-turn session and retrieval steps — so the portal is legible before there is an integration. Best-effort and silent: a demo that can break signup is not a demo. 🟡 S ✅
33. **Versioned docs site.** ~~Markdown in the repo with no searchable site.~~ A generator config that builds from the *existing* `docs/*.md` rather than duplicating them — a second copy is a second thing to keep true — with CI building it so a broken docs build is caught. Hosting is not set up, and nothing claims a live site exists. 🔴 M ◑
34. **Actionable error messages.** ~~Rejections named the symptom.~~ Phrasing centralised in `services/errors.py` so a message can't drift per-router, rewritten to name the fix. Status codes and response shapes unchanged — clients depend on them and this item is about the text. 🟡 S ✅
35. **One-click deploy.** ~~No blueprints.~~ `render.yaml`, `railway.json`, `fly.toml` and [ONE_CLICK.md](../deploy/ONE_CLICK.md). Not yet deployed against real accounts — flagged as such in the doc rather than implied working. 🟡 S ◑
36. **Migration guides.** ~~Nothing for people switching.~~ [MIGRATING.md](MIGRATING.md) — concept mapping for LangSmith and Langfuse, what moves cleanly, what doesn't, and the OTLP endpoint as the fastest path. 🟡 M ✅
37. **Interactive product tour.** ~~A populated portal was presented cold.~~ A dismissible first-visit tour over the sample project (#32), shown once. 🟢 M ✅
38. **Zero-config local mode polish.** Local mode skips login and lands in a default project — extend it to a single `provekit up` that runs backend + frontend + demo data. 🟡 S ◑

## D. Evaluation depth (39–52)

Datasets, scorers, experiments and a CI gate all exist. What's missing is everything that makes eval *trustworthy* and continuous.

39. **Online production evals.** Scoring only happens offline against a dataset. Sample live traces and score them async — the highest-value eval loop, and the one that needs no ground truth. 🔴 L ✖
40. **Human annotation queues.** A review inbox with a labelling UI. Feedback capture exists (👍/👎 + comment); queue-based review doesn't. 🔴 M ◑
41. **Statistical significance.** ~~Per-scorer means with no variance, CI or sample-size guidance.~~ n / sd / 95% interval per scorer, plus a seeded permutation test paired on dataset item, with an explicit caution when the sample is too small to conclude anything. 🔴 M ✅
42. **Trajectory scorers.** ~~Only final output was scoreable.~~ `expected_tools_used`, `tool_order`, `no_repeat`, `step_budget` over the span tree, ordered by captured start time rather than array position and tolerant of a rootless partial trace (#3/#4). All degrade continuously rather than pass/fail. 🟡 L ✅
43. **RAG scorers.** ~~Missing.~~ `faithfulness`, `context_relevance`, `answer_relevance`, taking context from the payload or from retrieval spans. Since `scorers.py` is client-side and can't import the server's judge, `set_judge()` is the seam and a documented lexical estimate is the no-judge default. 🟡 M ✅
44. **Multi-turn / session eval.** Datasets are single `{input, expected}` rows; sessions are captured but not evaluable as conversations. 🟡 L ✖
45. **Dataset versioning & splits.** ~~An experiment's dataset could change under it, silently invalidating comparisons.~~ Every content change bumps a version and the items carry a content fingerprint, so "comparable" is a fact rather than an assumption; `comparable()` distinguishes *changed* from *unknown*. Splits are hash-assigned so re-splitting can't move examples across the boundary, and experiments pin what they ran over (#52). Full snapshot history — retrieving a dataset's *old contents* — is still open. 🔴 M ◑
46. **Regression triage.** ~~A run reported a score delta but not *which rows* regressed.~~ `GET /api/experiments/{a}/triage/{b}` pairs rows by dataset item and reports what got worse, better, or changed category, worst first. Rows whose input drifted are reported as not-comparable rather than paired by position. 🔴 M ✅
47. **Automation rules.** "Route traces matching X into dataset Y / an annotation queue / an online eval." The connective tissue between production and eval. 🟡 L ✖
48. **Server-side custom scorers.** Scorers run client-side from `provekit.scorers`; a registry of sandboxed server-side scorers makes them shareable and usable in online eval. 🟡 L ◑
49. **LLM-judge calibration.** ~~Nothing measured the judge against human labels.~~ Agreement, Cohen's kappa, confusion matrix and the disagreement list over traces carrying both a human and a judge score. Kappa is the headline because a judge that says "good" to everything scores 90% agreement on a 90%-good dataset and is worthless. Below 20 pairs it refuses to give a verdict. 🔴 M ✅
50. **Cost & latency as eval axes.** ~~Quality was scored; the trade-off wasn't.~~ `cost_budget`, `latency_budget`, `token_budget` score `budget/actual` above budget rather than clipping to zero, so "3% better, 4x the cost" stays visible as a ratio. 🟡 S ✅
51. **GitHub Action.** ~~Every team wrote the same workflow YAML.~~ A composite action at `.github/actions/provekit-eval` that runs the eval, gates on a threshold and posts per-scorer deltas as a PR comment; usage in [CI_GATE.md](CI_GATE.md). 🟡 S ✅
52. **Eval reproducibility.** ~~A result was a number with no provenance.~~ Every experiment pins the dataset version and content fingerprint at creation, plus a free-form `config` for model, params and scorers. `compare` now refuses to present a clean delta when the two runs saw different data. 🔴 M ✅

## E. Debugging depth (53–64)

The strongest differentiator ProveKit has — edit-and-re-run, reconstructed replay, fork trees. These deepen it.

53. **Tool re-execution in replay.** ~~Tool spans weren't re-executed, so any run whose behaviour depended on a tool result diverged from reality.~~ Closed from the SDK side, which is the side that owns the tools: register them with `@pk.tool` and `pk.replay(..., mode="live")` calls the real thing on a cassette miss. 🔴 L ✅
54. **Recorded-response (VCR) mode.** ~~No way to replay tools against their captured responses.~~ `GET /v1/traces/{id}/cassette` hands back every tool call a trace made with the response it got; `pk.replay(trace_id, target)` serves them by (tool, arguments), falling back to recorded order. A call whose arguments changed is served *and reported diverged* — never counted as a faithful hit. 🔴 M ✅
55. **Sandboxed live tool calls.** ~~Nothing bounded real execution during replay.~~ `mode="live"` takes an `allow={...}` set and refuses anything outside it; `mode="dry-run"` executes nothing and returns a marker, so you can see what *would* have fired before letting it. 🔴 M ✅
56. **Step-through / time-travel.** Pause at a span, inspect state, advance. The natural end state of the fork tree. 🟡 XL ✖
57. **Multi-span editing.** ~~Each edit was a separate re-run, so two edits produced two branches that couldn't be combined.~~ `POST /api/replay/multi` carries N edits through one walk. N edits means N taint sources, and an edit whose text still contains an invalidated value is badged rather than presented as a clean live re-run. 🟡 M ✅
58. **Structural trace diff.** ~~Compare was side-by-side and visual.~~ `lib/traceDiff.ts` aligns the two trees, classifies each node same/changed/only-in-A/only-in-B, and leads with the first structural divergence. A differing duration is not divergence; a differing output or a missing span is. 🔴 M ✅
59. **Root-cause hinting.** ~~Nothing pointed at where two runs parted ways.~~ The first divergence is surfaced as a callout above the comparison. 🟡 M ✅
60. **Streaming playground output.** ~~Re-runs blocked until complete.~~ An SSE variant streams tokens as they arrive, following the pattern `/api/traces/stream` already established. The blocking endpoint is unchanged (replay and experiments share the layer), spend is still metered on the streamed path, and a mid-stream provider error surfaces instead of truncating into what looks like a short answer. 🟡 S ✅
61. **Runtime prompt fetch.** Prompt versions can be saved and restored in the portal, but there's no `pk.get_prompt("name", label="production")` — so a prompt change still needs a deploy. 🔴 M ◑
62. **Prompt A/B in production.** Serve two versions by traffic split and compare on live scores. 🟡 L ✖
63. **Agent/tool playground.** ~~Only LLM calls were editable.~~ Tool arguments can be edited: unchanged arguments are a cassette hit, changed ones keep the recorded result but badge it diverged and taint onward. No tool result is ever invented. 🟡 M ✅
64. **Replay from the SDK.** ~~Everything was portal-driven.~~ `pk.replay(trace_id, target, mode=...)` returns a `ReplayReport` (hits, misses, live calls, diverged, unused, `reliable`), so a production trace can be replayed deterministically in a test or a CI job. 🟡 M ✅

## F. Collaboration (65–74)

ProveKit is currently a single-player tool with multi-user auth.

65. **Comment threads with @mentions.** Span notes exist but are flat and silent — no replies, no notification, no resolve. 🔴 M ◑
66. **Slack / Discord alerting.** ~~Alerts emailed only.~~ A rule can carry a webhook URL, SSRF-guarded and validated at save time, with the body shape chosen per host. 🔴 S ✅
67. **PagerDuty / Opsgenie.** ~~Email and chat webhooks only.~~ `notify.payload_for` dispatches on host, so both slot in behind the existing `webhook_url` with no schema change. Alias is stable per rule, so repeated breaches deduplicate into one incident rather than paging someone twenty times. 🟡 S ✅
68. **Saved views.** ~~Filter combinations were ephemeral, so "our failing checkout traces" could be described but not handed over.~~ `/api/views` stores a named filter using the same parameters `/api/traces` already accepts — replayed through the normal read path, so a saved query can't drift from what the live one means. Names are unique per project; params are allowlisted. 🔴 S ✅
69. **Issue-tracker handoff.** ~~No path from a trace to a ticket.~~ A prefilled "new issue" URL carrying the share link, the failing span and the error — no credentials stored, nothing to leak, and it works for GitLab/Linear by URL too. 🟡 S ✅
70. **Redaction on share.** ~~A signed link handed over every prompt and completion, including whatever redaction missed.~~ The token itself carries what to withhold — signed, so a recipient can't widen it — and masking happens **server-side**, asserted against the raw response bytes. A masked token fails closed for any reader that doesn't opt into applying the mask. 🔴 M ✅
71. **Scheduled digests.** A weekly "here's what regressed" email or Slack post. 🟡 M ✖
72. **Finer roles.** ~~Owner/member only, and both could write — so a PM or support lead had to be handed a role that can delete the project's data.~~ A `viewer` role, enforced in `workspace.current_workspace` immediately after the project is resolved, method-based so a new mutating endpoint is covered the day it is written. An unrecognised role falls to viewer, not member. 🔴 M ✅
73. **Pending-invite state.** Members are invited by email; there's no visible pending/expired invite lifecycle. 🟡 S ◑
74. **Activity feed.** ~~No project-level history.~~ A read-only view over `audit_logs` — no second log to drift — gated by an **allowlist** of tenant-visible actions, because impersonation rows are recorded against the tenant's own workspace and scoping alone would have shown a support session to the tenant. It publishes its own coverage gaps as data, with a test that fails if a listed gap gets wired. 🟢 M ◑

## G. Operations & multi-tenancy (75–86)

What running ProveKit *for other people* requires. The [admin console](ADMIN.md) is the seed of this; it's currently two tables and a toggle.

75. **Audit log.** ~~No record of who granted superuser, revoked a key, or deleted a project.~~ `audit_logs` records actor/action/target/IP for privileged changes, snapshotted so a record outlives its subject. Read auditing still open. 🔴 M ◑
76. **Admin pagination & search.** ~~Both endpoints returned every row.~~ `limit`/`offset`/`q` with page-scoped aggregates and a console pager. 🔴 S ✅
77. **SSO — OIDC / SAML.** Email+password only. The hard gate on any company adopting a self-hosted tool. 🔴 L ✖
78. **SCIM provisioning.** Deprovisioning a departed employee is manual today. 🟡 L ✖
79. **Visible quotas.** ~~Limits existed but were invisible.~~ `GET /api/projects/usage` plus meters in Settings, with an explicit `approximate` flag when counters are per-worker. 🔴 M ✅
80. **Usage metering.** ~~No per-account accounting.~~ Monthly spans and project count are metered per account and enforced as quotas. Token/cost metering and a durable (non-counter) record for billing are still open. 🔴 M ◑
81. **Support impersonation.** ~~No way to see what a tenant sees.~~ A time-boxed claim inside the existing signed session, enforced read-only by an ASGI middleware that refuses every non-safe method, with start and stop audited. Reads go through the tenant's own query path, so "what they see" is literally the same query. No portal UI yet. 🟡 M ◑
82. **Tenant lifecycle.** Suspend, export, and hard-delete a tenant, with GDPR-grade deletion that actually removes spans. 🔴 M ◑
83. **Backup automation & restore drill.** ~~A recipe nobody automated and nobody had ever tested.~~ `install-backups.sh` schedules a nightly dump *and* a weekly `verify-restore.sh` that restores into a throwaway database and asserts tables, row counts and the alembic head. Exercised against a real Postgres container. A backup nobody has restored is a belief, not a capability. 🔴 S ✅
84. **Fleet health view.** ~~A span-count column.~~ `GET /api/admin/fleet` ranks tenants by share of the instance's errors and volume, reading pre-aggregated rollups rather than raw spans — measured at 28 statements for 200 tenants / 144k spans. Storage is labelled `approximate` because no per-tenant byte counter exists. 🟡 M ✅
85. **Compliance posture.** ~~Nothing existed.~~ A security-posture document grounded in controls that actually exist, a self-hosted subprocessor list, a retention statement, and a DPA **template** marked as requiring legal review — leading with "ProveKit is not SOC 2 certified" and an explicit gap list. Stays partial because certification needs an auditor, not a document. Reviewing it found a live SSRF gap. 🔴 L ◑
86. **Region / residency.** ~~Undocumented.~~ [RESIDENCY.md](RESIDENCY.md) — where data physically lives self-hosted, what leaves the box (provider calls, webhooks, email), and what an EU-resident deployment needs. Read out of the source, with no compliance claims invented. 🟢 L ✅

## H. Ecosystem & SDK (87–100)

ProveKit is OTel-native, which is real leverage — but the surface a team builds *against* is still one Python package and a portal.

87. **TypeScript SDK.** ~~No idiomatic TS client.~~ `clients/typescript` ships `trace`/`span`/`score`/`flush`/`diagnose` plus `observeOpenAI`/`observeAnthropic` (streaming included), zero runtime dependencies, same wire format as Python. Framework-level instrumentation (LangChain.js, Vercel AI SDK) still open. 🔴 L ✅
88. **Thin Go / Java guides.** ~~Undocumented.~~ [SDK_OTHER_LANGUAGES.md](SDK_OTHER_LANGUAGES.md) — the classification ladder, the attribute table across all three dialects, and the collector-vs-direct-JSON choice (Go's `otlptracehttp` is protobuf-only, and a protobuf body currently returns 200 with `errorMessage: invalid JSON`, which exporters read as success). 🟡 S ✅
89. **OTel convention conformance.** Track the evolving `gen_ai` semantic conventions and contribute the mapping upstream — cheap credibility for an OTel-native tool. 🟡 M ◑
90. **OpenAPI spec + generated clients.** ~~FastAPI served `/openapi.json`, but nothing committed it, diffed it, or kept it honest.~~ `scripts/export_openapi.py` writes [openapi.json](openapi.json), CI fails when it drifts, and [API.md](API.md) covers the auth split and client generation — with an honest audit of which endpoints still lack response models. 🔴 S ✅
91. **A real CLI.** ~~`provekit-demo` and `provekit-mcp` only.~~ `provekit traces list/get`, `datasets list/create/add`, `eval run --fail-under`, `doctor` — a pure HTTP client over the documented `/v1` endpoints, so it works against a remote instance. `--json` everywhere. Dataset *writes* still fall back to `/api` because `/v1/datasets` is read-only. 🟡 M ◑
92. **Outbound webhooks.** ~~Only a breached alert rule could push anywhere; everything else needed polling.~~ Per-project subscriptions to `trace.completed` / `trace.failed` / `experiment.finished` / `alert.fired`, HMAC-signed with the timestamp inside the signed material so a captured delivery can't be replayed. A dead endpoint backs off and disables itself *with the reason recorded*, and the destination is SSRF-guarded. Emitting is best-effort — a customer's slow endpoint must never fail an ingest. 🟡 M ✅
93. **Bulk & scheduled export.** ~~No way to get data out in bulk.~~ Streaming NDJSON export over cookie or key auth, resolving offloaded payloads so a warehouse gets content rather than blob pointers. *Scheduled* export needs somewhere to store a schedule and is not built — described, not faked. 🟡 M ◑
94. **OTLP gRPC ingest.** ~~A protobuf body returned `200 {"errorMessage": "invalid JSON"}` — which OTLP defines as success, so Go's protobuf-only exporter and every `http/protobuf` default had its spans silently discarded.~~ `/v1/traces` now decodes `application/x-protobuf` through the same pipeline (spool, quota, dedupe), and an undecodable body is a loud 400. **gRPC on :4317 is still not served** — that needs an HTTP/2 listener and a C-extension dependency. 🔴 M ◑
95. **MCP write operations.** ~~Read-only.~~ Promote a trace or span into a dataset, create a dataset, register an experiment — with a dry-run preview, the target named back in every result, and ambiguity refused rather than guessed. Deliberately append-only: no delete or edit tools, because rewriting an item's `expected` silently changes what every past experiment was scored against. 🟡 M ✅
96. **Helm chart / k8s manifests.** ~~Docker Compose was the only supported deployment.~~ A chart at `deploy/helm/provekit` and plain manifests at `deploy/k8s` (the latter verified with `kubectl kustomize`; the chart is **unlinted** — `helm` wasn't available — and says so). 🔴 M ◑
97. **Terraform provider.** Declarative projects, keys, and alerts for teams that manage infra as code. 🟢 L ✖
98. **API stability policy.** ~~No stated deprecation policy.~~ [API_STABILITY.md](API_STABILITY.md) — three tiers (stable `/v1` + SDK surface, experimental, internal `/api`), what counts as breaking, and the deprecation window with a worked example. 🔴 S ✅
99. **Custom span renderers.** ~~No way to render a domain span natively.~~ A keyed registry with a documented contract and total fallback — a throwing custom renderer drops to the default view rather than blanking the trace, because a debugger that dies on the span you're debugging is worse than a plain one. 🟢 L ✅
100. **Contribution ladder.** ~~No on-ramp.~~ Issue/PR templates plus an instrumentor guide that routes contributors at the dialect conformance suite (#11) — add a fixture, and the mapping it must satisfy is asserted for you. That suite is the best on-ramp this project has. 🟡 M ✅

---

## Where I'd actually start (the top 10)

Ordered by credibility-per-unit-effort, weighted toward the things whose *absence* would end an
evaluation:

1. ~~**Idempotent ingest** (#1)~~ — **shipped.** A correctness bug that silently inflated every number in the product. 🔴 S
2. ~~**Cursor pagination** (#15)~~ — **shipped.** Traces past the 200th were unreachable, exactly when someone starts succeeding with the tool. 🔴 M
3. ~~**`provekit doctor`** (#28)~~ — **shipped.** Fail-open is right for production and brutal for onboarding; silence was the #1 first-run failure. 🔴 S
4. ~~**Audit log** (#75)~~ — **shipped** for changes (reads still open). The cheapest item that unblocks enterprise conversations. 🔴 M
5. ~~**Slack alerting** (#66)~~ — **shipped.** Alerts that email nobody reads aren't alerts. 🔴 S
6. ~~**Streaming trace updates** (#21)~~ — **shipped.** Replaces the 5s poll and makes live runs feel live. 🔴 M
7. ~~**Tool re-execution / VCR replay** (#53–54)~~ — **shipped**, with the allowlist (#55) and SDK-driven replay (#64). Closes the fidelity gap in ProveKit's best differentiator. 🔴 L
8. ~~**Statistical significance in experiments** (#41)~~ — **shipped.** Without it, the eval stack invited teams to ship on noise. 🔴 M
9. ~~**TypeScript SDK** (#87)~~ — **shipped**, including OpenAI/Anthropic instrumentation. The largest single expansion in addressable users. 🔴 L
10. ~~**Metric rollups** (#16)~~ — **shipped.** The dashboard is the most-loaded page and the first thing to fall over. 🔴 L

**What I'd deliberately defer:** SCIM (#78), Terraform (#97), residency (#86), custom renderers
(#99), and time-travel (#56). Each is real, and each is a *response to demand you don't have
yet* — build them when a named user asks.

**The through-line:** ProveKit's features are now competitive; its *guarantees* aren't. Sections
A and B are what turn it from a tool people try into one they trust, and almost nothing in them
is glamorous. Do them anyway.
