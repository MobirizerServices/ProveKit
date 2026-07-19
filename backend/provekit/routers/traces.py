"""OTLP/HTTP trace ingest — point any OpenTelemetry GenAI exporter at /v1/traces and
its LLM/agent spans show up in ProveKit's history, no SDK swap required.

Auth: a workspace ingest key via `Authorization: Bearer <key>` (what real exporters can
send), or a session cookie for interactive/local use. Mint the key from
POST /api/workspace/ingest-key."""
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..models import Feedback, Run, Workspace, iso_utc
from ..services import apikey, deploy, limits, otel, redact, share
from ..services.workspace import current_workspace

router = APIRouter(prefix="/v1", tags=["traces"])
ws_router = APIRouter(prefix="/api/workspace", tags=["workspace"])
runs_router = APIRouter(prefix="/api", tags=["runs"])


def _resolve_ingest_ws(db: Session, request: Request, authorization: str | None) -> Workspace:
    """Bearer ingest key first (exporters), else fall back to the session cookie."""
    from ..services.workspace import workspace_from_key
    return workspace_from_key(db, request, authorization)


@router.post("/traces")
async def ingest_traces(request: Request, db: Session = Depends(get_db),
                        authorization: str | None = Header(default=None)):
    """Accept an OTLP ExportTraceServiceRequest (JSON) and persist gen_ai spans as runs.
    Returns the OTLP success shape so standard exporters are satisfied."""
    ws = _resolve_ingest_ws(db, request, authorization)
    limits.check_ingest_rate(ws.id)   # bound abuse/cost per project (429 when exceeded)
    try:
        payload = await request.json()
    except Exception:
        return {"partialSuccess": {"rejectedSpans": 0, "errorMessage": "invalid JSON"}}
    rows = otel.ingest(payload)
    if ws.redact_pii or get_settings().redact_pii:   # per-project toggle, or the global default
        rows = [redact.scrub_run(kw) for kw in rows]
    for kw in rows:
        db.add(Run(workspace_id=ws.id, **kw))
    if rows:
        db.commit()
        _prune_runs(db, ws)           # enforce retention so the table doesn't grow forever
    return {"partialSuccess": {}}


def _prune_runs(db: Session, ws: Workspace) -> None:
    """Keep only the newest N spans for a project (its own retention, or the global default)."""
    keep = ws.retention if ws.retention and ws.retention > 0 else get_settings().runs_retention
    if keep <= 0:
        return
    stale = [r.id for r in db.query(Run.id).filter(Run.workspace_id == ws.id)
             .order_by(Run.id.desc()).offset(keep).all()]
    if stale:
        db.query(Run).filter(Run.id.in_(stale)).delete(synchronize_session=False)
        db.commit()


class _KeyOut(BaseModel):
    ingest_key: str


@ws_router.post("/ingest-key", response_model=_KeyOut)
def rotate_ingest_key(db: Session = Depends(get_db), ws: Workspace = Depends(current_workspace)):
    """Mint/rotate this workspace's OTLP ingest key (shown once; stored hashed)."""
    plaintext, key_hash = deploy.new_api_key()
    ws.ingest_key_hash = key_hash
    db.commit()
    return {"ingest_key": plaintext}


# ---- captured runs (what the Traces view reads) ----
@runs_router.get("/runs")
def list_runs(limit: int = 50, db: Session = Depends(get_db),
              ws: Workspace = Depends(current_workspace)):
    limit = max(1, min(limit, 200))
    rows = (db.query(Run).filter(Run.workspace_id == ws.id)
            .order_by(Run.id.desc()).limit(limit).all())
    return [{"id": r.id, "type": r.type, "label": r.label, "status": r.status,
             "duration_ms": r.duration_ms, "created_at": iso_utc(r.created_at)} for r in rows]


@runs_router.get("/runs/{rid}")
def get_run(rid: int, db: Session = Depends(get_db), ws: Workspace = Depends(current_workspace)):
    r = db.get(Run, rid)
    if not r or r.workspace_id != ws.id:
        raise HTTPException(404, "Run not found")
    return {"id": r.id, "type": r.type, "label": r.label, "request": r.request,
            "result": r.result, "status": r.status, "duration_ms": r.duration_ms,
            "error": r.error, "created_at": iso_utc(r.created_at)}


