"""Give the model under test a set of MCP tools it can actually call.

A prompt request may attach MCP connections:

    "tools": [{"connection_id": 7, "tools": ["check_inventory"], "execute": true}]

Each attachment is resolved to the tools that server advertises (all of them unless
`tools` narrows it), translated into the shape the target provider expects, and — when the
model picks one — executed back through the same MCP connection. `execute: false` records
the call and stops instead, so a routing decision can be asserted without firing the real
side effect.

The model sees a sanitized name (providers require ^[A-Za-z0-9_-]{1,64}$, MCP does not);
events and assertions always report the server's real tool name, so `tool_called` reads the
way a user wrote it.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from ..models import Connection
from .providers import mcp_client

# Provider-legal function names. MCP tool names are unconstrained, so they're mapped.
_NAME_OK = re.compile(r"[^A-Za-z0-9_-]")
MAX_TOOL_ROUNDS = 25  # ceiling on a request's max_tool_rounds: a loop is a cost/latency risk


@dataclass
class Tool:
    """One MCP tool, ready to advertise to a model and to invoke."""
    api_name: str          # what the model is told (sanitized, unique across attachments)
    name: str              # the server's real tool name — what events/assertions report
    description: str
    input_schema: dict
    connection_id: int | None
    cfg: dict              # the resolved MCP connection config (authoritative for secrets)
    execute: bool          # False → capture the call and stop, never invoke


def _conn(db, cid, workspace_id=None) -> Connection | None:
    """Same tenancy rule as dispatch._conn: never resolve another workspace's connection."""
    if not cid:
        return None
    c = db.get(Connection, cid)
    if c and workspace_id is not None and c.workspace_id != workspace_id:
        return None
    return c


def _api_name(name: str, taken: set[str]) -> str:
    base = _NAME_OK.sub("_", name or "tool")[:64] or "tool"
    out, n = base, 2
    while out in taken:  # two servers exposing the same tool name must stay distinguishable
        suffix = f"_{n}"
        out, n = base[:64 - len(suffix)] + suffix, n + 1
    return out


@dataclass
class _Attach:
    """One resolved attachment, before its server has been asked what it offers."""
    name: str
    connection_id: int
    cfg: dict
    allow: set[str] | None  # None → every tool the server offers; a set → exactly those
    execute: bool


def plan(db, spec, workspace_id=None) -> list[_Attach]:
    """Resolve `tools` attachments against the database. Touches no network, so it is safe
    to call on the event loop; `discover` does the talking."""
    out = []
    for att in spec or []:
        if not isinstance(att, dict):
            continue
        cid = att.get("connection_id")
        conn = _conn(db, cid, workspace_id)
        if not conn:
            raise ValueError(f"tools: MCP connection {cid!r} not found")
        if conn.kind != "mcp":
            raise ValueError(f"tools: connection {conn.name!r} is a {conn.kind} connection, not mcp")
        # Omitting `tools` exposes everything; an explicit list means exactly that list —
        # including an empty one. Treating [] as "all" made unticking the last tool in the
        # UI silently hand the model every tool instead of none.
        raw = att.get("tools")
        out.append(_Attach(name=conn.name, connection_id=conn.id, cfg=conn.config or {},
                           allow=None if raw is None else {str(t) for t in raw},
                           execute=att.get("execute", True) is not False))
    return out


def discover(plans: list[_Attach]) -> list[Tool]:
    """Ask each MCP server what it offers. Blocking (HTTP, or spawning a stdio server), so
    callers on the event loop must offload this to a thread.

    An unreachable server fails the run up front rather than halfway through a model turn.
    """
    tools: list[Tool] = []
    taken: set[str] = set()
    for att in plans:
        try:
            discovered = _session(att.cfg).list_tools()
        except Exception as exc:
            raise ValueError(f"tools: MCP connection {att.name!r} discovery failed: {exc}")
        for t in discovered:
            if att.allow is not None and t["name"] not in att.allow:
                continue
            api = _api_name(t["name"], taken)
            taken.add(api)
            tools.append(Tool(api_name=api, name=t["name"], description=t.get("description", ""),
                              input_schema=t.get("input_schema") or {},
                              connection_id=att.connection_id, cfg=att.cfg, execute=att.execute))
    return tools


def resolve(db, spec, workspace_id=None) -> list[Tool]:
    """plan + discover, for synchronous callers (the CLI, tests)."""
    return discover(plan(db, spec, workspace_id))


def _session(cfg: dict) -> mcp_client.MCPSession:
    """An MCP session from a stored connection. The connection is authoritative for both
    destination and credentials — a caller never supplies a url or secret here."""
    if cfg.get("command"):
        return mcp_client.MCPSession(command=cfg["command"], args=cfg.get("args"),
                                     env=cfg.get("env"), spec=cfg.get("spec", "auto"))
    if not cfg.get("url"):
        raise ValueError("MCP connection has no url or command")
    return mcp_client.MCPSession(cfg["url"], headers=cfg.get("headers"),
                                 spec=cfg.get("spec", "auto"), oauth=cfg.get("oauth"))


def _render(out) -> str:
    if isinstance(out, str):
        return out
    try:
        return json.dumps(out)
    except (TypeError, ValueError):
        return str(out)


class Runner:
    """Holds one open MCP session per connection for the life of a run.

    Building a session is expensive — it re-runs the initialize handshake, spawns a fresh
    subprocess for stdio, and re-fetches an OAuth token — so a session per tool call would
    pay all of that on every round. Blocking, like everything else here: callers on the
    event loop must offload `call` to a thread, and `close` runs at the end of the run.
    """

    def __init__(self) -> None:
        self._open: dict[int | None, mcp_client.MCPSession] = {}

    def call(self, tool: Tool, args: dict) -> str:
        sess = self._open.get(tool.connection_id)
        if sess is None:
            sess = self._open[tool.connection_id] = _session(tool.cfg).open()
        return _render(sess.call_tool(tool.name, args or {}))

    def close(self) -> None:
        for sess in self._open.values():
            try:
                sess.close()
            except Exception:  # never let transport teardown mask the run's own outcome
                pass
        self._open.clear()


def call(tool: Tool, args: dict) -> str:
    """Invoke one tool on a throwaway session — for one-shot callers (CLI, tests)."""
    with _session(tool.cfg).session() as sess:
        return _render(sess.call_tool(tool.name, args or {}))


# ---- provider tool-definition schemas -------------------------------------------------
def _schema(t: Tool) -> dict:
    # Providers reject a bare {} — an object schema with no properties is the empty case.
    return t.input_schema or {"type": "object", "properties": {}}


def for_provider(tools: list[Tool], provider: str) -> list[dict] | None:
    if not tools:
        return None
    if provider == "anthropic":
        return [{"name": t.api_name, "description": t.description, "input_schema": _schema(t)}
                for t in tools]
    if provider == "openai-responses":
        return [{"type": "function", "name": t.api_name, "description": t.description,
                 "parameters": _schema(t)} for t in tools]
    return [{"type": "function", "function": {"name": t.api_name, "description": t.description,
                                              "parameters": _schema(t)}} for t in tools]
