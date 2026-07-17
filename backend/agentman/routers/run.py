"""Run a request (prompt | tool | agent), streaming unified events, evaluating any
assertions, and persisting to history. Also batch datasets (run over N input rows)."""
import json

import anyio
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import SessionLocal, get_db
from ..models import Environment, Run, Workspace, iso_utc
from ..services import assertions as assertion_engine
from ..services import dispatch, otel
from ..services.limits import check_rate, clamp_max_tokens, enforce_dataset_size, prune_runs
from ..services.masking import mask_body, mask_headers
from ..services.workspace import current_workspace

router = APIRouter(prefix="/api", tags=["run"])


class RunPayload(BaseModel):
    request: dict
    variables: dict = {}
    save: bool = True


class DatasetPayload(BaseModel):
    request: dict
    rows: list[dict] = []


def _active_vars(db: Session, ws_id: int) -> dict:
    e = db.query(Environment).filter(Environment.workspace_id == ws_id, Environment.is_active.is_(True)).first()
    return dict(e.variables or {}) if e else {}


def _label(req: dict) -> str:
    t = req.get("type")
    if t == "prompt":
        return f"{req.get('model', 'prompt')}: {(req.get('user') or '')[:60]}"
    if t == "tool":
        return f"tool: {req.get('tool', '?')}"
    if t == "agent":
        return f"{req.get('method', 'POST')} {req.get('path', '')}"
    return t or "run"


def _sanitize(req: dict) -> dict:
    """Strip/mask secrets before persisting to run history (returned by GET /runs/{id})."""
    out = {k: v for k, v in req.items() if k != "api_key"}
    if isinstance(out.get("headers"), dict):
        out["headers"] = mask_headers(out["headers"])
    if out.get("body") is not None:  # agent bodies can carry tokens/passwords
        out["body"] = mask_body(out["body"])
    return out


def _new_acc():
    # status starts as "interrupted" — only a `done` event sets the real outcome, so a
    # client disconnect mid-stream persists honestly instead of as "completed".
    return {"parts": [], "output": None, "meta": {}, "events": [], "status": "interrupted", "dur": 0, "err": ""}


def _apply(acc, ev):
    et = ev["type"]
    if et == "delta":
        acc["parts"].append(ev.get("text", ""))
    elif et == "result":
        acc["output"], acc["meta"] = ev.get("data"), ev.get("meta", {})
    elif et == "node":
        acc["events"].append(ev.get("data"))
    elif et == "error":
        acc["err"] = ev.get("error", "")
    elif et == "done":
        acc["status"], acc["dur"] = ev.get("status", "completed"), ev.get("duration_ms", 0)


def _run_dict(acc):
    result = {"text": "".join(acc["parts"]) or None, "output": acc["output"], "meta": acc["meta"]}
    if acc["events"]:
        result["events"] = acc["events"]
    return {"result": result, "status": acc["status"], "duration_ms": acc["dur"], "events": acc["events"], "error": acc["err"]}


async def _collect(db, req, variables, ws_id):
    acc = _new_acc()
    async for ev in dispatch.run(db, req, variables, ws_id):
        _apply(acc, ev)
    return _run_dict(acc)


async def _evaluate(db, assertions, rd, ws_id):
    """Offload assertion evaluation to a thread — the llm_judge assertion runs its own
    event loop (asyncio.run), which can't happen inside this request's loop."""
    if not assertions:
        return []
    return await anyio.to_thread.run_sync(assertion_engine.evaluate, db, assertions, rd, ws_id)


async def _persist_async(db, req, rd, asserts, ws_id):
    """Persist off the event loop — a blocking DB commit (esp. a contended SQLite write)
    must not stall every other in-flight stream sharing this loop."""
    await anyio.to_thread.run_sync(_persist, db, req, rd, asserts, ws_id)


def _persist(db, req, rd, asserts, ws_id):
    result = dict(rd["result"])
    if asserts:
        result["assertions"] = asserts
    try:
        row = Run(workspace_id=ws_id, type=req.get("type", "?"), label=_label(req), request=_sanitize(req),
                  result=result, status=rd["status"], duration_ms=rd["duration_ms"], error=rd["error"])
        db.add(row); db.commit()
        otel.emit_run(row)  # best-effort mirror to an OTLP collector if configured
        prune_runs(db, ws_id)
    except Exception:
        db.rollback()


