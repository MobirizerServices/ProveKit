# Framework quickstarts

Copy-paste starting points for the three frameworks people ask about most: **LangGraph**,
**CrewAI**, and **LlamaIndex**. Each section is a program you can paste into a file and run.

The integration is the same in all three — `pip install`, two environment variables, one
decorator at the entrypoint — because ProveKit doesn't have a per-framework adapter. It turns on
whichever OpenInference instrumentors are installed and lets them nest under the span the
decorator opened. The interesting part is therefore not *how you wire it up* but *what tree you
get out*, so every section below shows the actual captured tree.

Start with the [tracing guide](TRACING.md) if you haven't seen `@pk.trace` before.

## The three lines every quickstart shares

1. **Get a project key.** Portal → **Project keys** (`/api-keys`) → *Create key*. It's shown once.
2. **Point the SDK at your portal:**

```bash
export PROVEKIT_API_KEY=pk_...
export PROVEKIT_ENDPOINT=http://localhost:8000     # local dev; Docker Compose publishes :8100
```

3. **Decorate the entrypoint once.** Not every node, not every tool — the one function that
   represents "a run". Everything beneath it nests on its own.

If you'd rather not have a decorator at all, `import provekit.auto` at the top of your program
turns tracing on and captures the framework's spans as their own traces. The decorator only
exists to group one run under one named root, which is usually what you want for an agent.

## What actually auto-instruments

`backend/provekit/trace.py` holds the list (`_INSTRUMENTORS`), and it is the only thing that
decides whether a framework captures itself. For the three frameworks here:

| Framework | Instrumentor module | Ships in |
|---|---|---|
| LangGraph | `openinference.instrumentation.langchain` (there is **no** LangGraph-specific instrumentor) | `provekit[trace-all]` |
| CrewAI | `openinference.instrumentation.crewai` | `provekit[trace-all]` |
| LlamaIndex | `openinference.instrumentation.llama_index` | `provekit[trace-all]` |

`provekit[trace]` only carries the OpenAI and Anthropic instrumentors. With `[trace]` alone you
still get the model calls a framework makes — they go through a provider SDK — but you lose the
framework's own structure: the graph nodes, the crew, the retriever. Use `[trace-all]` for
anything on this page.

## How a span becomes a node

Worth reading once, because it explains the shape of all three trees below.
`services/otel.py` keeps **every** span and classifies each one from its attributes:

- `gen_ai.operation.name = invoke_agent` → **agent** (this is what `@pk.trace` sets)
- a `gen_ai.tool.name` attribute → **tool**
- a model or provider attribute (`gen_ai.request.model`, `llm.model_name`, `llm.provider`) → **llm**
- anything else → **step**

Framework structure spans — a LangGraph node, `Crew.kickoff`, a LlamaIndex retriever — carry no
model attribute, so they land as **step** nodes. That's the intended outcome: they're the shape
of the run, not calls to anything. The classification reads gen_ai/OpenInference *attributes*,
not the framework's own span kind, so a CrewAI span that OpenInference tags `AGENT` still renders
as a step. It is present, named, timed, and clickable either way.

---

## LangGraph

```bash
pip install "provekit[trace-all]" langgraph langchain-openai
```

LangGraph is captured through **LangChain's** instrumentor. LangGraph is built on
`langchain-core`, and every node invocation, sub-graph, and model call goes through that
callback system — which is exactly what `openinference-instrumentation-langchain` hooks. So
there is nothing LangGraph-specific to install, and nothing to add per node.

```python
from typing import TypedDict

import provekit.trace as pk
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph

model = ChatOpenAI(model="gpt-4o-mini", temperature=0)


class State(TypedDict):
    question: str
    docs: str
    answer: str


def retrieve(state: State) -> dict:
    return {"docs": f"[3 knowledge-base snippets for: {state['question']}]"}


def generate(state: State) -> dict:
    prompt = f"Context: {state['docs']}\nQuestion: {state['question']}"
    return {"answer": model.invoke(prompt).content}


g = StateGraph(State)
g.add_node("retrieve", retrieve)
g.add_node("generate", generate)
g.add_edge(START, "retrieve")
g.add_edge("retrieve", "generate")
g.add_edge("generate", END)
app = g.compile()


@pk.trace(name="langgraph-agent")           # the only ProveKit line in the file
def ask(question: str) -> str:
    return app.invoke({"question": question})["answer"]


print(ask("What's your pricing for a 20-person team?"))
```

### What shows up

One trace per `ask()` call:

```
langgraph-agent            agent   ← the decorator
└─ LangGraph               step    ← the compiled graph's own span
   ├─ retrieve             step    ← your node function
   └─ generate             step
      └─ ChatOpenAI        llm     ← model, prompt, completion, token counts
```

The graph span appears because the compiled graph is itself a LangChain runnable, and so is every
node — that's the whole reason no LangGraph-specific instrumentor is needed. Sub-graphs used as
nodes nest the same way: a compiled graph
invoked inside a node produces another `LangGraph` span underneath, and a `Send`-based
map-reduce fan-out produces one sibling subtree per dispatched branch.

