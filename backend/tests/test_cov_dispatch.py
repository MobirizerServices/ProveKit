"""Coverage-focused tests for the run dispatcher and its HTTP/A2A providers.

No real network or subprocess: httpx.AsyncClient is replaced with fakes (mirroring the
style in test_llm_providers.py / test_a2a.py), mcp_client.MCPSession is monkeypatched,
and netguard.guard_url is a no-op so localhost/private hosts aren't blocked.
"""
import asyncio

import httpx
import pytest

from agentman.database import SessionLocal
from agentman.models import Connection
from agentman.services import dispatch
from agentman.services.masking import MASK
from agentman.services.providers import a2a_client as a2a
from agentman.services.providers import agent_http

_REAL = httpx.AsyncClient  # real client, captured before any patching


def _run(coro):
    return asyncio.run(coro)


async def _collect(agen):
    return [ev async for ev in agen]


# --------------------------------------------------------------------------- #
# agent_http.arun — a fake AsyncClient whose .stream() yields a controllable
# async context manager exposing aiter_lines()/aiter_bytes().
# --------------------------------------------------------------------------- #
class _FakeStream:
    def __init__(self, *, status=200, headers=None, lines=None, chunks=None):
        self.status_code = status
        self.headers = headers or {}
        self._lines = lines or []
        self._chunks = chunks or []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def aiter_lines(self):
        for line in self._lines:
            yield line

    async def aiter_bytes(self):
        for chunk in self._chunks:
            yield chunk

    async def aread(self):
        return b"".join(self._chunks)


def _patch_agent_http(monkeypatch, stream_obj, capture=None):
    monkeypatch.setattr(agent_http, "guard_url", lambda u: None)

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def stream(self, method, url, **k):
            if capture is not None:
                capture["method"] = method
                capture["url"] = url
                capture["json"] = k.get("json")
                capture["headers"] = k.get("headers")
            return stream_obj

    monkeypatch.setattr(agent_http.httpx, "AsyncClient", _Client)


def test_agent_http_stream_events_and_deltas(monkeypatch):
    lines = [
        "",                                    # blank line skipped
        'data: {"foo": "bar"}',                # JSON -> event
        "data: plain text",                    # non-JSON data -> delta
        "raw line without prefix",             # non-data line -> delta
        "data: [DONE]",                        # terminates the loop
        'data: {"never": "seen"}',             # after [DONE]: never reached
    ]
    stream = _FakeStream(status=201, lines=lines)
    cap = {}
    _patch_agent_http(monkeypatch, stream, cap)
    evs = _run(_collect(agent_http.arun(base_url="http://host/", method="get", path="/chat",
                                        headers={"X-A": "1"}, body={"q": 1}, stream=True)))
    assert {"type": "event", "data": {"foo": "bar"}} in evs
    assert {"type": "delta", "text": "plain text"} in evs
    assert {"type": "delta", "text": "raw line without prefix"} in evs
    assert not any(e.get("data") == {"never": "seen"} for e in evs)
    result = evs[-1]
    assert result["type"] == "result" and result["meta"] == {"status": 201, "streamed": True}
    # URL is base + path (single slash), method upper-cased, headers merged with Accept.
    assert cap["url"] == "http://host/chat" and cap["method"] == "GET"
    assert cap["headers"]["Accept"].startswith("application/json")
    assert cap["headers"]["X-A"] == "1"
    assert cap["json"] == {"q": 1}


def test_agent_http_nonstream_json(monkeypatch):
    stream = _FakeStream(status=200, headers={"content-type": "application/json; charset=utf-8"},
                         chunks=[b'{"ok":', b' true}'])
    _patch_agent_http(monkeypatch, stream)
    evs = _run(_collect(agent_http.arun(base_url="http://host", method="POST", path="",
                                        headers=None, body=None, stream=False)))
    assert evs == [{"type": "result", "data": {"ok": True}, "meta": {"status": 200}}]


