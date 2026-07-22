"""Interactive debugging: re-run a captured LLM call with edited prompt/params (the playground),
and manage the per-project provider connections (BYO keys, sealed at rest) it uses.

The trace replay harness (POST /api/replay) is added in a later milestone and reuses the same
connections + llm_client here.
"""
import json
import secrets
import time
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import (
    DatasetItem, Experiment, ExperimentResult, Prompt, ProviderConnection, ReplayRun, Run,
    Workspace, _now, iso_utc,
)
from ..scorers import run_scorers
from ..services import errors, limits, pricing, share
from ..services.llm_client import LLMError, approx_usage, complete, judge, stream_complete
# The multi-span walk below deliberately reuses the single-fork path's helpers rather than
# copying them: `_messages`/`_text_of`/`_apply` are how ProveKit decides that a span's input
# changed, and two implementations of that would drift into two different verdicts about
# whether a replay is trustworthy.
from ..services.replay import _apply, _messages, _text_of, reconstruct
from ..services.replay import webhook as replay_webhook
from ..services.sealing import mask_key, seal, unseal
from ..services.workspace import current_workspace
from .experiments import _experiment_row
# The redacted share below must serve exactly the rows the authenticated read serves, minus the
# withheld fields. Rebuilding the row shape here would let the two drift, and a shared view that
# quietly omits a column is indistinguishable from one that masked it.
from .traces import _span_rows, _trace_spans

router = APIRouter(prefix="/api", tags=["playground"])

_PROVIDERS = {"openai", "anthropic", "openai_compatible", "mock"}
_MAX_TOKENS_CAP = 4096   # hard ceiling per run so an edit can't run up a huge bill


# ---- provider connections (BYO keys) ----
class _ConnIn(BaseModel):
    provider: str
    label: str = ""
    key: str = ""
    base_url: str = ""


def _conn_row(c: ProviderConnection) -> dict:
    return {"id": c.id, "provider": c.provider, "label": c.label, "key_hint": c.key_hint,
            "base_url": c.base_url, "last_used_at": iso_utc(c.last_used_at),
            "created_at": iso_utc(c.created_at)}


@router.get("/connections")
def list_connections(db: Session = Depends(get_db), ws: Workspace = Depends(current_workspace)):
    rows = (db.query(ProviderConnection).filter(ProviderConnection.workspace_id == ws.id)
            .order_by(ProviderConnection.id.desc()).all())
    return [_conn_row(c) for c in rows]


@router.post("/connections")
def create_connection(data: _ConnIn, db: Session = Depends(get_db),
                      ws: Workspace = Depends(current_workspace)):
    provider = data.provider.lower()
    if provider not in _PROVIDERS:
        raise HTTPException(422, errors.bad_provider(provider, _PROVIDERS))
    if provider != "mock" and not data.key.strip():
        raise HTTPException(422, errors.provider_key_required(provider))
    if provider == "openai_compatible" and not data.base_url.strip():
        raise HTTPException(422, errors.BASE_URL_REQUIRED)
    key = data.key.strip()
    c = ProviderConnection(
        workspace_id=ws.id, provider=provider,
        label=(data.label or provider)[:120],
        key_sealed=seal(key) if key else "",
        key_hint=mask_key(key) if key else "",
        base_url=data.base_url.strip()[:300])
    db.add(c); db.commit(); db.refresh(c)
    return _conn_row(c)


@router.delete("/connections/{cid}")
def delete_connection(cid: int, db: Session = Depends(get_db),
                      ws: Workspace = Depends(current_workspace)):
    c = db.get(ProviderConnection, cid)
    if not c or c.workspace_id != ws.id:
        raise HTTPException(404, errors.not_in_project("model connection", "GET /api/connections"))
    db.delete(c); db.commit()
    return {"ok": True}


# ---- the playground: re-run one LLM call ----
class _Msg(BaseModel):
    role: str
    content: str


class _RunIn(BaseModel):
    model: str
    messages: list[_Msg]
    params: dict = {}
    connection_id: int | None = None
    provider: str | None = None      # allows provider="mock" with no stored connection
    from_span_id: str | None = None  # provenance: which captured span this re-runs


