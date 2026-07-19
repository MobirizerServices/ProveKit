// Blog posts as plain data (no CMS, no build-time deps). Bodies are a small Markdown subset
// rendered by components/Markdown.tsx. Server-importable — used by the blog, sitemap, and RSS.

export interface Post {
  slug: string;
  title: string;
  date: string;        // ISO
  author: string;
  description: string;
  tags: string[];
  minutes: number;
  body: string;        // markdown subset
}

export const POSTS: Post[] = [
  {
    slug: "introducing-provekit",
    title: "Introducing ProveKit: drop-in tracing for any AI agent",
    date: "2026-07-19",
    author: "The ProveKit team",
    description:
      "See exactly what your AI agent did — add one decorator and get the whole nested flow, plus evaluation, dashboards, and a CI gate. Open source and self-hostable.",
    tags: ["announcement", "observability"],
    minutes: 4,
    body: `Agents are easy to build and hard to trust. A single request fans out into planner
calls, tool calls, retries, and sub-agents — and when something goes wrong, you're left
grepping logs to reconstruct what actually happened.

**ProveKit** makes that flow visible. Add one decorator (or a single \`import\`) and every run
your agent makes shows up in your portal as a nested trace — the model calls, the tools, the
retries, the failures — each with its input, output, tokens, cost, and logs.

## What you get

- **Drop-in tracing.** One import auto-captures OpenAI, Anthropic, LangChain, LlamaIndex,
  CrewAI, and your outbound HTTP — no per-call wiring.
- **A flow graph and a waterfall.** See the run as an animated node graph or a
  time-proportional waterfall. Click any span for the details.
- **Evaluation and CI gates.** Build datasets from real traces, score with built-in or custom
  scorers, and fail your build on a regression with \`pk.evaluate()\`.
- **Dashboards and alerts.** Latency, error rate, tokens, and cost over time — with threshold
  alerts.

## Two lines to your first trace

\`\`\`python
pip install "provekit[trace]"

import provekit.auto          # one import — captures everything below it
\`\`\`

That's the whole client integration. Everything else — the graph, the evals, the dashboards —
lives in the portal, which you can [self-host](/blog/self-host-provekit) on your own infra.

ProveKit is open source. [Star it on GitHub](https://github.com/MobirizerServices/ProveKit)
and tell us what your agents are doing.`,
  },
  {
    slug: "trace-an-agent-in-one-line",
    title: "Trace a LangChain (or any) agent in one line",
    date: "2026-07-19",
    author: "The ProveKit team",
    description:
      "How ProveKit captures the full nested flow of an agent with a single import — and how to add custom spans and scores where you want them.",
    tags: ["tutorial", "tracing"],
    minutes: 5,
    body: `The fastest way to trace an agent with ProveKit is to add nothing to your agent at
all. One import at your entrypoint turns on OpenTelemetry-based auto-instrumentation for the
libraries you already use.

## The one-liner

\`\`\`python
import provekit.auto      # reads PROVEKIT_API_KEY / PROVEKIT_ENDPOINT
\`\`\`

After this, calls to OpenAI, Anthropic, LangChain, LlamaIndex, CrewAI — and, with
\`provekit[http]\`, your outbound HTTP — are captured on their own and nested under the run.

## Group a run under a named root

Wrap your entrypoint so a whole invocation groups into one trace:

\`\`\`python
import provekit.trace as pk

@pk.trace(name="support-agent", session_id="conv-123")
def run(question):
    ...
\`\`\`

The optional \`session_id\` groups multi-turn conversations together in the portal.

## Custom steps and scores

For your own logic, wrap a block with \`pk.span()\`, and attach feedback with \`pk.score()\`:

\`\`\`python
with pk.span("retrieve") as s:
    docs = search(question)

pk.score("relevance", score=0.9)
\`\`\`

Everything is **fail-open**: if the key or endpoint aren't set, tracing degrades to a no-op and
your agent runs exactly as before. Read the full [tracing guide](https://github.com/MobirizerServices/ProveKit/blob/main/docs/TRACING.md).`,
  },
  {
    slug: "eval-gates-in-ci",
    title: "Stop shipping agent regressions: eval gates in CI",
    date: "2026-07-19",
    author: "The ProveKit team",
    description:
      "Turn production traces into a golden dataset, score a version against it, and fail the build when quality drops — with pk.evaluate().",
    tags: ["evaluation", "ci"],
    minutes: 5,
    body: `Prompt tweaks and model swaps are one-line changes with wide blast radius. The only
way to ship them safely is to measure quality on every change. ProveKit closes that loop:
capture production traces, curate the interesting ones into a dataset, then score each new
version against it.

## 1. Build a dataset

Use **"add to dataset"** on a real trace, or the Datasets page, to collect
\`{input, expected}\` examples.

## 2. Score a version

\`\`\`python
import provekit as pk

def target(question: str) -> str:
    return my_agent(question)

summary = pk.evaluate("qa-golden", target, scorers=["exact_match", "contains"])
\`\`\`

\`pk.evaluate\` pulls the dataset, runs your target over every item, scores each output, and
records an **experiment** you can compare over time.

## 3. Gate the build

Because \`evaluate\` returns the summary, a regression fails CI:

\`\`\`python
def test_agent_quality():
    summary = pk.evaluate("qa-golden", target, scorers=["exact_match", "contains"])
    assert summary["mean_score"] >= 0.8
\`\`\`

Bring your own scorers too — any \`fn(output, expected) -> float\` works, including an
LLM-as-judge. Now a bad prompt change turns red before it reaches your users.`,
  },
];

export function getPost(slug: string): Post | undefined {
  return POSTS.find((p) => p.slug === slug);
}
