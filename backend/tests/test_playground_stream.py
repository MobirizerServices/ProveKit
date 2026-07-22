"""The streamed playground re-run (SSE): frame contract, that limits/spend still apply, and
that a provider failure mid-stream surfaces as an error instead of a short answer."""
import functools
import json
import time

import anyio
import pytest
from fastapi.testclient import TestClient

from provekit.config import get_settings
from provekit.main import app
from provekit.routers import playground as pg
from provekit.services import limits, llm_client


def _frames(text: str) -> list[dict]:
    """Parse an SSE response body into its JSON payloads."""
    out = []
    for chunk in text.split("\n\n"):
        for line in chunk.splitlines():
            if line.startswith("data:"):
                out.append(json.loads(line[5:].strip()))
    return out


def test_stream_mock_run_emits_deltas_then_done():
    with TestClient(app, base_url="https://testserver") as c:
        r = c.post("/api/playground/run/stream", json={
            "provider": "mock", "model": "gpt-4o",
            "messages": [{"role": "user", "content": "hello world please"}]})
        assert r.status_code == 200, r.text
        assert r.headers["content-type"].startswith("text/event-stream")
        evs = _frames(r.text)

        deltas = [e for e in evs if e["type"] == "delta"]
        assert len(deltas) > 1                      # actually chunked, not one blob
        assert evs[-1]["type"] == "done"            # done is last, exactly once
        assert sum(1 for e in evs if e["type"] == "done") == 1

        done = evs[-1]
        assert done["output"] == "".join(d["text"] for d in deltas)   # concatenates to the answer
        assert done["output"].startswith("[mock:gpt-4o]")
        assert done["usage"]["output_tokens"] > 0
        assert done["provider"] == "mock" and done["model"] == "gpt-4o" and "latency_ms" in done


def test_stream_matches_the_non_streaming_endpoint():
    """Same input, same answer — the streamed path must not be a second, divergent implementation."""
    with TestClient(app, base_url="https://testserver") as c:
        body = {"provider": "mock", "model": "gpt-4o",
                "messages": [{"role": "user", "content": "compare these two paths"}]}
        plain = c.post("/api/playground/run", json=body).json()
        streamed = _frames(c.post("/api/playground/run/stream", json=body).text)[-1]
        assert streamed["output"] == plain["output"]
        assert streamed["usage"] == plain["usage"]
        assert streamed["finish_reason"] == plain["finish_reason"]


def test_frames_are_emitted_as_they_are_produced(monkeypatch):
    """The whole point: a slow completion must leave in pieces. Asserted on the response
    generator rather than through TestClient, which reads the body to the end before handing it
    over and so cannot tell a stream from a buffered blob."""
    async def slow(*a, **k):
        for w in ("one ", "two ", "three"):
            await anyio.sleep(0.05)
            yield {"type": "delta", "text": w}
        yield {"type": "done", "output": "one two three", "finish_reason": "stop",
               "usage": {"input_tokens": 3, "output_tokens": 3}}

    monkeypatch.setattr(pg, "stream_complete", slow)

    async def go():
        return [(time.monotonic(), f) async for f in pg._run_events(
            1, "gpt-4o", "mock", [{"role": "user", "content": "count"}], {}, "", "")]

    got = anyio.run(go)
    assert len(got) == 4
    assert got[-1][0] - got[0][0] >= 0.1   # spread over time, not one write at the end
    assert got[0][1].startswith("data: ") and got[0][1].endswith("\n\n")


def test_stream_validation_is_a_status_not_a_frame():
    """Rejections happen before the response starts, so a client still gets a real status code."""
    with TestClient(app, base_url="https://testserver") as c:
        assert c.post("/api/playground/run/stream", json={
            "provider": "mock", "model": "x", "messages": []}).status_code == 422
        # neither a connection nor provider=mock
        assert c.post("/api/playground/run/stream", json={
            "model": "x", "messages": [{"role": "user", "content": "hi"}]}).status_code == 422
        assert c.post("/api/playground/run/stream", json={
            "connection_id": 999999, "model": "x",
            "messages": [{"role": "user", "content": "hi"}]}).status_code == 404


def test_stream_respects_the_spend_cap(monkeypatch):
    """A streamed re-run must not be a way around the monthly cap."""
    get_settings.cache_clear()
    monkeypatch.setenv("PLAYGROUND_MONTHLY_USD_CAP", "0.01")
    get_settings.cache_clear()
    limits._window.cache_clear()
    try:
        with TestClient(app, base_url="https://testserver") as c:
            body = {"provider": "mock", "model": "gpt-4o",
                    "messages": [{"role": "user", "content": "spend something"}]}
            assert c.post("/api/playground/run/stream", json=body).status_code == 200
            # bill the project past the cap and re-ask — the stream must be refused outright
            ws_id = c.get("/api/projects").json()[0]["id"]
            limits.record_spend(ws_id, 0.05)
            r = c.post("/api/playground/run/stream", json=body)
            assert r.status_code == 402, r.text
    finally:
        get_settings.cache_clear()
        limits._window.cache_clear()