@router.post("/run/stream")
def run_stream(payload: RunPayload, db: Session = Depends(get_db), ws: Workspace = Depends(check_rate)):
    variables = {**_active_vars(db, ws.id), **(payload.variables or {})}
    req = payload.request
    clamp_max_tokens(req)
    assertions = req.get("assertions") or []
    ws_id = ws.id

    async def live():
        # Fresh session: FastAPI tears down the request's Depends(get_db) before this
        # generator runs (dependencies-with-yield exit when the endpoint returns).
        session = SessionLocal()
        acc = _new_acc()
        asserts: list = []
        try:
            async for ev in dispatch.run(session, req, variables, ws_id):
                _apply(acc, ev)
                yield f"data: {json.dumps(ev)}\n\n"
            rd = _run_dict(acc)
            asserts = await _evaluate(session, assertions, rd, ws_id)
            if asserts:
                yield f"data: {json.dumps({'type': 'assert', 'results': asserts})}\n\n"
            yield "data: [DONE]\n\n"
        finally:
            # Runs also on client disconnect (GeneratorExit) — history keeps the partial run.
            try:
                if payload.save:
                    await _persist_async(session, req, _run_dict(acc), asserts, ws_id)
            finally:
                session.close()

    return StreamingResponse(live(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/run")
async def run_once(payload: RunPayload, db: Session = Depends(get_db), ws: Workspace = Depends(check_rate)):
    clamp_max_tokens(payload.request)
    variables = {**_active_vars(db, ws.id), **(payload.variables or {})}
    rd = await _collect(db, payload.request, variables, ws.id)
    asserts = await _evaluate(db, payload.request.get("assertions") or [], rd, ws.id)
    if payload.save:
        await _persist_async(db, payload.request, rd, asserts, ws.id)
    return {"result": rd["result"], "status": rd["status"], "duration_ms": rd["duration_ms"], "assertions": asserts}


@router.post("/dataset/run")
async def dataset_run(payload: DatasetPayload, db: Session = Depends(get_db), ws: Workspace = Depends(check_rate)):
    enforce_dataset_size(len(payload.rows))
    clamp_max_tokens(payload.request)
    assertions = payload.request.get("assertions") or []
    base = _active_vars(db, ws.id)
    rows = []
    for i, row in enumerate(payload.rows):
        variables = {**base, **(row.get("variables") or {})}
        rd = await _collect(db, payload.request, variables, ws.id)
        asserts = await _evaluate(db, assertions, rd, ws.id)
        passed = all(a["ok"] for a in asserts) if asserts else rd["status"] == "completed"
        rows.append({
            "name": row.get("name") or f"row {i + 1}", "status": rd["status"],
            "text": rd["result"].get("text"), "output": rd["result"].get("output"),
            "assertions": asserts, "pass": passed, "duration_ms": rd["duration_ms"],
        })
    return {"rows": rows, "summary": {"passed": sum(1 for r in rows if r["pass"]), "total": len(rows)}}


@router.get("/runs")
def list_runs(limit: int = 30, db: Session = Depends(get_db), ws: Workspace = Depends(current_workspace)):
    limit = max(1, min(limit, 200))  # bound the page (SQLite treats LIMIT -1 as unlimited)
    rows = db.query(Run).filter(Run.workspace_id == ws.id).order_by(Run.id.desc()).limit(limit).all()
    return [{"id": r.id, "type": r.type, "label": r.label, "status": r.status,
             "duration_ms": r.duration_ms, "created_at": iso_utc(r.created_at)}
            for r in rows]


@router.get("/runs/{rid}")
def get_run(rid: int, db: Session = Depends(get_db), ws: Workspace = Depends(current_workspace)):
    r = db.get(Run, rid)
    if not r or r.workspace_id != ws.id:
        raise HTTPException(404, "Run not found")
    return {"id": r.id, "type": r.type, "label": r.label, "request": r.request,
            "result": r.result, "status": r.status, "duration_ms": r.duration_ms,
            "error": r.error, "created_at": iso_utc(r.created_at)}
