"""Trace → test: turn a captured run into a saved-Request payload the user can refine and
run in CI. This is the bridge's payoff — a real production run becomes a regression test.

The mapping is a strong *starting point*: a prompt request seeded from the captured input,
plus an `llm_judge` assertion that semantically checks a new response against the captured
output (robust to phrasing, unlike a substring match). If a connection is chosen at save
time it's wired to both the prompt target and the judge, so the test is runnable
immediately; otherwise the user attaches one in the console. A saved Request round-trips to
a `.provekit` file via services.testfile.
"""
from __future__ import annotations

import json

_REF_MAX = 1200  # cap the reference answer embedded in the judge criteria


def _as_text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    try:
        return json.dumps(v)
    except (TypeError, ValueError):
        return str(v)


def run_to_request_payload(request: dict | None, result: dict | None,
                           connection_id: int | None = None) -> dict:
    """Map a captured trace run (request={type,provider,model,operation,input},
    result={text,...}) to a saved-Request payload: a prompt whose `user` is the captured
    input, seeded with an `llm_judge` assertion against the captured output. If
    connection_id is given it targets both the prompt and the judge."""
    request = request or {}
    result = result or {}
    payload: dict = {"type": "prompt"}
    if request.get("model"):
        payload["model"] = request["model"]
    payload["user"] = _as_text(request.get("input"))
    if connection_id:
        payload["connection_id"] = connection_id

    ref = _as_text(result.get("text")).strip()[:_REF_MAX]
    if ref:
        judge = {"type": "llm_judge",
                 "criteria": ("The response should convey the same answer as this reference "
                              f"from the captured run, even if worded differently:\n\n{ref}")}
        if connection_id:
            judge["connection_id"] = connection_id
        payload["assertions"] = [judge]
    return payload
