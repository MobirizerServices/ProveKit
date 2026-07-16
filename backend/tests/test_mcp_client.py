"""MCP client: stdio transport (real subprocess), dual spec, pagination, OAuth, 401."""
import sys
from pathlib import Path

import pytest

from agentman.services.providers import mcp_client as mc

SERVER = str(Path(__file__).parent / "mcp_stdio_server.py")


# ---- stdio transport, end to end against a real subprocess ----
def test_stdio_list_and_call():
    tools = mc.MCPSession(command=sys.executable, args=[SERVER]).list_tools()
    assert [t["name"] for t in tools] == ["echo"]
    out = mc.MCPSession(command=sys.executable, args=[SERVER]).call_tool("echo", {"x": 1})
    assert out == {"echoed": {"x": 1}}


# ---- HTTP transport driven by a fake, to exercise spec / pagination / oauth / 401 ----
class _FakeHTTP:
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


def _session_with(monkeypatch, responder, **kw):
    sess = mc.MCPSession.__new__(mc.MCPSession)
    sess.spec = kw.get("spec", "auto")
    sess._stdio = False
    sess._stateful = kw.get("spec", "auto") != mc._STATELESS
    sess._t = _FakeHTTP(responder)
    return sess


def test_stateful_does_handshake(monkeypatch):
    def responder(p):
        m = p["method"]
        if m == "initialize":
            return {"result": {"protocolVersion": mc._STATEFUL}}
        if m == "tools/list":
            return {"result": {"tools": [{"name": "a", "inputSchema": {}}]}}
        return {"result": {}}
    sess = _session_with(monkeypatch, responder, spec="2025-11-25")
    assert [t["name"] for t in sess.list_tools()] == ["a"]
    methods = [x.get("method") for x in sess._t.sent]
    assert "initialize" in methods and "notifications/initialized" in methods


def test_stateless_skips_handshake(monkeypatch):
    def responder(p):
        assert p["method"] != "initialize", "stateless generation must not handshake"
        return {"result": {"tools": [{"name": "b", "inputSchema": {}}]}}
    sess = _session_with(monkeypatch, responder, spec="2026-07-28")
    assert [t["name"] for t in sess.list_tools()] == ["b"]
    assert all(x.get("method") != "initialize" for x in sess._t.sent)


def test_pagination_follows_cursor(monkeypatch):
    pages = {None: {"tools": [{"name": "t1", "inputSchema": {}}], "nextCursor": "c2"},
             "c2": {"tools": [{"name": "t2", "inputSchema": {}}]}}
    def responder(p):
        if p["method"] == "initialize":
            return {"result": {}}
        return {"result": pages[p["params"].get("cursor")]}
    sess = _session_with(monkeypatch, responder)
    assert [t["name"] for t in sess.list_tools()] == ["t1", "t2"]


def test_resources_and_prompts(monkeypatch):
    def responder(p):
        m = p["method"]
        if m == "resources/list":
            return {"result": {"resources": [{"uri": "file://x", "name": "X"}]}}
        if m == "prompts/list":
            return {"result": {"prompts": [{"name": "greet", "arguments": []}]}}
        return {"result": {}}
    s1 = _session_with(monkeypatch, responder)
    assert s1.list_resources()[0]["uri"] == "file://x"
    s2 = _session_with(monkeypatch, responder)
    assert s2.list_prompts()[0]["name"] == "greet"


def test_oauth_client_credentials(monkeypatch):
    captured = {}
    class _Resp:
        def raise_for_status(self): pass
        def json(self): return {"access_token": "tok-123"}
    def fake_post(url, data=None, timeout=None):
        captured["url"] = url; captured["data"] = data
        return _Resp()
    monkeypatch.setattr(mc.httpx, "post", fake_post)
    monkeypatch.setattr(mc, "guard_url", lambda u: None)
    # constructing with oauth should fetch a token and set the Authorization header
    monkeypatch.setattr(mc, "_HTTPTransport", lambda url, headers, timeout, stateful: _CaptureTransport(headers))
    sess = mc.MCPSession("http://server/mcp", oauth={"token_url": "http://auth/token",
                                                     "client_id": "id", "client_secret": "sec", "scope": "read"})
    assert sess._t.headers["Authorization"] == "Bearer tok-123"
    assert captured["data"]["grant_type"] == "client_credentials"
    assert captured["data"]["scope"] == "read"


class _CaptureTransport:
    def __init__(self, headers): self.headers = headers
    def close(self): pass


def test_401_surfaces_oauth_hint():
    import httpx

    class _Client:
        def post(self, *a, **k):
            return httpx.Response(401, headers={"www-authenticate": 'Bearer resource_metadata="http://s/.well-known"'},
                                  request=httpx.Request("POST", "http://s/mcp"))
        def close(self): pass

    t = mc._HTTPTransport.__new__(mc._HTTPTransport)
    t.url = "http://s/mcp"; t.headers = {}; t.stateful = False; t.session_id = None
    t._client = _Client()
    with pytest.raises(mc.MCPError, match="OAuth"):
        t.request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