def _resolve(db: Session, ws: Workspace, data: _RunIn) -> tuple[str, str, str]:
    """Return (provider, api_key, base_url) for the run, from a stored connection or a keyless
    mock. Marks the connection used."""
    if data.connection_id is not None:
        c = db.get(ProviderConnection, data.connection_id)
        if not c or c.workspace_id != ws.id:
            raise HTTPException(404, errors.not_in_project("model connection", "GET /api/connections"))
        c.last_used_at = _now(); db.commit()
        key = unseal(c.key_sealed) if c.key_sealed else ""
        return c.provider, key, c.base_url
    if (data.provider or "").lower() == "mock":
        return "mock", "", ""
    raise HTTPException(422, errors.NO_MODEL_CHOSEN)


def _admit(db: Session, ws: Workspace, data: _RunIn) -> tuple[str, str, str, list[dict], dict]:
    """Everything that must happen *before* a re-run is allowed to call a provider: rate limit,
    spend cap, validation, the max_tokens ceiling, and connection resolution.

    Shared by both run endpoints on purpose — on the streamed path these have to run while a
    real status code can still be returned, i.e. before the first byte of the response body.
    """
    limits.check_playground_rate(ws.id)
    limits.check_spend_cap(ws.id)
    if not data.messages:
        raise HTTPException(422, errors.NO_MESSAGES)
    params = dict(data.params or {})
    if params.get("max_tokens"):
        params["max_tokens"] = min(int(params["max_tokens"]), _MAX_TOKENS_CAP)
    provider, api_key, base_url = _resolve(db, ws, data)
    return provider, api_key, base_url, [{"role": m.role, "content": m.content} for m in data.messages], params


@router.post("/playground/run")
async def playground_run(data: _RunIn, db: Session = Depends(get_db),
                         ws: Workspace = Depends(current_workspace)):
    provider, api_key, base_url, messages, params = _admit(db, ws, data)
    t0 = time.monotonic()
    try:
        result = await complete(provider, data.model, messages, params,
                                api_key=api_key, base_url=base_url)
    except LLMError as e:
        raise HTTPException(502, errors.provider_failed(str(e)))
    result["latency_ms"] = round((time.monotonic() - t0) * 1000)
    result["provider"] = provider
    result["model"] = data.model
    limits.record_spend(ws.id, pricing.estimate(data.model, result["usage"].get("input_tokens"),
                                                result["usage"].get("output_tokens")))
    return result


# ---- the same re-run, streamed (SSE) so tokens appear as they arrive ----
def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


async def _run_events(ws_id: int, model: str, provider: str, messages: list[dict], params: dict,
                      api_key: str, base_url: str) -> AsyncIterator[str]:
    """Relay provider chunks as SSE frames, then bill for the run.

    A failure here can only be reported as an event, never as a status: by the time the first
    token has been written the response is already committed as a 200. So a provider error is
    emitted as an explicit `error` frame — simply dropping the connection would render as a
    complete-looking short answer, which is a wrong result disguised as a right one. The client
    treats a stream that ends with neither `done` nor `error` the same way.

    Spend is recorded on both exits. Tokens the provider generated before it failed are tokens
    it will still charge for, so an interrupted stream must not be a free way past the cap.
    """
    t0 = time.monotonic()
    parts: list[str] = []
    try:
        async for ev in stream_complete(provider, model, messages, params,
                                        api_key=api_key, base_url=base_url):
            if ev.get("type") == "delta":
                parts.append(ev.get("text") or "")
                yield _sse(ev)
                continue
            usage = ev.get("usage") or {}
            limits.record_spend(ws_id, pricing.estimate(model, usage.get("input_tokens"),
                                                        usage.get("output_tokens")))
            yield _sse({**ev, "latency_ms": round((time.monotonic() - t0) * 1000),
                        "provider": provider, "model": model})
    except LLMError as e:
        if parts:
            u = approx_usage(messages, "".join(parts))
            limits.record_spend(ws_id, pricing.estimate(model, u["input_tokens"], u["output_tokens"]))
        yield _sse({"type": "error", "error": str(e)})


@router.post("/playground/run/stream")
async def playground_run_stream(data: _RunIn, db: Session = Depends(get_db),
                                ws: Workspace = Depends(current_workspace)):
    """Server-sent events for one re-run: `delta` frames, then `done` (same body as
    /playground/run) or `error`. Limits and validation still answer with a real status code —
    they run before the response starts."""
    provider, api_key, base_url, messages, params = _admit(db, ws, data)
    return StreamingResponse(
        _run_events(ws.id, data.model, provider, messages, params, api_key, base_url),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive",
                 # nginx and friends buffer by default, which would collapse the stream into
                 # one delayed blob and undo the point of it.
                 "X-Accel-Buffering": "no"},
    )


