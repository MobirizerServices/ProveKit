"""Coverage-focused tests for llm.py, mcp_client.py and promptfoo.py.

These target the lines NOT already exercised by tests/test_llm_providers.py,
tests/test_mcp_client.py and tests/test_cli.py — mock reply branches, the sync
collect bridge, the OpenAI SSE parser, >=400 error paths, HTTP-transport session /
parse / oauth handling, and the remaining promptfoo mapping branches.

No real network or subprocess: httpx.AsyncClient / httpx.Client / httpx.post are all
monkeypatched, and netguard guards are turned into no-ops where a real URL check would
otherwise reach DNS.
"""
import asyncio

import httpx
import pytest

from provekit.services.providers import llm
from provekit.services.providers import mcp_client as mc


# =====================================================================
# llm.py
# =====================================================================

class _FakeAsyncStream:
    """Async context manager standing in for client.stream(...)'s return value."""

    def __init__(self, lines, status_code=200, body=b""):
        self._lines = lines
        self.status_code = status_code
        self._body = body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def aiter_lines(self):
        for line in self._lines:
            yield line

    async def aread(self):
        return self._body


def _patch_client(monkeypatch, lines, status_code=200, body=b"boom", capture=None):
    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def stream(self, *a, **k):
            if capture is not None:
                capture["json"] = k.get("json")
                capture["headers"] = k.get("headers")
                capture["url"] = a[1] if len(a) > 1 else k.get("url")
            return _FakeAsyncStream(lines, status_code=status_code, body=body)

    monkeypatch.setattr(llm.httpx, "AsyncClient", _Client)


def _collect(**kwargs):
    async def run():
        return [ev async for ev in llm.astream(**kwargs)]
    return asyncio.run(run())


# ---- _mock_reply branches (lines 23, 25, 27, 33) ----

def test_mock_empty_user_greeting():
    # no user message at all -> greeting branch (line 23)
    evs = _collect(provider="mock", base_url="", api_key="", model="m",
                   system=None, messages=[])
    text = "".join(e["text"] for e in evs if e["type"] == "delta")
    assert "ProveKit demo agent" in text
    assert any(e["type"] == "usage" for e in evs)


def test_mock_classify_branch():
    evs = _collect(provider="mock", base_url="", api_key="", model="m",
                   system="You classify tickets", messages=[{"role": "user", "content": "hello"}])
    text = "".join(e["text"] for e in evs if e["type"] == "delta").strip()
    assert text == "support_request"


def test_mock_extract_json_branch():
    evs = _collect(provider="mock", base_url="", api_key="", model="m",
                   system="return json please", messages=[{"role": "user", "content": "go"}])
    text = "".join(e["text"] for e in evs if e["type"] == "delta")
    assert "is_demo" in text


def test_mock_urgent_branch():
    evs = _collect(provider="mock", base_url="", api_key="", model="m",
                   system=None, messages=[{"role": "user", "content": "URGENT refund now asap"}])
    text = "".join(e["text"] for e in evs if e["type"] == "delta")
    assert "urgent" in text.lower()


def test_mock_agent_definition_branch():
    evs = _collect(provider="mock", base_url="", api_key="", model="m",
                   system=None, messages=[{"role": "user", "content": "what is an agent, explain"}])
    text = "".join(e["text"] for e in evs if e["type"] == "delta")
    assert "AI agent" in text


# ---- _aiter_sse edge cases (lines 71, 77-78) ----

def test_openai_sse_skips_noise_and_bad_json(monkeypatch):
    lines = [
        "",                       # blank -> skipped (line 71)
        ": keepalive comment",    # non-data prefix -> skipped (line 71)
        "data: not-json-at-all",  # JSONDecodeError -> continue (lines 77-78)
        'data: {"choices":[{"delta":{"content":"Hi"}}]}',
        'data: {"choices":[{"delta":{}}],"usage":{"total_tokens":4}}',
        "data: [DONE]",
    ]
    _patch_client(monkeypatch, lines)
    evs = _collect(provider="openai", base_url="", api_key="k", model="gpt",
                   system="be brief", messages=[{"role": "user", "content": "hi"}])
    assert "".join(e["text"] for e in evs if e["type"] == "delta") == "Hi"
    usage = next(e["usage"] for e in evs if e["type"] == "usage")
    assert usage["total_tokens"] == 4


