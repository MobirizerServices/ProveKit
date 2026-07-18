# Launch kit

Copy for shipping ProveKit. Positioning is deliberate (from the competitive analysis):
lead with **activation speed + entrypoint-only capture**; state OSS / OTel-native / self-host
as reassurance in the body, never the headline (they're table stakes vs Langfuse/Phoenix).

Before posting, fill the two blanks: the **demo GIF/video URL** and the **live playground URL**.

---

## Show HN

**Title:** Show HN: ProveKit – see your agent's whole flow from one decorator

**Body:**

I've built a lot of agents, and every time I wanted to *see what the thing actually did* —
which model calls, which tools, in what order — I hit the same wall: stand up a collector,
wire an exporter, learn a platform's model, or bolt a decorator onto every function.

ProveKit is my attempt to make that a 60-second thing. You:

1. create a project in the portal and copy a key,
2. `pip install "provekit[trace]"` and put the key in `.env`,
3. add **one** `@pk.trace` at your agent's entrypoint.

That's it. Everything beneath the entrypoint nests automatically — OpenAI/Anthropic calls
instrument themselves, and you can wrap your own steps with `with pk.span("retrieve"):`. The
portal shows the run as a nested flow with a time waterfall and per-span input/output/tokens.

```python
import provekit.trace as pk

@pk.trace(name="support-agent")
def run_agent(q):
    docs = retrieve(q)              # wrap in `with pk.span(...)` to see it
    return chat(q, docs)            # the OpenAI call captures itself
```

It's open source (MIT), self-hostable, and OpenTelemetry-native underneath, so your data is
portable and there's no lock-in — but the whole point is you never have to know that.

**Honest bit:** this is a crowded space (Langfuse, Phoenix, Laminar, Opik are all great and
more mature). I'm not claiming to beat them on features — I'm betting on being the fastest,
simplest way to a full agent-flow trace when you don't want a whole LLM-engineering platform.
If that's not you, those tools are excellent. If it is, I'd love your feedback.

Demo: <DEMO_URL>  ·  Live playground: <PLAYGROUND_URL>  ·  Repo: https://github.com/MobirizerServices/ProveKit

---

## Tweet / X thread

1/ You add ONE decorator to your agent's entrypoint. You get the whole nested flow — model
calls, tools, steps — as a time waterfall, with tokens. No collector, no per-function wiring,
no OpenTelemetry to learn. Open source. 🧵 <DEMO_URL>

2/ `pip install "provekit[trace]"` → drop a key in `.env` → `@pk.trace`. Your OpenAI/Anthropic
calls instrument themselves and nest underneath. Wrap your own steps with `pk.span()` when you
want them in the tree.

3/ It's OpenTelemetry under the hood, so nothing's locked in — but you never touch OTel. The
pitch is time-to-first-trace: portal → key → decorator → live flow, in under a minute.

4/ Crowded space, and I'll say it plainly: Langfuse/Phoenix/Laminar are more mature. I'm
betting on radical simplicity for people who just want to *see what their agent did*. Self-host
it next to your app. Feedback very welcome. Repo: <REPO_URL>

---

## Product Hunt

**Tagline:** One decorator. The whole agent flow.

**Description:** ProveKit is drop-in tracing for AI agents. Add one `@pk.trace` at your
entrypoint and review every run as a nested flow — model calls, tools, steps — with a time
waterfall and token usage. OpenAI/Anthropic calls capture themselves; no collector, no
framework lock-in. Open source and self-hostable.

**First comment (maker):** I kept rebuilding the same "wait, what did my agent actually do?"
setup for every project, so I made the version I wanted: one decorator, no config, the whole
flow. It's OTel-native and MIT-licensed. Honest about the field — Langfuse/Phoenix are great;
this is for when you want the trace, not the platform. Would love your thoughts.

---

## "Why not just Langfuse?" (for the landing / FAQ)

Langfuse is excellent and more mature — if you want a full LLM-engineering platform (evals,
datasets, prompt management), use it. ProveKit is smaller on purpose: it does one thing —
capture and review your agent's flow — with the fastest possible setup. One decorator at the
entrypoint, no collector, no per-function instrumentation, no OpenTelemetry knowledge required.
Same OTLP data underneath, so you're never locked in either way.