# ---- the replay harness: fork a trace at a span, re-run the flow with the edit ----
class _ReplayIn(BaseModel):
    origin_trace_id: str
    fork_span_id: str
    model: str
    messages: list[_Msg]
    params: dict = {}
    connection_id: int | None = None
    provider: str | None = None
    mode: str = "reconstructed"      # reconstructed | webhook


@router.post("/replay")
async def replay(data: _ReplayIn, db: Session = Depends(get_db),
                 ws: Workspace = Depends(current_workspace)):
    limits.check_playground_rate(ws.id)
    limits.check_spend_cap(ws.id)
    if not data.messages:
        raise HTTPException(422, errors.NO_MESSAGES)
    params = dict(data.params or {})
    if params.get("max_tokens"):
        params["max_tokens"] = min(int(params["max_tokens"]), _MAX_TOKENS_CAP)
    messages = [{"role": m.role, "content": m.content} for m in data.messages]
    try:
        if data.mode == "webhook":
            return await replay_webhook(db, ws, data.origin_trace_id, data.fork_span_id,
                                        {"model": data.model, "messages": messages, "params": params})
        provider, api_key, base_url = _resolve(db, ws, _RunIn(
            model=data.model, messages=data.messages, params=params,
            connection_id=data.connection_id, provider=data.provider))
        return await reconstruct(db, ws, data.origin_trace_id, data.fork_span_id,
                                 data.model, messages, params,
                                 provider=provider, api_key=api_key, base_url=base_url)
    except LLMError as e:
        raise HTTPException(502, errors.provider_failed(str(e)))
    except ValueError as e:
        raise HTTPException(404, errors.replay_target_missing(str(e)))


# ---- multi-span replay: several edits, ONE re-run (#57), including tool arguments (#63) ----
#
# Two edits are not two replays. The second edited span usually sits downstream of the first, so
# two separate re-runs produce two branches whose results cannot be combined afterwards — the
# combination only exists inside a single walk that carries both changes at once. Hence one
# request, one branch, one fidelity report.
_MAX_EDITS = 8   # bound the live provider calls a single request can make


class _EditIn(BaseModel):
    """One edit inside a multi-span replay.

    kind="llm"  — messages/model/params replace the captured request and the span is re-run live.
    kind="tool" — `arguments` replace the captured tool input. Nothing is executed: ProveKit does
                  not own the tool. Identical arguments serve the recorded response; changed
                  arguments make that response evidence of nothing (see _multi_reconstruct).
    """
    span_id: str
    kind: str = "llm"
    model: str = ""
    messages: list[_Msg] = []
    params: dict = {}
    arguments: str | dict | list | None = None


class _MultiReplayIn(BaseModel):
    origin_trace_id: str
    edits: list[_EditIn]
    connection_id: int | None = None
    provider: str | None = None


def _args_text(value) -> str:
    """The tool arguments as they will be stored on the replayed span's request.input, which is
    a string for every captured tool span."""
    if value is None:
        return ""
    return value if isinstance(value, str) else json.dumps(value, sort_keys=True)


def _args_equal(recorded, edited) -> bool:
    """Do these two payloads describe the SAME tool call?

    Compared as parsed JSON when both sides are JSON, so re-serialising a payload the user never
    touched — different key order, different whitespace, which is exactly what a round trip
    through a browser textarea produces — is not mistaken for a change. Getting this wrong in the
    permissive direction would hide a real edit; getting it wrong in the strict direction would
    badge an untouched tool 'diverged' and taint the whole run for nothing. Neither is acceptable,
    so the comparison is on meaning, not on bytes.
    """
    def norm(v):
        if isinstance(v, str):
            s = v.strip()
            if s.startswith(("{", "[")):
                try:
                    return json.loads(s)
                except ValueError:
                    return s
            return s
        return v
    return norm(recorded) == norm(edited)


