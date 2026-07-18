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

import anyio

from ..models import Connection
from . import tooling
from .masking import is_masked
from .providers import a2a_client, agent_http, llm, mcp_client


def _add_usage(total: dict, add: dict) -> dict:
    """Sum token counts across the turns of a tool loop — a run reports one usage total,
    but a tool-calling run makes N model calls.

    Recurses into the nested breakdowns every provider ships (`*_tokens_details`,
    Anthropic's cache counters). Summing only the top level would leave the totals
    internally inconsistent — parents summed over N turns, children from the last turn
    alone — which reads as real data in a product people use to measure cost.
    """
    if not total:
        return dict(add or {})
    out = dict(total)
    for k, v in (add or {}).items():
        prev = out.get(k)
        if isinstance(v, dict) and isinstance(prev, dict):
            out[k] = _add_usage(prev, v)
        elif isinstance(v, (int, float)) and isinstance(prev, (int, float)) and not isinstance(v, bool):
            out[k] = prev + v
        else:
            out[k] = v
    return out


def _rounds(raw) -> int:
    """max_tool_rounds, clamped. Absent → 5; explicit 0 means "never execute", so it must
    survive (a plain `or 5` would turn it into 5). Null/garbage is a caller error worth
    saying out loud rather than silently defaulting."""
    if raw is None:
        return 5
    try:
        n = int(raw)
    except (TypeError, ValueError):
        raise ValueError(f"max_tool_rounds must be a number, got {raw!r}")
    return max(0, min(n, tooling.MAX_TOOL_ROUNDS))

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


async def run_collect(db, req: dict, variables: dict | None = None, workspace_id=None) -> dict:
    """Run a request to completion (non-streaming) and return the collected result —
    used by the flow engine to execute prompt/tool/agent nodes."""
    text, output, meta, status, err, dur = [], None, {}, "completed", "", 0
    events = []
    async for ev in run(db, req, variables, workspace_id):
        t = ev["type"]
        if t == "delta":
            text.append(ev.get("text", ""))
        elif t == "node":
            # Keep node events: they carry the tool calls a `tool_called` assertion reads.
            # Dropping them made that assertion inert for anything run through a flow.
            events.append(ev.get("data"))
        elif t == "result":
            output, meta = ev.get("data"), ev.get("meta", {})
        elif t == "error":
            err = ev.get("error", "")
        elif t == "done":
            status, dur = ev.get("status", "completed"), ev.get("duration_ms", 0)
    return {"text": "".join(text) or None, "output": output, "meta": meta, "status": status,
            "error": err, "duration_ms": dur, "events": events}


def run_collect_sync(db, req: dict, variables: dict | None = None, workspace_id=None) -> dict:
    """Sync bridge for the CLI: drive the async run to completion. Never call from a loop."""
    return anyio.run(run_collect, db, req, variables, workspace_id)


async def run(db, req: dict, variables: dict | None = None, workspace_id=None):
    variables = variables or {}
    rtype = req.get("type")
    run_id = uuid.uuid4().hex[:12]
    yield {"type": "start", "run_id": run_id, "request_type": rtype}
    t0 = time.monotonic()
    try:
        if rtype == "prompt":
            gen = _run_prompt(db, req, variables, workspace_id)
        elif rtype == "tool":
            gen = _run_tool(db, req, variables, workspace_id)
        elif rtype == "agent":
            gen = _run_agent(db, req, variables, workspace_id)
        elif rtype == "a2a":
            gen = _run_a2a(db, req, variables, workspace_id)
        else:
            raise ValueError(f"unknown request type: {rtype!r}")
        async for ev in gen:
            yield ev
    except Exception as exc:
        yield {"type": "error", "error": str(exc)[:600]}
        yield {"type": "done", "status": "failed", "duration_ms": round((time.monotonic() - t0) * 1000)}
        return
    yield {"type": "done", "status": "completed", "duration_ms": round((time.monotonic() - t0) * 1000)}


