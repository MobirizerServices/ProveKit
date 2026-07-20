"""`provekit-demo` — a zero-setup smoke test.

Sends a small gallery of traces to your portal so a fresh install + project key can be
verified in ~10 seconds. No LLM key needed: the model is mocked, but recorded as a real
gen_ai LLM span (model, tokens, temperature) so the portal renders it as a proper chat call.

    pip install "provekit[trace]"
    export PROVEKIT_API_KEY=pk_...        # a project key from the portal
    export PROVEKIT_ENDPOINT=https://your-provekit-host
    provekit-demo

For richer, framework-native examples (LangGraph, a deep multi-agent orchestrator) see the
examples/ folder: https://github.com/MobirizerServices/ProveKit/tree/main/examples
"""
from __future__ import annotations

import argparse
import logging
import os
import time

from . import trace as pk

log = logging.getLogger("provekit-demo")

_KB = {
    "refund": "I've started your refund — it lands in 3–5 business days.",
    "vpn": "Forget the VPN profile and re-add it; that clears the stale auth token.",
    "pricing": "The Pro plan is $49/seat/mo; annual billing saves ~15%.",
    "export": "Settings → Data → Export builds a downloadable JSON of your workspace.",
}


def _mock_llm(span, model: str, prompt: str, temperature: float = 0.7) -> str:
    """A deterministic, offline stand-in for an LLM — recorded as a real gen_ai LLM span."""
    key = next((k for k in _KB if k in prompt.lower()), None)
    answer = _KB.get(key, "Thanks for reaching out — a teammate will follow up shortly.")
    if span:
        span.set_attribute("gen_ai.request.model", model)
        span.set_attribute("gen_ai.request.temperature", temperature)
        span.set_attribute("gen_ai.input.messages", prompt)
        span.set_attribute("gen_ai.usage.input_tokens", 40 + len(prompt) // 4)
        span.set_attribute("gen_ai.usage.output_tokens", 12 + len(answer) // 4)
        span.set_attribute("gen_ai.output.messages", answer)
        span.set_attribute("gen_ai.response.finish_reasons", "stop")
    time.sleep(0.01)
    return answer


@pk.trace(name="support-agent")
def _support_agent(question: str, model: str = "gpt-4o") -> str:
    with pk.span("retrieve") as s:
        if s:
            s.set_attribute("gen_ai.tool.name", "kb_search")
            s.set_attribute("gen_ai.input.messages", question)
        log.info("retrieved 3 candidate docs")
    with pk.span("chat") as s:
        answer = _mock_llm(s, model, question)
    pk.score("helpfulness", score=0.9, comment="demo auto-score")
    return answer


@pk.trace(name="support-agent", session_id="conv-demo-1")
def _support_turn(question: str) -> str:
    with pk.span("chat") as s:
        return _mock_llm(s, "gpt-4o-mini", question)


@pk.trace(name="flaky-agent")
def _flaky_agent(question: str) -> str:
    with pk.span("call-upstream") as s:
        if s:
            s.set_attribute("gen_ai.tool.name", "billing_api")
        raise RuntimeError("upstream billing_api returned 503")


def main(argv=None) -> None:
    p = argparse.ArgumentParser(
        prog="provekit-demo",
        description="Send a small gallery of demo traces to your ProveKit portal (no LLM key needed).")
    p.add_argument("--api-key", default=os.environ.get("PROVEKIT_API_KEY"),
                   help="project key (default: $PROVEKIT_API_KEY)")
    p.add_argument("--endpoint", default=os.environ.get("PROVEKIT_ENDPOINT"),
                   help="portal URL (default: $PROVEKIT_ENDPOINT)")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    if not (args.api_key and args.endpoint):
        raise SystemExit("Set PROVEKIT_API_KEY and PROVEKIT_ENDPOINT (or pass --api-key / --endpoint).\n"
                         "Grab a key from your portal → Project keys.")
    if not pk.configure(api_key=args.api_key, endpoint=args.endpoint):
        raise SystemExit("ProveKit could not start — check your key/endpoint.")

    for q, model in (("I want a refund for my order", "gpt-4o"),
                     ("VPN won't connect after the update", "gpt-4o"),
                     ("What's your pricing for a 20-person team?", "claude-sonnet-5"),
                     ("How do I export my data?", "gpt-4o-mini")):
        print("→", _support_agent(q, model=model)[:60])

    # a two-turn conversation (same session) so sessions light up
    _support_turn("Is the Pro plan monthly?")
    _support_turn("And does annual billing save money?")

    # a failed run so the dashboard error-rate + a red trace show up
    try:
        _flaky_agent("charge dispute")
    except RuntimeError as exc:
        print("✗ flaky-agent failed as designed:", exc)

    from opentelemetry import trace as _t
    provider = _t.get_tracer_provider()
    if hasattr(provider, "force_flush"):
        provider.force_flush()
    print("\nDone — open your ProveKit portal:", args.endpoint.rstrip("/") + "/traces")


if __name__ == "__main__":
    main()
