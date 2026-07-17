"""Generic MCP client — the best test client for Model Context Protocol servers.

Transports:      Streamable HTTP  ·  stdio (spawn a local server process)
Spec generations: stateful 2025-11-25 (initialize handshake + Mcp-Session-Id)
                  stateless 2026-07-28 (no session, server/discover) · auto-detect
Auth:            static bearer (via headers) · OAuth 2.1 client-credentials grant;
                 a 401 surfaces the resource-metadata hint so the user knows what's needed.
Discovery:       tools · resources · prompts, all cursor-paginated.
"""
from __future__ import annotations

import json
import subprocess
import threading

import httpx

from ..netguard import guard_stdio, guard_url

_ACCEPT = "application/json, text/event-stream"
_STATEFUL = "2025-11-25"
_STATELESS = "2026-07-28"
_lock = threading.Lock()
_id = 0


def _next_id() -> int:
    global _id
    with _lock:
        _id += 1
        return _id


class MCPError(RuntimeError):
    pass


def _fetch_oauth_token(oauth: dict) -> str:
    """Exchange client credentials for a bearer token (OAuth 2.1 client_credentials).
    Interactive auth-code/PKCE flows need a browser and are out of scope here."""
    token_url = oauth.get("token_url")
    if not token_url:
        raise MCPError("oauth config needs a token_url")
    guard_url(token_url)
    data = {"grant_type": "client_credentials",
            "client_id": oauth.get("client_id", ""),
            "client_secret": oauth.get("client_secret", "")}
    if oauth.get("scope"):
        data["scope"] = oauth["scope"]
    if oauth.get("resource"):  # RFC 8707 resource indicator
        data["resource"] = oauth["resource"]
    r = httpx.post(token_url, data=data, timeout=30, follow_redirects=False)
    r.raise_for_status()
    tok = r.json().get("access_token")
    if not tok:
        raise MCPError("no access_token in the OAuth token response")
    return tok


class _HTTPTransport:
    def __init__(self, url, headers, timeout, stateful: bool):
        guard_url(url)
        self.url = url.rstrip("/")
        self.headers = {"Content-Type": "application/json", "Accept": _ACCEPT, **(headers or {})}
        self.stateful = stateful
        self.session_id: str | None = None
        self._client = httpx.Client(timeout=timeout, follow_redirects=False)

    def _hdrs(self):
        h = dict(self.headers)
        if self.session_id:
            h["Mcp-Session-Id"] = self.session_id
        return h

    def request(self, payload) -> dict:
        resp = self._client.post(self.url, json=payload, headers=self._hdrs())
        sid = resp.headers.get("mcp-session-id")
        if sid:
            self.session_id = sid
        if resp.status_code == 401:
            meta = resp.headers.get("www-authenticate", "")
            raise MCPError(f"401 Unauthorized — server requires OAuth. {meta}".strip())
        resp.raise_for_status()
        return _parse_http(resp)

    def notify(self, payload) -> None:
        self._client.post(self.url, json=payload, headers=self._hdrs())

    def close(self):
        self._client.close()


class _StdioTransport:
    """Newline-delimited JSON-RPC over a spawned process's stdin/stdout."""
    def __init__(self, command, args, env, timeout):
        guard_stdio()  # RCE gate: never spawn a local process in hosted mode
        self.proc = subprocess.Popen(
            [command, *(args or [])], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, bufsize=1, env=env)

    def request(self, payload) -> dict:
        assert self.proc.stdin and self.proc.stdout
        self.proc.stdin.write(json.dumps(payload) + "\n")
        self.proc.stdin.flush()
        want = payload.get("id")
        for line in self.proc.stdout:
            line = line.strip()
            if not line:
                continue
            msg = json.loads(line)
            if msg.get("id") == want:
                return msg
        raise MCPError("stdio server closed before replying")

    def notify(self, payload) -> None:
        assert self.proc.stdin
        self.proc.stdin.write(json.dumps(payload) + "\n")
        self.proc.stdin.flush()

    def close(self):
        try:
            self.proc.terminate()
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()