async def _multi_reconstruct(db: Session, ws: Workspace, origin_trace_id: str,
                             edits: dict[str, _EditIn], *, provider: str, api_key: str,
                             base_url: str) -> dict:
    """Rebuild a trace branch with every edit applied in one pass.

    Same accounting as services/replay.py::reconstruct, extended to N simultaneous edits, which
    means N taint sources instead of one:

      * `subs`    — old output → new output, threaded forward out of every LIVE re-run;
      * `tainted` — recorded outputs we can no longer stand behind. Unlike `subs` there is no
        replacement value: a tool whose arguments changed would not have returned its recorded
        result, and ProveKit cannot run the tool to find out what it *would* have returned. So
        the recorded value is kept, badged, and everything derived from it is badged too.

    An edited LLM span is re-run live even when it sits downstream of a taint — the user typed
    its input, so it is theirs to assert. But if the text they submitted still *contains* an
    invalidated value (the common case: the portal seeds the editor from the recording), the new
    output is a confident answer built on fiction. It is produced, badged
    `meta.replay_input_tainted`, counted against reliability, and its recorded output is tainted
    so the badge cascades — the alternative, presenting it as a clean live re-run, is the exact
    failure this whole feature exists to expose.
    """
    spans = (db.query(Run).filter(Run.workspace_id == ws.id, Run.trace_id == origin_trace_id)
             .order_by(Run.id.asc()).all())
    if not spans:
        raise ValueError("origin trace not found")
    order = {s.span_id: i for i, s in enumerate(spans)}
    missing = [sid for sid in edits if sid not in order]
    if missing:
        raise ValueError(f"edited span(s) not in trace: {', '.join(sorted(missing))}")
    first_i = min(order[sid] for sid in edits)

    # The params/model a *threaded* downstream re-run inherits. reconstruct uses the fork's; with
    # several forks the earliest LLM edit is the closest analogue — it is the change the rest of
    # the flow is being re-derived from.
    lead = next((edits[s.span_id] for s in spans
                 if s.span_id in edits and edits[s.span_id].kind != "tool"), None)
    lead_params = dict(lead.params or {}) if lead else {}
    lead_model = (lead.model if lead else "") or ""

    new_tid = secrets.token_hex(16)
    id_map: dict[str, str] = {}
    subs: dict[str, str] = {}
    tainted: set[str] = set()
    diverged_ids: set[str] = set()
    tainted_inputs: set[str] = set()     # live re-runs whose submitted input carried fiction
    new_rows: list[Run] = []
    outputs: dict[str, str] = {}         # edited span id → the text this replay produced for it

    def _tainted_ref(text: str) -> bool:
        return any(t and t in text for t in tainted)

    async def _live(model: str, messages: list[dict], params: dict) -> dict:
        """One billable call. The cap is re-checked before every call, not just at admission: a
        multi-edit replay makes N calls from one request, so checking once would let a single
        request walk straight past the ceiling it is supposed to enforce."""
        limits.check_spend_cap(ws.id)
        r = await complete(provider, model, messages, params, api_key=api_key, base_url=base_url)
        limits.record_spend(ws.id, pricing.estimate(model, r["usage"].get("input_tokens"),
                                                    r["usage"].get("output_tokens")))
        return r

    for i, s in enumerate(spans):
        new_sid = secrets.token_hex(8)
        id_map[s.span_id] = new_sid
        new_parent = id_map.get(s.parent_span_id, "") if s.parent_span_id else ""
        req = dict(s.request or {})
        res = dict(s.result or {})
        meta = dict(res.get("meta") or {})
        edit = edits.get(s.span_id)
        state = "unchanged"
        input_tainted = False

        if edit is not None and edit.kind == "tool":
            # #63: the portal can edit a tool's arguments but can never produce a tool's answer.
            new_args = _args_text(edit.arguments)
            same = _args_equal(req.get("input") or "", new_args)
            req = {**req, "input": new_args}
            out = _text_of(res)
            if same:
                # A cassette hit. The tool is a function of its arguments, so pinning them to the
                # recorded ones makes the recorded answer valid evidence again — which is also
                # how a user deliberately stops a taint cascade from an upstream edit.
                state = "recorded"
            else:
                state = "diverged"
                diverged_ids.add(s.span_id)
                if out:
                    tainted.add(out)
        elif edit is not None:
            msgs = [{"role": m.role, "content": m.content} for m in edit.messages]
            input_tainted = any(_tainted_ref(m["content"]) for m in msgs)
            model = edit.model or req.get("model") or lead_model
            params = dict(edit.params or {})
            r = await _live(model, msgs, params)
            old_out, new_out = _text_of(res), r["output"]
            outputs[s.span_id] = new_out
            if old_out and old_out != new_out:
                subs[old_out] = new_out
            if input_tainted:
                tainted_inputs.add(s.span_id)
                if old_out:
                    # Downstream spans reference the OLD text, so that is what has to carry the
                    # badge forward — the new output is derived from an invalidated input.
                    tainted.add(old_out)
            req = {**req, "model": model, "input": json.dumps(msgs)}
            res = {"text": new_out, "meta": {**meta, "usage": r["usage"], "model": model,
                                             "params": params}}
            state = "live"
        elif i < first_i:
            state = "unchanged"
        elif s.parent_span_id in diverged_ids or _tainted_ref(json.dumps(req.get("input") or "")):
            state = "diverged"
            diverged_ids.add(s.span_id)
            out = _text_of(res)
            if out:
                tainted.add(out)
        elif s.type == "llm" and subs:
            new_msgs, any_changed = [], False
            for m in _messages(req):
                c, ch = _apply(subs, m["content"])
                any_changed = any_changed or ch
                new_msgs.append({"role": m["role"], "content": c})
            if any_changed:
                dmodel = req.get("model") or lead_model
                r = await _live(dmodel, new_msgs, lead_params)
                old_out = _text_of(res)
                if old_out and old_out != r["output"]:
                    subs[old_out] = r["output"]
                req = {**req, "input": json.dumps(new_msgs)}
                res = {"text": r["output"], "meta": {**meta, "usage": r["usage"]}}
                state = "live"
            else:
                state = "recorded"
        else:
            _, ref_changed = _apply(subs, json.dumps(req.get("input") or ""))
            state = "diverged" if ref_changed else "recorded"
            if ref_changed:
                diverged_ids.add(s.span_id)
                out = _text_of(res)
                if out:
                    tainted.add(out)

        meta_out = dict(res.get("meta") or {})
        meta_out["replay_of"] = origin_trace_id
        meta_out["replay_state"] = state
        if s.span_id in edits:
            meta_out["replay_edited"] = True
        if input_tainted:
            meta_out["replay_input_tainted"] = True
        res["meta"] = meta_out
        new_rows.append(Run(
            workspace_id=ws.id, type=s.type, label=s.label, duration_ms=s.duration_ms,
            status=s.status, trace_id=new_tid, span_id=new_sid, parent_span_id=new_parent,
            request=req, result=res, error=s.error, session_id=s.session_id))

    db.add_all(new_rows)
    rr = ReplayRun(
        workspace_id=ws.id, origin_trace_id=origin_trace_id,
        # One column, several forks: the earliest edited span is the branch point; the full set
        # lives in `overrides`, which is JSON and needs no schema change.
        fork_span_id=spans[first_i].span_id,
        overrides={"multi": True, "edits": [
            {"span_id": e.span_id, "kind": e.kind, "model": e.model, "params": e.params,
             "arguments": _args_text(e.arguments) if e.kind == "tool" else None}
            for e in edits.values()]},
        mode="reconstructed", new_trace_id=new_tid, status="completed")
    db.add(rr)
    db.commit(); db.refresh(rr)

    def _count(state: str) -> int:
        return sum(1 for r in new_rows if (r.result.get("meta") or {}).get("replay_state") == state)

    live, diverged = _count("live"), _count("diverged")
    reasons = []
    if diverged:
        reasons.append(
            f"{diverged} span(s) diverged: their inputs changed, so their recorded outputs — and "
            "anything downstream of them — are not what this run would actually have produced. "
            "ProveKit can't re-run your tools; use webhook replay for an exact re-run.")
    if tainted_inputs:
        reasons.append(
            f"{len(tainted_inputs)} edited span(s) were re-run on text an earlier edit had "
            "already invalidated, so their new output rests on a value this run cannot stand "
            "behind.")
    return {"new_trace_id": new_tid, "replay_run_id": rr.id,
            "outputs": outputs, "fork_output": next(iter(outputs.values()), ""),
            "fidelity": {"live": live, "diverged": diverged, "recorded": _count("recorded"),
                         "unchanged": _count("unchanged")},
            # A branch with any diverged span, or any edit re-run on invalidated text, is a
            # hypothesis about the run — never a reproduction of it.
            "reliable": not diverged and not tainted_inputs,
            "fidelity_warning": " ".join(reasons),
            "tainted_input_spans": sorted(tainted_inputs),
            "live_count": live, "span_count": len(new_rows), "edit_count": len(edits),
            "mode": "reconstructed-multi"}