# ---- _stream_openai body/headers + delta + usage (lines 115-132, 121) ----

def test_openai_stream_sets_auth_header_and_body(monkeypatch):
    cap = {}
    lines = [
        'data: {"choices":[{"delta":{"content":"a"}}]}',
        'data: {"choices":[{"delta":{"content":"b"}}]}',
        "data: [DONE]",
    ]
    _patch_client(monkeypatch, lines, capture=cap)
    evs = _collect(provider="openai", base_url="http://host/v1", api_key="secret",
                   model="gpt-4o", system="sys", messages=[{"role": "user", "content": "hi"}])
    assert "".join(e["text"] for e in evs if e["type"] == "delta") == "ab"
    assert cap["headers"]["Authorization"] == "Bearer secret"       # line 121
    assert cap["json"]["messages"][0] == {"role": "system", "content": "sys"}
    assert cap["json"]["stream_options"] == {"include_usage": True}
    assert cap["url"] == "http://host/v1/chat/completions"


def test_openai_default_base_url_used(monkeypatch):
    cap = {}
    _patch_client(monkeypatch, ["data: [DONE]"], capture=cap)
    _collect(provider="openai", base_url=None, api_key="", model="gpt",
             system=None, messages=[{"role": "user", "content": "x"}])
    # falls back to DEFAULT_BASE["openai"]; no api_key -> no Authorization header
    assert cap["url"].startswith("https://api.openai.com/v1")
    assert "Authorization" not in cap["headers"]


# ---- >=400 -> RuntimeError for all three streaming providers (lines 149, 176 + openai) ----

def test_openai_http_error_raises(monkeypatch):
    _patch_client(monkeypatch, [], status_code=500, body=b"internal")
    with pytest.raises(RuntimeError, match="LLM error 500"):
        _collect(provider="openai", base_url="", api_key="k", model="m",
                 system=None, messages=[{"role": "user", "content": "hi"}])


def test_responses_http_error_raises(monkeypatch):
    _patch_client(monkeypatch, [], status_code=429, body=b"rate limited")
    with pytest.raises(RuntimeError, match="LLM error 429"):
        _collect(provider="openai-responses", base_url="", api_key="k", model="m",
                 system=None, messages=[{"role": "user", "content": "hi"}])


def test_anthropic_http_error_raises(monkeypatch):
    _patch_client(monkeypatch, [], status_code=401, body=b"unauthorized")
    with pytest.raises(RuntimeError, match="LLM error 401"):
        _collect(provider="anthropic", base_url="", api_key="k", model="m",
                 system=None, messages=[{"role": "user", "content": "hi"}])


# ---- anthropic system + api-key header (line 169), _maybe_temp with None ----

def test_anthropic_sets_system_and_apikey_header(monkeypatch):
    cap = {}
    lines = [
        'data: {"type":"message_start","message":{"usage":{"input_tokens":2}}}',
        'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"ok"}}',
        'data: {"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"output_tokens":1}}',
    ]
    _patch_client(monkeypatch, lines, capture=cap)
    evs = _collect(provider="anthropic", base_url="", api_key="ak", model="claude",
                   system="you are helpful", messages=[{"role": "user", "content": "hi"}],
                   temperature=None)
    assert cap["json"]["system"] == "you are helpful"      # line 169
    assert "temperature" not in cap["json"]                # _maybe_temp None branch
    assert cap["headers"]["x-api-key"] == "ak"
    # end_turn stop_reason is NOT surfaced as a node
    assert not any(e["type"] == "node" and e["data"].get("stop_reason") for e in evs)
    usage = next(e["usage"] for e in evs if e["type"] == "usage")
    assert usage["output_tokens"] == 1


# ---- collect_text_sync bridge (lines 105-111) ----

def test_collect_text_sync(monkeypatch):
    lines = [
        'data: {"choices":[{"delta":{"content":"Hello "}}]}',
        'data: {"choices":[{"delta":{"content":"world"}}]}',
        "data: [DONE]",
    ]
    _patch_client(monkeypatch, lines)
    out = llm.collect_text_sync(provider="openai", base_url="", api_key="k", model="m",
                                system=None, messages=[{"role": "user", "content": "hi"}])
    assert out == "Hello world"