def test_agent_http_nonstream_text(monkeypatch):
    stream = _FakeStream(status=200, headers={"content-type": "text/plain"},
                         chunks=[b"hello ", b"world"])
    _patch_agent_http(monkeypatch, stream)
    evs = _run(_collect(agent_http.arun(base_url="http://host", method="POST", path="/x",
                                        stream=False)))
    assert evs == [{"type": "result", "data": "hello world", "meta": {"status": 200}}]


def test_agent_http_response_cap_raises(monkeypatch):
    big = b"x" * (agent_http.MAX_RESPONSE_BYTES + 1)
    stream = _FakeStream(status=200, headers={"content-type": "text/plain"}, chunks=[big])
    _patch_agent_http(monkeypatch, stream)
    with pytest.raises(ValueError, match="exceeded"):
        _run(_collect(agent_http.arun(base_url="http://host", method="POST", path="/x",
                                      stream=False)))


# --------------------------------------------------------------------------- #
# a2a_client — MockTransport, mirroring test_a2a.py.
# --------------------------------------------------------------------------- #
def _patch_a2a(monkeypatch, handler):
    monkeypatch.setattr(a2a, "guard_url", lambda u: None)
    monkeypatch.setattr(a2a.httpx, "AsyncClient",
                        lambda **k: _REAL(transport=httpx.MockTransport(handler)))


def test_a2a_fetch_card_missing_name_tries_next_then_fails(monkeypatch):
    # v1.0 path returns 200 but no name -> ValueError caught -> falls through to v0.3
    # which 500s -> RuntimeError with the last error recorded.
    def handler(request):
        if request.url.path == "/.well-known/agent-card.json":
            return httpx.Response(200, json={"protocolVersion": "1.0"})  # missing name
        return httpx.Response(500)
    _patch_a2a(monkeypatch, handler)
    with pytest.raises(RuntimeError, match="no agent card"):
        _run(a2a.fetch_card("http://a/"))


def test_a2a_fetch_card_success_returns_card(monkeypatch):
    def handler(request):
        if request.url.path == "/.well-known/agent-card.json":
            return httpx.Response(200, json={"name": "Booker", "protocolVersion": "1.0",
                                             "url": "http://a/rpc"})
        return httpx.Response(404)
    _patch_a2a(monkeypatch, handler)
    card = _run(a2a.fetch_card("http://a"))
    assert card["name"] == "Booker"
    assert card["_path"] == "/.well-known/agent-card.json"
    assert card["_version"] == "1.0"


def test_a2a_arun_jsonrpc_error_field_raises(monkeypatch):
    def handler(request):
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": "1",
                                         "error": {"code": -32000, "message": "task failed"}})
    _patch_a2a(monkeypatch, handler)
    with pytest.raises(RuntimeError, match="task failed"):
        _run(_collect(a2a.arun(base_url="http://a", text="x")))


def test_a2a_arun_jsonrpc_error_no_message(monkeypatch):
    # error present but no message -> default "A2A error"
    def handler(request):
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": "1", "error": None})
    _patch_a2a(monkeypatch, handler)
    with pytest.raises(RuntimeError, match="A2A error"):
        _run(_collect(a2a.arun(base_url="http://a", text="x")))


def test_a2a_extract_text_variants():
    # parts on a Message
    assert a2a._extract_text({"parts": [{"kind": "text", "text": "hi"},
                                        {"kind": "image"}]}) == "hi"
    # artifacts on a Task
    assert a2a._extract_text({"artifacts": [{"parts": [{"text": "a"}, {"text": "b"}]}]}) == "ab"
    # status.message.parts fallback
    assert a2a._extract_text({"status": {"message": {"parts": [{"text": "done"}]}}}) == "done"
    # non-dict / empty
    assert a2a._extract_text("nope") == ""
    assert a2a._extract_text({}) == ""


def test_a2a_endpoint_prefers_card_url():
    assert a2a._endpoint("http://base/", {"url": "http://rpc"}) == "http://rpc"
    assert a2a._endpoint("http://base/", None) == "http://base"
    assert a2a._endpoint("http://base/", {}) == "http://base"