def _validate_edits(data: _MultiReplayIn) -> dict[str, _EditIn]:
    out: dict[str, _EditIn] = {}
    if not data.edits:
        raise HTTPException(422, errors.NO_EDITS)
    if len(data.edits) > _MAX_EDITS:
        raise HTTPException(422, errors.too_many_edits(len(data.edits), _MAX_EDITS))
    for e in data.edits:
        if not e.span_id:
            raise HTTPException(422, errors.EDIT_NEEDS_SPAN_ID)
        if e.span_id in out:
            # Two edits of one span have no defined order and would silently drop one of them.
            raise HTTPException(422, errors.duplicate_edit(e.span_id))
        if e.kind not in ("llm", "tool"):
            raise HTTPException(422, errors.bad_edit_kind(e.kind))
        if e.kind == "llm" and not e.messages:
            raise HTTPException(422, errors.span_no_messages(e.span_id))
        if e.kind == "tool" and e.arguments is None:
            raise HTTPException(422, errors.tool_edit_needs_arguments(e.span_id))
        if e.kind == "llm" and e.params.get("max_tokens"):
            e.params = {**e.params, "max_tokens": min(int(e.params["max_tokens"]), _MAX_TOKENS_CAP)}
        out[e.span_id] = e
    return out


@router.post("/replay/multi")
async def replay_multi(data: _MultiReplayIn, db: Session = Depends(get_db),
                       ws: Workspace = Depends(current_workspace)):
    """Fork a trace at SEVERAL spans at once and re-run it once.

    Editing the planner and the summariser used to be two replays whose results could not be
    combined; this is the combined run, with one honest fidelity report over both changes. Tool
    spans can be edited too — their arguments only, because ProveKit cannot execute a tool.
    """
    # One re-run per edit against the burst limit: this endpoint makes as many live calls as it
    # has LLM edits, so charging it as a single run would make it the cheap way past the ceiling.
    edits = _validate_edits(data)
    for _ in range(sum(1 for e in edits.values() if e.kind == "llm") or 1):
        limits.check_playground_rate(ws.id)
    limits.check_spend_cap(ws.id)
    lead = next((e for e in edits.values() if e.kind == "llm"), None)
    if lead is not None:
        provider, api_key, base_url = _resolve(db, ws, _RunIn(
            model=lead.model, messages=lead.messages,
            connection_id=data.connection_id, provider=data.provider))
    else:
        # Tool-only edits never call a provider — `subs` (the only thing that triggers a threaded
        # live re-run) is fed exclusively by LLM edits — so demanding a connection would refuse a
        # replay that costs nothing. An empty provider fails loudly if that ever stops holding,
        # rather than quietly serving mock text as if it were a real re-run.
        provider, api_key, base_url = "", "", ""
    try:
        return await _multi_reconstruct(db, ws, data.origin_trace_id, edits,
                                        provider=provider, api_key=api_key, base_url=base_url)
    except LLMError as e:
        raise HTTPException(502, errors.provider_failed(str(e)))
    except ValueError as e:
        raise HTTPException(404, errors.replay_target_missing(str(e)))