# ---- traces (spans grouped into a nested tree) ----
# The listing/detail logic is shared by two auth paths: the cookie-authed /api/* routes the
# portal UI calls, and the key-authed /v1/* routes an MCP server or script calls with the
# project key. Same data, two doors — so "debug via MCP" needs no new client code.
def _list_traces(db: Session, ws: Workspace, limit: int, status: str | None,
                 window_hours: int | None = None):
    limit = max(1, min(limit, 200))
    q = (db.query(Run).filter(Run.workspace_id == ws.id, Run.parent_span_id == ""))
    if status:
        q = q.filter(Run.status == status)
    if window_hours and window_hours > 0:
        from datetime import timedelta

        from ..models import _now
        q = q.filter(Run.created_at >= _now() - timedelta(hours=window_hours))
    roots = q.order_by(Run.id.desc()).limit(limit).all()
    trace_ids = [r.trace_id for r in roots if r.trace_id]
    counts: dict = {}
    tokens: dict = {}
    if trace_ids:
        for tid, cnt in (db.query(Run.trace_id, func.count(Run.id))
                         .filter(Run.workspace_id == ws.id, Run.trace_id.in_(trace_ids))
                         .group_by(Run.trace_id).all()):
            counts[tid] = cnt
        for tid, result in (db.query(Run.trace_id, Run.result)
                            .filter(Run.workspace_id == ws.id, Run.trace_id.in_(trace_ids)).all()):
            u = (result or {}).get("meta", {}).get("usage", {}) if isinstance(result, dict) else {}
            tokens[tid] = tokens.get(tid, 0) + (u.get("input_tokens") or 0) + (u.get("output_tokens") or 0)
    return [{"id": r.id, "trace_id": r.trace_id, "label": r.label, "type": r.type,
             "status": r.status, "duration_ms": r.duration_ms,
             "span_count": counts.get(r.trace_id, 1) if r.trace_id else 1,
             "tokens": tokens.get(r.trace_id, 0), "session_id": r.session_id,
             "created_at": iso_utc(r.created_at)} for r in roots]


def _span_rows(spans: list) -> list[dict]:
    return [{"id": s.id, "span_id": s.span_id, "parent_span_id": s.parent_span_id,
             "type": s.type, "label": s.label, "status": s.status, "duration_ms": s.duration_ms,
             "request": s.request, "result": s.result, "error": s.error,
             "session_id": s.session_id, "created_at": iso_utc(s.created_at)} for s in spans]


def _trace_spans(db: Session, ws_id: int, trace_id: str) -> list:
    return (db.query(Run).filter(Run.workspace_id == ws_id, Run.trace_id == trace_id)
            .order_by(Run.id.asc()).all())


def _get_trace(db: Session, ws: Workspace, trace_id: str):
    spans = _trace_spans(db, ws.id, trace_id)
    if not spans:
        raise HTTPException(404, "Trace not found")
    return _span_rows(spans)


# ---- feedback / scoring (attached to a whole trace) ----
class _FeedbackIn(BaseModel):
    name: str
    score: float | None = None
    value: str | None = None
    comment: str | None = None
    source: str = "human"


def _add_feedback(db: Session, ws: Workspace, trace_id: str, data: _FeedbackIn) -> dict:
    fb = Feedback(workspace_id=ws.id, trace_id=trace_id, name=(data.name or "")[:120],
                  score=data.score, value=(data.value or "")[:200],
                  comment=data.comment or "", source=(data.source or "human")[:16])
    db.add(fb)
    db.commit()
    return _feedback_row(fb)


def _feedback_row(fb: Feedback) -> dict:
    return {"id": fb.id, "trace_id": fb.trace_id, "name": fb.name, "score": fb.score,
            "value": fb.value, "comment": fb.comment, "source": fb.source,
            "created_at": iso_utc(fb.created_at)}


def _list_feedback(db: Session, ws: Workspace, trace_id: str) -> list[dict]:
    rows = (db.query(Feedback)
            .filter(Feedback.workspace_id == ws.id, Feedback.trace_id == trace_id)
            .order_by(Feedback.id.desc()).all())
    return [_feedback_row(f) for f in rows]


