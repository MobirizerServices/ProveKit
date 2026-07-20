#!/usr/bin/env python3
"""ProveKit × LangGraph — a simple agent, auto-traced.

A two-node LangGraph (retrieve → generate) wrapped in one `@pk.trace`. ProveKit captures the
whole run: the graph nodes and the LangChain LLM call nest underneath automatically. Runs fully
offline by default (a canned chat model); set OPENAI_API_KEY in .env to use gpt-4o-mini instead.

    pip install -r requirements.txt
    cp .env.example .env      # then fill in PROVEKIT_API_KEY / PROVEKIT_ENDPOINT
    python run_langgraph.py
"""
from __future__ import annotations

import logging
import os
from typing import TypedDict

from dotenv import load_dotenv

import provekit.trace as pk
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.graph import END, START, StateGraph

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("langgraph-demo")

_KB = {
    "refund": "I've started your refund — it should land in 3–5 business days.",
    "vpn": "Forget the VPN profile and re-add it; that clears the stale auth token.",
    "pricing": "The Pro plan is $49/seat/mo, and annual billing saves about 15%.",
    "export": "Settings → Data → Export creates a downloadable JSON of your workspace.",
}


class CannedChat(BaseChatModel):
    """A deterministic stand-in for a real chat model — a proper LangChain BaseChatModel, so
    the LangChain instrumentor records it as a genuine LLM span (model, tokens, output)."""

    @property
    def _llm_type(self) -> str:
        return "canned"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        text = (messages[-1].content if messages else "").lower()
        answer = next((v for k, v in _KB.items() if k in text), "A teammate will follow up shortly.")
        msg = AIMessage(content=answer, usage_metadata={"input_tokens": 32, "output_tokens": 14, "total_tokens": 46})
        return ChatResult(generations=[ChatGeneration(message=msg)])


def _make_model() -> BaseChatModel:
    if os.environ.get("OPENAI_API_KEY"):
        try:
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(model="gpt-4o-mini", temperature=0)
        except Exception:
            log.warning("OPENAI_API_KEY set but langchain-openai not installed — using the canned model")
    return CannedChat()


class State(TypedDict):
    question: str
    docs: str
    answer: str


_model = _make_model()


def retrieve(state: State) -> dict:
    """A stand-in retrieval tool — nests as a step under the trace."""
    log.info("retrieving context for: %s", state["question"][:40])
    return {"docs": f"[3 knowledge-base snippets for: {state['question'][:40]}]"}


def generate(state: State) -> dict:
    """The LLM node — the model call is auto-captured as a nested gen_ai span."""
    prompt = f"Use this context to answer.\nContext: {state['docs']}\nQuestion: {state['question']}"
    resp = _model.invoke(prompt)
    return {"answer": resp.content}


def _build_graph():
    g = StateGraph(State)
    g.add_node("retrieve", retrieve)
    g.add_node("generate", generate)
    g.add_edge(START, "retrieve")
    g.add_edge("retrieve", "generate")
    g.add_edge("generate", END)
    return g.compile()


_app = _build_graph()


@pk.trace(name="langgraph-agent")
def ask(question: str) -> str:
    """One decorated entrypoint — the whole LangGraph run is captured beneath it."""
    return _app.invoke({"question": question})["answer"]


def main() -> None:
    load_dotenv()
    if not (os.environ.get("PROVEKIT_API_KEY") and os.environ.get("PROVEKIT_ENDPOINT")):
        raise SystemExit("Set PROVEKIT_API_KEY and PROVEKIT_ENDPOINT in .env (see .env.example).")
    if not pk.configure():
        raise SystemExit("ProveKit could not start — check your key/endpoint in .env.")

    for q in ("I want a refund for my order",
              "VPN won't connect after the update",
              "What's your pricing for a 20-person team?",
              "How do I export my data?"):
        print("→", ask(q)[:70])

    from opentelemetry import trace as _t
    provider = _t.get_tracer_provider()
    if hasattr(provider, "force_flush"):
        provider.force_flush()
    print("\nDone — open your ProveKit portal:",
          os.environ["PROVEKIT_ENDPOINT"].rstrip("/") + "/traces")


if __name__ == "__main__":
    main()
