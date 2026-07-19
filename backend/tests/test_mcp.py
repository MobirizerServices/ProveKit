"""The MCP debug-server data layer — the thin client over /v1/traces the `provekit-mcp`
command exposes. We stub httpx so no network is touched; we assert the env contract and the
URL/params it builds."""
import types

import httpx
import pytest

import provekit.mcp as mcp


class _Resp:
    def __init__(self, data):
        self._data = data
        self.captured = None

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


def _stub(monkeypatch, data, sink):
    def fake_get(url, headers=None, params=None, timeout=None, follow_redirects=None):
        sink.append({"url": url, "headers": headers, "params": params})
        return _Resp(data)
    monkeypatch.setattr(mcp.httpx, "get", fake_get)


def test_base_requires_env(monkeypatch):
    monkeypatch.delenv("PROVEKIT_API_KEY", raising=False)
    monkeypatch.delenv("PROVEKIT_ENDPOINT", raising=False)
    with pytest.raises(RuntimeError):
        mcp._base()


def test_list_and_get_build_key_authed_calls(monkeypatch):
    monkeypatch.setenv("PROVEKIT_API_KEY", "pk_test")
    monkeypatch.setenv("PROVEKIT_ENDPOINT", "https://portal.test/")
    calls = []
    _stub(monkeypatch, [{"trace_id": "t1"}], calls)

    rows = mcp.list_traces(limit=5)
    assert rows == [{"trace_id": "t1"}]
    assert calls[-1]["url"] == "https://portal.test/v1/traces"
    assert calls[-1]["headers"]["Authorization"] == "Bearer pk_test"
    assert calls[-1]["params"] == {"limit": 5}

    mcp.list_failures(limit=3)
    assert calls[-1]["params"] == {"limit": 3, "status": "failed"}

    mcp.get_trace("t-xyz")
    assert calls[-1]["url"].endswith("/v1/traces/t-xyz")


def test_build_server_registers_tools(monkeypatch):
    # Only run if the optional `mcp` package is importable; otherwise this path is user-side.
    pytest.importorskip("mcp.server.fastmcp")
    server = mcp.build_server()
    assert server is not None
