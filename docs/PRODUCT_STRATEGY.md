# ProveKit — Product Strategy (finalized July 16, 2026)

> Synthesis of a 4-track deep research effort (competitive landscape in testing/evals,
> builders/deployment, protocol standards, and OSS business playbooks). ~180 sources,
> star counts and pricing verified live on 2026-07-16. Full source lists live in the
> research reports; the key citations are inlined below.

---

## 1. The finalized idea

**ProveKit is the open-source universal agent client.**

> *Test, debug, and evaluate any AI agent — any provider, any protocol, no SDK required.
> Point it at an LLM API, an MCP server, or a deployed HTTP agent; chat and stream with it;
> step-debug it; freeze sessions into assertions and regression suites; run them in CI;
> and promote what works into a versioned, hosted endpoint.*

One sentence for the README: **"The place where you prove your agent works."**

This is the Postman insight transplanted to agents: a *client* you point at someone
else's (or your deployed) endpoint with zero code changes — not another SDK you
instrument your code with, and not another canvas to rebuild your agent in.

---

## 2. Why this exact position (the evidence)

### The seat is empty — verified from three independent directions

1. **Every observability/evals platform is instrumentation-first.** LangSmith, Langfuse,
   Braintrust, Phoenix, Opik: you add their SDK/OTel exporter to *your* code and look at
   traces after the fact. Their "playgrounds" are clients for *model APIs*, not agents.
   Smoking gun: Langfuse discussion #7346 ("Test own LLM application endpoint in the
   playground") — maintainer, 2025: *"not possible yet, on our roadmap."*
2. **The only comparable assertion engine is batch-only and no longer neutral.**
   Promptfoo (CLI/YAML, no interactive client) was **acquired by OpenAI in March 2026**.
   Helicone → Mintlify (maintenance mode). Galileo → Cisco. Langfuse → ClickHouse.
   OpenAI's hosted Evals + Agent Builder **shut down Nov 30, 2026** — with an official
   migration pointer to Promptfoo. The vendor-neutral, open-source position is vacant
   *this year*.
3. **Every funded interactive agent-tester went voice-vertical** (Coval $31M, Hamming,
   Cekura). The horizontal text/HTTP/MCP developer client was left unbuilt. The two
   protocol clients that exist are shallow (official MCP Inspector — no suites/CI) or
   single-protocol (MCPJam, 2.1k★, "Postman for MCP" — that narrower wedge is taken).

### The demand is quantified

- LangChain's State of Agent Engineering: **~89% observability adoption vs ~52% evals**;
  quality is the #1 barrier to production (32%). Teams can *watch* agents but can't
  *test* them. The stated reason evals lag: they're code-first and hard. An interactive
  **session → one-click assertion → dataset suite → CI** flow attacks exactly that gap.

### What NOT to build: the canvas is commoditized

- n8n ~197k★, Langflow ~152k★, Dify ~149k★, Flowise ~55k★ — all with self-host and
  flow-as-API-endpoint. **Deploy-as-endpoint is table stakes, not a wedge.**
- OpenAI killed its own Agent Builder after ~13 months despite unbeatable distribution.
  Big platforms keep building *builders* and killing them; nobody builds the *client*.
- But: **no OSS player combines all four of** visual building + step-debugging +
  assertions/datasets/regression + deploy. Everyone has at most two legs
  (LangSmith: evals+debug but LangGraph-locked; Vellum: closest combo but closed and
  sales-led; Dify: best OSS step-debug, zero evals; Flowise: evals paywalled;
  n8n: evals young, no step-debugger). ProveKit keeps its flow builder + step-debugger
  as a supporting leg — **the pitch is verification, deploy is retention glue.**

### The wedge decision (was: test-first vs deploy-first vs both)