# ---- saved prompt versions ----
class _PromptIn(BaseModel):
    name: str
    model: str = ""
    messages: list[_Msg] = []
    params: dict = {}


def _prompt_row(p: Prompt) -> dict:
    return {"id": p.id, "name": p.name, "version": p.version, "model": p.model,
            "messages": p.messages, "params": p.params, "created_at": iso_utc(p.created_at)}


@router.get("/prompts")
def list_prompts(db: Session = Depends(get_db), ws: Workspace = Depends(current_workspace)):
    rows = (db.query(Prompt).filter(Prompt.workspace_id == ws.id)
            .order_by(Prompt.id.desc()).all())
    return [_prompt_row(p) for p in rows]


@router.post("/prompts")
def save_prompt(data: _PromptIn, db: Session = Depends(get_db),
                ws: Workspace = Depends(current_workspace)):
    if not data.name.strip():
        raise HTTPException(422, errors.PROMPT_NAME_REQUIRED)
    # auto-increment the version for this name within the project
    prev = (db.query(Prompt).filter(Prompt.workspace_id == ws.id, Prompt.name == data.name.strip())
            .order_by(Prompt.version.desc()).first())
    p = Prompt(workspace_id=ws.id, name=data.name.strip()[:160], version=(prev.version + 1 if prev else 1),
               model=data.model, messages=[m.model_dump() for m in data.messages], params=data.params)
    db.add(p); db.commit(); db.refresh(p)
    return _prompt_row(p)


