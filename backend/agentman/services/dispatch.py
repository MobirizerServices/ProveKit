"""The unified run dispatcher. Routes a request (prompt | tool | agent) to the right
provider and normalizes everything to one event schema:

    {"type":"start",  "run_id", "request_type"}
    {"type":"delta",  "text"}                          # streamed tokens
    {"type":"node",   "data"}                            # passthrough agent SSE event
    {"type":"result", "data", "meta"}                    # final structured output
    {"type":"done",   "status", "duration_ms"}
    {"type":"error",  "error"}
"""
from __future__ import annotations

import re
import time
import uuid

from ..models import Connection
from .masking import is_masked
from .providers import a2a_client, agent_http, llm, mcp_client

_VAR = re.compile(r"\{\{\s*([\w.\-]+)\s*\}\}")


def interpolate(text, variables: dict):
    if not isinstance(text, str):
        return text
    return _VAR.sub(lambda m: str(variables.get(m.group(1), m.group(0))), text)


def _interp_obj(obj, variables: dict):
    if isinstance(obj, str):
        return interpolate(obj, variables)
    if isinstance(obj, list):
        return [_interp_obj(x, variables) for x in obj]
    if isinstance(obj, dict):
        return {k: _interp_obj(v, variables) for k, v in obj.items()}
    return obj


def _conn(db, cid, workspace_id=None) -> Connection | None:
    if not cid:
        return None
    c = db.get(Connection, cid)
    # Tenancy: never resolve a connection outside the caller's workspace (prevents using
    # another tenant's stored credentials by passing its connection_id). workspace_id=None
    # (CLI / single-tenant) skips the check.
    if c and workspace_id is not None and c.workspace_id != workspace_id:
        return None
    return c


def run_collect(db, req: dict, variables: dict | None = None, workspace_id=None) -> dict:
    """Run a request to completion (non-streaming) and return the collected result —
    used by the flow engine to execute prompt/tool/agent nodes."""
    text, output, meta, status, err = [], None, {}, "completed", ""
    for ev in run(db, req, variables, workspace_id):
        t = ev["type"]
        if t == "delta":
            text.append(ev.get("text", ""))
        elif t == "result":
            output, meta = ev.get("data"), ev.get("meta", {})
        elif t == "error":
            err = ev.get("error", "")
        elif t == "done":
            status = ev.get("status", "completed")
    return {"text": "".join(text) or None, "output": output, "meta": meta, "status": status, "error": err}


def run(db, req: dict, variables: dict | None = None, workspace_id=None):
    variables = variables or {}
    rtype = req.get("type")
    run_id = uuid.uuid4().hex[:12]
    yield {"type": "start", "run_id": run_id, "request_type": rtype}
    t0 = time.monotonic()
    try:
        if rtype == "prompt":
            yield from _run_prompt(db, req, variables, workspace_id)
        elif rtype == "tool":
            yield from _run_tool(db, req, variables, workspace_id)
        elif rtype == "agent":
            yield from _run_agent(db, req, variables, workspace_id)
        elif rtype == "a2a":
            yield from _run_a2a(db, req, variables, workspace_id)
        else:
            raise ValueError(f"unknown request type: {rtype!r}")
    except Exception as exc:
        yield {"type": "error", "error": str(exc)[:600]}
        yield {"type": "done", "status": "failed", "duration_ms": round((time.monotonic() - t0) * 1000)}
        return
    yield {"type": "done", "status": "completed", "duration_ms": round((time.monotonic() - t0) * 1000)}


