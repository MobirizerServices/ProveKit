#!/usr/bin/env python3
"""ProveKit × LangGraph — a DEEP, multi-agent research orchestrator, fully auto-traced.

One run → a large, deeply-nested trace (~70 spans) from a single `@pk.trace`:

  research-orchestrator (@pk.trace)
    ├─ plan (LLM)                                   ← decompose into subtopics
    ├─ fan-out → research subgraph × N subtopics    ← PARALLEL map (LangGraph Send API)
    │    ├─ retrieve (tool)                          ← RAG: a flaky fetch that retries, + doc spans
    │    ├─ analyze (LLM)
    │    └─ critique → revise → critique  (CYCLE)    ← a reflection loop, bounded
    ├─ synthesize (LLM, a bigger model)             ← reduce: join all findings
    └─ guardrail (tool)

Runs FULLY OFFLINE by default (canned models with distinct names, so the dashboard's per-model
+ cost breakdowns fill in). Set OPENAI_API_KEY in .env to use gpt-4o-mini instead.

    pip install -r requirements.txt
    cp .env.example .env      # then fill in PROVEKIT_API_KEY / PROVEKIT_ENDPOINT
    python run_langgraph_complex.py
"""
from __future__ import annotations

import logging
import operator
import os
from typing import Annotated, TypedDict

from dotenv import load_dotenv

import provekit.trace as pk
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send
from opentelemetry.trace import Status, StatusCode

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("langgraph-complex")


class CannedChat(BaseChatModel):
    """A deterministic stand-in for a real chat model — a proper LangChain BaseChatModel, so the
    LangChain instrumentor records it as a genuine LLM span. `model_name` surfaces in the portal
    so the per-model + cost breakdowns are populated."""

    model_name: str = "canned-model"
    reply: str = "ok"
    in_tokens: int = 60
    out_tokens: int = 30

    @property
    def _llm_type(self) -> str:
        return self.model_name

    @property
    def _identifying_params(self) -> dict:
        return {"model_name": self.model_name, "ls_model_name": self.model_name}

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        msg = AIMessage(content=self.reply, usage_metadata={
            "input_tokens": self.in_tokens, "output_tokens": self.out_tokens,
            "total_tokens": self.in_tokens + self.out_tokens})
        return ChatResult(generations=[ChatGeneration(message=msg)])


def _model(name: str, reply: str, itok: int, otok: int) -> BaseChatModel:
    if os.environ.get("OPENAI_API_KEY"):
        try:
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(model="gpt-4o-mini", temperature=0)
        except Exception:
            log.warning("OPENAI_API_KEY set but langchain-openai missing — using canned models")
    return CannedChat(model_name=name, reply=reply, in_tokens=itok, out_tokens=otok)


planner = _model("gpt-4o-mini", "Subtopics: pricing, security, integrations", 120, 40)
analyst = _model("gpt-4o", "The evidence is broadly positive with two caveats.", 800, 220)
critic = _model("gpt-4o-mini", "Claims 2 and 4 need a supporting source.", 300, 90)
reviser = _model("gpt-4o", "Revised: added sources for the flagged claims.", 850, 260)
synthesizer = _model("claude-sonnet-5", "Final synthesis across all subtopics is ready.", 1500, 600)


# ---------------- research subgraph (runs once per subtopic, in parallel) ----------------
class ResearchState(TypedDict):
    # Deliberately shares only `findings` with the parent — parallel branches each write their
    # findings back through its reducer. Sharing a plain (non-reducer) key across parallel
    # branches would collide ("can receive only one value per step").
    topic: str
    docs: list
    analysis: str
    revisions: int
    findings: Annotated[list, operator.add]


def retrieve(state: ResearchState) -> dict:
    """A RAG retriever: a flaky fetch that fails once then retries, plus per-doc spans."""
    topic = state["topic"]
    with pk.span("fetch-attempt-1") as s:      # a red span inside a green run
        if s:
            s.set_attribute("gen_ai.tool.name", "web_fetch")
            s.set_status(Status(StatusCode.ERROR, "upstream timeout"))
            s.record_exception(TimeoutError("web_fetch timed out"))
        log.warning("[%s] fetch attempt 1 timed out — retrying", topic)
    with pk.span("fetch-attempt-2") as s:
        if s:
            s.set_attribute("gen_ai.tool.name", "web_fetch")
    with pk.span("retrieve-docs") as s:
        if s:
            s.set_attribute("gen_ai.tool.name", "vector_search")
        for i in range(3):
            with pk.span(f"doc:{topic}-{i + 1}"):
                pass
    return {"docs": [f"{topic} doc {i + 1}" for i in range(3)], "revisions": 0}