def _parse_http(resp: httpx.Response) -> dict:
    ctype = resp.headers.get("content-type", "")
    if ctype.startswith("text/event-stream"):
        for line in resp.text.splitlines():
            if line.startswith("data:"):
                chunk = json.loads(line[5:].strip())
                if isinstance(chunk, dict) and ("result" in chunk or "error" in chunk):
                    return chunk
        raise MCPError("no JSON-RPC message in SSE stream")
    return resp.json()


class MCPSession:
    """A short-lived MCP session over one transport.

    HTTP:  MCPSession(url, headers=..., spec="auto"|"2025-11-25"|"2026-07-28", oauth=...)
    stdio: MCPSession(command="python", args=["server.py"], env=...)
    """

    def __init__(self, url: str | None = None, headers: dict | None = None, timeout: float = 30, *,
                 command: str | None = None, args: list | None = None, env: dict | None = None,
                 spec: str = "auto", oauth: dict | None = None):
        headers = dict(headers or {})
        if oauth:
            headers.setdefault("Authorization", f"Bearer {_fetch_oauth_token(oauth)}")
        self.spec = spec
        self._stdio = command is not None
        if self._stdio:
            self._t = _StdioTransport(command, args, env, timeout)
            self._stateful = True  # stdio is always a stateful session
        else:
            if not url:
                raise MCPError("MCP session needs a url (HTTP) or command (stdio)")
            self._stateful = spec != _STATELESS
            self._t = _HTTPTransport(url, headers, timeout, self._stateful)

    def _rpc(self, method: str, params: dict | None = None) -> dict:
        payload = {"jsonrpc": "2.0", "id": _next_id(), "method": method, "params": params or {}}
        data = self._t.request(payload)
        if "error" in data:
            raise MCPError(str(data["error"].get("message", "MCP error")))
        return data.get("result", {})

    def _init(self) -> None:
        if not self._stateful:
            return  # stateless generation: no handshake, no session id
        try:
            self._rpc("initialize", {
                "protocolVersion": _STATEFUL if self.spec == "auto" else self.spec,
                "capabilities": {},
                "clientInfo": {"name": "agentman", "version": "0.1.0"},
            })
            self._t.notify({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        except Exception:
            # auto: a server that rejects initialize is treated as stateless.
            if self.spec == "auto":
                self._stateful = False

    def _paginate(self, method: str, key: str) -> list[dict]:
        items, cursor = [], None
        while True:
            res = self._rpc(method, {"cursor": cursor} if cursor else {})
            items += res.get(key, [])
            cursor = res.get("nextCursor")
            if not cursor:
                return items

    def list_tools(self) -> list[dict]:
        try:
            self._init()
            tools = self._paginate("tools/list", "tools")
            return [{"name": t["name"], "description": t.get("description", ""),
                     "input_schema": t.get("inputSchema") or {}} for t in tools]
        finally:
            self._t.close()

    def list_resources(self) -> list[dict]:
        try:
            self._init()
            res = self._paginate("resources/list", "resources")
            return [{"uri": r.get("uri"), "name": r.get("name", ""),
                     "mime_type": r.get("mimeType", "")} for r in res]
        finally:
            self._t.close()

    def list_prompts(self) -> list[dict]:
        try:
            self._init()
            pr = self._paginate("prompts/list", "prompts")
            return [{"name": p["name"], "description": p.get("description", ""),
                     "arguments": p.get("arguments", [])} for p in pr]
        finally:
            self._t.close()

    def call_tool(self, name: str, args: dict) -> dict:
        try:
            self._init()
            res = self._rpc("tools/call", {"name": name, "arguments": args or {}})
        finally:
            self._t.close()
        if res.get("isError"):
            raise MCPError(_text(res) or f"tool '{name}' failed")
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
