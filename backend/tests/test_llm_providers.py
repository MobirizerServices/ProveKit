"""Provider SSE parsing — Responses + Anthropic — driven by synthetic async streams."""
import asyncio

from agentman.services.providers import llm


class _FakeAsyncStream:
    def __init__(self, lines):
        self._lines = lines
        self.status_code = 200

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def aiter_lines(self):
        for line in self._lines:
            yield line

    async def aread(self):
        return b""


def _patch(monkeypatch, lines):
    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def stream(self, *a, **k):
            _patch.body = k.get("json")
            return _FakeAsyncStream(lines)

    monkeypatch.setattr(llm.httpx, "AsyncClient", _Client)


def _collect(**kwargs):
    async def run():
        return [ev async for ev in llm.astream(**kwargs)]
    return asyncio.run(run())


def test_responses_stream_parses_text_and_usage(monkeypatch):
    lines = [
        'data: {"type":"response.output_text.delta","delta":"Hel"}',
        'data: {"type":"response.output_text.delta","delta":"lo"}',
        'data: {"type":"response.output_item.added","item":{"type":"function_call","name":"search"}}',
        'data: {"type":"response.completed","response":{"usage":{"input_tokens":5,"output_tokens":2}}}',
        "data: [DONE]",
    ]
    _patch(monkeypatch, lines)
    evs = _collect(provider="openai-responses", base_url="", api_key="k", model="gpt-4o-mini",
                   system="be nice", messages=[{"role": "user", "content": "hi"}])
    assert "".join(e["text"] for e in evs if e["type"] == "delta") == "Hello"
    # the model asking for a tool surfaces as a structured tool_call for the dispatch loop
    assert next(e["call"]["name"] for e in evs if e["type"] == "tool_call") == "search"
    usage = next(e["usage"] for e in evs if e["type"] == "usage")
    assert usage["input_tokens"] == 5
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
    evs = _collect(provider="anthropic", base_url="", api_key="k", model="claude-x",
                   system=None, messages=[{"role": "user", "content": "hi"}])
    tool_ev = next(e for e in evs if e["type"] == "tool_call")
    assert tool_ev["call"]["name"] == "lookup"
    assert any(e["type"] == "node" and e["data"].get("stop_reason") == "refusal" for e in evs)
    assert "".join(e["text"] for e in evs if e["type"] == "delta") == "ok"


def test_tool_called_assertion_matches_streamed_tool_event(monkeypatch):
    """End-to-end: a tool the model asks for reaches a `tool_called` assertion.

    Driven through dispatch, because llm now yields a structured tool_call and it is the
    dispatch loop that turns it into the `node` event assertions read. A tool the model was
    never given (none attached here) is still recorded, then the run stops.
    """
    import anyio

    from agentman.services import assertions as ae
    from agentman.services import dispatch

    lines = [
        'data: {"type":"content_block_start","content_block":{"type":"tool_use","id":"t1","name":"get_weather"}}',
        'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"sunny"}}',
    ]
    _patch(monkeypatch, lines)

    async def _run():
        req = {"type": "prompt", "provider": "anthropic", "api_key": "k", "model": "c",
               "user": "weather?"}
        return [ev async for ev in dispatch.run(None, req)]

    evs = anyio.run(_run)
    events = [e["data"] for e in evs if e["type"] == "node"]
    assert any(d.get("tool_calls") for d in events)
    res = ae.evaluate(None, [{"type": "tool_called", "value": "get_weather"}],
                      {"result": {"text": "sunny", "output": None, "meta": {}}, "events": events,
                       "duration_ms": 1})
    assert res[0]["ok"] is True


def test_openai_accumulates_streamed_tool_call_fragments(monkeypatch):
    """Chat Completions streams a tool call in pieces: the id/name arrive first, then the
    arguments a few characters at a time, keyed by index. Parallel calls interleave."""
    lines = [
        'data: {"choices":[{"delta":{"content":"thinking"}}]}',
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"c1","function":{"name":"check","arguments":"{\\"sku\\""}}]}}]}',
        'data: {"choices":[{"delta":{"tool_calls":[{"index":1,"id":"c2","function":{"name":"other","arguments":"{}"}}]}}]}',
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":": \\"A\\"}"}}]}}]}',
        'data: {"choices":[{"finish_reason":"tool_calls","delta":{}}],"usage":{"total_tokens":9}}',
        "data: [DONE]",
    ]
    _patch(monkeypatch, lines)
    evs = _collect(provider="openai", base_url="", api_key="k", model="gpt-4o-mini",
                   system=None, messages=[{"role": "user", "content": "stock?"}],
                   tools=[{"type": "function", "function": {"name": "check", "parameters": {}}}])
    calls = {e["call"]["name"]: e["call"] for e in evs if e["type"] == "tool_call"}
    assert calls["check"]["args"] == {"sku": "A"}, "fragments must reassemble into one JSON object"
    assert calls["check"]["id"] == "c1"
    assert calls["other"]["args"] == {}          # a second, parallel call is kept separate
    assert next(e["usage"] for e in evs if e["type"] == "usage")["total_tokens"] == 9
    assert _patch.body["tools"][0]["function"]["name"] == "check"  # tools actually sent


def test_openai_sends_no_tools_key_when_none_attached(monkeypatch):
    _patch(monkeypatch, ['data: {"choices":[{"delta":{"content":"hi"}}]}', "data: [DONE]"])
    _collect(provider="openai", base_url="", api_key="k", model="m", system=None,
             messages=[{"role": "user", "content": "hi"}])
    assert "tools" not in _patch.body


def test_responses_tool_call_keeps_the_filled_in_arguments(monkeypatch):
    """`.added` announces the call with EMPTY arguments and `.done` carries the real ones.

    Taking the first event and deduping on call_id reported every Responses tool call with
    no arguments at all — a check_inventory() with no SKU.
    """
    lines = [
        'data: {"type":"response.output_item.added","item":{"type":"function_call","call_id":"call_abc","name":"get_weather","arguments":""}}',
        'data: {"type":"response.output_item.done","item":{"type":"function_call","call_id":"call_abc","name":"get_weather","arguments":"{\\"city\\": \\"Paris\\"}"}}',
        "data: [DONE]",
    ]
    _patch(monkeypatch, lines)
    evs = _collect(provider="openai-responses", base_url="", api_key="k", model="m", system=None,
                   messages=[{"role": "user", "content": "weather?"}],
                   tools=[{"type": "function", "name": "get_weather", "parameters": {}}])
    calls = [e["call"] for e in evs if e["type"] == "tool_call"]
    assert len(calls) == 1, "the two events describe one call, not two"
    assert calls[0] == {"id": "call_abc", "name": "get_weather", "args": {"city": "Paris"}}
    assert _patch.body["tools"][0]["name"] == "get_weather"


def test_responses_reports_a_call_announced_but_never_completed(monkeypatch):
    """A stream cut off after `.added` still reports the call rather than losing it."""
    _patch(monkeypatch, ['data: {"type":"response.output_item.added","item":{"type":"function_call","call_id":"c9","name":"search","arguments":"{}"}}'])
    evs = _collect(provider="openai-responses", base_url="", api_key="k", model="m", system=None,
                   messages=[{"role": "user", "content": "x"}])
    assert [e["call"]["name"] for e in evs if e["type"] == "tool_call"] == ["search"]