def test_a2a_arun_nonstream_delta_and_result(monkeypatch):
    def handler(request):
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": "1",
                                         "result": {"parts": [{"kind": "text", "text": "yo"}]}})
    _patch_a2a(monkeypatch, handler)
    evs = _run(_collect(a2a.arun(base_url="http://a", text="hi")))
    assert {"type": "delta", "text": "yo"} in evs
    assert evs[-1]["type"] == "result" and evs[-1]["meta"] == {"protocol": "a2a"}


def test_a2a_arun_4xx_raises(monkeypatch):
    _patch_a2a(monkeypatch, lambda r: httpx.Response(404, text="not found"))
    with pytest.raises(RuntimeError, match="A2A error 404"):
        _run(_collect(a2a.arun(base_url="http://a", text="hi")))


def test_a2a_arun_stream_collects_and_errors(monkeypatch):
    sse = ("data: garbage-not-json\n"
           'data: {"result": {"parts": [{"kind": "text", "text": "one "}]}}\n'
           "\n"
           'data: {"result": {"parts": [{"kind": "text", "text": "two"}]}}\n')

    def handler(request):
        return httpx.Response(200, text=sse, headers={"content-type": "text/event-stream"})
    _patch_a2a(monkeypatch, handler)
    evs = _run(_collect(a2a.arun(base_url="http://a", text="hi", stream=True,
                                 card={"url": "http://a/rpc"})))
    assert "".join(e["text"] for e in evs if e["type"] == "delta") == "one two"
    result = evs[-1]
    assert result["type"] == "result" and result["data"] == {"text": "one two"}
    assert result["meta"] == {"protocol": "a2a", "streamed": True}


def test_a2a_arun_stream_4xx_raises(monkeypatch):
    def handler(request):
        return httpx.Response(500, text="boom", headers={"content-type": "text/event-stream"})
    _patch_a2a(monkeypatch, handler)
    with pytest.raises(RuntimeError, match="A2A error 500"):
        _run(_collect(a2a.arun(base_url="http://a", text="hi", stream=True)))


def test_a2a_arun_stream_empty_yields_none_result(monkeypatch):
    def handler(request):
        return httpx.Response(200, text="event: ping\n", headers={"content-type": "text/event-stream"})
    _patch_a2a(monkeypatch, handler)
    evs = _run(_collect(a2a.arun(base_url="http://a", text="hi", stream=True)))
    assert evs == [{"type": "result", "data": None, "meta": {"protocol": "a2a", "streamed": True}}]


# --------------------------------------------------------------------------- #
# dispatch — real DB + monkeypatched providers.
# --------------------------------------------------------------------------- #
def _mk_conn(cfg, kind="agent", workspace_id=None):
    db = SessionLocal()
    c = Connection(name="c", kind=kind, config=cfg, workspace_id=workspace_id)
    db.add(c)
    db.commit()
    db.refresh(c)
    cid = c.id
    db.close()
    return cid


def test_interpolate_and_interp_obj():
    assert dispatch.interpolate("hi {{name}}", {"name": "Ann"}) == "hi Ann"
    assert dispatch.interpolate("{{missing}}", {}) == "{{missing}}"  # unknown var untouched
    assert dispatch.interpolate(42, {}) == 42  # non-str passthrough
    out = dispatch._interp_obj({"a": ["{{x}}", 1], "b": {"c": "{{x}}"}}, {"x": "Z"})
    assert out == {"a": ["Z", 1], "b": {"c": "Z"}}


def test_conn_tenancy():
    db = SessionLocal()
    try:
        assert dispatch._conn(db, None) is None                  # no id
        cid = _mk_conn({"base_url": "http://x"}, workspace_id=1)
        assert dispatch._conn(db, cid, workspace_id=1).id == cid  # same tenant
        assert dispatch._conn(db, cid, workspace_id=2) is None     # foreign tenant blocked
        assert dispatch._conn(db, cid).id == cid                   # workspace_id=None skips check
        assert dispatch._conn(db, 999999, workspace_id=1) is None  # unknown id
    finally:
        db.close()