def test_stream_records_spend(monkeypatch):
    spent = []
    monkeypatch.setattr("provekit.routers.playground.limits.record_spend",
                        lambda ws_id, usd: spent.append((ws_id, usd)))
    # the mock model is free, so price it as a real one to prove the accounting runs
    monkeypatch.setattr("provekit.routers.playground.pricing.estimate",
                        lambda model, i, o: 0.001 * ((i or 0) + (o or 0)))
    with TestClient(app, base_url="https://testserver") as c:
        r = c.post("/api/playground/run/stream", json={
            "provider": "mock", "model": "gpt-4o",
            "messages": [{"role": "user", "content": "bill me for this run"}]})
        assert r.status_code == 200
    assert spent and spent[-1][1] > 0


# ---- provider streaming, with httpx mocked (no network) ----
class _FakeStream:
    """Stands in for httpx.AsyncClient().stream() — replays canned SSE lines."""
    lines: list[str] = []
    status = 200
    body: dict = {}
    last: dict | None = None

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def stream(self, method, url, json=None, headers=None):
        type(self).last = {"url": url, "json": json, "headers": headers}
        return self

    # the response is the same object — status, aread(), aiter_lines()
    @property
    def status_code(self):
        return type(self).status

    def json(self):
        return type(self).body

    async def aread(self):
        return b""

    async def aiter_lines(self):
        for ln in type(self).lines:
            yield ln


async def _collect(provider, **kw):
    return [ev async for ev in llm_client.stream_complete(
        provider, kw.pop("model", "m"), kw.pop("messages", [{"role": "user", "content": "x"}]),
        None, **kw)]


def test_openai_stream_parses_deltas_and_usage(monkeypatch):
    monkeypatch.setattr(llm_client.httpx, "AsyncClient", _FakeStream)
    _FakeStream.status = 200
    _FakeStream.lines = [
        'data: {"choices":[{"delta":{"content":"Hel"}}]}',
        "",
        ': comment',
        'data: {"choices":[{"delta":{"content":"lo"},"finish_reason":"stop"}]}',
        'data: {"choices":[],"usage":{"prompt_tokens":7,"completion_tokens":2}}',
        "data: [DONE]",
    ]
    evs = anyio.run(functools.partial(_collect, "openai", api_key="sk-k"))
    assert [e["text"] for e in evs if e["type"] == "delta"] == ["Hel", "lo"]
    done = evs[-1]
    assert done["output"] == "Hello" and done["finish_reason"] == "stop"
    assert done["usage"] == {"input_tokens": 7, "output_tokens": 2}
    # usage has to be requested explicitly or a streamed run reports (and bills) nothing
    assert _FakeStream.last["json"]["stream"] is True
    assert _FakeStream.last["json"]["stream_options"] == {"include_usage": True}


def test_stream_without_usage_still_estimates_tokens(monkeypatch):
    """An OpenAI-compatible endpoint that ignores stream_options must not yield a free run —
    zero tokens would mean zero estimated cost and the spend cap would never move."""
    monkeypatch.setattr(llm_client.httpx, "AsyncClient", _FakeStream)
    _FakeStream.status = 200
    _FakeStream.lines = ['data: {"choices":[{"delta":{"content":"a fairly long answer here"}}]}']
    evs = anyio.run(functools.partial(_collect, "openai_compatible", api_key="k",
                                      base_url="https://llm.internal/v1"))
    assert evs[-1]["usage"]["output_tokens"] > 0
    assert evs[-1]["usage"]["input_tokens"] > 0
    assert _FakeStream.last["url"] == "https://llm.internal/v1/chat/completions"


def test_openai_stream_http_error_raises(monkeypatch):
    monkeypatch.setattr(llm_client.httpx, "AsyncClient", _FakeStream)
    _FakeStream.status = 401
    _FakeStream.body = {"error": {"message": "bad key"}}
    _FakeStream.lines = []
    with pytest.raises(llm_client.LLMError) as e:
        anyio.run(functools.partial(_collect, "openai", api_key="sk-bad"))
    assert "bad key" in str(e.value)
    _FakeStream.status = 200


def test_anthropic_stream_parses_events(monkeypatch):
    monkeypatch.setattr(llm_client.httpx, "AsyncClient", _FakeStream)
    _FakeStream.status = 200
    _FakeStream.lines = [
        "event: message_start",
        'data: {"type":"message_start","message":{"usage":{"input_tokens":9}}}',
        "event: content_block_delta",
        'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"hi "}}',
        'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"there"}}',
        'data: {"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"output_tokens":4}}',
    ]
    evs = anyio.run(functools.partial(
        _collect, "anthropic", api_key="ak-k",
        messages=[{"role": "system", "content": "be brief"}, {"role": "user", "content": "hi"}]))
    done = evs[-1]
    assert done["output"] == "hi there" and done["finish_reason"] == "end_turn"
    assert done["usage"] == {"input_tokens": 9, "output_tokens": 4}
    assert _FakeStream.last["json"]["system"] == "be brief"       # system hoisted, as unstreamed
    assert _FakeStream.last["headers"]["x-api-key"] == "ak-k"


