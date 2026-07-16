"""Generic visual-flow engine. Walks a graph of nodes (input · prompt · tool · agent ·
condition · output), threading a shared context, and streams rich per-node events so the
canvas can animate + inspect execution. Nodes reuse the providers via dispatch.run_collect.
Supports breakpoints + single-step (like a debugger).
"""
from __future__ import annotations

import json
import re
import time
import uuid

from . import dispatch

MAX_STEPS = 100
_REF = re.compile(r"\{\{\s*([\w.\-]+)\s*\}\}")
_RUNS: dict[str, dict] = {}       # run_id -> ctx (for pause/continue debugging)
_RUN_TS: dict[str, float] = {}    # run_id -> last-touch monotonic time
_RUN_TTL = 1800                   # evict paused runs abandoned for 30 min
_RUN_MAX = 200                    # hard cap on retained paused runs


def _store_run(rid: str, ctx: dict) -> None:
    """Retain a paused run's context, evicting expired and excess entries (bounded memory)."""
    now = time.monotonic()
    _RUNS[rid] = ctx
    _RUN_TS[rid] = now
    for k in [k for k, t in list(_RUN_TS.items()) if now - t > _RUN_TTL]:
        _RUNS.pop(k, None); _RUN_TS.pop(k, None)
    if len(_RUNS) > _RUN_MAX:
        for k in sorted(_RUN_TS, key=_RUN_TS.get)[: len(_RUNS) - _RUN_MAX]:
            _RUNS.pop(k, None); _RUN_TS.pop(k, None)


def _drop_run(rid: str) -> None:
    _RUNS.pop(rid, None); _RUN_TS.pop(rid, None)

# Catalog served to the frontend palette + inspector.
NODE_TYPES = {
    "input": {"label": "Input", "category": "trigger", "color": "muted"},
    "prompt": {"label": "Prompt", "category": "ai", "color": "prompt"},
    "tool": {"label": "Tool", "category": "tool", "color": "tool"},
    "agent": {"label": "Agent", "category": "agent", "color": "agent"},
    "condition": {"label": "Condition", "category": "logic", "color": "purple", "branches": ["true", "false"]},
    "output": {"label": "Output", "category": "output", "color": "ok"},
}


def _resolve(ref: str, ctx: dict):
    parts = [p for p in ref.split(".") if p]
    if not parts:
        return None
    root = parts[0]
    cur = ctx.get("input") if root == "input" else (ctx.get("nodes") or {}).get(root)
    for p in parts[1:]:
        if isinstance(cur, dict):
            cur = cur.get(p)
        elif isinstance(cur, list):
            try:
                cur = cur[int(p)]
            except (ValueError, IndexError):
                return None
        else:
            return None
    return cur


def _interp(text, ctx):
    if not isinstance(text, str):
        return text

    def sub(m):
        v = _resolve(m.group(1), ctx)
        if v is None:
            return m.group(0)
        return v if isinstance(v, str) else json.dumps(v)
    return _REF.sub(sub, text)


def _interp_obj(obj, ctx):
    if isinstance(obj, str):
        return _interp(obj, ctx)
    if isinstance(obj, list):
        return [_interp_obj(x, ctx) for x in obj]
    if isinstance(obj, dict):
        return {k: _interp_obj(v, ctx) for k, v in obj.items()}
    return obj


def _trim(v, _d=0):
    if _d > 6:
        return "…"
    if isinstance(v, str):
        return v if len(v) <= 2000 else v[:2000] + "…"
    if isinstance(v, dict):
        return {k: _trim(x, _d + 1) for k, x in list(v.items())[:50]}
    if isinstance(v, list):
        return [_trim(x, _d + 1) for x in v[:40]]
    return v


def _adjacency(edges):
    adj = {}
    for e in edges:
        adj.setdefault(e["source"], []).append(e)
    return adj


def _next(adj, cur, branch):
    outs = adj.get(cur, [])
    if branch is not None:
        for e in outs:
            if (e.get("condition") or {}).get("branch") == branch:
                return e["target"]
        return None
    uncond = [e for e in outs if not (e.get("condition") or {}).get("branch")]
    return (uncond[0]["target"] if uncond else (outs[0]["target"] if outs else None))


def _find_trigger(graph):
    indeg = {n["id"]: 0 for n in graph["nodes"]}
    for e in graph["edges"]:
        if e["target"] in indeg:
            indeg[e["target"]] += 1
    for n in graph["nodes"]:
        if n["type"] == "input" and indeg.get(n["id"], 0) == 0:
            return n["id"]
    for n in graph["nodes"]:
        if indeg.get(n["id"], 0) == 0:
            return n["id"]
    return graph["nodes"][0]["id"] if graph["nodes"] else None