def _run_prompt(db, req, variables, workspace_id=None):
    conn = _conn(db, req.get("connection_id"), workspace_id)
    cfg = (conn.config or {}) if conn else {}
    if conn:
        # A stored connection is authoritative for destination AND credentials.
        # Honoring per-request base_url/api_key here would let any caller point the
        # stored key at their own host (credential exfiltration).
        provider = cfg.get("provider") or "openai"
        base_url = cfg.get("base_url") or ""
        api_key = cfg.get("api_key") or ""
    else:
        provider = req.get("provider") or "openai"
        base_url = req.get("base_url") or ""
        api_key = req.get("api_key") or ""
    model = req.get("model") or (cfg.get("models") or ["gpt-4o-mini"])[0]
    system = interpolate(req.get("system"), variables)

    messages = []
    for turn in req.get("messages") or []:
        role = "assistant" if turn.get("role") == "assistant" else "user"
        messages.append({"role": role, "content": interpolate(turn.get("content", ""), variables)})
    user = interpolate(req.get("user", ""), variables)
    # Anthropic rejects empty content blocks — when a messages[] history is supplied,
    # only append the final user turn if it actually says something.
    if user or not messages:
        messages.append({"role": "user", "content": user})

    parts, usage = [], {}
    for ev in llm.stream(provider=provider, base_url=base_url, api_key=api_key, model=model,
                         system=system, messages=messages,
                         temperature=float(req.get("temperature", 0.7)),
                         max_tokens=int(req.get("max_tokens", 1024))):
        if ev["type"] == "delta":
            parts.append(ev["text"])
            yield {"type": "delta", "text": ev["text"]}
        elif ev["type"] == "usage":
            usage = ev["usage"]
    yield {"type": "result", "data": {"text": "".join(parts)},
           "meta": {"provider": provider, "model": model, "usage": usage}}


def _run_tool(db, req, variables, workspace_id=None):
    conn = _conn(db, req.get("connection_id"), workspace_id)
    cfg = (conn.config or {}) if conn else {}
    name = req.get("tool")
    if not name:
        raise ValueError("tool run needs a tool name")
    args = _interp_obj(req.get("args") or {}, variables)
    sess = _mcp_session(cfg, req if not conn else {})
    result = sess.call_tool(name, args)
    yield {"type": "result", "data": result, "meta": {"tool": name, "url": cfg.get("url") or req.get("url")}}


def _mcp_session(cfg: dict, adhoc: dict):
    """Build an MCP session from a connection config (stdio | http, spec, oauth). `adhoc`
    supplies url only for connection-less ad-hoc runs (never carries stored secrets)."""
    if cfg.get("command"):  # stdio transport
        return mcp_client.MCPSession(command=cfg["command"], args=cfg.get("args"), env=cfg.get("env"),
                                     spec=cfg.get("spec", "auto"))
    url = cfg.get("url") or adhoc.get("url")
    if not url:
        raise ValueError("tool run needs an MCP connection (or a url)")
    return mcp_client.MCPSession(url, headers=cfg.get("headers"), spec=cfg.get("spec", "auto"),
                                 oauth=cfg.get("oauth"))


def _run_agent(db, req, variables, workspace_id=None):
    conn = _conn(db, req.get("connection_id"), workspace_id)
    # Same rule as prompts/tools: stored auth headers travel only to the stored base_url.
    base = ((conn.config or {}).get("base_url") if conn else None) or (req.get("base_url") if not conn else None)
    if not base:
        raise ValueError("agent run needs an agent connection (or base_url)")
    # Drop masked values (e.g. a run replayed from history) so the connection's real
    # header wins instead of being overwritten by "••••1234".
    req_headers = {k: v for k, v in (req.get("headers") or {}).items() if not is_masked(v)}
    headers = {**((conn.config or {}).get("headers") or {} if conn else {}), **req_headers}
    body = _interp_obj(req.get("body"), variables)
    for ev in agent_http.run(base_url=base, method=req.get("method", "POST"),
                             path=interpolate(req.get("path", ""), variables),
                             headers=headers, body=body, stream=bool(req.get("stream"))):
        if ev["type"] == "delta":
            yield {"type": "delta", "text": ev["text"]}
        elif ev["type"] == "event":
            yield {"type": "node", "data": ev["data"]}
        elif ev["type"] == "result":
            yield {"type": "result", "data": ev.get("data"), "meta": ev.get("meta", {})}


def _run_a2a(db, req, variables, workspace_id=None):
    conn = _conn(db, req.get("connection_id"), workspace_id)
    base = ((conn.config or {}).get("base_url") if conn else None) or (req.get("base_url") if not conn else None)
    if not base:
        raise ValueError("A2A run needs an A2A connection (or base_url)")
    headers = (conn.config or {}).get("headers") if conn else (req.get("headers") or None)
    text = interpolate(req.get("message") or req.get("text") or "", variables)
    card = None
    try:  # discover the endpoint from the agent card; fall back to base_url on failure
        card = a2a_client.fetch_card(base, headers=headers)
    except Exception:
        pass
    yield from a2a_client.run(base_url=base, text=text, headers=headers,
                             stream=bool(req.get("stream")), card=card)
