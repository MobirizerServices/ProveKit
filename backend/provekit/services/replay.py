"""Trace replay harness (reconstructed mode) — the framework-agnostic differentiator.

Given a captured trace and an edit at one LLM span ("the fork"), produce a NEW trace branch:
  - spans BEFORE the fork are copied verbatim (unaffected);
  - the fork LLM call is re-run LIVE with the edited prompt/params → a new output;
  - the new output is threaded forward: any downstream LLM call whose recorded input contained
    the old output has it substituted and is re-run LIVE too (chained);
  - other downstream spans replay their recorded output, flagged 'diverged' if their input
    referenced a value that changed.

Each new span carries meta.replay_state ∈ {unchanged, live, recorded, diverged} and
meta.replay_of = origin_trace_id. This approximates LangGraph-style time-travel from a
read-only trace, with no runtime ownership. Exact downstream re-execution is the opt-in
webhook mode (M4); this is best-effort and honestly badged.
"""
from __future__ import annotations

import json
import secrets

import httpx
from sqlalchemy.orm import Session

from ..models import ReplayRun, Run, Workspace
from . import limits, otel, pricing
from .llm_client import LLMError, complete
from .netguard import guard_url


_ROLE_ALIASES = {"human": "user", "ai": "assistant", "bot": "assistant", "ai_message": "assistant",
                 "human_message": "user", "system_message": "system"}


def _norm_role(role: str) -> str:
    """Normalize framework-specific role spellings (LangChain's message "type" field uses
    human/ai/system, never role/user/assistant) to the standard chat-API roles a real provider
    call expects — otherwise a re-run would send an invalid role and the provider would reject it."""
    return _ROLE_ALIASES.get(role.lower(), role)