**Runnable examples:** [`examples/langgraph_demo.py`](../examples/langgraph_demo.py) is the same
two-node graph over a small knowledge base, with a canned chat model so it runs with no LLM key.
[`examples/langgraph_complex_demo.py`](../examples/langgraph_complex_demo.py) is the deep
version — parallel fan-out, a sub-graph as a node, a critique→revise cycle, a flaky tool that
fails then retries, five models. [`testkit/`](../testkit/) packages both with a
`requirements.txt` and a `.env.example` if you want a folder to hand someone.

> **Verified.** Both examples were run against a local OTLP sink with no network and no API key.
> `langgraph_demo.py` produced 4 traces of 5 spans each with exactly the tree above (the LLM span
> named `CannedChat`, 32/14/46 prompt/completion/total tokens);
> `langgraph_complex_demo.py` produced 138 spans across 2 traces, 4 levels deep, with the
> per-branch subtrees and the failed-then-retried `fetch-attempt-1` span. Neither was run against
> a live provider: swap in `ChatOpenAI` and the LLM span takes that class's name and model id.

---

## CrewAI

```bash
pip install "provekit[trace-all]" crewai
```

```python
import provekit.trace as pk
from crewai import LLM, Agent, Crew, Task

llm = LLM(model="openai/gpt-4o-mini")       # reads OPENAI_API_KEY

researcher = Agent(role="Researcher", goal="Answer pricing questions",
                   backstory="You know the price book.", llm=llm)
task = Task(description="What does the Pro plan cost?",
            expected_output="One sentence.", agent=researcher)
crew = Crew(agents=[researcher], tasks=[task])


@pk.trace(name="pricing-crew")
def run(question: str) -> str:
    return str(crew.kickoff(inputs={"question": question}))


print(run("What does the Pro plan cost?"))
```

### What shows up

```
pricing-crew                        agent   ← the decorator
└─ Crew_<uuid>.kickoff              step    ← the crew run
   └─ Researcher._execute_core      step    ← one per agent turn
      └─ ChatCompletion             llm     ← model, both messages, finish reason, token counts
```

Two instrumentors are doing the work, which is why `[trace-all]` matters here. The **CrewAI**
instrumentor produces the crew and agent-turn spans, giving you the shape of the run; the
**provider** instrumentor produces the model call. Note that the crew/task identifiers CrewAI
puts on those spans do not survive ingest — `map_span` in `backend/provekit/services/otel.py`
keeps a curated set of attributes, and anything outside it is dropped. You get the tree and the
timings, not `crew_id`. Recent CrewAI calls the OpenAI SDK
directly, so with an `openai/...` model the LLM span comes from
`openinference-instrumentation-openai` (in the base `[trace]` extra). Route the crew through
another provider and the corresponding instrumentor picks it up instead, as long as it's in the
list in `trace.py`.

A crew with tools adds a span per tool call under the agent turn. Multi-agent crews add one
`_execute_core` sibling per delegation, so the trace reads as the sequence of turns that actually
happened rather than the crew you declared.

**Runnable example:** none in `examples/` yet — the program above is the starting point.

> **Verified.** The program above was run end to end (CrewAI 1.15.5) against a local
> OpenAI-compatible stub and a local OTLP sink: no real API key, no outbound network. It produced
> the 4-span trace shown above with `llm.model_name=gpt-4o-mini` and 120/24/144 tokens. What was
> **not** exercised: a real provider endpoint, tools, and multi-agent delegation — the tool and
> delegation shapes described above are read from the instrumentor's behaviour, not observed here.

---

## LlamaIndex

```bash
pip install "provekit[trace-all]" llama-index
```

```python
import provekit.trace as pk
from llama_index.core import Document, VectorStoreIndex

index = VectorStoreIndex.from_documents([
    Document(text="The Pro plan is $49/seat/mo; annual billing saves ~15%."),
    Document(text="Refunds land in 3-5 business days."),
])
engine = index.as_query_engine()            # defaults to OpenAI; reads OPENAI_API_KEY


@pk.trace(name="docs-qa")
def ask(question: str) -> str:
    return str(engine.query(question))


print(ask("What does the Pro plan cost?"))
```

### What shows up

LlamaIndex is the most granular of the three — its instrumentor traces the whole query pipeline,
not just the model call:

```
docs-qa                                          agent   ← the decorator
└─ RetrieverQueryEngine.query                    step
   └─ RetrieverQueryEngine._query                step
      ├─ VectorIndexRetriever.retrieve           step
      │  └─ VectorIndexRetriever._retrieve       step
      │     └─ <Embed>.get_query_embedding       step
      │        └─ <Embed>._get_query_embedding   step
      └─ CompactAndRefine.synthesize             step
         └─ CompactAndRefine.get_response        step    ← one nesting per refine round, so a
            ├─ TokenTextSplitter.split_text      step      long-context answer shows the loop
            └─ CompactAndRefine.get_response     step
               ├─ TokenTextSplitter.split_text   step
               └─ DefaultRefineProgram.__call__  step
                  └─ <LLM>.predict               llm    ← model, messages, token counts
                     └─ <LLM>.complete           llm
```