def test_collect_text_sync_over_mock():
    # mock provider needs no patching; exercises the asyncio.run bridge end to end
    out = llm.collect_text_sync(provider="mock", base_url="", api_key="", model="m",
                                system=None, messages=[{"role": "user", "content": "hello there"}])
    assert isinstance(out, str) and out.strip()


# =====================================================================
# mcp_client.py — HTTP transport paths
# =====================================================================

def _make_transport(monkeypatch, client, *, url="http://server/mcp", headers=None,
                    stateful=True):
    """Build an _HTTPTransport with guard_url stubbed and a fake httpx.Client."""
    monkeypatch.setattr(mc, "guard_url", lambda u: None)
    monkeypatch.setattr(mc.httpx, "Client", lambda **k: client)
    return mc._HTTPTransport(url, headers or {}, 30, stateful)


class _FakeHttpxClient:
    """Fake httpx.Client whose .post returns queued/scripted httpx.Response objects."""

    def __init__(self, responder):
        self.responder = responder
        self.posts = []
        self.closed = False

    def post(self, url, json=None, headers=None):
        self.posts.append({"url": url, "json": json, "headers": headers})
        return self.responder(json, headers)

    def close(self):
        self.closed = True


def _resp(status=200, *, json_body=None, text=None, headers=None):
    hdrs = dict(headers or {})
    if json_body is not None:
        return httpx.Response(status, json=json_body, headers=hdrs,
                              request=httpx.Request("POST", "http://server/mcp"))
    return httpx.Response(status, text=text or "", headers=hdrs,
                          request=httpx.Request("POST", "http://server/mcp"))


# ---- _HTTPTransport init + session-id capture + _hdrs (lines 62-67, 72, 79, 83-84) ----

def test_http_transport_captures_session_id(monkeypatch):
    def responder(payload, headers):
        return _resp(json_body={"result": {"ok": True}},
                     headers={"mcp-session-id": "sess-42", "content-type": "application/json"})
    client = _FakeHttpxClient(responder)
    t = _make_transport(monkeypatch, client, headers={"X-Custom": "1"})
    # default headers merged with caller headers (lines 62-67)
    assert t.headers["Accept"] == mc._ACCEPT
    assert t.headers["X-Custom"] == "1"
    assert t.url == "http://server/mcp"          # trailing slash stripped
    out = t.request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert out == {"result": {"ok": True}}
    assert t.session_id == "sess-42"             # line 79
    # subsequent request carries the session id header (line 72)
    t.request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert client.posts[-1]["headers"]["Mcp-Session-Id"] == "sess-42"


def test_http_transport_notify_and_close(monkeypatch):
    def responder(payload, headers):
        return _resp(json_body={"result": {}})
    client = _FakeHttpxClient(responder)
    t = _make_transport(monkeypatch, client)
    t.notify({"jsonrpc": "2.0", "method": "notifications/initialized"})   # line 87
    assert client.posts[-1]["json"]["method"] == "notifications/initialized"
    t.close()                                                             # line 90
    assert client.closed is True


# ---- _parse_http: SSE stream, SSE-without-message error, JSON fallback (lines 129-137) ----

def test_parse_http_sse_stream(monkeypatch):
    sse = ("event: message\n"
           'data: {"jsonrpc":"2.0","id":1,"result":{"tools":[]}}\n\n')
    resp = _resp(text=sse, headers={"content-type": "text/event-stream"})
    assert mc._parse_http(resp) == {"jsonrpc": "2.0", "id": 1, "result": {"tools": []}}


def test_parse_http_sse_without_message_raises():
    resp = _resp(text="event: ping\ndata: 123\n\n",
                 headers={"content-type": "text/event-stream"})
    with pytest.raises(mc.MCPError, match="no JSON-RPC message"):
        mc._parse_http(resp)


def test_parse_http_json_fallback():
    resp = _resp(json_body={"result": {"x": 1}}, headers={"content-type": "application/json"})
    assert mc._parse_http(resp) == {"result": {"x": 1}}