def analyze(state: ResearchState) -> dict:
    prompt = f"Analyze these docs for '{state['topic']}':\n" + "\n".join(state["docs"])
    return {"analysis": analyst.invoke(prompt).content}


def critique(state: ResearchState) -> dict:
    critic.invoke(f"Critique this analysis of '{state['topic']}':\n{state['analysis']}")
    return {}


def revise(state: ResearchState) -> dict:
    revised = reviser.invoke(f"Revise the analysis of '{state['topic']}' addressing the critique.")
    return {"analysis": revised.content, "revisions": state["revisions"] + 1}


def finalize(state: ResearchState) -> dict:
    return {"findings": [f"{state['topic']}: {state['analysis']}"]}


def _needs_revision(state: ResearchState) -> str:
    return "revise" if state["revisions"] < 1 else "finalize"     # bounded reflection loop


def _build_research_subgraph():
    g = StateGraph(ResearchState)
    g.add_node("retrieve", retrieve)
    g.add_node("analyze", analyze)
    g.add_node("critique", critique)
    g.add_node("revise", revise)
    g.add_node("finalize", finalize)
    g.add_edge(START, "retrieve")
    g.add_edge("retrieve", "analyze")
    g.add_edge("analyze", "critique")
    g.add_conditional_edges("critique", _needs_revision, {"revise": "revise", "finalize": "finalize"})
    g.add_edge("revise", "critique")       # the cycle
    g.add_edge("finalize", END)
    return g.compile()


research_subgraph = _build_research_subgraph()


# ---------------- parent orchestrator graph ----------------
class OrchState(TypedDict):
    question: str
    subtopics: list
    findings: Annotated[list, operator.add]
    answer: str


def plan(state: OrchState) -> dict:
    planner.invoke(f"Decompose this question into subtopics: {state['question']}")
    return {"subtopics": ["pricing", "security", "integrations"]}


def fan_out(state: OrchState):
    """Map: dispatch one parallel research branch per subtopic (LangGraph Send API)."""
    return [Send("research", {"topic": t}) for t in state["subtopics"]]


def synthesize(state: OrchState) -> dict:
    """Reduce: join all findings into one answer."""
    joined = "\n".join(state["findings"])
    answer = synthesizer.invoke(f"Synthesize a final answer from these findings:\n{joined}").content
    return {"answer": answer}


def guardrail(state: OrchState) -> dict:
    with pk.span("guardrail") as s:
        if s:
            s.set_attribute("gen_ai.tool.name", "safety_check")
    return {}


def _build_orchestrator():
    g = StateGraph(OrchState)
    g.add_node("plan", plan)
    g.add_node("research", research_subgraph)   # a compiled subgraph as a node
    g.add_node("synthesize", synthesize)
    g.add_node("guardrail", guardrail)
    g.add_edge(START, "plan")
    g.add_conditional_edges("plan", fan_out, ["research"])
    g.add_edge("research", "synthesize")        # join: runs after all branches finish
    g.add_edge("synthesize", "guardrail")
    g.add_edge("guardrail", END)
    return g.compile()


orchestrator = _build_orchestrator()


@pk.trace(name="research-orchestrator")
def research(question: str) -> str:
    """One decorated entrypoint — the whole multi-agent LangGraph run is captured beneath it."""
    result = orchestrator.invoke({"question": question})
    pk.score("depth", score=0.92, comment="demo auto-score")
    return result["answer"]


def main() -> None:
    load_dotenv()
    if not (os.environ.get("PROVEKIT_API_KEY") and os.environ.get("PROVEKIT_ENDPOINT")):
        raise SystemExit("Set PROVEKIT_API_KEY and PROVEKIT_ENDPOINT in .env (see .env.example).")
    if not pk.configure():
        raise SystemExit("ProveKit could not start — check your key/endpoint in .env.")

    for q in ("How should we evaluate ProveKit for our team?",
              "Is this platform a good fit for a regulated fintech?"):
        print("→", research(q)[:70])

    from opentelemetry import trace as _t
    provider = _t.get_tracer_provider()
    if hasattr(provider, "force_flush"):
        provider.force_flush()
    print("\nDone — open your ProveKit portal:",
          os.environ["PROVEKIT_ENDPOINT"].rstrip("/") + "/traces")


if __name__ == "__main__":
    main()