`<LLM>` and `<Embed>` are the class names of whatever you configured — with the defaults above,
the OpenAI classes. The retrieve/synthesize split is the useful part: it tells you whether a wrong
answer came from fetching the wrong chunks or from reasoning badly over the right ones.

What it does **not** give you today is the chunks themselves. LlamaIndex emits them as
`retrieval.documents.N.*`, and ingest drops them — `map_span` keeps a curated attribute set
(model, messages, tokens, tool name, session, finish reason) and discards the rest, so the
retriever and embedding spans persist as bare steps with a label and timing. If you need the
retrieved text in the trace, put it on a span yourself:

```python
with pk.span("retrieve", input=question) as s:
    nodes = retriever.retrieve(question)
```

**Runnable example:** none in `examples/` yet — the program above is the starting point.

> **Verified.** The program above was run end to end (`llama-index-core` 0.14.23) with
> `MockLLM` and `MockEmbedding` substituted via `Settings`, against a local OTLP sink: no API
> key, no outbound network. It produced the 15-span tree shown above. The sink captured the raw
> OTLP, *not* a ProveKit instance — so the tree shape is verified, while what each span carries
> after ingest is read from `map_span`. Substituting the real OpenAI defaults changes the LLM
> span's model name and token counts; it was not run against a live provider.

---

## Everything else

The frameworks above are three entries in one list. `_INSTRUMENTORS` in
`backend/provekit/trace.py` also covers AutoGen, OpenAI Agents, smolagents, DSPy, Haystack,
Guardrails, Instructor, Agno, and Pydantic AI, plus the provider SDKs. **Anything in that list
behaves exactly like the three above** — install its `openinference-instrumentation-*` package,
decorate your entrypoint, done. Note that `[trace-all]` bundles the common subset, not all of
them; for AutoGen, OpenAI Agents, smolagents, Guardrails, Instructor, Agno, Pydantic AI, Google
GenAI, and Vertex AI you install the matching instrumentor package yourself. Each is dormant
until its target library is importable, so installing one you don't use costs nothing.

**For a framework that isn't in the list at all**, you have three options and none of them
require a ProveKit change:

- If it emits OpenTelemetry spans of its own, they already nest under `@pk.trace` — the decorator
  makes its span the current context, and ProveKit's exporter ships whatever the OTel SDK
  collects. Spans without gen_ai attributes land as **step** nodes.
- If it makes its LLM calls through a provider SDK that *is* instrumented, you get the model
  calls automatically and can add the framework's structure with `with pk.span("plan"):` — one
  line per step you care about.
- If it does neither, wrap the calls yourself with `pk.span()` and set
  `gen_ai.input.messages` / `gen_ai.output.messages` so the portal renders the input and output.
  See [TRACING.md](TRACING.md#sub-steps-with-pkspan).

Anything that speaks OTLP/JSON can `POST` to `${PROVEKIT_ENDPOINT}/v1/traces` with the project
key as a bearer token, in any language — the Python SDK is the convenient path, not the only one.

## If nothing shows up

Tracing is fail-open by design, so a bad key, a missing extra, and an unreachable portal all look
identical: nothing happens. `provekit-doctor` is the thing that tells you which:

```
$ provekit-doctor
ProveKit doctor
===============

  PASS  PROVEKIT_API_KEY
        set (pk_tes…test)
  PASS  PROVEKIT_ENDPOINT
        http://localhost:8000
  PASS  opentelemetry-sdk
        installed
  PASS  Instrumentation
        auto-instrumenting crewai, llama_index, openai
  WARN  Instrumentation gap
        installed but not instrumented: httpx, requests
        → Calls to these won't appear as spans. pip install "provekit[http]"
  PASS  Portal reachable
        http://localhost:8000/v1/traces accepted the request (200)

Tracing will work, but something above will limit what you capture.
```

The **Instrumentation** line is the one that matters on this page: it names the frameworks you
have installed whose instrumentor is also installed. If your framework is missing from it, you're
usually on `[trace]` instead of `[trace-all]`, and you'll get the model calls without the
structure. One exception to know about: the doctor probes for the `langchain` meta-package, so a
LangGraph project that installed only `langchain-core` won't be listed even though its graph is
being captured — trust the trace over the line in that one case.

Two other things that look like "tracing is broken" and aren't:

- **Spans arrive late.** They're batched and flushed when the process exits. In a short script,
  `pk.init(batch=False)` exports each span synchronously instead.
- **The traces page is empty but the run worked.** On ingest the project is resolved from the
  bearer key alone (`workspace_from_key`), not from whatever project the portal has selected. A
  key minted in another project writes to that other project; switch to it and the run is there.
