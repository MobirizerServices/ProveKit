# Community post variants

Each community has a different culture — a copy-pasted HN post reads as spam everywhere
else. These are written native to each place. Post to HN first (it's the canonical thread),
then adapt these over the following days. Always lead with the demo GIF/video.

**Universal rules:** disclose you're the author, no upvote-begging, reply to every comment
fast, and never cross-post the identical text. Read each community's self-promotion rules
first (some require a ratio of contribution to self-posts).

---

## r/LocalLLaMA

*Culture: practitioners, local-first zealots, allergic to SaaS and hype. Lead with
offline + no-account. They will respect "MIT, runs with no key" more than any feature.*

**Title:** `ProveKit: open-source client to test/eval any agent (LLM, MCP, HTTP) — runs offline, no account`

**Body:**
> I kept ending up with three tabs open to test one agent — curl for the HTTP endpoint, the
> MCP Inspector for the tools, and a Python script for the eval — and none of them shared
> anything. So I built one client that does all three.
>
> ProveKit lets you point at an LLM API, an MCP server, an HTTP agent, or an A2A agent, run
> it with live streaming, then turn that run into an assertion (contains / json_path /
> latency / llm-judge / …) and save it as a plain-text `.provekit` file you can run in CI.
>
> It's MIT and **local-first** — no account, no telemetry, and it ships with a keyless mock
> agent so you can try the whole thing offline before pointing it at anything real. Works
> against any OpenAI-compatible base URL too (vLLM, Ollama, LM Studio, OpenRouter).
>
> MCP is first-class: stdio + Streamable HTTP, OAuth 2.1, and it can test a server against
> both the 2025 and the newer 2026 stateless spec generations.
>
> Demo (90s): <link> · Repo: <link>
>
> It's early — no external security audit yet, not load-tested against real providers at
> scale — which is exactly why I want people running it against their own setups. Would love
> to know what breaks and which local backends you'd want first-class support for.

---

## r/LLMDevs

*Culture: builders shipping LLM apps, care about eval rigor and CI. Lead with the
observability-vs-evals gap and the CI story.*

**Title:** `Built a universal agent client — turn a live run into a regression test, run it in CI (open source)`

**Body:**
> Everyone has tracing now (~89% adoption in LangChain's survey) but almost no one has evals
> (~52%) — because evals are code-first and annoying to write. I tried to close that gap with
> an interactive-first tool.
>
> ProveKit: point it at any agent (LLM / MCP / HTTP / A2A), poke at it live, then click once
> to turn the run you just watched into an assertion. Save the request + assertions as
> git-diffable `.provekit` files (connections referenced by name, so no secrets in the repo)
> and run the suite headless with `provekit run` — JUnit output, non-zero exit on failure.
>
> It's a *client*, not another SDK — you don't instrument your code, you point at a deployed
> thing. It also ingests OpenTelemetry GenAI traces, so you can see runs from agents you
> built in other frameworks without swapping SDKs, and it imports promptfoo configs.
>
> MIT, FastAPI + Next.js, streaming path is fully async. Demo: <link> · Repo: <link>
>
> Open question for this crowd: is llm-judge enough for "did the agent do the right thing,"
> or do you want trajectory/goal assertions (called tool X before Y, reached goal state)?
> That's the next thing I'd build and I'd rather build what people actually need.

---

## MCP Discord / modelcontextprotocol GitHub Discussions

*Culture: people writing MCP servers, deep on the spec. This is your sharpest wedge — their
current testing story is the official Inspector, manually. Be specific and technical; don't
market. Ideally reply on a specific "I built an MCP server" thread with a clip of it running
their server.*

**Message (discussion post or thread reply):**
> If you're writing MCP servers, I built an open-source client that might save you the
> manual-Inspector loop: ProveKit connects over stdio or Streamable HTTP (with OAuth 2.1),
> auto-discovers your tools/resources/prompts, and lets you call a tool, assert on the
> structured result, and save that as a regression test you can run in CI.
>
> The bit I think matters for this group: it can run the same tool suite against a server on
> the **2025-11-25 stateful** spec and the new **2026-07-28 stateless** revision, so you can
> diff behavior across the transition instead of eyeballing it.
>
> It's MIT and local-first. Happy to point it at your server and send back a 60s clip of it
> exercising your tools if that's useful — genuinely want feedback on whether the assertion
> model fits how you think about testing a server.
>
> Repo: <link>

**When replying to someone's "I shipped an MCP server for X" post** (the give-first move):
> Nice — just pointed ProveKit at it, here's a 60s clip of it discovering your tools and
> asserting `<tool>` returns valid <shape>: <clip>. If you want the test as a committable
> file it's one export. Repo if useful: <link>

---

## Framework Discords (LangChain / LangGraph / CrewAI / Pydantic AI / Mastra)

*Culture: people who already built an agent in that framework. Angle: test it from the
outside, and you don't have to rip out their tracing.*

**Message:**
> For anyone with an agent built in <framework> — I made an open-source client to test it
> from the outside (no SDK to add): point ProveKit at the deployed endpoint, run it, assert
> on the output, and freeze that into a CI test. It also ingests your OpenTelemetry GenAI
> traces, so it sits alongside whatever tracing you already have rather than replacing it.
> MIT, runs locally. Demo: <link> · Repo: <link> — curious if the black-box testing angle is
> useful or if you'd rather it hook into <framework> directly.

---

## Twitter/X (building-in-public reply + a standalone thread)

**Standalone (post with the 30s video):**
> Testing an AI agent shouldn't need 3 tabs (curl + MCP Inspector + a python eval script).
>
> ProveKit is one open-source client: point it at any agent (LLM / MCP / HTTP / A2A), run it
> live, turn the run into a test in one click, run the suite in CI.
>
> MIT, local-first, runs offline. 🧵/link

**Helpful reply to someone demoing an agent (do this often, sparingly self-promotional):**
> love this — does it have regression tests yet? if useful, you can point this at it and turn
> a run into a CI test in ~2 min (open source): <link>. happy to record it running yours.

---

## Timing summary

1. **Day 0:** Show HN (canonical thread). Engage 6h.
2. **Day 0–1:** r/LocalLLaMA + r/LLMDevs. MCP Discord + 3–5 give-first thread replies.
3. **Day 1–3:** framework Discords, Twitter thread, and continued give-first replies as you
   see people ship agents/servers.
4. **Everywhere:** link the demo, disclose authorship, answer fast, don't spam identical text.