def _exec_node(db, node, ctx, variables=None):
    """Execute one node; return (output, branch). `variables` (the active environment)
    fill any {{name}} refs the flow context didn't resolve, matching console behavior."""
    t = node["type"]
    cfg = node.get("config") or {}
    if t == "input":
        return ctx.get("input") or {}, None
    if t == "prompt":
        system = cfg.get("system")
        if cfg.get("prompt_key"):  # pull the shared prompt from the registry (single source of truth)
            reg = _registry_prompt(db, cfg["prompt_key"])
            if reg is not None:
                system = reg
        req = {"type": "prompt", "connection_id": cfg.get("connection_id"), "model": cfg.get("model"),
               "system": _interp(system, ctx), "user": _interp(cfg.get("user", ""), ctx),
               "temperature": cfg.get("temperature", 0.7), "max_tokens": cfg.get("max_tokens", 1024)}
        r = dispatch.run_collect(db, req, variables)
        if r["status"] == "failed":
            raise RuntimeError(r["error"] or "prompt failed")
        return {"text": r["text"]}, None
    if t == "tool":
        req = {"type": "tool", "connection_id": cfg.get("connection_id"), "tool": cfg.get("tool"),
               "args": _interp_obj(cfg.get("args") or {}, ctx)}
        r = dispatch.run_collect(db, req, variables)
        if r["status"] == "failed":
            raise RuntimeError(r["error"] or "tool failed")
        return r["output"], None
    if t == "agent":
        req = {"type": "agent", "connection_id": cfg.get("connection_id"), "method": cfg.get("method", "POST"),
               "path": _interp(cfg.get("path", ""), ctx), "headers": cfg.get("headers") or {},
               "body": _interp_obj(cfg.get("body"), ctx)}
        r = dispatch.run_collect(db, req, variables)
        if r["status"] == "failed":
            raise RuntimeError(r["error"] or "agent failed")
        return r["output"], None
    if t == "condition":
        # Unresolved refs become "" (not the literal "{{ref}}") so `exists`/comparisons are correct.
        left = _interp_blank(cfg.get("left", ""), ctx)
        right = _interp_blank(cfg.get("right", ""), ctx)
        op = cfg.get("op", "==")
        ok = _compare(left, right, op)
        return {"result": ok, "left": left, "right": right, "op": op}, ("true" if ok else "false")
    if t == "output":
        val = _interp_obj(cfg.get("value", ""), ctx)
        return {"value": val}, None
    return {}, None


def _registry_prompt(db, key: str):
    """Resolve a Prompt Registry entry's content by key (None if missing)."""
    from ..models import Prompt
    row = db.query(Prompt).filter(Prompt.key == key).first()
    return row.content if row else None


def _interp_blank(text, ctx):
    """Like _interp but resolves unknown refs to "" instead of echoing the literal template —
    correct for condition comparisons / exists checks."""
    if not isinstance(text, str):
        return text

    def sub(m):
        v = _resolve(m.group(1), ctx)
        if v is None:
            return ""
        return v if isinstance(v, str) else json.dumps(v)
    return _REF.sub(sub, text)


def _compare(left, right, op):
    if op == "exists":
        return left not in (None, "", "null")
    if op == "contains":
        return str(right) in str(left)
    if op in ("==", "equals"):
        return str(left) == str(right)
    if op == "!=":
        return str(left) != str(right)
    try:
        lf, rf = float(left), float(right)
        return lf > rf if op == ">" else lf < rf if op == "<" else False
    except (ValueError, TypeError):
        return False


def run_stream(db, flow: dict, flow_input: dict, breakpoints=None, single_step=False,
               start_at=None, ctx=None, run_id=None, variables=None):
    breakpoints = set(breakpoints or [])
    graph = {"nodes": flow["nodes"], "edges": flow["edges"]}
    nodes = {n["id"]: n for n in graph["nodes"]}
    adj = _adjacency(graph["edges"])
    ctx = ctx or {"input": flow_input or {}, "nodes": {}}
    rid = run_id or uuid.uuid4().hex[:12]
    yield {"type": "start", "run_id": rid}

    node_id = start_at or _find_trigger(graph)
    steps, first = ctx.get("_steps", 0), True  # cumulative across pause/continue so cycles stay bounded
    while node_id:
        # Skip the breakpoint check only for the node we're resuming ONTO.
        if node_id in breakpoints and not (first and start_at):
            ctx["_steps"] = steps
            _store_run(rid, ctx)
            yield {"type": "pause", "node_id": node_id, "run_id": rid, "reason": "breakpoint"}
            return
        steps += 1
        if steps > MAX_STEPS:
            _drop_run(rid)
            yield {"type": "error", "error": "step budget exceeded (cycle?)"}
            yield {"type": "done", "status": "failed"}
            return
        node = nodes.get(node_id)
        if not node:
            break
        ntype = node["type"]
        title = (node.get("data") or {}).get("title") or NODE_TYPES.get(ntype, {}).get("label", ntype)
        yield {"type": "node", "node_id": node_id, "node_type": ntype, "title": title, "status": "running"}
        t0 = time.monotonic()
        try:
            output, branch = _exec_node(db, node, ctx, variables)
        except Exception as exc:
            _drop_run(rid)
            yield {"type": "node", "node_id": node_id, "node_type": ntype, "title": title,
                   "status": "error", "error": str(exc)[:400], "duration_ms": round((time.monotonic() - t0) * 1000)}
            yield {"type": "done", "status": "failed"}
            return
        dur = round((time.monotonic() - t0) * 1000)
        ctx["nodes"][node_id] = output
        yield {"type": "node", "node_id": node_id, "node_type": ntype, "title": title, "status": "ok",
               "branch": branch, "duration_ms": dur, "input": _trim(node.get("config") or {}),
               "output": _trim(output)}
        nxt = _next(adj, node_id, branch)
        if single_step and nxt:
            ctx["_steps"] = steps
            _store_run(rid, ctx)
            yield {"type": "pause", "node_id": nxt, "run_id": rid, "reason": "step"}
            return
        node_id = nxt
        first = False

    _drop_run(rid)
    yield {"type": "done", "status": "completed", "output": _trim({k: v for k, v in (ctx.get("nodes") or {}).items()})}


def get_ctx(run_id: str) -> dict | None:
    return _RUNS.get(run_id)


def pop_ctx(run_id: str) -> dict | None:
    """Atomically take a paused run's context so a concurrent /continue can't resume it twice."""
    _RUN_TS.pop(run_id, None)
    return _RUNS.pop(run_id, None)