@router.delete("/prompts/{pid}")
def delete_prompt(pid: int, db: Session = Depends(get_db),
                  ws: Workspace = Depends(current_workspace)):
    p = db.get(Prompt, pid)
    if not p or p.workspace_id != ws.id:
        raise HTTPException(404, errors.not_in_project("saved prompt", "GET /api/prompts"))
    db.delete(p); db.commit()
    return {"ok": True}


# ---- run an edited prompt over a dataset → a scored experiment ----
class _ExpIn(BaseModel):
    dataset_id: int
    name: str = ""
    model: str
    messages: list[_Msg]
    params: dict = {}
    connection_id: int | None = None
    provider: str | None = None
    scorers: list[str] = ["exact_match", "contains"]


_EXP_ITEM_CAP = 100   # bound cost: score at most N items per run


def _fill(messages: list[dict], item_input: str, item_expected: str) -> list[dict]:
    """Substitute {{input}} / {{expected}} in the prompt for a dataset item. If the prompt
    references NEITHER placeholder (a plain, non-templated prompt), append the item input as a
    trailing user message so it still runs against real data. A prompt that references only
    {{expected}} (e.g. a grading-style template) is left as-is — it doesn't need item_input
    appended too, which would otherwise silently add an unrequested extra message."""
    out, referenced = [], False
    for m in messages:
        c = m["content"]
        if "{{input}}" in c or "{{expected}}" in c:
            referenced = True
        c = c.replace("{{input}}", item_input).replace("{{expected}}", item_expected)
        out.append({"role": m["role"], "content": c})
    if not referenced:
        out.append({"role": "user", "content": item_input})
    return out


@router.post("/playground/experiment")
async def playground_experiment(data: _ExpIn, db: Session = Depends(get_db),
                                ws: Workspace = Depends(current_workspace)):
    limits.check_playground_rate(ws.id)
    limits.check_spend_cap(ws.id)
    items = (db.query(DatasetItem)
             .filter(DatasetItem.workspace_id == ws.id, DatasetItem.dataset_id == data.dataset_id)
             .order_by(DatasetItem.id.asc()).limit(_EXP_ITEM_CAP).all())
    if not items:
        raise HTTPException(404, errors.dataset_unusable(data.dataset_id))
    params = dict(data.params or {})
    if params.get("max_tokens"):
        params["max_tokens"] = min(int(params["max_tokens"]), _MAX_TOKENS_CAP)
    provider, api_key, base_url = _resolve(db, ws, _RunIn(
        model=data.model, messages=data.messages, params=params,
        connection_id=data.connection_id, provider=data.provider))
    base_msgs = [{"role": m.role, "content": m.content} for m in data.messages]

    exp = Experiment(workspace_id=ws.id, name=(data.name or f"Playground · {data.model}")[:160],
                     dataset_id=data.dataset_id)
    db.add(exp); db.commit(); db.refresh(exp)
    try:
        want_judge = "llm_judge" in data.scorers
        sync_scorers = [s for s in data.scorers if s != "llm_judge"]
        for it in items:
            msgs = _fill(base_msgs, it.input, it.expected)
            r = await complete(provider, data.model, msgs, params, api_key=api_key, base_url=base_url)
            limits.record_spend(ws.id, pricing.estimate(data.model, r["usage"].get("input_tokens"),
                                                        r["usage"].get("output_tokens")))
            scores = run_scorers(sync_scorers, r["output"], it.expected)
            if want_judge:
                scores["llm_judge"] = await judge(provider, data.model, it.input, it.expected,
                                                  r["output"], api_key=api_key, base_url=base_url)
            db.add(ExperimentResult(workspace_id=ws.id, experiment_id=exp.id, item_id=it.id,
                                    input=it.input, output=r["output"], expected=it.expected, scores=scores))
        db.commit()
    except LLMError as e:
        db.commit()   # keep whatever scored before the failure
        raise HTTPException(502, errors.provider_failed(str(e)))
    return _experiment_row(db, exp)