def _content_text(content) -> str:
    """Flatten a message's content to plain text: a string as-is, or a list of multimodal
    content blocks (OpenAI/Anthropic-style {"type":"text","text":...} + non-text blocks) joined
    by their text parts — so a re-run sends clean text, not a Python repr of the block list."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [c if isinstance(c, str) else (c.get("text") or "") for c in content if isinstance(c, (str, dict))]
        return " ".join(p for p in parts if p)
    return str(content) if content else ""


def _messages(span_request: dict) -> list[dict]:
    """Best-effort extraction of chat messages from a captured LLM span's request. Handles a
    bare array, a {"messages": [...]} wrapper (the shape OpenInference's `input.value` and
    current gen_ai.input.messages both use), and — for completions-style or unrecognized
    payloads (e.g. legacy {"prompt": "..."} calls) — falls back to prompt/input/text or the raw
    JSON as a single user message, so content is never silently dropped."""
    raw = (span_request or {}).get("input")
    if isinstance(raw, list):
        data = raw
    elif isinstance(raw, str):
        s = raw.strip()
        if not s:
            return [{"role": "user", "content": ""}]
        if s.startswith("[") or s.startswith("{"):
            try:
                data = json.loads(s)
            except ValueError:
                return [{"role": "user", "content": raw}]
        else:
            return [{"role": "user", "content": raw}]
    else:
        return [{"role": "user", "content": ""}]

    if isinstance(data, list):
        arr = data
    elif isinstance(data, dict):
        arr = data.get("messages")
        if not isinstance(arr, list):
            for key in ("prompt", "input", "text"):
                if isinstance(data.get(key), str) and data[key]:
                    return [{"role": "user", "content": data[key]}]
            return [{"role": "user", "content": json.dumps(data)}]
    else:
        arr = None

    out = []
    for m in arr or []:
        if not isinstance(m, dict):
            continue
        # LangChain's own message serialization (HumanMessage.model_dump(), etc.) carries a
        # "type" field ("human"/"ai"/"system"), never "role" — a real shape for any trace whose
        # input.value came from the OpenInference LangChain instrumentor, not just an edge case.
        role = m.get("role") or m.get("type") or m.get("name")
        if role:
            out.append({"role": _norm_role(str(role)), "content": _content_text(m.get("content", ""))})
    return out or [{"role": "user", "content": ""}]


def _text_of(span_result: dict) -> str:
    r = span_result or {}
    return r.get("text") or (r.get("output") if isinstance(r.get("output"), str) else "") or ""


def _apply(subs: dict[str, str], text: str) -> tuple[str, bool]:
    """Apply accumulated old→new substitutions to a piece of text; report whether it changed."""
    changed = False
    for old, new in subs.items():
        if old and old in text:
            text = text.replace(old, new)
            changed = True
    return text, changed


async def reconstruct(db: Session, ws: Workspace, origin_trace_id: str, fork_span_id: str,
                      model: str, messages: list[dict], params: dict,
                      *, provider: str, api_key: str, base_url: str) -> dict:
    """Run a reconstructed replay. `messages`/`model`/`params` are the EDITED fork inputs.
    Returns {new_trace_id, replay_run_id, fork_output, spans:[…]}."""
    spans = (db.query(Run).filter(Run.workspace_id == ws.id, Run.trace_id == origin_trace_id)
             .order_by(Run.id.asc()).all())
    if not spans:
        raise ValueError("origin trace not found")
    order = {s.span_id: i for i, s in enumerate(spans)}
    if fork_span_id not in order:
        raise ValueError("fork span not in trace")
    fork_i = order[fork_span_id]

    new_tid = secrets.token_hex(16)
    id_map: dict[str, str] = {}
    subs: dict[str, str] = {}          # old output text → new output text, threaded forward
    new_rows: list[Run] = []
    fork_output = ""

    for i, s in enumerate(spans):
        new_sid = secrets.token_hex(8)
        id_map[s.span_id] = new_sid
        new_parent = id_map.get(s.parent_span_id, "") if s.parent_span_id else ""
        req = dict(s.request or {})
        res = dict(s.result or {})
        meta = dict(res.get("meta") or {})
        state = "unchanged"
        dur = s.duration_ms

        if i < fork_i:
            state = "unchanged"
        elif s.span_id == fork_span_id:
            r = await complete(provider, model, messages, params, api_key=api_key, base_url=base_url)
            limits.record_spend(ws.id, pricing.estimate(model, r["usage"].get("input_tokens"),
                                                        r["usage"].get("output_tokens")))
            old_out = _text_of(res)
            fork_output = r["output"]
            if old_out and old_out != fork_output:
                subs[old_out] = fork_output
            req = {**req, "model": model, "input": json.dumps(messages)}
            res = {"text": fork_output, "meta": {**meta, "usage": r["usage"], "model": model,
                                                 "params": params}}
            state = "live"
        elif s.type == "llm" and subs:
            msgs = _messages(req)
            new_msgs, any_changed = [], False
            for m in msgs:
                c, ch = _apply(subs, m["content"])
                any_changed = any_changed or ch
                new_msgs.append({"role": m["role"], "content": c})
            if any_changed:
                dmodel = req.get("model") or model
                r = await complete(provider, dmodel, new_msgs, params,
                                   api_key=api_key, base_url=base_url)
                limits.record_spend(ws.id, pricing.estimate(dmodel, r["usage"].get("input_tokens"),
                                                            r["usage"].get("output_tokens")))
                old_out = _text_of(res)
                if old_out and old_out != r["output"]:
                    subs[old_out] = r["output"]
                req = {**req, "input": json.dumps(new_msgs)}
                res = {"text": r["output"], "meta": {**meta, "usage": r["usage"]}}
                state = "live"
            else:
                state = "recorded"
        else:
            # tool/step (or an llm with no upstream change): replay recorded output; flag if its
            # input referenced something that changed downstream of the fork.
            inp = json.dumps(req.get("input") or "")
            _, ref_changed = _apply(subs, inp)
            state = "diverged" if ref_changed else "recorded"

        meta_out = dict(res.get("meta") or {})
        meta_out["replay_of"] = origin_trace_id
        meta_out["replay_state"] = state
        res["meta"] = meta_out
        new_rows.append(Run(
            workspace_id=ws.id, type=s.type, label=s.label, duration_ms=dur, status=s.status,
            trace_id=new_tid, span_id=new_sid, parent_span_id=new_parent,
            request=req, result=res, error=s.error, session_id=s.session_id))

    db.add_all(new_rows)
    rr = ReplayRun(workspace_id=ws.id, origin_trace_id=origin_trace_id, fork_span_id=fork_span_id,
                   overrides={"model": model, "params": params}, mode="reconstructed",
                   new_trace_id=new_tid, status="completed")
    db.add(rr)
    db.commit(); db.refresh(rr)

    live = sum(1 for r in new_rows if (r.result.get("meta") or {}).get("replay_state") == "live")
    return {"new_trace_id": new_tid, "replay_run_id": rr.id, "fork_output": fork_output,
            "live_count": live, "span_count": len(new_rows), "mode": "reconstructed"}


async def webhook(db: Session, ws: Workspace, origin_trace_id: str, fork_span_id: str,
                  overrides: dict) -> dict:
    """Exact replay: POST the fork override to the project's replay_url; the customer re-runs
    their real agent and returns OTLP, which we ingest as a new branch. SSRF-guarded."""
    if not ws.replay_url:
        raise ValueError("no replay webhook configured for this project (Settings → Replay webhook)")
    guard_url(ws.replay_url)   # block internal/metadata addresses in hosted mode
    payload = {"origin_trace_id": origin_trace_id, "fork_span_id": fork_span_id, "overrides": overrides}
    try:
        async with httpx.AsyncClient(timeout=90.0) as c:
            r = await c.post(ws.replay_url, json=payload)
    except httpx.HTTPError as e:
        raise LLMError(f"replay webhook error: {e}") from e
    if r.status_code >= 400:
        raise LLMError(f"replay webhook returned {r.status_code}")
    try:
        rows = otel.ingest(r.json())
    except Exception as e:
        raise LLMError(f"replay webhook returned invalid OTLP: {e}") from e
    if not rows:
        raise ValueError("replay webhook returned no spans")

    new_tid = rows[0].get("trace_id") or secrets.token_hex(16)
    new_rows = []
    for kw in rows:
        kw = dict(kw)
        kw["trace_id"] = kw.get("trace_id") or new_tid
        res = dict(kw.get("result") or {})
        meta = dict(res.get("meta") or {})
        meta["replay_of"] = origin_trace_id
        meta["replay_state"] = "live"      # the whole branch is a real, live re-execution
        res["meta"] = meta
        kw["result"] = res
        new_rows.append(Run(workspace_id=ws.id, **kw))
    db.add_all(new_rows)
    rr = ReplayRun(workspace_id=ws.id, origin_trace_id=origin_trace_id, fork_span_id=fork_span_id,
                   overrides=overrides, mode="webhook", new_trace_id=new_tid, status="completed")
    db.add(rr)
    db.commit(); db.refresh(rr)
    return {"new_trace_id": new_tid, "replay_run_id": rr.id, "fork_output": "",
            "live_count": len(new_rows), "span_count": len(new_rows), "mode": "webhook"}
