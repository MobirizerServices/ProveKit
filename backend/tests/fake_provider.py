"""An httpx stand-in that answers like an OpenAI-shaped provider, echoing the prompt back.

This replaces the offline `mock` provider the suite used to run through. The difference matters:
with `mock`, a flow/replay test exercised a branch that only tests ever took. Here the test
creates a *real* openai connection and only the socket is faked, so the code under test is the
same path production runs — request shaping, SSE framing, usage accounting and all.

Echoing (rather than a fixed canned string) is what lets the executor tests assert that a
trigger's input actually reached the model call.
"""
from __future__ import annotations

import json


def openai_connection(client, label: str = "test") -> int:
    """Create a real openai connection and return its id — what a run names instead of 'mock'."""
    r = client.post("/api/connections",
                    json={"provider": "openai", "label": label, "key": "sk-test-0000"})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _last_user(body: dict | None) -> str:
    msgs = (body or {}).get("messages") or []
    for m in reversed(msgs):
        if m.get("role") == "user":
            return str(m.get("content") or "")
    return str(msgs[-1].get("content") or "") if msgs else ""


def _is_grader(body: dict | None) -> bool:
    return any("strict grader" in str(m.get("content") or "")
               for m in (body or {}).get("messages") or [] if m.get("role") == "system")


def _grade(body: dict | None) -> str:
    """Answer a judge prompt the way a grader model would: with just a number.

    Parses the expected answer and the answer under test back out of the prompt and scores by
    overlap. Deterministic, so llm_judge assertions stay exact.
    """
    prompt = _last_user(body)
    def section(head: str, nxt: str) -> str:
        if head not in prompt:
            return ""
        rest = prompt.split(head, 1)[1]
        return (rest.split(nxt, 1)[0] if nxt and nxt in rest else rest).strip()
    exp = section("Expected answer:\n", "\n\nAnswer to grade:").strip().lower()
    out = section("Answer to grade:\n", "\n\nScore").strip().lower()
    if not exp:
        return "1.0" if out else "0.0"
    if exp in out:
        return "1.0"
    return "0.5" if any(w in out for w in exp.split()) else "0.0"


def echo_text(body: dict | None) -> str:
    """Deterministic transform of the last user message, so an edit visibly changes the output."""
    if _is_grader(body):
        return _grade(body)
    model = (body or {}).get("model") or "model"
    text = f"[echo:{model}] " + " ".join(_last_user(body).split()[:60]).strip()
    return text if text.strip().endswith((".", "!", "?")) else text + "."


def _in_tokens(body: dict | None) -> int:
    return sum(len(str(m.get("content", "")).split()) for m in (body or {}).get("messages") or [])


class FakeResp:
    def __init__(self, status: int, data: dict):
        self.status_code = status
        self._data = data

    def json(self) -> dict:
        return self._data

    @property
    def text(self) -> str:
        return json.dumps(self._data)


class FakeStream:
    """What `httpx.AsyncClient.stream(...)` yields: an async CM exposing SSE lines."""

    def __init__(self, lines: list[str], status: int = 200):
        self.status_code = status
        self._lines = lines

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def aread(self):
        return b""

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class EchoClient:
    """Stands in for httpx.AsyncClient against an OpenAI-shaped endpoint. No network.

    `last` records the most recent request so a test can assert on shaping; set `fail_status`
    to make the next call return an error instead.
    """

    last: dict | None = None
    fail_status: int | None = None

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None, headers=None):
        type(self).last = {"url": url, "json": json, "headers": headers}
        if type(self).fail_status:
            return FakeResp(type(self).fail_status, {"error": {"message": "provider said no"}})
        text = echo_text(json)
        return FakeResp(200, {
            "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": _in_tokens(json), "completion_tokens": len(text.split())},
        })

    def stream(self, method, url, json=None, headers=None):
        type(self).last = {"url": url, "json": json, "headers": headers, "method": method}
        if type(self).fail_status:
            return FakeStream([], status=type(self).fail_status)
        text = echo_text(json)
        # Two content deltas then a usage-bearing terminal frame — the shape _openai_stream reads.
        head, tail = text[: len(text) // 2], text[len(text) // 2:]
        lines = [
            "data: " + json_dumps({"choices": [{"delta": {"content": head}}]}),
            "data: " + json_dumps({"choices": [{"delta": {"content": tail}}]}),
            "data: " + json_dumps({"choices": [{"delta": {}, "finish_reason": "stop"}],
                                   "usage": {"prompt_tokens": _in_tokens(json),
                                             "completion_tokens": len(text.split())}}),
            "data: [DONE]",
        ]
        return FakeStream(lines)


def json_dumps(o) -> str:
    return json.dumps(o, separators=(",", ":"))
