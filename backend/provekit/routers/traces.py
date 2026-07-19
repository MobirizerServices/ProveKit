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
from ..models import Run, Workspace, iso_utc
from ..services import apikey, deploy, limits, otel
from ..services.workspace import current_workspace

router = APIRouter(prefix="/v1", tags=["traces"])
ws_router = APIRouter(prefix="/api/workspace", tags=["workspace"])
runs_router = APIRouter(prefix="/api", tags=["runs"])


def _resolve_ingest_ws(db: Session, request: Request, authorization: str | None) -> Workspace:
    """Bearer ingest key first (exporters), else fall back to the session cookie."""
    if authorization and authorization.lower().startswith("bearer "):
        key = authorization[7:].strip()
        # A named pk_ key (portal-issued, revocable) first, then the legacy per-workspace
        # ingest key. Both are SHA-256 bearer keys; either resolves the same workspace.
        ws = apikey.resolve_workspace(db, key)
        if ws:
            return ws
        ws = db.query(Workspace).filter(Workspace.ingest_key_hash == deploy.hash_key(key)).first()
        if ws:
            return ws
        raise HTTPException(403, "Invalid ingest key")
    # No bearer key: only allowed via a logged-in session (or local mode's default user).
    from ..services.auth import get_current_user
    from ..services.workspace import get_or_create_default_workspace
    user = get_current_user(request, db)
    return get_or_create_default_workspace(db, user)


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
    for kw in rows:
        db.add(Run(workspace_id=ws.id, **kw))
    if rows:
        db.commit()
        _prune_runs(db, ws.id)        # enforce retention so the table doesn't grow forever
    return {"partialSuccess": {}}


def _prune_runs(db: Session, ws_id: int) -> None:
    """Keep only the newest `runs_retention` spans for a project; delete the rest."""
    keep = get_settings().runs_retention
    if keep <= 0:
        return
    stale = [r.id for r in db.query(Run.id).filter(Run.workspace_id == ws_id)
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
@runs_router.get("/traces")
def list_traces(limit: int = 50, db: Session = Depends(get_db),
                ws: Workspace = Depends(current_workspace)):
    """One row per trace: its root span (the decorated entrypoint), with a span count."""
    limit = max(1, min(limit, 200))
    roots = (db.query(Run)
             .filter(Run.workspace_id == ws.id, Run.parent_span_id == "")
             .order_by(Run.id.desc()).limit(limit).all())
    counts = dict(db.query(Run.trace_id, func.count(Run.id))
                  .filter(Run.workspace_id == ws.id)
                  .group_by(Run.trace_id).all())
    return [{"id": r.id, "trace_id": r.trace_id, "label": r.label, "type": r.type,
             "status": r.status, "duration_ms": r.duration_ms,
             "span_count": counts.get(r.trace_id, 1) if r.trace_id else 1,
             "created_at": iso_utc(r.created_at)} for r in roots]


@runs_router.get("/traces/{trace_id}")
def get_trace(trace_id: str, db: Session = Depends(get_db),
              ws: Workspace = Depends(current_workspace)):
    """All spans of one trace, in start order — the client rebuilds the tree from
    span_id / parent_span_id."""
    spans = (db.query(Run)
             .filter(Run.workspace_id == ws.id, Run.trace_id == trace_id)
             .order_by(Run.id.asc()).all())
    if not spans:
        raise HTTPException(404, "Trace not found")
    return [{"id": s.id, "span_id": s.span_id, "parent_span_id": s.parent_span_id,
             "type": s.type, "label": s.label, "status": s.status, "duration_ms": s.duration_ms,
             "request": s.request, "result": s.result, "error": s.error,
             "created_at": iso_utc(s.created_at)} for s in spans]
