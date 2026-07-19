#!/usr/bin/env python3
"""ProveKit COMPLEX demo — a deep, multi-agent research orchestrator.

One run produces a large, deeply-nested trace that exercises nearly every ProveKit surface:

  research-orchestrator (agent)
    ├─ plan (llm)
    ├─ sub-agent: <subtopic> (agent)              ← nested agents
    │    ├─ retrieve (tool)                         ← RAG: a retriever with N doc spans
    │    │    ├─ doc:… (step) ×3
    │    ├─ analyze (llm)
    │    ├─ fetch-attempt-1 (tool)  ✗ timeout       ← a failed span, then a retry
    │    ├─ fetch-attempt-2 (tool)  ✓
    │    ├─ critique (llm)  →  revise (llm)         ← a reflection loop
    │    └─ guardrail (tool)
    ├─ … (more sub-agents)
    ├─ synthesize (llm, a bigger model)
    └─ guardrail: final (tool)
  + a feedback score on the whole run

No LLM key needed — the model is mocked, so it runs fully offline against your portal.

    pip install "provekit[trace]"
    export PROVEKIT_API_KEY=pk_...
    export PROVEKIT_ENDPOINT=https://your-provekit-host
    python examples/complex_demo.py
"""
from __future__ import annotations

import contextlib
import json
import logging
import os
import time

import provekit.trace as pk

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("research-agent")

MODELS = {"plan": "gpt-4o-mini", "analyze": "gpt-4o", "critique": "gpt-4o-mini",
          "revise": "gpt-4o", "synthesize": "claude-sonnet-5"}


# ---- span helpers (set the gen_ai.* attributes the portal classifies on) ----
@contextlib.contextmanager
def agent_span(name: str):
    with pk.span(name) as s:
        if s:
            s.set_attribute("gen_ai.operation.name", "invoke_agent")
        yield s