def test_anthropic_mid_stream_error_event_raises(monkeypatch):
    """Anthropic reports an overload *inside* a 200 response. Ignoring that frame would end the
    stream cleanly and present half an answer as the whole answer."""
    monkeypatch.setattr(llm_client.httpx, "AsyncClient", _FakeStream)
    _FakeStream.status = 200
    _FakeStream.lines = [
        'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"partial"}}',
        'data: {"type":"error","error":{"type":"overloaded_error","message":"Overloaded"}}',
    ]
    with pytest.raises(llm_client.LLMError) as e:
        anyio.run(functools.partial(_collect, "anthropic", api_key="ak-k"))
    assert "Overloaded" in str(e.value)


def test_anthropic_stream_http_error_raises(monkeypatch):
    monkeypatch.setattr(llm_client.httpx, "AsyncClient", _FakeStream)
    _FakeStream.status = 429
    _FakeStream.body = {"error": {"message": "rate limited"}}
    _FakeStream.lines = []
    with pytest.raises(llm_client.LLMError) as e:
        anyio.run(functools.partial(_collect, "anthropic", api_key="ak-k"))
    assert "rate limited" in str(e.value)
    _FakeStream.status = 200


def test_stream_network_error_raises(monkeypatch):
    class _Boom(_FakeStream):
        def stream(self, *a, **k):
            raise llm_client.httpx.ConnectError("dns fail")

    monkeypatch.setattr(llm_client.httpx, "AsyncClient", _Boom)
    for provider in ("openai", "anthropic"):
        with pytest.raises(llm_client.LLMError) as e:
            anyio.run(functools.partial(_collect, provider, api_key="k"))
        assert "network error" in str(e.value)


def test_stream_ignores_unparseable_frames(monkeypatch):
    """A truncated or non-JSON frame is noise, not a reason to fail a run."""
    monkeypatch.setattr(llm_client.httpx, "AsyncClient", _FakeStream)
    _FakeStream.status = 200
    _FakeStream.lines = ['data: {"choices":[{"delta":', 'data: {"choices":[{"delta":{"content":"ok"}}]}']
    assert anyio.run(functools.partial(_collect, "openai", api_key="k"))[-1]["output"] == "ok"
    _FakeStream.lines = ['data: not json', 'data: {"type":"content_block_delta","delta":{"text":"ok"}}']
    assert anyio.run(functools.partial(_collect, "anthropic", api_key="k"))[-1]["output"] == "ok"


def test_stream_requires_a_key():
    for provider in ("openai", "anthropic"):
        with pytest.raises(llm_client.LLMError) as e:
            anyio.run(functools.partial(_collect, provider))
        assert "API key" in str(e.value)


def test_unknown_provider_stream_raises():
    with pytest.raises(llm_client.LLMError):
        anyio.run(functools.partial(_collect, "grok"))


def test_stream_still_caps_max_tokens(monkeypatch):
    """The per-run ceiling is what stops an edit running up a bill; it must apply to the
    streamed path too, not just the blocking one."""
    monkeypatch.setattr(llm_client.httpx, "AsyncClient", _FakeStream)
    _FakeStream.status = 200
    _FakeStream.lines = ['data: {"choices":[{"delta":{"content":"hi"}}]}']
    with TestClient(app, base_url="https://testserver") as c:
        conn = c.post("/api/connections", json={"provider": "openai", "label": "cap",
                                                "key": "sk-live-1234"}).json()
        r = c.post("/api/playground/run/stream", json={
            "connection_id": conn["id"], "model": "gpt-4o", "params": {"max_tokens": 999999},
            "messages": [{"role": "user", "content": "hi"}]})
        assert r.status_code == 200, r.text
        assert _frames(r.text)[-1]["type"] == "done"
    assert _FakeStream.last["json"]["max_tokens"] == 4096


def test_endpoint_surfaces_a_mid_stream_provider_failure(monkeypatch):
    """The response is already a 200 by the time tokens flow, so the failure has to arrive as an
    error frame — and the partial tokens must still be billed."""
    async def boom(*a, **k):
        yield {"type": "delta", "text": "half an answer"}
        raise llm_client.LLMError("provider error 529: Overloaded")

    monkeypatch.setattr("provekit.routers.playground.stream_complete", boom)
    spent = []
    monkeypatch.setattr("provekit.routers.playground.limits.record_spend",
                        lambda ws_id, usd: spent.append(usd))
    monkeypatch.setattr("provekit.routers.playground.pricing.estimate",
                        lambda model, i, o: 0.001 * ((i or 0) + (o or 0)))

    with TestClient(app, base_url="https://testserver") as c:
        r = c.post("/api/playground/run/stream", json={
            "provider": "mock", "model": "gpt-4o",
            "messages": [{"role": "user", "content": "hi"}]})
        assert r.status_code == 200
        evs = _frames(r.text)
    assert evs[0]["type"] == "delta"
    assert evs[-1]["type"] == "error" and "Overloaded" in evs[-1]["error"]
    assert not any(e["type"] == "done" for e in evs)   # never looks like a finished answer
    assert spent and spent[-1] > 0                     # streamed tokens are still charged for
