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
2. **Durable accept.** Ingest writes straight through to the DB; a write failure loses the batch with no retry path. Accept → queue → persist, so a DB blip doesn't destroy data. 🔴 M ✖
3. **Orphan & late-span handling.** A child whose parent hasn't landed yet (or never will, if the process died) should render as a rooted partial tree with an explicit marker, not vanish from the flow. 🔴 M ◑
4. **Incomplete-trace indicator.** ~~A run whose root never arrived was missing from the list entirely, not merely unbadged.~~ Rootless traces are listed via a stand-in span and badged **partial**, distinct from *failed*. 🔴 S ✅
5. **Clock-skew defence.** The waterfall positions bars by client-supplied start offsets; a skewed client produces a nonsensical chart with no warning. Detect skew against server receipt time and flag it. 🟡 M ✖
6. **Documented truncation policy.** Large payloads collapse in the UI, but what actually got *stored* vs. dropped is unstated. Truncate at a documented boundary, store a marker, never silently lose the tail. 🔴 S ◑
7. **Redaction test corpus.** [redact.py](../backend/provekit/services/redact.py) is regex-based, so it has both false positives (mangling real output) and false negatives (leaked PII). Build a labelled corpus, measure both rates, publish them. 🔴 M ◑
8. **Redaction provenance.** Show "redacted" on any span that was masked, so a confusing output is traceable to the masker rather than blamed on the model. 🟡 S ✖
9. **Versioned price table.** [pricing.py](../backend/provekit/services/pricing.py) is hardcoded and drifts as vendors reprice. Version it, stamp each span with the version used, and make historical cost reproducible. 🔴 M ◑
10. **Estimated-vs-reported tokens.** ~~Cost was priced from a fabricated 50/50 input/output split, and a call reporting no usage looked like one reporting zero.~~ The real split now reaches the client, and `usage_coverage` labels a partial estimate. 🔴 S ✅
11. **Dialect conformance suite.** ~20 instrumentors across 3 attribute dialects, one regression test. Capture golden OTLP payloads per instrumentor and assert the mapping — this is where genericness bugs keep coming from (see #177–#182). 🔴 M ◑
12. **Migration integrity tests.** 9 migrations run automatically on boot against production data; nothing tests upgrade (or downgrade) on a *populated* database. 🔴 M ✖
13. **Observable retention.** Pruning silently deletes at a cap. Report what was pruned and when, so "my trace is missing" has an answer. 🟡 S ◑
14. **Self-observability.** [observability.py](../backend/provekit/observability.py) exists; extend it to ingest lag, dropped-batch count, and queue depth — ProveKit should be the first tool to tell you ProveKit is unhealthy. 🟡 M ◑

## B. Scale & performance (15–26)

Everything here is fine on a demo instance and breaks on a real one.

15. **Cursor pagination on the trace list.** ~~Beyond 200 traces, older runs were unreachable.~~ `cursor=<last id>` on `/api/traces` and `/v1/traces`; keyset rather than offset so a continuously-filling list can't repeat or skip rows. 🔴 M ✅
16. **Pre-aggregated metric rollups.** `/api/metrics` scans raw `Run` rows per request; a 90-day window on a busy project is a full table scan on every dashboard load. Roll up hourly. 🔴 L ✖
17. **Indexed full-text search.** Search is `ILIKE '%term%'` over `Run.result` — unindexable, and it degrades linearly. Postgres `tsvector` + GIN. 🔴 M ◑
18. **Index audit.** `span_id` is unindexed; several hot filters aren't covered. Capture query plans for the top 10 paths and fix what's sequential. 🔴 S ✖
19. **Time-partitioned span storage.** Spans grow without bound and dominate the schema. Partition by time so retention becomes a partition drop, not a delete storm. 🟡 L ✖
20. **Payload offload.** Big inputs/outputs live inline in the row. Move them to object storage past a threshold and keep rows narrow. 🟡 L ✖
21. **Streaming trace updates.** ~~Every viewer refetched the whole list every 5s.~~ `GET /api/traces/stream` (SSE) announces new traces and the client refetches through its normal path; a 30s poll remains as a fallback. 🔴 M ✅
22. **Large-trace virtualization.** A 1000-span trace renders every node. Virtualize the tree and waterfall. 🔴 M ✖
23. **Ingest backpressure.** No queue between accept and write — a traffic spike becomes DB pressure and 5xx (which, per #1, then duplicate). 🔴 M ✖
24. **SDK-side durable buffer.** If the portal is unreachable the batch is dropped by design (fail-open). A bounded on-disk buffer would make brief outages lossless without ever blocking the app. 🟡 M ✖
25. **Published load numbers.** No soak test, no "X spans/sec on Y hardware". Teams sizing a self-host deployment have nothing to go on. 🔴 M ✖
26. **Frontend perf budget.** Bundle size and Lighthouse aren't gated in CI, so regressions land invisibly. 🟢 S ✖

## C. Onboarding & time-to-first-trace (27–38)

The single strongest lever on adoption. ProveKit's pitch is "one import" — the surrounding path should be equally short.

27. **Hosted free tier.** Self-host is the only path to a key today; most people evaluate before they deploy. Signup → project key in under 60 seconds. 🔴 L ◑
28. **`provekit doctor`.** ~~Every misconfiguration looked identical to "working".~~ `provekit-doctor` checks config, packages, instrumentation coverage, reachability and auth, naming the fix for each; non-zero exit on real failure. 🔴 S ✅
29. **Framework quickstarts.** Copy-paste starting points for LangGraph, CrewAI, and LlamaIndex, each verified end to end. The examples exist; the docs don't route people to them by framework. 🔴 S ◑
30. **Instrumentation coverage report.** ~~No way to see which installed libraries aren't instrumented.~~ Reported by `provekit-doctor`; not yet surfaced in the portal. 🟡 S ◑
31. **Diagnostic empty state.** The "listening for your first trace…" state is good; make it say *why* nothing has arrived (no key seen, key seen but no spans, spans rejected). 🔴 S ◑
32. **Preloaded sample project.** A new account should have traces to click before it has an integration. `provekit-demo` does this from the CLI — do it server-side at signup. 🟡 S ◑
33. **Versioned docs site.** Docs are markdown in the repo; there's no searchable, versioned site, which is table-stakes for evaluation. 🔴 M ✖
34. **Actionable error messages.** Every rejection (bad key, malformed OTLP, rate limit) should name the fix, not the failure. 🟡 S ◑
35. **One-click deploy.** Railway / Render / Fly buttons that stand up a working instance from the repo. 🟡 S ✖
36. **Migration guides.** "Coming from LangSmith / Langfuse" — the concept mapping and the import path. Adoption is usually a switch, not a greenfield choice. 🟡 M ✖
37. **Interactive product tour.** First visit to a populated portal should teach the flow graph, not present it cold. 🟢 M ✖
38. **Zero-config local mode polish.** Local mode skips login and lands in a default project — extend it to a single `provekit up` that runs backend + frontend + demo data. 🟡 S ◑

## D. Evaluation depth (39–52)

Datasets, scorers, experiments and a CI gate all exist. What's missing is everything that makes eval *trustworthy* and continuous.

39. **Online production evals.** Scoring only happens offline against a dataset. Sample live traces and score them async — the highest-value eval loop, and the one that needs no ground truth. 🔴 L ✖
40. **Human annotation queues.** A review inbox with a labelling UI. Feedback capture exists (👍/👎 + comment); queue-based review doesn't. 🔴 M ◑
41. **Statistical significance.** ~~Per-scorer means with no variance, CI or sample-size guidance.~~ n / sd / 95% interval per scorer, plus a seeded permutation test paired on dataset item, with an explicit caution when the sample is too small to conclude anything. 🔴 M ✅
42. **Trajectory scorers.** Agent quality is about *path* (right tools, right order, no loops), not just final output. ProveKit captures the tree — it's uniquely placed to score it. 🟡 L ✖
43. **RAG scorers.** Faithfulness, context relevance, answer relevance over retrieved chunks. 🟡 M ✖
44. **Multi-turn / session eval.** Datasets are single `{input, expected}` rows; sessions are captured but not evaluable as conversations. 🟡 L ✖
45. **Dataset versioning & splits.** No version history, no train/test split — an experiment's dataset can change under it, silently invalidating comparisons. 🔴 M ✖
46. **Regression triage.** A run reports a score delta but not *which rows* regressed. Row-level diff between experiments. 🔴 M ✖
47. **Automation rules.** "Route traces matching X into dataset Y / an annotation queue / an online eval." The connective tissue between production and eval. 🟡 L ✖
48. **Server-side custom scorers.** Scorers run client-side from `provekit.scorers`; a registry of sandboxed server-side scorers makes them shareable and usable in online eval. 🟡 L ◑
49. **LLM-judge calibration.** A judge scorer exists; nothing measures it against human labels, which is the only thing that makes a judge credible. 🔴 M ◑
50. **Cost & latency as eval axes.** Quality is scored; the trade-off against cost and latency isn't, though both are already captured per span. 🟡 S ◑
51. **GitHub Action.** `pk.evaluate()` can gate CI, but every team writes the same workflow YAML. Ship it, with PR-comment score deltas. 🟡 S ✖
52. **Eval reproducibility.** Pin model, params, dataset version, and scorer version into the experiment record so a result can be re-derived months later. 🔴 M ◑

## E. Debugging depth (53–64)

The strongest differentiator ProveKit has — edit-and-re-run, reconstructed replay, fork trees. These deepen it.

53. **Tool re-execution in replay.** Reconstructed replay re-runs LLM calls and threads outputs downstream, but tool spans aren't re-executed — so any run whose behaviour depends on tool results diverges from reality. The biggest fidelity gap in the feature. 🔴 L ◑
54. **Recorded-response (VCR) mode.** Replay tools against their captured responses for deterministic, free, side-effect-free replay. 🔴 M ✖
55. **Sandboxed live tool calls.** For when you *do* want real execution: an allowlist and a dry-run mode, so replay can't fire a production side effect twice. 🔴 M ✖
56. **Step-through / time-travel.** Pause at a span, inspect state, advance. The natural end state of the fork tree. 🟡 XL ✖
57. **Multi-span editing.** Edit two prompts and re-run once; today each edit is a separate re-run. 🟡 M ✖
58. **Structural trace diff.** Compare is side-by-side and visual; a diff that aligns trees and highlights *first divergence* is what you actually want. 🔴 M ◑
59. **Root-cause hinting.** Given a failed trace and a passing one, point at the first divergent span. 🟡 M ✖
60. **Streaming playground output.** Re-runs block until complete; streaming makes the loop feel interactive. 🟡 S ✖
61. **Runtime prompt fetch.** Prompt versions can be saved and restored in the portal, but there's no `pk.get_prompt("name", label="production")` — so a prompt change still needs a deploy. 🔴 M ◑
62. **Prompt A/B in production.** Serve two versions by traffic split and compare on live scores. 🟡 L ✖
63. **Agent/tool playground.** The playground edits single LLM calls; editing a tool's arguments and re-running the step is the missing sibling. 🟡 M ✖
64. **Replay from the SDK.** Everything is portal-driven; `pk.replay(trace_id)` would put it in tests and CI. 🟡 M ✖

## F. Collaboration (65–74)

ProveKit is currently a single-player tool with multi-user auth.

65. **Comment threads with @mentions.** Span notes exist but are flat and silent — no replies, no notification, no resolve. 🔴 M ◑
66. **Slack / Discord alerting.** ~~Alerts emailed only.~~ A rule can carry a webhook URL, SSRF-guarded and validated at save time, with the body shape chosen per host. 🔴 S ✅
67. **PagerDuty / Opsgenie.** For anyone treating agent failures as on-call. 🟡 S ✖
68. **Saved views.** Filter + time-window + search combinations are ephemeral; teams want "our failing checkout traces" as a shareable URL. 🔴 S ✖
69. **Issue-tracker handoff.** One click from a trace to a GitHub issue with the shared link and context embedded. 🟡 S ✖
70. **Redaction on share.** Signed `/shared/{token}` links expose the full payload; sharing a trace externally needs field-level masking. 🔴 M ◑
71. **Scheduled digests.** A weekly "here's what regressed" email or Slack post. 🟡 M ✖
72. **Finer roles.** Owner/member only — no read-only viewer, which is what most stakeholders should get. 🔴 M ◑
73. **Pending-invite state.** Members are invited by email; there's no visible pending/expired invite lifecycle. 🟡 S ◑
74. **Activity feed.** Who changed a prompt, promoted a dataset row, or resolved an alert. 🟢 M ✖

## G. Operations & multi-tenancy (75–86)

What running ProveKit *for other people* requires. The [admin console](ADMIN.md) is the seed of this; it's currently two tables and a toggle.

75. **Audit log.** ~~No record of who granted superuser, revoked a key, or deleted a project.~~ `audit_logs` records actor/action/target/IP for privileged changes, snapshotted so a record outlives its subject. Read auditing still open. 🔴 M ◑
76. **Admin pagination & search.** ~~Both endpoints returned every row.~~ `limit`/`offset`/`q` with page-scoped aggregates and a console pager. 🔴 S ✅
77. **SSO — OIDC / SAML.** Email+password only. The hard gate on any company adopting a self-hosted tool. 🔴 L ✖
78. **SCIM provisioning.** Deprovisioning a departed employee is manual today. 🟡 L ✖
79. **Visible quotas.** Per-project ingest limits and spend caps exist but aren't surfaced — a throttled project looks broken rather than capped. 🔴 M ◑
80. **Usage metering.** Per-tenant span/token/cost accounting as a first-class, queryable record — the prerequisite for any billing model. 🔴 M ◑
81. **Support impersonation.** Read-only "view as tenant", fully audited. The difference between a support request taking 5 minutes and a day. 🟡 M ✖
82. **Tenant lifecycle.** Suspend, export, and hard-delete a tenant, with GDPR-grade deletion that actually removes spans. 🔴 M ◑
83. **Backup automation & restore drill.** A documented recipe exists; nothing automates it and nothing has ever tested a restore. 🔴 S ◑
84. **Fleet health view.** Per-tenant ingest lag, error rate, and storage — the operator's answer to "who is filling the database?" beyond a span-count column. 🟡 M ◑
85. **Compliance posture.** SOC 2 evidence, DPA, subprocessor list, data-retention statement. Nothing exists; every enterprise deal asks. 🔴 L ✖
86. **Region / residency.** A documented single-region story now, and a path to EU-resident deployment. 🟢 L ✖

## H. Ecosystem & SDK (87–100)

ProveKit is OTel-native, which is real leverage — but the surface a team builds *against* is still one Python package and a portal.

87. **TypeScript SDK.** ~~No idiomatic TS client.~~ `clients/typescript` ships `trace`/`span`/`score`/`flush`/`diagnose`, zero runtime dependencies, same wire format as Python. Provider auto-instrumentation still to come. 🔴 L ◑
88. **Thin Go / Java guides.** No SDK needed — document the OTLP exporter config that produces correctly-classified spans. 🟡 S ✖
89. **OTel convention conformance.** Track the evolving `gen_ai` semantic conventions and contribute the mapping upstream — cheap credibility for an OTel-native tool. 🟡 M ◑
90. **OpenAPI spec + generated clients.** The read API is documented in prose; a spec makes it programmable and testable. 🔴 S ✖
91. **A real CLI.** `provekit-demo` and `provekit-mcp` only. `provekit traces`, `provekit eval`, `provekit datasets` would put the product in scripts and CI. 🟡 M ◑
92. **Outbound webhooks.** Trace-completed / alert-fired / experiment-finished events pushed to customer systems. 🟡 M ✖
93. **Bulk & scheduled export.** To S3 or a warehouse, so trace data joins the rest of a company's analytics. 🟡 M ✖
94. **OTLP gRPC ingest.** HTTP/JSON only; gRPC is the default in several exporters and its absence reads as incomplete OTel support. 🔴 M ✖
95. **MCP write operations.** The MCP channel is read-only (list, get, failures). Letting Claude *curate a dataset* or *start an experiment* from a trace closes the loop. 🟡 M ◑
96. **Helm chart / k8s manifests.** Docker Compose is the only supported deployment; most companies self-host on Kubernetes. 🔴 M ✖
97. **Terraform provider.** Declarative projects, keys, and alerts for teams that manage infra as code. 🟢 L ✖
98. **API stability policy.** Pre-1.0 with no stated deprecation policy — reasonable today, but a blocker to depending on it. 🔴 S ✖
99. **Custom span renderers.** A plugin hook so a team can render *their* domain span (a retrieval, a simulation, a game state) natively. 🟢 L ✖
100. **Contribution ladder.** Good-first-issues, an instrumentor contribution guide, and a template gallery — an OSS tool's ecosystem is its moat or its ceiling. 🟡 M ◑

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
7. **Tool re-execution / VCR replay** (#53–54) — closes the fidelity gap in ProveKit's best differentiator. 🔴 L
8. ~~**Statistical significance in experiments** (#41)~~ — **shipped.** Without it, the eval stack invited teams to ship on noise. 🔴 M
9. ~~**TypeScript SDK** (#87)~~ — **shipped** (auto-instrumentation still open). The largest single expansion in addressable users. 🔴 L
10. **Metric rollups** (#16) — the dashboard is the most-loaded page and the first thing to fall over. 🔴 L

**What I'd deliberately defer:** SCIM (#78), Terraform (#97), residency (#86), custom renderers
(#99), and time-travel (#56). Each is real, and each is a *response to demand you don't have
yet* — build them when a named user asks.

**The through-line:** ProveKit's features are now competitive; its *guarantees* aren't. Sections
A and B are what turn it from a tool people try into one they trust, and almost nothing in them
is glamorous. Do them anyway.
