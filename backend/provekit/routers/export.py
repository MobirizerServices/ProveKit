"""Bulk export — stream a project's spans out as NDJSON (#93).

Two doors onto the same stream, matching the pattern the read APIs already use:
`/api/export/*` for the portal's session cookie, and `/v1/export/*` for a project key. The
key-authed door is the one that matters here — an export nobody can fetch without a browser
session cannot be driven by cron, Airflow or a warehouse loader, which is where a bulk export
is actually consumed.

Scheduling is here now, as its own table (models.ExportSchedule) so the cursor survives a
restart — see services/export_schedule.py for why each of the obvious shortcuts fails quietly.
Driving it from your own scheduler still works and is documented in docs/EXPORT.md.
"""
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import ExportSchedule, Workspace
from ..services import audit, errors, netguard
from ..services import export as export_svc
from ..services import export_schedule
from ..services.auth import get_current_user
from ..services.workspace import current_workspace, workspace_from_key

router = APIRouter(prefix="/api/export", tags=["export"])
key_router = APIRouter(prefix="/v1/export", tags=["export"])

NDJSON = "application/x-ndjson"


def _window(since: str | None, until: str | None):
    try:
        return export_svc.parse_ts(since), export_svc.parse_ts(until)
    except ValueError:
        raise HTTPException(422, "since/until must be ISO-8601, e.g. 2026-07-01T00:00:00Z") from None


def _stream(db: Session, ws: Workspace, request: Request, actor, *, since, until,
            after_id: int, resolve: bool, limit: int, sentinel: bool,
            auth: str) -> StreamingResponse:
    """Audit the request, then hand back the stream.

    The audit row is written *before* the first byte, and records what was asked for rather than
    what was delivered — the generator outlives this request scope, with no session and no user
    to attribute a row to by then. A bulk read of every prompt in a project is exactly the
    privileged action `audit_logs` exists for, and recording the intent is both honest and
    enough to answer "who pulled this project's data, when, for what window".
    """
    audit.record(db, actor, export_svc.EXPORT_ACTION, workspace_id=ws.id,
                 target_type="project", target_id=ws.id, target_label=ws.name,
                 detail={"since": since.isoformat() if since else None,
                         "until": until.isoformat() if until else None,
                         "after_id": after_id, "resolve": resolve, "limit": limit,
                         "auth": auth},
                 request=request)
    body = export_svc.iter_ndjson(ws.id, since=since, until=until, after_id=after_id,
                                  resolve=resolve, limit=limit, sentinel=sentinel)
    return StreamingResponse(body, media_type=NDJSON, headers={
        "Content-Disposition": f'attachment; filename="{export_svc.filename(ws.id)}"',
        # Same reason as the SSE endpoint: several proxies buffer a response by default, which
        # turns a stream into one long-delayed blob and defeats the point of streaming it.
        "X-Accel-Buffering": "no",
        "Cache-Control": "no-store",
    })


@router.get("/traces.ndjson")
def export_traces(request: Request, since: str | None = None, until: str | None = None,
                  after_id: int = 0, resolve: bool = True, limit: int = 0,
                  sentinel: bool = True, db: Session = Depends(get_db), ws: Workspace = Depends(current_workspace),
                  user=Depends(get_current_user)):
    """Stream this project's spans as NDJSON, oldest first.

    `since`/`until` bound the window (ISO-8601, UTC assumed, half-open). `after_id` is the
    incremental cursor — pass the last id you loaded. `resolve=false` leaves offloaded payloads
    as `{"__ref__": …}` references, which is only useful if the consumer can read the blob store
    itself (see docs/EXPORT.md). `limit=N` caps the row count, for sampling the shape first.
    `sentinel=false` drops the trailing status line, and with it the only way to tell a
    truncated file from a complete one.
    """
    s, u = _window(since, until)
    return _stream(db, ws, request, user, since=s, until=u, after_id=after_id,
                   resolve=resolve, limit=limit, sentinel=sentinel, auth="session")


@router.get("/estimate")
def estimate(since: str | None = None, until: str | None = None, after_id: int = 0,
             db: Session = Depends(get_db), ws: Workspace = Depends(current_workspace)):
    """How many spans that window holds, and its real edges — ask before pointing this at a
    bucket, because the export itself is the expensive way to find out."""
    s, u = _window(since, until)
    return export_svc.count(db, ws.id, s, u, after_id)


@key_router.get("/traces.ndjson")
def export_traces_by_key(request: Request, since: str | None = None, until: str | None = None,
                         after_id: int = 0, resolve: bool = True, limit: int = 0,
                         sentinel: bool = True, db: Session = Depends(get_db),
                         authorization: str | None = Header(default=None)):
    """The same stream, authed by the project key (Bearer) — what a cron job or loader uses."""
    ws = workspace_from_key(db, request, authorization)
    s, u = _window(since, until)
    return _stream(db, ws, request, None, since=s, until=u, after_id=after_id,
                   resolve=resolve, limit=limit, sentinel=sentinel, auth="project_key")


@key_router.get("/estimate")
def estimate_by_key(request: Request, since: str | None = None, until: str | None = None,
                    after_id: int = 0, db: Session = Depends(get_db),
                    authorization: str | None = Header(default=None)):
    ws = workspace_from_key(db, request, authorization)
    s, u = _window(since, until)
    return export_svc.count(db, ws.id, s, u, after_id)


# ---- scheduled export (#93) ----
class _ScheduleIn(BaseModel):
    name: str = ""
    cadence: str = "daily"
    destination_url: str
    enabled: bool = True


@router.get("/schedules")
def list_schedules(db: Session = Depends(get_db), ws: Workspace = Depends(current_workspace)):
    rows = (db.query(ExportSchedule).filter(ExportSchedule.workspace_id == ws.id)
            .order_by(ExportSchedule.id.desc()).all())
    return [export_schedule.row(s) for s in rows]


@router.post("/schedules")
def create_schedule(data: _ScheduleIn, db: Session = Depends(get_db),
                    ws: Workspace = Depends(current_workspace)):
    if data.cadence not in export_schedule.CADENCES:
        raise HTTPException(422, f"cadence must be one of: "
                                 f"{', '.join(sorted(export_schedule.CADENCES))}")
    url = (data.destination_url or "").strip()
    try:
        netguard.guard_url(url)
    except Exception as exc:
        raise HTTPException(422, errors.bad_webhook(str(exc))) from None
    s = ExportSchedule(workspace_id=ws.id, name=(data.name or "export")[:120],
                       cadence=data.cadence, destination_url=url[:500], enabled=data.enabled)
    db.add(s); db.commit(); db.refresh(s)
    return export_schedule.row(s)


def _own(db: Session, ws: Workspace, sid: int) -> ExportSchedule:
    s = db.get(ExportSchedule, sid)
    if not s or s.workspace_id != ws.id:
        raise HTTPException(404, errors.not_in_project("export schedule",
                                                       "GET /api/export/schedules"))
    return s


@router.post("/schedules/{sid}/run")
def run_schedule(sid: int, db: Session = Depends(get_db),
                 ws: Workspace = Depends(current_workspace)):
    """Run one now — so a destination can be proven before waiting a cadence to find out."""
    s = _own(db, ws, sid)
    result = export_schedule.run(db, s)
    return {**result, "schedule": export_schedule.row(s)}


@router.delete("/schedules/{sid}")
def delete_schedule(sid: int, db: Session = Depends(get_db),
                    ws: Workspace = Depends(current_workspace)):
    s = _own(db, ws, sid)
    db.delete(s); db.commit()
    return {"ok": True}
