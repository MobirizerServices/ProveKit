"""A2A client: agent-card discovery (both paths) and message/send parsing."""
import httpx
import pytest

from agentman.services.providers import a2a_client as a2a

_REAL_CLIENT = httpx.Client  # capture before any patching (a2a.httpx is the same module object)


def _patch(monkeypatch, handler):
    monkeypatch.setattr(a2a, "guard_url", lambda u: None)
    monkeypatch.setattr(a2a.httpx, "Client",
                        lambda **k: _REAL_CLIENT(transport=httpx.MockTransport(handler)))


def test_fetch_card_v1_path(monkeypatch):
    def handler(request):
        if request.url.path == "/.well-known/agent-card.json":
            return httpx.Response(200, json={"name": "Booker", "protocolVersion": "1.0",
                                             "url": "http://a/rpc", "skills": [{"name": "book"}]})
        return httpx.Response(404)
    _patch(monkeypatch, handler)
    card = a2a.fetch_card("http://a")
    assert card["name"] == "Booker" and card["_path"] == "/.well-known/agent-card.json"
    assert card["_version"] == "1.0"


def test_fetch_card_falls_back_to_v03_path(monkeypatch):
    def handler(request):
        if request.url.path == "/.well-known/agent-card.json":
            return httpx.Response(404)
        if request.url.path == "/.well-known/agent.json":
            return httpx.Response(200, json={"name": "Legacy", "version": "0.3.0", "url": "http://a"})
        return httpx.Response(404)
    _patch(monkeypatch, handler)
    card = a2a.fetch_card("http://a")
    assert card["_path"] == "/.well-known/agent.json" and card["_version"] == "0.3.0"


def test_fetch_card_missing_raises(monkeypatch):
    _patch(monkeypatch, lambda r: httpx.Response(404))
    with pytest.raises(RuntimeError, match="no agent card"):
        a2a.fetch_card("http://a")


def test_message_send_parses_task_artifacts(monkeypatch):
    def handler(request):
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": "1", "result": {
            "id": "task1", "status": {"state": "completed"},
            "artifacts": [{"parts": [{"kind": "text", "text": "Booked "}, {"kind": "text", "text": "for 8pm"}]}]}})
    _patch(monkeypatch, handler)
    evs = list(a2a.run(base_url="http://a", text="book me a table",
                       card={"url": "http://a/rpc"}))
    assert "".join(e["text"] for e in evs if e["type"] == "delta") == "Booked for 8pm"
    assert any(e["type"] == "result" for e in evs)


def test_message_send_parses_message_result(monkeypatch):
    def handler(request):
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": "1", "result": {
            "role": "agent", "parts": [{"kind": "text", "text": "hi from agent"}], "messageId": "m1"}})
    _patch(monkeypatch, handler)
    evs = list(a2a.run(base_url="http://a", text="hi"))
    assert "".join(e["text"] for e in evs if e["type"] == "delta") == "hi from agent"


def test_jsonrpc_error_raises(monkeypatch):
    def handler(request):
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": "1", "error": {"code": -32000, "message": "task failed"}})
    _patch(monkeypatch, handler)
    with pytest.raises(RuntimeError, match="task failed"):
        list(a2a.run(base_url="http://a", text="x"))