async def _run_prompt(db, req, variables, workspace_id=None):
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

    # MCP tools the model may call, discovered up front so an unreachable server fails the
    # run before any tokens are spent. The DB lookup is cheap and stays here; discovery is
    # blocking (HTTP, or spawning a stdio server) and must not sit on the event loop.
    plans = tooling.plan(db, req.get("tools"), workspace_id)
    tools = await anyio.to_thread.run_sync(tooling.discover, plans) if plans else []
    by_api = {t.api_name: t for t in tools}
    defs = tooling.for_provider(tools, provider)
    rounds_left = _rounds(req.get("max_tool_rounds"))
    runner = tooling.Runner()

    parts, usage = [], {}
    # Sessions the loop opens must be torn down even if the model stream fails,
    # or a stdio MCP subprocess would outlive the run.
    try:
        while True:
            text, calls = [], []
            async for ev in llm.astream(provider=provider, base_url=base_url, api_key=api_key, model=model,
                                        system=system, messages=messages,
                                        temperature=float(req.get("temperature", 0.7)),
                                        max_tokens=int(req.get("max_tokens", 1024)), tools=defs):
                if ev["type"] == "delta":
                    text.append(ev["text"]); parts.append(ev["text"])
                    yield {"type": "delta", "text": ev["text"]}
                elif ev["type"] == "tool_call":
                    calls.append(ev["call"])
                elif ev["type"] == "node":
                    yield ev  # stop_reason and other provider events
                elif ev["type"] == "usage":
                    usage = _add_usage(usage, ev["usage"])  # one result per run, N model turns
            if not calls:
                break
            # Report the server's real tool name, not the sanitized one the model was given, so
            # a `tool_called` assertion matches what the user sees in the MCP server.
            yield {"type": "node", "data": {"tool_calls": [
                {"id": c["id"], "name": (by_api[c["name"]].name if c["name"] in by_api else c["name"]),
                 "args": c["args"]} for c in calls]}}
            # Only an explicit `execute: false` (or the cap) stops the run. A name we don't know
            # is the model's mistake, not the user's intent, and is handled below as a failed
            # tool turn so it can correct itself.
            dry = [c for c in calls if c["name"] in by_api and not by_api[c["name"]].execute]
            if dry or rounds_left <= 0:
                reason = ("tool execution is off for this request" if dry else "hit max_tool_rounds")
                yield {"type": "node", "data": {"tools_stopped": reason}}
                break
            rounds_left -= 1
            messages = messages + [{"role": "assistant", "content": "".join(text),
                                    "tool_calls": [{"id": c["id"], "name": c["name"], "args": c["args"]}
                                                   for c in calls]}]
            for c in calls:
                tool = by_api.get(c["name"])
                if tool is None:
                    # A hallucinated tool. Feed the error back rather than ending the run: the
                    # model can pick a real tool on the next turn.
                    known = ", ".join(sorted(by_api)) or "none"
                    out, ok, err = (f"Tool error: no tool named '{c['name']}'. Available: {known}",
                                    False, f"unknown tool '{c['name']}'")
                    name = c["name"]
                else:
                    name = tool.name
                    try:
                        # MCP is sync and may spawn a process — never run it on the event loop.
                        out = await anyio.to_thread.run_sync(runner.call, tool, c["args"])
                        ok, err = True, ""
                    except Exception as exc:  # a failed tool is a turn the model sees, not a dead run
                        out, ok, err = f"Tool error: {exc}", False, str(exc)
                yield {"type": "node", "data": {"tool_result": {"name": name, "ok": ok,
                                                                "output": out, "error": err}}}
                messages.append({"role": "tool", "tool_call_id": c["id"], "name": c["name"],
                                 "content": out})
    finally:
        runner.close()
    yield {"type": "result", "data": {"text": "".join(parts)},
           "meta": {"provider": provider, "model": model, "usage": usage}}


async def _run_tool(db, req, variables, workspace_id=None):
    conn = _conn(db, req.get("connection_id"), workspace_id)
    cfg = (conn.config or {}) if conn else {}
    name = req.get("tool")
    if not name:
        raise ValueError("tool run needs a tool name")
    args = _interp_obj(req.get("args") or {}, variables)
    sess = _mcp_session(cfg, req if not conn else {})
    # MCP is a one-shot blocking call (incl. a possible stdio subprocess) — offload to a
    # thread so the event loop isn't blocked for its duration.
    result = await anyio.to_thread.run_sync(sess.call_tool, name, args)
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


async def _run_agent(db, req, variables, workspace_id=None):
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
    async for ev in agent_http.arun(base_url=base, method=req.get("method", "POST"),
                                    path=interpolate(req.get("path", ""), variables),
                                    headers=headers, body=body, stream=bool(req.get("stream"))):
        if ev["type"] == "delta":
            yield {"type": "delta", "text": ev["text"]}
        elif ev["type"] == "event":
            yield {"type": "node", "data": ev["data"]}
        elif ev["type"] == "result":
            yield {"type": "result", "data": ev.get("data"), "meta": ev.get("meta", {})}


async def _run_a2a(db, req, variables, workspace_id=None):
    conn = _conn(db, req.get("connection_id"), workspace_id)
    base = ((conn.config or {}).get("base_url") if conn else None) or (req.get("base_url") if not conn else None)
    if not base:
        raise ValueError("A2A run needs an A2A connection (or base_url)")
    # Drop masked values on the ad-hoc path (a run replayed from history) so we don't send
    # the literal "••••1234" placeholder as an auth header.
    headers = ((conn.config or {}).get("headers") if conn
               else {k: v for k, v in (req.get("headers") or {}).items() if not is_masked(v)} or None)
    text = interpolate(req.get("message") or req.get("text") or "", variables)
    card = None
    try:  # discover the endpoint from the agent card; fall back to base_url on failure
        card = await a2a_client.fetch_card(base, headers=headers)
    except Exception:
        pass
    async for ev in a2a_client.arun(base_url=base, text=text, headers=headers,
                                    stream=bool(req.get("stream")), card=card):
        yield ev