**Test-first. Definitively.** The evidence: the deploy/canvas space is saturated and
capital-flooded; the testing seat is empty; the evals user base is literally being
orphaned (OpenAI Evals shutdown Nov 2026); and the OSS distribution playbook (Bruno
610→45k★ on Insomnia's trust failure) runs on being the honest, local-first alternative
to a closed incumbent — which in this category is Postman itself (relaunched "AI-native"
March 2026, credit-metered, closed, with a documented trust deficit).

---

## 3. Target user & positioning

- **Primary:** indie developers and startup teams shipping agents to production
  (bottom-up, single-player-first adoption).
- **Secondary (expansion):** platform/QA teams standardizing agent quality gates in CI;
  enterprises needing self-hosted/air-gapped agent testing (data sovereignty is the #1
  enterprise objection to cloud agent tooling — n8n and Langfuse both converted it).
- **Against Postman:** open source, local-first forever, no login wall, no AI credits.
- **Against LangSmith/Langfuse:** no SDK, no instrumentation — point at the endpoint.
- **Against Promptfoo:** interactive-first and vendor-neutral (they're CLI-batch and
  OpenAI-owned).
- **Against n8n/Dify/Flowise:** we don't ask you to rebuild your agent in our canvas;
  we test the agent you already have, wherever it runs.

---

## 4. Protocol strategy (from the standards research)

**Table stakes by end of 2026 — must ship:**

| Protocol | Notes |
|---|---|
| MCP (stdio + Streamable HTTP + OAuth 2.1) | The single most important protocol. Linux Foundation-governed, universal vendor adoption. **Dual-spec support (2025-11-25 stateful + 2026-07-28 stateless revision) is an immediate differentiator** — "test my server against both spec generations." |
| OpenAI Chat Completions | The lingua franca; already have it. |
| OpenAI Responses / "Open Responses" | All agentic features are Responses-only; open spec cloned by vLLM/Ollama/HF/OpenRouter. Support stateful + stateless modes. |
| Anthropic Messages (native) | Content blocks, tool_use round-trips, SSE, stop_reason, beta headers. Do NOT use the OpenAI-compat shim. |
| OTel GenAI trace ingest (`gen_ai.*`) | Every framework emits it by default now. Thin mapping layer (schema still churning: accept legacy + OpenInference + v1.37+ shapes). Also emit spans from ProveKit's own runs. |
| AGENTS.md awareness | Read/validate; treat CLAUDE.md as overlay. |

**Strategic bets:** A2A agent-card client (JSON-RPC first — official A2A Inspector is
450★ v0.1.0 "hobby-grade"; cheap land-grab), promptfoo config import (catch the OpenAI
Evals + Promptfoo-neutrality refugees), Agent Skills (SKILL.md), Inspect format.

**Wait/avoid:** llms.txt, ChatKit, Managed Agents protocol, anything built on the dying
Assistants API / Agent Builder / hosted Evals.

---

## 5. Business model (from the playbook research)

**The refined Langfuse doctrine — the model the market just validated with an exit:**

1. **All product features MIT-licensed and self-hostable. Local-first and
   offline-capable, forever, in writing.** No feature rug-pulls, ever (Insomnia 8.0 is
   the archetype of trajectory-ending betrayal; Bruno's entire 610→45k★ rise was
   harvesting it).
2. **Monetize:** (a) hosted cloud with usage pricing (per eval-run/trace, retention
   tiers) and **unlimited seats** (the Langfuse/Braintrust pattern — AI tooling is
   abandoning per-seat); (b) self-host **enterprise license** for the governance bundle:
   SCIM, fine-grained RBAC, audit logs, retention policies, SLAs (basic SSO stays free —
   avoid the resented "SSO tax"); (c) optionally a **metered server-side service**
   (hosted eval/simulation compute) free below a quota — Promptfoo's "smartest gate":
   nothing to fork.
3. **The viral artifact:** a plain-text, git-diffable test/flow file format (the `.bru`
   / Postman-collection analog). It's simultaneously the growth loop, the CI story, and
   the anti-lock-in proof. Design for a template gallery from day one (n8n's 10k+
   template/creator economy was arguably its biggest channel).
4. **Sober expectations:** open-core converts <1–2% of *active deployments* (not stars).
   First paid dollars at months 6–12; $1M ARR by month 15–24 is top-decile. The realistic
   12-month milestone is adoption + seed funding, not revenue. Acquisition is a live
   scenario in this category (Langfuse, Promptfoo both exited pre-Series-A-scale
   revenue). The most credible expansion revenue: a compliance-budget product on top of
   the wedge (agent reliability/safety certification for production deploys — the
   Promptfoo security-pivot pattern).

---

## 6. Top 5 differentiators (vs named competitors)

1. **Point-at-anything client** — LLM API / MCP server / raw HTTP+SSE agent (later A2A),
   interactive with protocol-aware streaming. Nobody has this (Postman: OpenAI-compat
   only; MCPJam: MCP only; Apidog: one-shot SSE).
2. **Session → assertion → suite in one click** — turn a live conversation into a
   regression test without writing YAML. Attacks the 89%-observability/52%-evals gap.
3. **Framework-agnostic step-debugging** — the best step-debugger today (LangGraph
   Studio) is framework-locked; Dify's is builder-locked. Ours points at anything.
4. **Git-native, local-first, MIT** — the Bruno/Hoppscotch distribution wedge aimed at
   Postman's trust deficit, in the year the neutral OSS flags (Promptfoo, Langfuse) got
   absorbed.
5. **Dual-generation MCP testing + OTel ingest** — be the reference client for the July
   2026 MCP transition and the tool that can *see* traces from any framework without an
   SDK swap.

## 7. Biggest risks

1. **Postman ships "agent request + judge assertion"** — it's one release away; closest
   capability set. Mitigants: closed source, credit metering, builder-centric gravity,
   trust deficit with exactly our audience. Speed matters.
2. **Langfuse/ClickHouse ships endpoint testing** — it's on their public roadmap
   (#7346), and they now have ClickHouse resources. Our edge: interactive client UX +
   local-first + no 6-container self-host.
3. **MCPJam expands from MCP to general agents** — same "Postman for X" DNA, funded.
4. **Category consolidation** — the acquirers (OpenAI, Cisco, ClickHouse) can bundle.
   Neutrality + OSS is the defense, and also the acquirable asset if that's the outcome.
5. **Base rates** — Bruno/Hoppscotch achieved sustainability (~20-person teams), not
   riches. The breakouts rode a wave with perfect timing (n8n) or sold distribution.
   Plan runway accordingly.

---

## 8. Six-month roadmap emphasis (reordering the existing task list)

The prototype already covers: connect (LLM/MCP/HTTP), streaming runs, assertions
(incl. llm_judge), dataset suites, flows + step-debug, run history. That's a real head
start on the empty seat. What the research changes:

**Now (weeks 1–6) — the wedge, single-player:**
- P0 security fixes (tasks #2–#6) — unchanged, still first.
- **NEW: git-diffable test/suite file format + `provekit` CLI runner with CI exit codes**
  — the viral artifact + the CI story. This outranks multi-tenant cloud.
- **NEW: protocol coverage** — OpenAI Responses/Open Responses; Anthropic Messages
  upgrades; MCP OAuth 2.1 + stdio + dual-spec (July 28 revision lands in ~2 weeks).
- **NEW: one-click "session → assertion"** UX in the console.
- **NEW: promptfoo config import** (catch the OpenAI Evals migration wave before Nov 30).

**Next (months 2–4) — launch:**
- OSS launch prep: MIT license, README/docs, template gallery, Show HN. Bruno/Langfuse
  precedent: 1k–5k stars if the launch lands; budget for it not landing first try.
- OTel GenAI trace ingest; AGENTS.md awareness; A2A agent-card client (cheap land-grab).
- Deploy-as-endpoint (#13–#15) ships here as **retention glue, not the pitch**.

**Later (months 4–6+) — monetize:**
- Hosted cloud (auth #7, tenancy #9, Postgres #8, Redis #10, async #11, quotas #12
  move here — they serve the *cloud*, which follows OSS adoption, not precedes it).
- Enterprise self-host license scaffolding (SCIM/RBAC/audit) only when pulled.

**Positioning sentence to build everything around:**
*"The place where you prove your agent works — before and after every change,
wherever it runs."*