def test_run_unknown_type_emits_error():
    db = SessionLocal()
    try:
        evs = _run(_collect(dispatch.run(db, {"type": "nope"})))
    finally:
        db.close()
    assert evs[0]["type"] == "start"
    assert any(e["type"] == "error" and "unknown request type" in e["error"] for e in evs)
    assert evs[-1] == {"type": "done", "status": "failed", **{k: evs[-1][k] for k in ("duration_ms",)}}
    assert evs[-1]["status"] == "failed"


def test_run_collect_prompt_aggregates(monkeypatch):
    async def fake_astream(**kw):
        # a stored connection must win over per-request overrides
        assert kw["base_url"] == "http://stored" and kw["api_key"] == "STOREDKEY"
        assert kw["provider"] == "anthropic"
        assert kw["model"] == "claude-x"          # from cfg.models[0]
        assert kw["system"] == "sys Ann"          # interpolated
        # messages: history turn + final user turn, both interpolated
        assert kw["messages"][0] == {"role": "assistant", "content": "prior"}
        assert kw["messages"][-1] == {"role": "user", "content": "hello Ann"}
        yield {"type": "delta", "text": "Hi "}
        yield {"type": "node", "data": {"stop_reason": "end"}}
        yield {"type": "delta", "text": "there"}
        yield {"type": "usage", "usage": {"output_tokens": 2}}

    monkeypatch.setattr(dispatch.llm, "astream", fake_astream)
    cid = _mk_conn({"provider": "anthropic", "base_url": "http://stored", "api_key": "STOREDKEY",
                    "models": ["claude-x"]}, kind="llm", workspace_id=7)
    req = {"type": "prompt", "connection_id": cid,
           # these overrides must be ignored because a stored connection exists
           "provider": "openai", "base_url": "http://attacker", "api_key": "PWN",
           "system": "sys {{name}}",
           "messages": [{"role": "assistant", "content": "prior"}],
           "user": "hello {{name}}"}
    db = SessionLocal()
    try:
        out = _run(dispatch.run_collect(db, req, {"name": "Ann"}, workspace_id=7))
    finally:
        db.close()
    assert out["text"] == "Hi there"
    assert out["output"] == {"text": "Hi there"}
    assert out["meta"]["usage"] == {"output_tokens": 2}
    assert out["status"] == "completed"


def test_run_prompt_no_connection_uses_request_and_defaults(monkeypatch):
    seen = {}

    async def fake_astream(**kw):
        seen.update(kw)
        yield {"type": "delta", "text": "ok"}

    monkeypatch.setattr(dispatch.llm, "astream", fake_astream)
    # No connection_id: request base_url/api_key/provider are used; model defaults to gpt-4o-mini;
    # no messages + empty user -> a single empty user turn is still appended.
    req = {"type": "prompt", "base_url": "http://req", "api_key": "K", "provider": "compatible"}
    db = SessionLocal()
    try:
        out = _run(dispatch.run_collect(db, req))
    finally:
        db.close()
    assert out["text"] == "ok"
    assert seen["base_url"] == "http://req" and seen["api_key"] == "K"
    assert seen["provider"] == "compatible" and seen["model"] == "gpt-4o-mini"
    assert seen["messages"] == [{"role": "user", "content": ""}]