def _llm(step: str, prompt: str, *, temperature: float = 0.4) -> str:
    model = MODELS.get(step, "gpt-4o")
    answer = f"[{step}] " + prompt[:60].replace("\n", " ")
    with pk.span(step) as s:
        if s:
            s.set_attribute("gen_ai.request.model", model)
            s.set_attribute("gen_ai.request.temperature", temperature)
            s.set_attribute("gen_ai.request.max_tokens", 512)
            s.set_attribute("gen_ai.input.messages", json.dumps(
                [{"role": "system", "content": f"You are the {step} step."},
                 {"role": "user", "content": prompt}]))
            s.set_attribute("gen_ai.usage.input_tokens", 60 + len(prompt) // 3)
            s.set_attribute("gen_ai.usage.output_tokens", 25 + len(answer) // 3)
            s.set_attribute("gen_ai.output.messages", json.dumps([{"role": "assistant", "content": answer}]))
            s.set_attribute("gen_ai.response.finish_reasons", "stop")
        time.sleep(0.01)
    return answer


def _retrieve(query: str, k: int = 3) -> list[str]:
    with pk.span("retrieve") as s:
        if s:
            s.set_attribute("gen_ai.tool.name", "vector_search")
            s.set_attribute("gen_ai.input.messages", query)
        docs = []
        for i in range(k):
            with pk.span(f"doc:{query[:14]}#{i}") as d:
                snippet = f"Document {i} about '{query}' — relevance {0.95 - i * 0.11:.2f}"
                if d:
                    d.set_attribute("relevance_score", round(0.95 - i * 0.11, 2))
                    d.set_attribute("gen_ai.output.messages", snippet)
                docs.append(snippet)
                time.sleep(0.003)
        if s:
            s.set_attribute("gen_ai.output.messages", json.dumps(docs))
        log.info("retrieved %d docs for %r", k, query[:30])
    return docs


def _tool(name: str, tool: str, *, fail: bool = False, args: dict | None = None) -> str:
    with pk.span(name) as s:
        if s:
            s.set_attribute("gen_ai.tool.name", tool)
            s.set_attribute("gen_ai.input.messages", json.dumps(args or {}))
        time.sleep(0.005)
        if fail:
            raise TimeoutError(f"{tool} timed out")
        result = f"{tool} ok"
        if s:
            s.set_attribute("gen_ai.output.messages", result)
        return result


def _sub_agent(subtopic: str, question: str) -> str:
    """One nested research sub-agent: retrieve → analyze → (fail+retry tool) → critique → revise."""
    with agent_span(f"sub-agent: {subtopic}"):
        docs = _retrieve(f"{subtopic} for {question}")
        analysis = _llm("analyze", f"Analyze these docs on {subtopic}:\n" + "\n".join(docs))

        # a flaky tool: first attempt fails, a retry succeeds (shows a red span mid-success)
        try:
            _tool("fetch-attempt-1", "web_fetch", fail=True, args={"topic": subtopic})
        except TimeoutError:
            log.warning("web_fetch failed for %s — retrying", subtopic)
            _tool("fetch-attempt-2", "web_fetch", args={"topic": subtopic, "retry": True})

        critique = _llm("critique", f"Critique this analysis: {analysis}")
        revised = _llm("revise", f"Revise given critique:\n{analysis}\n---\n{critique}")
        _tool("guardrail", "policy_check", args={"text": revised[:40]})
        return revised


@pk.trace(name="research-orchestrator")
def research(question: str, subtopics: list[str]) -> str:
    """A deep orchestrator: plan → fan out to sub-agents → synthesize → final guardrail."""
    _llm("plan", f"Break this into research subtopics: {question}")
    findings = [_sub_agent(st, question) for st in subtopics]
    synthesis = _llm("synthesize", "Synthesize the findings:\n" + "\n".join(findings), temperature=0.2)
    _tool("guardrail: final", "policy_check", args={"final": True})
    pk.score("groundedness", score=0.88, comment="complex-demo auto-score")
    pk.score("thumbs", value="up")
    return synthesis


@pk.trace(name="research-orchestrator", session_id="research-session-1")
def followup(question: str) -> str:
    """A follow-up turn in the same session — smaller, but grouped with the first."""
    docs = _retrieve(question, k=2)
    return _llm("analyze", "Given prior research, answer:\n" + question + "\n" + "\n".join(docs))


@pk.trace(name="research-orchestrator")
def research_that_fails(question: str) -> str:
    """A whole run that dies mid-flow — shows as a failed trace."""
    _llm("plan", question)
    with agent_span("sub-agent: broken"):
        _retrieve(question, k=2)
        _tool("fetch", "web_fetch", fail=True, args={"q": question})   # unrecovered → trace fails
    return "unreachable"


def main() -> None:
    if not (os.environ.get("PROVEKIT_API_KEY") and os.environ.get("PROVEKIT_ENDPOINT")):
        raise SystemExit("Set PROVEKIT_API_KEY and PROVEKIT_ENDPOINT first (see this file's header).")
    if not pk.configure():
        raise SystemExit("ProveKit could not start — check your key/endpoint and install.")

    runs = [
        ("What are the tradeoffs of RAG vs long-context LLMs?",
         ["retrieval quality", "cost & latency", "context window limits"]),
        ("How should a startup price a developer tool?",
         ["usage-based pricing", "seat-based pricing", "free-tier design"]),
    ]
    for q, subs in runs:
        out = research(q, subs)
        print("→", out[:70])

    # a follow-up in a session
    followup("And which approach scales better past 1M tokens?")

    # a whole failed run
    try:
        research_that_fails("Summarize an unreachable source")
    except TimeoutError as exc:
        print("✗ research_that_fails failed as designed:", exc)

    from opentelemetry import trace as _t
    provider = _t.get_tracer_provider()
    if hasattr(provider, "force_flush"):
        provider.force_flush()
    print("\nDone — open your ProveKit portal:",
          os.environ["PROVEKIT_ENDPOINT"].rstrip("/") + "/traces")


if __name__ == "__main__":
    main()
