"""Generic MCP client — speaks MCP (JSON-RPC 2.0) over the Streamable-HTTP transport to
ANY MCP server URL. Handles both plain-JSON and SSE responses, and the initialize +
session-id handshake for stateful servers (also works with stateless ones)."""
from __future__ import annotations

import json
import threading

import httpx

from ..netguard import guard_url

_ACCEPT = "application/json, text/event-stream"
_lock = threading.Lock()
_id = 0


def _next_id() -> int:
    global _id
    with _lock:
        _id += 1
        return _id


def _parse(resp: httpx.Response) -> dict:
    ctype = resp.headers.get("content-type", "")
    if ctype.startswith("text/event-stream"):
        for line in resp.text.splitlines():
            if line.startswith("data:"):
                chunk = json.loads(line[5:].strip())
                if isinstance(chunk, dict) and ("result" in chunk or "error" in chunk):
                    return chunk
        raise RuntimeError("no JSON-RPC message in SSE stream")
    return resp.json()


class MCPSession:
    """A short-lived MCP session against one server URL."""

    def __init__(self, url: str, headers: dict | None = None, timeout: float = 30):
        guard_url(url)
        self.url = url.rstrip("/")
        self.headers = {"Content-Type": "application/json", "Accept": _ACCEPT, **(headers or {})}
        self.timeout = timeout
        self.session_id: str | None = None

    def _rpc(self, client: httpx.Client, method: str, params: dict | None = None) -> dict:
        headers = dict(self.headers)
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        payload = {"jsonrpc": "2.0", "id": _next_id(), "method": method, "params": params or {}}
        resp = client.post(self.url, json=payload, headers=headers)
        sid = resp.headers.get("mcp-session-id")
        if sid:
            self.session_id = sid
        resp.raise_for_status()
        data = _parse(resp)
        if "error" in data:
            raise RuntimeError(str(data["error"].get("message", "MCP error")))
        return data.get("result", {})

    def _notify(self, client: httpx.Client, method: str) -> None:
        headers = dict(self.headers)
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        client.post(self.url, json={"jsonrpc": "2.0", "method": method, "params": {}}, headers=headers)

    def _init(self, client: httpx.Client) -> None:
        try:
            self._rpc(client, "initialize", {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "agentman", "version": "0.1.0"},
            })
            self._notify(client, "notifications/initialized")
        except Exception:
            # Stateless servers may reject/ignore initialize — proceed anyway.
            pass

    def list_tools(self) -> list[dict]:
        with httpx.Client(timeout=self.timeout) as client:
            self._init(client)
            tools = self._rpc(client, "tools/list").get("tools", [])
            return [{"name": t["name"], "description": t.get("description", ""),
                     "input_schema": t.get("inputSchema") or {}} for t in tools]

    def call_tool(self, name: str, args: dict) -> dict:
        with httpx.Client(timeout=self.timeout) as client:
            self._init(client)
            res = self._rpc(client, "tools/call", {"name": name, "arguments": args or {}})
        if res.get("isError"):
            raise RuntimeError(_text(res) or f"tool '{name}' failed")
        return _unwrap(res)


def _text(res: dict) -> str | None:
    for block in res.get("content", []):
        if block.get("type") == "text":
            return block.get("text")
    return None


def _unwrap(res: dict):
    sc = res.get("structuredContent")
    if sc is not None:
        if isinstance(sc, dict) and set(sc.keys()) == {"result"}:
            return sc["result"]
        return sc
    txt = _text(res)
    if txt is None:
        return res.get("content", res)
    try:
        return json.loads(txt)
    except json.JSONDecodeError:
        return {"text": txt}