def test_run_tool_via_mcp_stdio(monkeypatch):
    calls = {}

    class FakeSession:
        def __init__(self, **kw):
            calls["init"] = kw

        def call_tool(self, name, args):
            calls["call"] = (name, args)
            return {"echo": args}

    monkeypatch.setattr(dispatch.mcp_client, "MCPSession", FakeSession)
    # stdio config: command present -> _mcp_session builds a stdio session.
    cid = _mk_conn({"command": "python", "args": ["srv.py"], "env": {"E": "1"}, "spec": "auto"},
                   kind="mcp", workspace_id=3)
    req = {"type": "tool", "connection_id": cid, "tool": "greet",
           "args": {"who": "{{name}}"}}
    db = SessionLocal()
    try:
        out = _run(dispatch.run_collect(db, req, {"name": "Bo"}, workspace_id=3))
    finally:
        db.close()
    assert calls["init"] == {"command": "python", "args": ["srv.py"], "env": {"E": "1"}, "spec": "auto"}
    assert calls["call"] == ("greet", {"who": "Bo"})   # args interpolated
    assert out["output"] == {"echo": {"who": "Bo"}}
    assert out["meta"]["tool"] == "greet"


def test_run_tool_http_adhoc_url(monkeypatch):
    seen = {}

    class FakeSession:
        def __init__(self, *a, **kw):
            seen["args"] = a
            seen["kw"] = kw

        def call_tool(self, name, args):
            return {"ok": name}

    monkeypatch.setattr(dispatch.mcp_client, "MCPSession", FakeSession)
    # No connection: url comes from the ad-hoc request; positional url is passed.
    req = {"type": "tool", "tool": "t", "args": {}, "url": "http://mcp"}
    db = SessionLocal()
    try:
        out = _run(dispatch.run_collect(db, req))
    finally:
        db.close()
    assert seen["args"] == ("http://mcp",)
    assert out["meta"]["url"] == "http://mcp"


def test_run_tool_missing_name_errors():
    db = SessionLocal()
    try:
        out = _run(dispatch.run_collect(db, {"type": "tool"}))
    finally:
        db.close()
    assert out["status"] == "failed" and "tool name" in out["error"]


def test_run_tool_no_url_errors(monkeypatch):
    monkeypatch.setattr(dispatch.mcp_client, "MCPSession", lambda *a, **k: None)
    db = SessionLocal()
    try:
        out = _run(dispatch.run_collect(db, {"type": "tool", "tool": "t", "args": {}}))
    finally:
        db.close()
    assert out["status"] == "failed" and "MCP connection" in out["error"]


def test_run_agent_stored_conn_masked_headers_dropped(monkeypatch):
    seen = {}

    async def fake_arun(**kw):
        seen.update(kw)
        yield {"type": "delta", "text": "d1"}
        yield {"type": "event", "data": {"n": 1}}
        yield {"type": "result", "data": {"r": 1}, "meta": {"m": 1}}

    monkeypatch.setattr(dispatch.agent_http, "arun", fake_arun)
    cid = _mk_conn({"base_url": "http://stored", "headers": {"Authorization": "Bearer real"}},
                   kind="agent", workspace_id=5)
    req = {"type": "agent", "connection_id": cid, "method": "POST", "path": "/run/{{p}}",
           # masked value must be dropped; a real per-request header is merged in
           "headers": {"Authorization": MASK + "1234", "X-Extra": "e"},
           "base_url": "http://ignored", "body": {"q": "{{p}}"}, "stream": False}
    db = SessionLocal()
    try:
        evs = _run(_collect(dispatch.run(db, req, {"p": "42"}, workspace_id=5)))
    finally:
        db.close()
    # stored base_url wins; path interpolated; body interpolated
    assert seen["base_url"] == "http://stored"
    assert seen["path"] == "/run/42"
    assert seen["body"] == {"q": "42"}
    # masked Authorization dropped -> stored header survives; X-Extra merged
    assert seen["headers"]["Authorization"] == "Bearer real"
    assert seen["headers"]["X-Extra"] == "e"
    types = [e["type"] for e in evs]
    assert "delta" in types and "node" in types and "result" in types


