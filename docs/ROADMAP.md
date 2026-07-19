# ProveKit Roadmap — to a world-class agent-observability tool

Research-backed (deep dive into LangSmith, Langfuse, Arize Phoenix, Braintrust, plus
Datadog / Helicone / Laminar / Pydantic Logfire signals). Every leader treats an
**evaluation stack, prompt management, human feedback, and dashboards/alerts** as
table-stakes — ProveKit has none of that yet. It has a strong *tracing* core (flow graph +
waterfall, ~20-framework auto-instrumentation, logs-as-events, tokens/cost, retention).

**Legend** — Impact: 🔴 table-stakes (needed to be credible) · 🟡 differentiator · 🟢 nice-to-have.
Effort: S (days) · M (1–2 wk) · L (3–4 wk) · XL (>1 mo). Status: ✅ present · ◑ partial · ✖ missing.

> **Honest note:** this is a *menu to prioritize from*, not a build-all-now list. Shipping
> and getting users beats building all 150. The **top-10** at the bottom is where I'd start.

---

## Part 1 — 50 features (net-new capabilities)

### A. Evaluation (the #1 gap — every leader has it) ✖
1. **Datasets** — a first-class object: named sets of `{input, expected?, metadata}` rows. 🔴 M ✖
2. **Curate a dataset from a production trace/span** (one click "add to dataset"). 🔴 M ✖
3. **Code/heuristic scorers** — deterministic functions (contains, regex, JSON-schema, exact). 🔴 M ✖
4. **LLM-as-a-judge scorers** — reference-free and reference-based, via function-calling for structured scores (Phoenix's pattern). 🔴 L ✖
5. **Offline evals / experiments** — run a config over a dataset, store an immutable, comparable result. 🔴 L ✖
6. **Online (production) evals** — score live traces async as they land (no ground truth → LLM-judge). 🔴 L ✖
7. **Pairwise comparison** — compare two runs/versions side by side; A/B a prompt or model. 🔴 M ✖
8. **Experiment comparison view** — diff scores across runs/versions over time. 🔴 M ✖
9. **CI eval gate** — `provekit eval` fails a build on score regression (block bad deploys). 🟡 M ✖
10. **Eval dashboard** — score trends, pass rates, per-scorer breakdown. 🔴 M ✖

### B. Prompt & dataset management ✖
11. **Prompt registry** — versioned prompts, keyed by name. 🔴 M ✖
12. **Git-style prompt versioning** — re-push under a name auto-creates a commit; prior versions preserved. 🔴 M ✖
13. **Labels** (e.g. `production`) — fetch a prompt by label at runtime → deploy prompt changes with no code change. 🟡 M ✖
14. **Tags** — mark milestone commits. 🟢 S ✖
15. **Prompt playground** — set model + variables, run, see output. 🔴 L ✖
16. **Run a prompt over a whole dataset** from the playground → creates an experiment. 🔴 M ✖
17. **Prompt diffing** — compare two versions' text + eval scores. 🟡 S ✖
18. **Pull prompts via SDK** (`pk.get_prompt("name", label="production")`). 🟡 S ✖

### C. Trace visualization & debugging ◑
19. **Shareable trace links** — a public/authed URL to one trace. 🔴 S ◑
20. **Side-by-side trace/run comparison.** 🔴 M ✖
21. **Span search & filter** — by type, model, status, latency, tokens, text. 🔴 M ✖
22. **Sessions / threads / conversations** — group multi-turn traces by a session id. 🔴 M ✖
23. **RAG retrieval view** — retrieved docs with relevance score + order + embedding model (Phoenix). Data may already arrive via OpenInference. 🟡 M ◑
24. **Deep span metadata panel** — invocation params (temperature, system prompt), tool schemas, finish reason, function selection. Likely already ingested → UI only. 🔴 M ◑
25. **Trace-as-transcript view** (Laminar) — read a run as a linear chat transcript. 🟡 M ✖
26. **Time-travel / step-through replay** of an agent run. 🟢 XL ✖
27. **Large-trace virtualization** — render 1000+ span traces without lag. 🟡 M ✖
28. **Attachments** — image/audio input-output rendering (Helicone does images). 🟢 M ✖
29. **Raw-attributes inspector** — show every captured OTel attribute for a span. 🟢 S ◑
30. **Export a trace** (JSON / OTLP). 🟡 S ✖

### D. Monitoring, dashboards, cost & analytics ◑
31. **Custom dashboards** — charts for latency, tokens, cost, error rate, throughput over time. 🔴 L ✖
32. **Alerts** — threshold/anomaly alerts on error rate, latency, cost, eval scores → email/webhook. 🔴 M ✖
33. **Automation rules** — route matching traces to a dataset / annotation queue / webhook / online-eval. 🟡 L ✖
34. **Cost attribution** — cost per model / project / user / tag over time. 🟡 M ◑
35. **Live model pricing** — a maintained price feed (vs today's hardcoded estimate). 🟡 M ◑
36. **Budget alerts** (Logfire) — notify when a project exceeds a spend threshold. 🟢 S ✖
37. **SQL / query access** to trace data (Langfuse/Logfire expose SQL). 🟢 L ✖
38. **Anomaly/outlier detection** on latency/cost/error (Datadog). 🟢 L ✖

### E. Agent-specific ◑
39. **Agent-graph aggregated view** — condense repeated steps into nodes with counters (Langfuse). 🟡 M ◑
40. **Multi-agent / handoff visualization** — show agent-to-agent handoffs distinctly. 🟡 M ✖
41. **Tool-call debugging** — tool name, args, result, and a re-run-this-tool affordance. 🟡 M ◑
42. **Guardrails observability** — surface guardrail checks/violations as span events. 🟢 M ✖
43. **MCP observability** — first-class rendering of MCP tool/resource calls. 🟢 M ✖

### F. Data model & ingestion ◑
44. **PII redaction / masking** — regex + entity masking on ingest (before storage). 🔴 M ✖
45. **Sampling** — head/tail sampling to control volume at scale. 🟡 M ✖
46. **Async batching at scale** — a durable ingest queue (the sync per-span write won't hold at 1000s/sec). 🔴 L ◑
47. **TTL / tiered retention** — per-project retention windows + cold storage. 🟡 M ◑
48. **A TypeScript/JS SDK** (huge slice of agents are TS — Vercel AI SDK, Mastra). 🔴 L ✖
49. **Stock OTLP-protobuf ingest** — accept any standard OTel exporter, not just JSON. 🟡 M ◑

### G. Collaboration & enterprise ✖
50. **Teams / orgs / RBAC** — invite members, roles per project. 🔴 L ✖

*(Enterprise continues in the improvements list: SSO/SAML, audit logs, SOC2, data residency,
comments/annotations — all ✖ today and gating for any team/enterprise adoption.)*

---

## Part 2 — 100 improvements (sharpen what exists)

### SDK & capture (1–20)
1. Auto-instrument on `import` (zero-call setup) via an optional `provekit.auto`. 🟢 S
2. Async decorator support (`async def` entrypoints) — verify + test. 🔴 S
3. Streaming-response capture (capture the final assembled output of a streamed call). 🟡 M
4. Capture exceptions with full traceback as a span event (not just status). 🔴 S
5. Capture `gen_ai.request` params (temperature/top_p/max_tokens) into meta explicitly. 🔴 S
6. Capture tool call args + results as structured span fields. 🟡 M
7. Session/thread id support (`pk.trace(..., session_id=)`). 🔴 S
8. User id / tags on a trace (`pk.trace(..., user=, tags=)`) for later filtering. 🔴 S
9. `pk.score()` — attach a feedback score to the current trace from code. 🔴 S
10. Manual `pk.event()` API for custom events. 🟢 S
11. Redact-before-send hook (`pk.configure(redact=fn)`). 🔴 S
12. Configurable log-capture level + per-logger allow/deny. 🟢 S
13. Sampling knob in the SDK (`pk.configure(sample_rate=)`). 🟡 S
14. Graceful flush on process exit (atexit) so short scripts don't lose the last batch. 🔴 S
15. Retry/backoff on export with a bounded in-memory buffer. 🟡 S
16. `pk.configure(debug=True)` — print what got captured, for onboarding. 🟢 S
17. Support OpenTelemetry context propagation across threads/async tasks. 🟡 M
18. Decorate class methods / bound methods cleanly. 🟢 S
19. Capture model + provider for more instrumentors (normalize across OpenInference). 🟡 M
20. A `pk.trace` decorator that also works as `with pk.trace(...)`. 🟢 S

### Trace graph / flow view (21–40)
21. Auto-layout with dagre for wide/deep trees (current layout overlaps at scale). 🟡 M
22. Collapse/expand a subtree (aggregate repeated steps). 🟡 M
23. Time-proportional node widths (encode duration in the node, not just the bar). 🟢 S
24. Edge labels (e.g. "calls", "returns"). 🟢 S
25. Node status ring/icon (✓ / ✕ / ⚠) at a glance. 🟢 S
26. Fit-to-selection + focus mode (dim non-ancestors of the selected node). 🟡 S
27. Keyboard nav between nodes (arrow keys). 🟢 M
28. Hover tooltip with quick stats (no click). 🟢 S
29. Search-in-graph highlights matching nodes. 🟡 S
30. Critical-path highlight (the longest dependency chain). 🟡 M
31. Toggle: collapse `step` nodes to declutter. 🟢 S
32. Persist the selected view (flow/waterfall) per user. 🟢 S
33. Deep-link to a specific span (`/traces/{id}?span=`). 🟡 S
34. Copy-node-as-JSON. 🟢 S
35. Render errors with the exception message on the node. 🔴 S
36. Show cost/tokens as a subtle heat color on nodes. 🟢 S
37. Group sibling tool calls visually. 🟢 M
38. A minimap density toggle for huge traces. 🟢 S
39. Animate live traces as spans arrive (real-time). 🟡 M
40. Export the graph as PNG/SVG for sharing. 🟢 S

### Waterfall & span detail (41–55)
41. True time-bars anchored to a shared timeline axis with tick labels. 🟡 S
42. Show gaps/idle time between spans. 🟢 S
43. Render LLM messages as a chat transcript (roles, not raw JSON). 🔴 M
44. Syntax-highlight JSON input/output. 🟢 S
45. Collapse long input/output with "show more". 🟢 S
46. Copy input/output buttons. 🟢 S
47. Diff a span's input vs output where relevant. 🟢 M
48. Show invocation params (temp, max_tokens) in the detail. 🔴 S
49. Show finish_reason / stop reason. 🟡 S
50. Show the tool schema for tool spans. 🟡 S
51. Show retrieved chunks + scores for retriever spans. 🟡 M
52. Per-span cost (already on nodes) with the price basis shown on hover. 🟢 S
53. Latency percentile context ("p95 for this span type"). 🟢 M
54. Jump-to-parent / jump-to-children links in the detail. 🟢 S
55. A "logs" tab in the detail with level filter. 🟡 S

### Trace list & navigation (56–68)
56. Server-side pagination / infinite scroll. 🔴 M
57. Column filters (status, model, provider, latency, cost, tokens, tags, time range). 🔴 M
58. Full-text search over inputs/outputs. 🟡 L
59. Time-range picker. 🔴 S
60. Saved views / filters. 🟢 M
61. Sort by latency / cost / tokens / time. 🟡 S
62. Status + error badge in the row. 🔴 S
63. Cost per trace in the list (tokens already there). 🟡 S
64. Bulk select → add to dataset / delete. 🟡 M
65. Group by session/thread. 🔴 M
66. Group by trace name (aggregate stats per agent). 🟡 M
67. A "failed only" quick filter. 🟢 S
68. Live "new traces" indicator + auto-prepend. 🟢 S

### Cost & analytics (69–76)
69. Live/maintained pricing source instead of the hardcoded table. 🟡 M
70. Cost broken down by model within a trace. 🟢 S
71. Per-project cost-over-time chart. 🟡 M
72. Token/cost leaderboard (most expensive traces/prompts). 🟡 M
73. Cache-hit / cached-token accounting (providers report it). 🟢 M
74. Handle reasoning tokens (o-series) in cost. 🟡 S
75. Currency + rate config. 🟢 S
76. "Cost estimate" clearly labelled + a way to override prices. 🟢 S

### Onboarding & DX (77–86)
77. In-app "waiting for first trace" that auto-advances (already partial — poll+highlight the new one). ◑ 🟢 S
78. A copy-paste snippet per framework (LangChain/LlamaIndex/…) on the keys page. 🟡 S
79. A `provekit doctor` CLI that checks env + connectivity + instrumentors. 🟡 S
80. A public demo/sandbox project (see traces without signing up). 🟡 M
81. First-run product tour. 🟢 M
82. Empty states everywhere with the next action. 🟢 S
83. Example agents in `examples/` (LangChain, CrewAI, raw OpenAI). 🟡 S
84. A one-command local quickstart (`docker run provekit`). 🟡 S
85. Better error messages when a key/endpoint is wrong. 🟢 S
86. Inline docs links from the UI. 🟢 S

### UI/UX polish (87–94)
87. Light theme (currently dark-only). 🟡 M
88. Keyboard shortcuts + a command palette. 🟢 M
89. Responsive/mobile trace viewing. 🟢 M
90. Loading skeletons instead of "Loading…". 🟢 S
91. Toast/notification system consistency. 🟢 S
92. Accessibility pass (focus states, ARIA, contrast). 🟡 M
93. Density toggle (comfortable/compact). 🟢 S
94. Persist user prefs (theme, view, density). 🟢 S

### Platform, security & ops (95–100)
95. PII redaction/masking on ingest. 🔴 M
96. SSO / SAML / OAuth login. 🔴 L
97. Audit logs. 🟡 M
98. Comments / annotations on a trace (collaboration). 🟡 M
99. Backups automation + restore docs (recipe exists; automate it). 🟡 S
100. Content-Security-Policy + a security hardening pass for public hosting. 🔴 S

---

## Part 3 — where I'd actually start (the top 10)

Given the research **and** the honest reality that shipping beats building, these 10 give the
most "world-class" credibility per unit effort — most reuse data ProveKit already ingests:

1. **Deep span-detail panel** (#24, #48–51) — surface invocation params, tool schemas, finish
   reasons, RAG chunks that OpenInference already sends. *Presentation, not new capture.* 🔴 S–M
2. **LLM messages as a chat transcript** (#43) — the single biggest "feels basic → feels pro" win. 🔴 M
3. **Trace list: filter + time-range + pagination + search** (#56–62). 🔴 M
4. **Sessions/threads** (#22, #7, #65) — multi-turn grouping. 🔴 M
5. **Shareable trace links** (#19). 🔴 S
6. **Datasets + curate-from-trace** (#1–2) — the foundation everything eval builds on. 🔴 M
7. **Code + LLM-as-judge scorers + a simple experiment** (#3–5). 🔴 L
8. **`pk.score()` + human feedback capture** (#9, #98). 🔴 S–M
9. **A dashboard** (latency/cost/tokens/error over time) + basic alerts (#31–32). 🔴 L
10. **PII redaction + CSP** (#95, #100) — the two that gate real production use. 🔴 S–M

**Caveat from the research:** the verified evidence concentrated on LangSmith/Langfuse/
Braintrust/Phoenix; gateway tools (Helicone/Portkey), OTel-native tools (OpenLIT/Traceloop),
and the enterprise/ingestion-scale dimensions are under-covered here — revisit before
committing to items #37, #45–47, #96–97. And remember: **a shipped tool with 20 of these
beats a perfect roadmap with 0 users.**