def test_http_transport_request_parses_sse(monkeypatch):
    """End-to-end request() through an SSE response body."""
    def responder(payload, headers):
        sse = 'data: {"jsonrpc":"2.0","id":1,"result":{"pong":true}}\n'
        return _resp(text=sse, headers={"content-type": "text/event-stream"})
    client = _FakeHttpxClient(responder)
    t = _make_transport(monkeypatch, client)
    out = t.request({"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert out == {"jsonrpc": "2.0", "id": 1, "result": {"pong": True}}


# ---- 401 through the real _HTTPTransport.request path (lines 80-82) ----

def test_http_transport_401_raises_oauth_hint(monkeypatch):
    def responder(payload, headers):
        return _resp(401, text="", headers={"www-authenticate": 'Bearer realm="mcp"'})
    client = _FakeHttpxClient(responder)
    t = _make_transport(monkeypatch, client)
    with pytest.raises(mc.MCPError, match="OAuth"):
        t.request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})


# ---- _fetch_oauth_token: happy path + errors (lines 43, 51, 56) ----

def test_fetch_oauth_token_with_resource(monkeypatch):
    captured = {}

    class _R:
        def raise_for_status(self):
            pass

        def json(self):
            return {"access_token": "TOK"}

    def fake_post(url, data=None, timeout=None, follow_redirects=None):
        captured["url"] = url
        captured["data"] = data
        return _R()

    monkeypatch.setattr(mc, "guard_url", lambda u: None)
    monkeypatch.setattr(mc.httpx, "post", fake_post)
    tok = mc._fetch_oauth_token({"token_url": "http://auth/token", "client_id": "id",
                                 "client_secret": "sec", "resource": "http://api"})
    assert tok == "TOK"
    assert captured["data"]["resource"] == "http://api"     # line 51 (RFC 8707)
    assert captured["data"]["grant_type"] == "client_credentials"


def test_fetch_oauth_token_missing_token_url():
    with pytest.raises(mc.MCPError, match="token_url"):
        mc._fetch_oauth_token({"client_id": "id"})           # line 43


def test_fetch_oauth_token_no_access_token(monkeypatch):
    class _R:
        def raise_for_status(self):
            pass

        def json(self):
            return {}     # no access_token

    monkeypatch.setattr(mc, "guard_url", lambda u: None)
    monkeypatch.setattr(mc.httpx, "post", lambda *a, **k: _R())
    with pytest.raises(mc.MCPError, match="no access_token"):   # line 56
        mc._fetch_oauth_token({"token_url": "http://auth/token"})


# ---- MCPSession: url required + stateless init short-circuit + auto downgrade ----

def test_session_requires_url_or_command():
    with pytest.raises(mc.MCPError, match="needs a url"):        # line 160
        mc.MCPSession()


class _FakeTransport:
    def __init__(self, responder):
        self.responder = responder
        self.sent = []

    def request(self, payload):
        self.sent.append(payload)
        return self.responder(payload)

    def notify(self, payload):
        self.sent.append(payload)

    def close(self):
        pass


def _session_with(responder, **kw):
    sess = mc.MCPSession.__new__(mc.MCPSession)
    sess.spec = kw.get("spec", "auto")
    sess._stdio = False
    sess._stateful = kw.get("spec", "auto") != mc._STATELESS
    sess._t = _FakeTransport(responder)
    return sess


def test_init_auto_downgrades_to_stateless_on_initialize_failure():
    """auto spec: a server that errors on initialize is treated as stateless (lines 181-184)."""
    def responder(p):
        if p["method"] == "initialize":
            return {"error": {"message": "no initialize here"}}
        return {"result": {"tools": [{"name": "t", "inputSchema": {}}]}}
    sess = _session_with(responder, spec="auto")
    tools = sess.list_tools()
    assert [t["name"] for t in tools] == ["t"]
    assert sess._stateful is False     # downgraded


def test_rpc_error_raises_mcperror():
    def responder(p):
        return {"error": {"message": "kaboom"}}
    sess = _session_with(responder, spec="2026-07-28")  # stateless: goes straight to tools/list
    with pytest.raises(mc.MCPError, match="kaboom"):     # line 168
        sess.list_tools()