@runs_router.post("/traces/{trace_id}/feedback")
def add_feedback(trace_id: str, data: _FeedbackIn, db: Session = Depends(get_db),
                 ws: Workspace = Depends(current_workspace)):
    """Attach a human annotation/score to a trace from the portal."""
    return _add_feedback(db, ws, trace_id, data)


@runs_router.get("/traces/{trace_id}/feedback")
def list_feedback(trace_id: str, db: Session = Depends(get_db),
                  ws: Workspace = Depends(current_workspace)):
    return _list_feedback(db, ws, trace_id)


@router.post("/traces/{trace_id}/feedback")
def add_feedback_by_key(trace_id: str, data: _FeedbackIn, request: Request,
                        db: Session = Depends(get_db), authorization: str | None = Header(default=None)):
    """Attach a score to a trace using the project key — what `pk.score()` and offline
    evaluators post."""
    ws = _resolve_ingest_ws(db, request, authorization)
    return _add_feedback(db, ws, trace_id, data)


@router.get("/traces/{trace_id}/feedback")
def list_feedback_by_key(trace_id: str, request: Request, db: Session = Depends(get_db),
                         authorization: str | None = Header(default=None)):
    ws = _resolve_ingest_ws(db, request, authorization)
    return _list_feedback(db, ws, trace_id)


# ---- shareable read-only links (a signed token; no login to view) ----
@runs_router.post("/traces/{trace_id}/share")
def share_trace(trace_id: str, db: Session = Depends(get_db),
                ws: Workspace = Depends(current_workspace)):
    """Mint a signed, read-only share token for a trace. Anyone with the link can view it
    at /shared/{token} (backed by GET /v1/share/{token}) without an account."""
    if not db.query(Run.id).filter(Run.workspace_id == ws.id, Run.trace_id == trace_id).first():
        raise HTTPException(404, "Trace not found")
    return {"token": share.make_share_token(ws.id, trace_id), "trace_id": trace_id}


@router.get("/share/{token}")
def read_shared_trace(token: str, db: Session = Depends(get_db)):
    """Public, read-only view of a shared trace. Verifies the signature — no auth."""
    resolved = share.verify_share_token(token)
    if not resolved:
        raise HTTPException(404, "Invalid or expired share link")
    ws_id, trace_id = resolved
    spans = _trace_spans(db, ws_id, trace_id)
    if not spans:
        raise HTTPException(404, "Trace not found")
    return _span_rows(spans)


@runs_router.get("/traces")
def list_traces(limit: int = 50, status: str | None = None, window_hours: int | None = None,
                db: Session = Depends(get_db), ws: Workspace = Depends(current_workspace)):
    """One row per trace: its root span (the decorated entrypoint), with a span count and
    total token usage (so the list is scannable at a glance). `status=failed` filters to
    failures; `window_hours=N` limits to the last N hours."""
    return _list_traces(db, ws, limit, status, window_hours)


@runs_router.get("/traces/{trace_id}")
def get_trace(trace_id: str, db: Session = Depends(get_db),
              ws: Workspace = Depends(current_workspace)):
    """All spans of one trace, in start order — the client rebuilds the tree from
    span_id / parent_span_id."""
    return _get_trace(db, ws, trace_id)


# ---- key-authed read API (for the MCP server / scripts; same key as ingest) ----
@router.get("/traces")
def list_traces_by_key(request: Request, limit: int = 50, status: str | None = None,
                       window_hours: int | None = None, db: Session = Depends(get_db),
                       authorization: str | None = Header(default=None)):
    """List traces using the project key (Bearer). Backs the ProveKit MCP server so an
    agent can pull recent runs — `status=failed` surfaces just the failures to debug,
    `window_hours=N` limits to the last N hours."""
    ws = _resolve_ingest_ws(db, request, authorization)
    return _list_traces(db, ws, limit, status, window_hours)


@router.get("/traces/{trace_id}")
def get_trace_by_key(trace_id: str, request: Request, db: Session = Depends(get_db),
                     authorization: str | None = Header(default=None)):
    """Full span tree of one trace using the project key (Bearer)."""
    ws = _resolve_ingest_ws(db, request, authorization)
    return _get_trace(db, ws, trace_id)
