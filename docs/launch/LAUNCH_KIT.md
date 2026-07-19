# ProveKit — launch kit

Copy-paste-ready posts for launching provekit.online. Edit the bracketed bits, then ship.
Everything below points at the **live** site (https://provekit.online) and the public repo.

> Pre-flight (do these first): see the **Launch checklist** at the bottom.

---

## 1. Show HN

**Title** (HN likes plain + specific, ≤80 chars):

```
Show HN: ProveKit – open-source, self-hostable tracing for AI agents
```

**Body:**

```
Hi HN — I built ProveKit because debugging AI agents meant grepping logs to reconstruct
what actually happened across planner calls, tool calls, retries, and sub-agents.

ProveKit is drop-in tracing for any AI agent. You add one import:

    import provekit.auto

…and every run shows up in a portal as a nested trace — the model calls, tools, retries,
and failures, each with input/output, tokens, cost, and logs. It auto-instruments OpenAI,
Anthropic, LangChain, LlamaIndex, CrewAI and outbound HTTP via OpenTelemetry, so there's no
per-call wiring and no framework lock-in.

Beyond tracing it also does evaluation (build a dataset from real traces, score a version
with pk.evaluate() and fail CI on a regression), dashboards + alerts, and a debug-over-MCP
channel so you can point Claude/Cursor at your traces.

The part I care about most: it's open source and self-hostable. Your traces never leave your
infra, you bring your own model keys, and the whole thing is a `docker compose up`. I'm
running the hosted demo on a single VPS with its own Caddy doing auto-HTTPS.

Live: https://provekit.online
Code: https://github.com/MobirizerServices/ProveKit
Two-line quickstart: pip install "provekit[trace]"; import provekit.auto

It's early and I'd love feedback — especially on the evaluation workflow and what would make
you actually switch from raw logs. Happy to answer anything.
```

**Timing:** post ~8–10am ET on a weekday. Reply to every comment for the first few hours.

---

## 2. Tweet / X thread

**1/**
```
I built ProveKit: open-source, self-hostable tracing for AI agents.

One import → every run your agent makes shows up as a nested trace: model calls, tools,
retries, failures — with tokens, cost, and logs.

Live: https://provekit.online 🧵
```

**2/**
```
The whole client integration is one line:

    import provekit.auto

It auto-instruments OpenAI, Anthropic, LangChain, LlamaIndex, CrewAI + outbound HTTP via
OpenTelemetry. No per-call wiring, no framework lock-in.
```

**3/**
```
It's not just traces:
• flow graph + waterfall views
• evaluation: build datasets from real traces, score with pk.evaluate(), gate CI on regressions
• dashboards + threshold alerts
• debug over MCP (point Claude/Cursor at your traces)
```

**4/**
```
The important part: self-hostable and open source.

Your traces never leave your infra. Bring your own keys. `docker compose up`.

Code: https://github.com/MobirizerServices/ProveKit
Would love feedback 🙏
```

---

## 3. Product Hunt

**Tagline** (≤60 chars):
```
Drop-in, open-source tracing & evals for AI agents
```

**Description:**
```
ProveKit is open-source, self-hostable observability for AI agents. Add one import and see
every run as a nested trace — model calls, tools, retries, tokens, cost, and logs. Plus
datasets + evaluation with CI gates, dashboards, alerts, and debug-over-MCP. Your data stays
on your infra.
```

**First comment (maker):** reuse the Show HN body, trimmed.

---

## 4. Reddit (r/LocalLLaMA, r/MachineLearning [D], r/LangChain)

**Title:**
```
[P] ProveKit: open-source, self-hostable tracing + evals for AI agents (one-line setup)
```
Body: a shorter version of the Show HN post. Lead with "self-hostable, your data stays put"
for r/LocalLLaMA.

---

## 5. LinkedIn / personal note

```
For the last while I've been building ProveKit — open-source, self-hostable tracing and
evaluation for AI agents. Add one line of code and you can see exactly what your agent did:
the model calls, tools, retries, and failures, with tokens and cost. Then turn real traces
into a golden dataset and gate your CI on quality.

It's live and open source. I'd genuinely value your feedback: https://provekit.online
```

---

## Launch checklist (run before posting)

- [ ] `https://provekit.online` loads with a valid padlock (✓ live).
- [ ] Sign up works; you can create a project + key and see a trace (✓ tested).
- [ ] **Email works** — the SMTP password currently fails (535). Reset it in the Titan panel
      so password-reset/verify emails send *before* real users sign up.
- [ ] The landing OG image + title render (paste the URL into a Slack/Twitter box to preview).
- [ ] `NEXT_PUBLIC_SITE_URL=https://provekit.online` is set (so sitemap/OG resolve) — set in
      the server env if not.
- [ ] Rotate the VPS root password + disable SSH password login (security).
- [ ] Pin a GitHub repo description + topics (agent, observability, tracing, llm, evals).
- [ ] Have the 2-line quickstart ready to paste in replies.
- [ ] A demo GIF/screenshot ready (docs/launch has one; a clean screencast is better).
- [ ] Decide what "self-hosted vs hosted" you're offering, and say it clearly on the landing.

## After launch

- Reply to **every** comment for the first 4–6 hours (this is what makes/breaks HN & PH).
- Watch the dashboard: real signups will generate real traces — see what breaks under real use.
- Capture feature requests as GitHub issues; that's your real roadmap now (not the 200-list).
- Post a follow-up ("what I learned launching ProveKit") a week later — good for the blog.
