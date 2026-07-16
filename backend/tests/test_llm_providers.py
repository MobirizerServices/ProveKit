"""Provider SSE parsing — Responses + Anthropic — driven by synthetic streams (no network)."""
import httpx
import pytest

from agentman.services.providers import llm


class _FakeStream:
    def __init__(self, lines):
        self._lines = lines
        self.status_code = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def iter_lines(self):
        return iter(self._lines)

    def read(self):
        return b""


def _patch(monkeypatch, lines):
    class _Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def stream(self, *a, **k):
            _patch.body = k.get("json")
            return _FakeStream(lines)

    monkeypatch.setattr(llm.httpx, "Client", _Client)


def test_responses_stream_parses_text_and_usage(monkeypatch):
    lines = [
        'data: {"type":"response.output_text.delta","delta":"Hel"}',
        'data: {"type":"response.output_text.delta","delta":"lo"}',
        'data: {"type":"response.output_item.added","item":{"type":"function_call","name":"search"}}',
        'data: {"type":"response.completed","response":{"usage":{"input_tokens":5,"output_tokens":2}}}',
        "data: [DONE]",
    ]
    _patch(monkeypatch, lines)
    evs = list(llm.stream(provider="openai-responses", base_url="", api_key="k", model="gpt-4o-mini",
                          system="be nice", messages=[{"role": "user", "content": "hi"}]))
    assert "".join(e["text"] for e in evs if e["type"] == "delta") == "Hello"
    assert any(e["type"] == "node" and e["data"].get("tool_calls") for e in evs)
    usage = next(e["usage"] for e in evs if e["type"] == "usage")
    assert usage["input_tokens"] == 5
    # request shape: instructions + input, not chat messages
    assert _patch.body["instructions"] == "be nice"
    assert _patch.body["input"][0]["role"] == "user"


def test_anthropic_surfaces_tool_use_and_refusal(monkeypatch):
    lines = [
        'data: {"type":"message_start","message":{"usage":{"input_tokens":3}}}',
        'data: {"type":"content_block_start","content_block":{"type":"tool_use","name":"lookup"}}',
        'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"ok"}}',
        'data: {"type":"message_delta","delta":{"stop_reason":"refusal"},"usage":{"output_tokens":1}}',
    ]
    _patch(monkeypatch, lines)
    evs = list(llm.stream(provider="anthropic", base_url="", api_key="k", model="claude-x",
                          system=None, messages=[{"role": "user", "content": "hi"}]))
    tool_ev = next(e for e in evs if e["type"] == "node" and e["data"].get("tool_calls"))
    assert tool_ev["data"]["tool_calls"][0]["name"] == "lookup"
    assert any(e["type"] == "node" and e["data"].get("stop_reason") == "refusal" for e in evs)
    assert "".join(e["text"] for e in evs if e["type"] == "delta") == "ok"
    # temperature omitted when None (2026 model drift)
    assert "temperature" not in _patch.body or _patch.body.get("temperature") is not None


def test_tool_called_assertion_matches_streamed_tool_event(monkeypatch):
    from agentman.services import assertions as ae
    lines = [
        'data: {"type":"content_block_start","content_block":{"type":"tool_use","name":"get_weather"}}',
        'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"sunny"}}',
    ]
    _patch(monkeypatch, lines)
    events = [e["data"] for e in llm.stream(provider="anthropic", base_url="", api_key="k",
              model="c", system=None, messages=[{"role": "user", "content": "weather?"}])
              if e["type"] == "node"]
    res = ae.evaluate(None, [{"type": "tool_called", "value": "get_weather"}],
                      {"result": {"text": "sunny", "output": None, "meta": {}}, "events": events, "duration_ms": 1})
    assert res[0]["ok"] is True