# ---- call_tool: isError + result unwrapping (lines 229, 237, 243-252) ----

def _tool_session(result):
    def responder(p):
        if p["method"] == "initialize":
            return {"result": {}}
        return {"result": result}
    return _session_with(responder, spec="2025-11-25")


def test_call_tool_is_error_raises():
    res = {"isError": True, "content": [{"type": "text", "text": "tool blew up"}]}
    sess = _tool_session(res)
    with pytest.raises(mc.MCPError, match="tool blew up"):    # line 229 + _text 237
        sess.call_tool("boom", {})


def test_call_tool_is_error_no_text_falls_back_to_name():
    res = {"isError": True, "content": [{"type": "image", "data": "..."}]}
    sess = _tool_session(res)
    with pytest.raises(mc.MCPError, match="tool 'boom' failed"):   # _text returns None -> line 237/229
        sess.call_tool("boom", {})


def test_call_tool_structured_content_result_key():
    # structuredContent == {"result": X} is unwrapped to X (lines 243-245)
    sess = _tool_session({"structuredContent": {"result": 42}})
    assert sess.call_tool("t", {}) == 42


def test_call_tool_structured_content_dict():
    sess = _tool_session({"structuredContent": {"a": 1, "b": 2}})
    assert sess.call_tool("t", {}) == {"a": 1, "b": 2}


def test_call_tool_text_json_parsed():
    sess = _tool_session({"content": [{"type": "text", "text": '{"k": "v"}'}]})
    assert sess.call_tool("t", {}) == {"k": "v"}      # line 248 -> json.loads


def test_call_tool_text_non_json_wrapped():
    sess = _tool_session({"content": [{"type": "text", "text": "plain answer"}]})
    assert sess.call_tool("t", {}) == {"text": "plain answer"}   # lines 251-252


def test_call_tool_no_text_returns_content():
    # no structuredContent, _text None -> returns res.get("content", res) (line 248 branch)
    res = {"content": [{"type": "image", "data": "b64"}]}
    sess = _tool_session(res)
    assert sess.call_tool("t", {}) == [{"type": "image", "data": "b64"}]


# ---- _StdioTransport remaining lines (empty-line skip, closed-before-reply, kill) ----

class _FakeStdin:
    def __init__(self):
        self.written = []

    def write(self, s):
        self.written.append(s)

    def flush(self):
        pass


class _FakeProc:
    def __init__(self, lines):
        self.stdin = _FakeStdin()
        self.stdout = iter(lines)

    def terminate(self):
        raise RuntimeError("terminate failed")   # force the except -> kill fallback

    def wait(self, timeout=None):
        pass

    def kill(self):
        self.killed = True


def _stdio_transport(proc, timeout=5):
    # Mirror _StdioTransport.__init__ minus the real subprocess: set the read deadline and
    # start the background reader that pumps the fake proc.stdout into the queue request() reads.
    import queue as _queue
    import threading as _threading
    t = mc._StdioTransport.__new__(mc._StdioTransport)
    t.proc = proc
    t.timeout = timeout
    t._lines = _queue.Queue()
    t._reader = _threading.Thread(target=t._pump, daemon=True)
    t._reader.start()
    return t


