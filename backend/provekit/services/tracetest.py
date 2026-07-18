"""Trace → test: turn a captured run into a saved-Request payload the user can refine and
run in CI. This is the bridge's payoff — a real production run becomes a regression test.

The mapping is deliberately a *starting point*, not a finished test: a trace can't carry
everything a runnable request needs (which connection to hit, the exact assertion that
matters), so we seed a prompt request from the captured input and a `contains` assertion
from the captured output, and let the user attach a connection / sharpen the assertion in
the console. A saved Request round-trips to a `.provekit` file via services.testfile.
"""
from __future__ import annotations

import json

_SNIPPET = 120  # chars of captured output to seed the assertion with


def _as_text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    try:
        return json.dumps(v)
    except (TypeError, ValueError):
        return str(v)


def run_to_request_payload(request: dict | None, result: dict | None) -> dict:
    """Map a captured trace run (request={type,provider,model,operation,input},
    result={text,...}) to a saved-Request payload: a prompt whose `user` is the captured
    input, seeded with a `contains` assertion on the captured output."""
    request = request or {}
    result = result or {}
    payload: dict = {"type": "prompt"}
    if request.get("model"):
        payload["model"] = request["model"]
    payload["user"] = _as_text(request.get("input"))

    snippet = _as_text(result.get("text")).strip()[:_SNIPPET]
    if snippet:
        # a starting assertion — the user sharpens it (exact match, llm_judge, …) in the console
        payload["assertions"] = [{"type": "contains", "value": snippet}]
    return payload