# ---- sharing a trace outside the company: redacted links (#70) + issue handoff (#69) ----
#
# `POST /api/traces/{id}/share` (routers/traces.py) mints a link to the WHOLE payload. These
# three routes are the redacted path: the caller says what to withhold, the choice is signed
# into the token, and the public read below strips those fields server-side — the response body
# a recipient can open in devtools never contains them.


class _RedactedShareIn(BaseModel):
    ttl_days: int = share.DEFAULT_TTL_DAYS
    withhold: list[str] = []         # any of share.MASKABLE_FIELDS
    spans: list[str] = []            # span ids to mask; empty = the whole trace


class _IssueLinkIn(_RedactedShareIn):
    tracker: str = "github"
    repo: str = ""                   # owner/name or a full project URL
    template: str = ""               # any other tracker, via {title}/{body} placeholders


def _mask_of(data: _RedactedShareIn) -> share.ShareMask:
    try:
        return share.normalize_mask(data.withhold, data.spans)
    except ValueError as e:
        raise HTTPException(422, str(e))


def _rows_for_share(db: Session, ws: Workspace, trace_id: str) -> list[dict]:
    spans = _trace_spans(db, ws.id, trace_id)
    if not spans:
        raise HTTPException(404, "Trace not found")
    return _span_rows(spans)


def _share_response(ws_id: int, trace_id: str, data: _RedactedShareIn,
                    mask: share.ShareMask) -> dict:
    token = share.make_share_token(ws_id, trace_id, data.ttl_days, mask)
    return {"token": token, "url": share.share_url(token), "trace_id": trace_id,
            "expires_in_days": data.ttl_days if data.ttl_days > 0 else None,
            "withheld": list(mask.fields), "spans": list(mask.spans)}


@router.post("/traces/{trace_id}/share/redacted")
def share_trace_redacted(trace_id: str, data: _RedactedShareIn, db: Session = Depends(get_db),
                         ws: Workspace = Depends(current_workspace)):
    """Mint a share link that withholds named fields (`withhold: ["input","output"]`).

    The mask travels inside the signed token, so a recipient cannot widen their own grant by
    editing the link, and there is no share table to keep in step with it.
    """
    mask = _mask_of(data)
    _rows_for_share(db, ws, trace_id)
    return _share_response(ws.id, trace_id, data, mask)


@router.get("/share/{token}")
def read_shared_trace_redacted(token: str, db: Session = Depends(get_db)):
    """Public, read-only view of a shared trace with its mask applied. No auth — the signature
    is the credential. Masking happens here, on the way out of the database, so the withheld
    content is never in the response at all."""
    resolved = share.verify_share_token(token, allow_masked=True)
    if not resolved:
        raise HTTPException(404, "Invalid or expired share link")
    ws_id, trace_id = resolved
    spans = _trace_spans(db, ws_id, trace_id)
    if not spans:
        raise HTTPException(404, "Trace not found")
    return share.mask_span_rows(_span_rows(spans), token)


@router.post("/traces/{trace_id}/issue-link")
def trace_issue_link(trace_id: str, data: _IssueLinkIn, db: Session = Depends(get_db),
                     ws: Workspace = Depends(current_workspace)):
    """One click from a trace to a filed bug: returns a prefilled "new issue" URL carrying the
    share link, the failing span, the error and the model.

    A URL, not an API call — ProveKit stores no tracker credential and makes no outbound
    request, and the issue is authored by the human who clicks it rather than by a bot.
    The body is built from the MASKED rows, so a field withheld from the link is not handed
    over in the issue instead.
    """
    mask = _mask_of(data)
    rows = share.apply_mask(_rows_for_share(db, ws, trace_id), mask)
    resp = _share_response(ws.id, trace_id, data, mask)
    title, body = share.issue_draft(share.issue_context(rows), resp["url"], mask)
    try:
        url = share.issue_url(data.tracker, data.repo, title, body, data.template)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return {**resp, "issue_url": url, "title": title, "body": body}