def test_run_agent_adhoc_base_url(monkeypatch):
    seen = {}

    async def fake_arun(**kw):
        seen.update(kw)
        yield {"type": "delta", "text": "x"}

    monkeypatch.setattr(dispatch.agent_http, "arun", fake_arun)
    req = {"type": "agent", "base_url": "http://adhoc",
           "headers": {"Authorization": MASK + "9999", "X-Ok": "1"}}
    db = SessionLocal()
    try:
        out = _run(dispatch.run_collect(db, req))
    finally:
        db.close()
    assert seen["base_url"] == "http://adhoc"
    assert "Authorization" not in seen["headers"]  # masked -> dropped
    assert seen["headers"]["X-Ok"] == "1"
    assert out["text"] == "x"


def test_run_agent_no_base_errors():
    db = SessionLocal()
    try:
        out = _run(dispatch.run_collect(db, {"type": "agent"}))
    finally:
        db.close()
    assert out["status"] == "failed" and "base_url" in out["error"]


def test_run_a2a_stored_conn_card_and_stream(monkeypatch):
    seen = {}

    async def fake_fetch_card(base, headers=None):
        seen["card_base"] = base
        seen["card_headers"] = headers
        return {"name": "Agent", "url": "http://a/rpc"}

    async def fake_arun(**kw):
        seen.update(kw)
        yield {"type": "delta", "text": "hi"}
        yield {"type": "result", "data": {"text": "hi"}, "meta": {"protocol": "a2a"}}

    monkeypatch.setattr(dispatch.a2a_client, "fetch_card", fake_fetch_card)
    monkeypatch.setattr(dispatch.a2a_client, "arun", fake_arun)
    cid = _mk_conn({"base_url": "http://stored", "headers": {"Authorization": "Bearer real"}},
                   kind="agent", workspace_id=9)
    req = {"type": "a2a", "connection_id": cid, "message": "hey {{who}}",
           "base_url": "http://ignored", "stream": True}
    db = SessionLocal()
    try:
        out = _run(dispatch.run_collect(db, req, {"who": "Sam"}, workspace_id=9))
    finally:
        db.close()
    assert seen["card_base"] == "http://stored"
    assert seen["card_headers"] == {"Authorization": "Bearer real"}
    assert seen["base_url"] == "http://stored"
    assert seen["text"] == "hey Sam"
    assert seen["stream"] is True
    assert seen["card"] == {"name": "Agent", "url": "http://a/rpc"}
    assert out["text"] == "hi"


def test_run_a2a_adhoc_card_failure_masked_headers(monkeypatch):
    seen = {}

    async def fake_fetch_card(base, headers=None):
        raise RuntimeError("no card")  # discovery failure -> falls back to base_url

    async def fake_arun(**kw):
        seen.update(kw)
        yield {"type": "delta", "text": "z"}

    monkeypatch.setattr(dispatch.a2a_client, "fetch_card", fake_fetch_card)
    monkeypatch.setattr(dispatch.a2a_client, "arun", fake_arun)
    # ad-hoc path: masked header dropped; text falls back to req["text"]
    req = {"type": "a2a", "base_url": "http://adhoc", "text": "yo",
           "headers": {"Authorization": MASK + "1", "X-Keep": "k"}}
    db = SessionLocal()
    try:
        out = _run(dispatch.run_collect(db, req))
    finally:
        db.close()
    assert seen["card"] is None                     # fetch failed
    assert seen["base_url"] == "http://adhoc"
    assert seen["text"] == "yo"
    assert "Authorization" not in seen["headers"]   # masked dropped
    assert seen["headers"]["X-Keep"] == "k"
    assert out["text"] == "z"


def test_run_a2a_no_base_errors():
    db = SessionLocal()
    try:
        out = _run(dispatch.run_collect(db, {"type": "a2a"}))
    finally:
        db.close()
    assert out["status"] == "failed" and "base_url" in out["error"]


def test_run_collect_sync_bridge(monkeypatch):
    async def fake_astream(**kw):
        yield {"type": "delta", "text": "sync"}

    monkeypatch.setattr(dispatch.llm, "astream", fake_astream)
    db = SessionLocal()
    try:
        out = dispatch.run_collect_sync(db, {"type": "prompt", "user": "hi"})
    finally:
        db.close()
    assert out["text"] == "sync"