def test_stdio_request_skips_blank_lines():
    # a blank line before the matching reply exercises the `continue` (lines 108-109)
    proc = _FakeProc(["\n", '{"id": 1, "result": {"ok": true}}\n'])
    t = _stdio_transport(proc)
    out = t.request({"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert out == {"id": 1, "result": {"ok": True}}
    assert proc.stdin.written[0].endswith("\n")


def test_stdio_request_closed_before_reply():
    proc = _FakeProc([])   # stdout exhausted with no matching id
    t = _stdio_transport(proc)
    with pytest.raises(mc.MCPError, match="closed before replying"):   # line 113
        t.request({"jsonrpc": "2.0", "id": 99, "method": "ping"})


def test_stdio_close_falls_back_to_kill():
    proc = _FakeProc([])
    t = _stdio_transport(proc)
    t.close()                      # terminate raises -> except -> kill (lines 124-125)
    assert getattr(proc, "killed", False) is True


# =====================================================================
# promptfoo.py — remaining mapping branches
# =====================================================================

from provekit.services.promptfoo import (  # noqa: E402
    _map_assert,
    _provider_to_request,
    import_promptfoo,
)


def test_map_assert_regex_json_latency():
    assert _map_assert({"type": "regex", "value": "a.*b"})[0] == {"type": "regex", "value": "a.*b"}
    # is-json with a dict value -> json_schema carries the schema (line 28-31)
    mapped, warn = _map_assert({"type": "is-json", "value": {"type": "object"}})
    assert mapped == {"type": "json_schema", "schema": {"type": "object"}} and warn is None
    # is-valid-json without a dict value -> empty schema
    mapped2, _ = _map_assert({"type": "is-valid-json", "value": None})
    assert mapped2["schema"] == {}
    # latency-lt uses threshold when present
    mapped3, _ = _map_assert({"type": "latency-lt", "threshold": 1500})
    assert mapped3 == {"type": "latency_lt", "value": 1500}
    mapped4, _ = _map_assert({"type": "latency", "value": 800})
    assert mapped4 == {"type": "latency_lt", "value": 800}


def test_map_assert_equals_and_judge_and_unsupported():
    assert _map_assert({"type": "is-equals", "value": "x"})[0]["type"] == "equals"
    assert _map_assert({"type": "g-eval", "value": "is helpful"})[0] == {
        "type": "llm_judge", "criteria": "is helpful"}
    mapped, warn = _map_assert({"type": "python", "value": "1"})
    assert mapped is None and "unsupported assert type 'python'" in warn


def test_provider_to_request_http_dict():
    # dict provider with id 'http' -> agent request (lines 45-51)
    req, conn = _provider_to_request({"id": "http",
                                      "config": {"method": "PUT", "url": "http://x/api",
                                                 "body": {"q": 1}}})
    assert req == {"type": "agent", "method": "PUT", "path": "", "body": {"q": 1}}
    assert conn == "http"


def test_provider_to_request_dict_with_url_config():
    # dict provider whose config has a url (but non-http id) -> still agent
    req, conn = _provider_to_request({"id": "myserver", "config": {"url": "http://y"}})
    assert req["type"] == "agent"
    assert conn == "myserver"


def test_provider_to_request_dict_model_shorthand():
    req, conn = _provider_to_request({"id": "anthropic:claude-haiku-4-5"})
    assert req == {"type": "prompt", "model": "claude-haiku-4-5"}
    assert conn == "anthropic"


def test_provider_to_request_none_and_bare_label():
    assert _provider_to_request(None) == ({"type": "prompt", "model": ""}, None)   # line 53
    req, conn = _provider_to_request("openai")
    assert req == {"type": "prompt", "model": "openai"} and conn == "openai"


def test_import_promptfoo_multiple_prompts_warning():
    text = """
providers:
  - openai:gpt-4o-mini
prompts:
  - "first {{q}}"
  - "second {{q}}"
tests:
  - description: t1
    assert:
      - type: equals
        value: yes
"""
    files, warnings = import_promptfoo(text)
    assert len(files) == 1
    assert any("prompts found" in w for w in warnings)   # line 69


def test_import_promptfoo_no_tests_warning():
    text = """
providers:
  - openai:gpt-4o-mini
prompts:
  - "hi"
"""
    files, warnings = import_promptfoo(text)
    assert files == []
    assert any("no tests found" in w for w in warnings)   # line 91


def test_import_promptfoo_http_provider_end_to_end():
    """dict http provider flows into an agent request; user prompt is not attached."""
    text = """
providers:
  - id: http
    config:
      method: POST
      url: http://svc/run
      body: {input: "{{q}}"}
prompts:
  - "ignored for agent"
tests:
  - description: call
    vars: {q: "ping"}
    assert:
      - type: contains
        value: pong
"""
    files, warnings = import_promptfoo(text)
    assert len(files) == 1
    import provekit.services.testfile as tf
    doc = tf.load(files[0][1])
    assert doc["request"]["type"] == "agent"
    assert doc["request"]["method"] == "POST"
    assert "user" not in doc["request"]     # user prompt only added for prompt-type
