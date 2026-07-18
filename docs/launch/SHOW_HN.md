# Show HN — launch post

> Draft copy for the Show HN post + the author's first comment. HN rewards plainness and
> honesty and punishes marketing. Every line below is written to that audience: what it is,
> how to try it in 30 seconds, and what's genuinely unfinished.

---

## Title options (pick one — keep it literal, no adjectives)

1. **Show HN: ProveKit – open-source "Postman for AI agents"**
2. **Show HN: Test and eval any AI agent (LLM, MCP server, HTTP agent) – no SDK**
3. **Show HN: A universal client to test, debug, and deploy AI agents (MIT)**

HN favors #1 or #2 — a concrete metaphor or a concrete capability. Avoid "world-class",
"revolutionary", "AI-powered". The metaphor ("Postman for agents") does the work.

---

## Post body

> ProveKit is an open-source client for testing and evaluating AI agents. You point it at
> an LLM API, an MCP server, an HTTP agent, or an A2A agent — no SDK, no code changes — then
> chat with it, stream the output, assert on the result, and freeze that into a regression
> test you can run in CI.
>
> The gap I kept hitting: the observability tools (LangSmith, Langfuse, Braintrust) want you
> to instrument your code and look at traces *after the fact*. The eval tools (Promptfoo,
> DeepEval) are great but are CLI/YAML batch runs — no interactive client. And the visual
> builders (n8n, Flowise) want you to rebuild your agent in their canvas. Nobody had the
> Postman thing: a client you point at an agent you already have and just *poke at it*.
>
> So ProveKit is that. Concretely:
> - Connect an LLM / MCP server / HTTP agent / A2A agent; run it and stream tokens live.
> - Turn any run into an assertion in one click (contains / json_path / latency / llm-judge…).
> - Save requests + assertions as plain-text `.provekit` files (git-diffable, no secrets in
>   them) and run the suite headless with the `provekit` CLI — JUnit output for CI.
> - Build multi-step flows visually, step-debug them with breakpoints, and deploy a flow as
>   a versioned hosted API endpoint.
> - MCP is first-class: stdio + Streamable HTTP, OAuth 2.1, and it can test a server against
>   both the 2025 and the new 2026 stateless spec generations.
>
> It's MIT, local-first, and runs fully offline with a keyless mock agent, so you can try it
> without an API key or an account.
>
> Try it:
> ```
> git clone … && cd provekit && make setup && make backend  # + make frontend
> ```
> Open localhost:3001, hit Run on the seeded demo agent.
>
> **Honest status:** it's early. I've written the security model (encrypted creds, SSRF
> guard, tenant isolation — see SECURITY.md) but it hasn't had an external pentest. It's
> tested (81 tests) and I load-tested the async streaming path (60 concurrent streams, no
> errors), but not against real providers at scale. No email-verification provider is bundled
> (SMTP is configurable, else reset links get logged). I'd love feedback on the assertion
> model and which protocols matter most to you.
>
> Repo: <link> · 2-min demo: <gif/loom link>

---

## Author's first comment (post immediately after submitting)

> Author here. Quick backstory + a few things I'd genuinely like input on.
>
> I built this because I was testing an agent that used an MCP server plus a couple of model
> calls, and I had three tabs open: curl for the HTTP agent, the MCP Inspector for the tools,
> and a Python script for the eval. They didn't share anything. ProveKit collapses that into
> one client where the same run you just watched becomes the test you commit.
>
> Design decisions I'm not sure about and want to hear opinions on:
> - **Assertions.** Right now it's contains/equals/regex/json_path/json_schema/tool_called/
>   latency/llm-judge. Is llm-judge enough for "did the agent do the right thing", or do
>   people want trajectory/goal-based checks (did it call tool X before Y)?
> - **The `.provekit` file format.** I made it plain-text YAML, connections referenced by
>   name so no secrets leak into the repo. Curious if people would actually commit these.
> - **Deploy.** A flow can become a hosted endpoint. I'm treating that as retention glue, not
>   the pitch — the pitch is testing. Push back if you think that's backwards.
>
> Tech: FastAPI + Next.js. The streaming path is fully async (httpx.AsyncClient) so a
> long stream doesn't hold a thread. Providers: OpenAI Chat + Responses/Open Responses,
> Anthropic Messages, MCP (dual spec), A2A, plus OpenTelemetry GenAI trace ingest so you can
> see traces from agents built in *other* frameworks without swapping in an SDK.
>
> Not trying to compete with the observability platforms — different shape (they instrument
> your code; this is a client you point at a deployed thing). Happy to answer anything.

---

## Mechanics (the stuff that decides whether it lands)

- **When:** Tue–Thu, ~8–10am ET (weekday US morning is peak HN). Avoid weekends/holidays.
- **The demo matters more than the words.** Record a <90s GIF/Loom: connect → run → stream →
  one-click assert → run the suite in a terminal. Put it at the top of the README too.
- **Reply to every comment for the first 4–6 hours**, fast and substantively. Engagement in
  the first hour drives ranking. Don't get defensive on criticism — "good point, that's on
  the roadmap / here's why I chose X" converts skeptics.
- **Don't ask for upvotes anywhere** (HN will bury it). Just post and engage.
- **Have the repo ready:** a README that works clone-to-run, a LICENSE, a CONTRIBUTING, a
  demo GIF, and issues enabled. A broken `make setup` in the first hour kills it.
- **Cross-post *after* HN**, not before, so the HN thread is the canonical discussion. Then
  Reddit (r/LocalLLaMA, r/LLMDevs), then the MCP/agent Discords (see OUTREACH.md).
- **If it doesn't land, that's normal.** Bruno needed an incumbent's blow-up *and* a second
  HN attempt. Iterate the title/demo and try again in a few weeks with a concrete new thing.
