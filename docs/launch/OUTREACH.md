# First-10-users outreach plan

The goal of the first 10 isn't growth — it's **truth**. You need 10 developers running
AgentMan against *their own real agents* so the parts that only break in the real world
(a weird MCP server, a slow agent endpoint, an auth flow you didn't anticipate) surface
while you can still fix them fast. Optimize for depth, not reach.

## The one-liner (use it everywhere, verbatim)

> **AgentMan — the open-source universal agent client. Test, debug, and evaluate any AI
> agent (LLM, MCP server, HTTP agent, A2A) with no SDK. MIT, local-first.**

## What "activated" means (measure this, not stars)

A user is real when they've: (1) connected *their own* agent (not the mock), and (2) run it
and saved at least one assertion. Track **active self-hosted instances** and **connections
created against non-mock providers** — GitHub stars are a vanity metric that doesn't predict
retention. Add a single privacy-respecting, opt-in ping if you want counts, or just ask.

## Where the first 10 actually are (specific, not "social media")

Ranked by fit. Go narrow and deep — one great thread beats ten shallow posts.

1. **The MCP ecosystem.** People writing MCP servers have the exact pain (testing a server
   is currently: the official Inspector, manually). Modelcontextprotocol GitHub discussions,
   the MCP Discord, "I built an MCP server for X" posts on Twitter/Reddit. This is your
   sharpest wedge — reply with "you can point AgentMan at it and turn the tools into a test
   suite" and *show* it on their server.
2. **r/LocalLLaMA and r/LLMDevs.** Practitioners building agents, allergic to hype, love
   local-first + no-account. Post the demo, lead with "runs offline, no key needed."
3. **Agent-framework communities** — LangChain/LangGraph, CrewAI, Pydantic AI, Mastra
   Discords/forums. Angle: "test the agent you built in <framework> from outside it, and
   ingest its OTel traces without swapping SDKs."
4. **Twitter/X "building in public" agent devs.** Reply-guy (helpfully) on people posting
   agent demos: "does it have tests? here's a 2-min way to add regression tests to that."
5. **Your own network first.** DM 5–10 people you know who are building with agents. Warm
   intros convert 10x better than cold posts and give you honest, unfiltered feedback.

## The motion: give first, ask second

Don't pitch. **Offer to test their thing.** The killer move: someone posts an agent or MCP
server → you spend 15 minutes actually pointing AgentMan at it, record a 60s clip of it
running + one assertion, and send *that*. You've done their work for them and proven the
product in one shot. This is how you convert a skeptic into user #3.

## DM / email template (short, specific, no ask for the first message)

> Hey <name> — saw your <MCP server / agent / post>. I built an open-source client for
> testing agents like it (point it at the endpoint, no SDK) and used it on yours for a sec —
> here's a 60s clip of it running your <tool/flow> and asserting the output stays valid JSON:
> <clip>. It's MIT and runs locally. If it's useful, repo's here: <link>. Either way, would
> genuinely value your take on the assertion model — that's the part I'm least sure about.

Why it works: you led with a gift (you already tested their thing), you're not asking for
anything, and the one question you do ask is specific and flattering (their expertise).

## Two-week plan

**Week 1 — instrument and seed.**
- Ship the Show HN (see SHOW_HN.md) with a working demo GIF. Engage hard for 6 hours.
- Same day: post to r/LocalLLaMA + r/LLMDevs and drop the "give-first" clips in 3–5 MCP/agent
  threads. DM 5 people in your network.
- Watch for the first real connection-against-a-real-provider. When it happens, DM that user,
  thank them, ask what almost made them bounce. Fix that thing this week.

**Week 2 — depth with the ones who showed up.**
- Get on a 20-min call with 3 activated users. Watch them use it (don't guide). Every place
  they hesitate is a bug or a doc gap. This is worth more than any amount of new traffic.
- Ship 2–3 fixes from those sessions and tell each user "you asked for this, it's in." That
  turns a trial user into an advocate and often into a contributor.
- Ask each: "who else building agents should try this?" — that's how 10 becomes 30.

## Objections you'll hear (and honest answers)

- **"How's this different from LangSmith/Langfuse?"** They instrument your code and show
  traces after the fact; this is a client you point at a deployed agent, no SDK — and it can
  *ingest* their OTel traces too, so it's complementary, not a replacement.
- **"How's this different from Promptfoo?"** Promptfoo is a great CLI/YAML batch runner (now
  owned by OpenAI). AgentMan is interactive-first and vendor-neutral — you poke at the agent
  live, then freeze it into a test. It can import promptfoo configs.
- **"Why not just use Postman?"** Postman's agent support is closed, credit-metered, and
  OpenAI-compatible-only. This is MIT, local-first, protocol-native (MCP dual-spec, A2A), and
  the tests live in your repo.
- **"Is it production-ready?"** Be honest: "it's early — secure defaults and tested, but no
  external pentest and not load-tested against real providers at scale yet. That's exactly
  why I want early users. Run it locally first." Honesty converts; overclaiming gets caught.

## What to resist

- Don't chase stars or a viral moment; chase 10 people who *keep using it*.
- Don't add features from a loud thread before you've watched a real user hit the wall.
- Don't paywall or gate anything yet — the whole asset right now is trust and adoption.
