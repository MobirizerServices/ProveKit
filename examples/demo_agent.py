#!/usr/bin/env python3
"""ProveKit demo agent — generates a realistic gallery of traces so a fresh portal has
something to explore: nested agent/tool/LLM spans, logs, token usage, a multi-turn session,
a failed run, and a feedback score. No real LLM key needed — the "model" is mocked, so the
demo runs fully offline against your ProveKit portal.

    pip install "provekit[trace]"
    export PROVEKIT_API_KEY=pk_...            # a project key from the portal
    export PROVEKIT_ENDPOINT=https://your-provekit-host
    python examples/demo_agent.py

Then open the portal: Traces (nested flows + a session + a failure), Dashboard (volume,
errors, latency, tokens, top models), and use "add to dataset" on a trace to try evaluation.
"""
from __future__ import annotations

import logging
import os
import time

import provekit.trace as pk

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("demo-agent")

# A tiny mock "LLM": no network, deterministic, but recorded as a real LLM span (model,
# tokens, temperature) so the portal renders it as a chat call with usage and cost.
_KB = {
    "refund": "I've started your refund — it lands in 3–5 business days.",
    "vpn": "Try forgetting the VPN profile and re-adding it; that clears the stale token.",
    "pricing": "The Pro plan is $49/seat/mo; annual billing saves ~15%.",
}


def _mock_llm(span, model: str, prompt: str, temperature: float = 0.7) -> str:
    key = next((k for k in _KB if k in prompt.lower()), None)
    answer = _KB.get(key, "Thanks for reaching out — a teammate will follow up shortly.")
    if span:  # record it as a proper gen_ai LLM span
        span.set_attribute("gen_ai.request.model", model)
        span.set_attribute("gen_ai.request.temperature", temperature)
        span.set_attribute("gen_ai.input.messages", prompt)
        span.set_attribute("gen_ai.usage.input_tokens", 40 + len(prompt) // 4)
        span.set_attribute("gen_ai.usage.output_tokens", 12 + len(answer) // 4)
        span.set_attribute("gen_ai.output.messages", answer)
        span.set_attribute("gen_ai.response.finish_reasons", "stop")
    time.sleep(0.02)
    return answer


@pk.trace(name="support-agent")
def support_agent(question: str, model: str = "gpt-4o") -> str:
    """Retrieve → answer: the canonical two-step agent, captured as a nested flow."""
    with pk.span("retrieve") as s:
        if s:
            s.set_attribute("gen_ai.tool.name", "kb_search")
            s.set_attribute("gen_ai.input.messages", question)
        log.info("retrieved 3 candidate docs for: %s", question[:40])
        time.sleep(0.01)
    with pk.span("chat") as s:
        answer = _mock_llm(s, model, question)
    pk.score("helpfulness", score=0.9, comment="demo auto-score")
    return answer


@pk.trace(name="support-agent", session_id="conv-demo-1")
def support_turn(question: str) -> str:
    """Same agent, but tagged with a session so multi-turn runs group in the portal."""
    with pk.span("chat") as s:
        return _mock_llm(s, "gpt-4o-mini", question)


@pk.trace(name="flaky-agent")
def flaky_agent(question: str) -> str:
    """A run that fails mid-flow — shows as a failed trace with the error on the span."""
    with pk.span("call-upstream") as s:
        if s:
            s.set_attribute("gen_ai.tool.name", "billing_api")
        log.warning("upstream billing API is slow…")
        raise RuntimeError("upstream billing_api returned 503")


def main() -> None:
    if not (os.environ.get("PROVEKIT_API_KEY") and os.environ.get("PROVEKIT_ENDPOINT")):
        raise SystemExit("Set PROVEKIT_API_KEY and PROVEKIT_ENDPOINT first (see this file's header).")
    if not pk.configure():
        raise SystemExit("ProveKit could not start — check your key/endpoint and `pip install provekit[trace]`.")

    prompts = [
        ("I want a refund for my order", "gpt-4o"),
        ("VPN won't connect after the update", "gpt-4o"),
        ("What's your pricing for a 20-person team?", "claude-sonnet-5"),
        ("How do I export my data?", "gpt-4o-mini"),
    ]
    for q, model in prompts:
        print("→", support_agent(q, model=model)[:60])

    # a two-turn conversation (same session_id) so sessions light up
    support_turn("Is the Pro plan monthly?")
    support_turn("And does annual billing save money?")

    # a failed run so the dashboard error-rate + a red trace show up
    try:
        flaky_agent("charge dispute")
    except RuntimeError as exc:
        print("✗ flaky-agent failed as designed:", exc)

    # flush the batched spans before the process exits
    from opentelemetry import trace as _t
    provider = _t.get_tracer_provider()
    if hasattr(provider, "force_flush"):
        provider.force_flush()
    print("\nDone — open your ProveKit portal:",
          os.environ["PROVEKIT_ENDPOINT"].rstrip("/") + "/traces")


if __name__ == "__main__":
    main()
