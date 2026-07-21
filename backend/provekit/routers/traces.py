"""OTLP/HTTP trace ingest — point any OpenTelemetry GenAI exporter at /v1/traces and
its LLM/agent spans show up in ProveKit's history, no SDK swap required.

Auth: a workspace ingest key via `Authorization: Bearer <key>` (what real exporters can
send), or a session cookie for interactive/local use. Mint the key from
POST /api/workspace/ingest-key."""
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import asyncio
import json
import logging
import time

from sqlalchemy import String, case, cast, func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..models import Feedback, Run, SpanNote, Workspace, iso_utc
from ..services import apikey, deploy, limits, otel, redact, share
from ..services.auth import get_current_user
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
    if _persist_spans(db, ws, rows):
        _prune_runs(db, ws)           # enforce retention so the table doesn't grow forever
    return {"partialSuccess": {}}


def _persist_spans(db: Session, ws: Workspace, rows: list[dict]) -> int:
    """Store spans we haven't seen before; return how many landed.

    An OTLP exporter retries on 5xx and replays the *whole* batch, so the same span arrives
    more than once in normal operation. A duplicate is not an error to report back — the
    exporter did the right thing — it's a row we must not write twice. The `uq_run_span` index
    is the actual guarantee; this filter keeps the common retry off the failure path.

    Identity is (trace_id, span_id): OTel scopes span-id uniqueness to a trace, so two traces
    may legitimately reuse one and both must be kept.
    """
    if not rows:
        return 0
    tids = {kw["trace_id"] for kw in rows if kw.get("span_id")}
    seen = set()
    if tids:
        seen = {(t, s) for t, s in db.query(Run.trace_id, Run.span_id)
                .filter(Run.workspace_id == ws.id, Run.trace_id.in_(tids), Run.span_id != "").all()}
    fresh = []
    for kw in rows:
        key = (kw.get("trace_id") or "", kw.get("span_id") or "")
        if key[1] and key in seen:
            continue
        if key[1]:
            seen.add(key)             # a batch can also repeat a span within itself
        fresh.append(kw)
    if not fresh:
        return 0
    for kw in fresh:
        db.add(Run(workspace_id=ws.id, **kw))
    try:
        db.commit()
        return len(fresh)
    except IntegrityError:
        # Concurrent retries of the same batch raced past the filter above. Re-apply row by
        # row so the spans that genuinely are new still land instead of the batch being lost.
        db.rollback()
        stored = 0
        for kw in fresh:
            try:
                with db.begin_nested():
                    db.add(Run(workspace_id=ws.id, **kw))
            except IntegrityError:
                continue              # the other request stored it; nothing to do
            stored += 1
        db.commit()
        return stored


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


# Full-text search prefilters to this many candidate traces before the page is cut. Raising it
# without an index (see docs/ROADMAP_100.md #17) just makes the LIKE scan more expensive.
_SEARCH_MATCH_CAP = 500

log = logging.getLogger(__name__)


# Bounds the rootless-trace scan. Well above any healthy deployment's crash rate, so hitting
# it means something is badly wrong — which is itself worth seeing.
_ORPHAN_CAP = 200


def _rootless_trace_heads(db: Session, ws: Workspace, cutoff) -> set[int]:
    """Ids of the earliest span of each trace that has spans but no root span.

    Spans are exported when they end, so a run killed mid-flight (OOM, timeout, SIGKILL)
    never emits its root. Listing only `parent_span_id == ''` therefore hid exactly the
    traces worth looking at.
    """
    q = (db.query(func.min(Run.id))
         .filter(Run.workspace_id == ws.id, Run.trace_id != "")
         .group_by(Run.trace_id)
         .having(func.sum(case((Run.parent_span_id == "", 1), else_=0)) == 0))
    if cutoff is not None:
        q = q.filter(Run.created_at >= cutoff)
    return {mid for (mid,) in q.limit(_ORPHAN_CAP).all()}


# ---- traces (spans grouped into a nested tree) ----
# The listing/detail logic is shared by two auth paths: the cookie-authed /api/* routes the
# portal UI calls, and the key-authed /v1/* routes an MCP server or script calls with the
# project key. Same data, two doors — so "debug via MCP" needs no new client code.
def _list_traces(db: Session, ws: Workspace, limit: int, status: str | None,
                 window_hours: int | None = None, search: str | None = None,
                 cursor: int | None = None):
    """One page of traces, newest first.

    Paging is keyset, not offset: `cursor` is the `id` of the last row you were given and the
    next page is everything below it. Traces arrive continuously, so an offset would skip or
    repeat rows as new ones land above the window. The caller knows there's more when it gets
    a full `limit` back, which keeps the response a plain list — `/v1/traces` is a documented
    key-authed API that MCP and scripts already consume, and an envelope would break them.
    """
    limit = max(1, min(limit, 200))
    cutoff = None
    if window_hours and window_hours > 0:
        from datetime import timedelta

        from ..models import _now
        cutoff = _now() - timedelta(hours=window_hours)

    # A trace with no root span is one whose process died before the root ended (spans are
    # only exported on end). Promote its earliest span to stand in, or the run that crashed —
    # usually the one you most need — is missing from the list entirely.
    stand_ins = _rootless_trace_heads(db, ws, cutoff)
    q = db.query(Run).filter(Run.workspace_id == ws.id)
    q = q.filter(or_(Run.parent_span_id == "", Run.id.in_(stand_ins)) if stand_ins
                 else Run.parent_span_id == "")
    if cursor is not None and cursor > 0:
        q = q.filter(Run.id < cursor)
    if status:
        q = q.filter(Run.status == status)
    if cutoff is not None:
        q = q.filter(Run.created_at >= cutoff)
    if search and search.strip():
        # Full-text-ish: match a trace if ANY of its spans contains the term in its label or its
        # (JSON) request/result — so you can find a run by something it said, not just the label.
        term = f"%{search.strip()}%"
        match_tids = [t for (t,) in db.query(Run.trace_id).filter(
            Run.workspace_id == ws.id,
            or_(Run.label.ilike(term), cast(Run.request, String).ilike(term),
                cast(Run.result, String).ilike(term))).distinct().limit(_SEARCH_MATCH_CAP).all()]
        if len(match_tids) >= _SEARCH_MATCH_CAP:
            # The candidate set is capped, so paging past it would end early and silently look
            # like "no more results". Say so rather than let the UI imply the search was total.
            log.info("search %r hit the %d-trace candidate cap in project %s",
                     search.strip(), _SEARCH_MATCH_CAP, ws.id)
        if not match_tids:
            return []
        q = q.filter(Run.trace_id.in_(match_tids))
    roots = q.order_by(Run.id.desc()).limit(limit).all()
    trace_ids = [r.trace_id for r in roots if r.trace_id]
    counts: dict = {}
    tokens: dict = {}
    models: dict = {}
    if trace_ids:
        for tid, cnt in (db.query(Run.trace_id, func.count(Run.id))
                         .filter(Run.workspace_id == ws.id, Run.trace_id.in_(trace_ids))
                         .group_by(Run.trace_id).all()):
            counts[tid] = cnt
        for tid, result in (db.query(Run.trace_id, Run.result)
                            .filter(Run.workspace_id == ws.id, Run.trace_id.in_(trace_ids)).all()):
            meta = (result or {}).get("meta", {}) if isinstance(result, dict) else {}
            u = meta.get("usage", {})
            tokens[tid] = tokens.get(tid, 0) + (u.get("input_tokens") or 0) + (u.get("output_tokens") or 0)
            if meta.get("model") and tid not in models:   # first model seen in the trace
                models[tid] = meta["model"]
    return [{"id": r.id, "trace_id": r.trace_id, "label": r.label, "type": r.type,
             "status": r.status, "duration_ms": r.duration_ms,
             "span_count": counts.get(r.trace_id, 1) if r.trace_id else 1,
             "tokens": tokens.get(r.trace_id, 0), "session_id": r.session_id,
             "model": models.get(r.trace_id),
             # True when this row is standing in for a root that never arrived, so the client
             # can say "ended unexpectedly" rather than present a partial run as a whole one.
             "incomplete": r.id in stand_ins,
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


# ---- per-span collaboration notes ----
class _NoteIn(BaseModel):
    span_id: str = ""
    body: str


def _note_row(n: SpanNote) -> dict:
    return {"id": n.id, "trace_id": n.trace_id, "span_id": n.span_id, "author": n.author,
            "body": n.body, "created_at": iso_utc(n.created_at)}


@runs_router.get("/traces/{trace_id}/notes")
def list_notes(trace_id: str, db: Session = Depends(get_db),
               ws: Workspace = Depends(current_workspace)):
    rows = (db.query(SpanNote).filter(SpanNote.workspace_id == ws.id, SpanNote.trace_id == trace_id)
            .order_by(SpanNote.id.asc()).all())
    return [_note_row(n) for n in rows]


@runs_router.post("/traces/{trace_id}/notes")
def add_note(trace_id: str, data: _NoteIn, request: Request, db: Session = Depends(get_db),
             ws: Workspace = Depends(current_workspace)):
    if not data.body.strip():
        raise HTTPException(422, "note body is required")
    author = ""
    try:
        author = (get_current_user(request, db).name or "")[:120]
    except Exception:
        pass
    n = SpanNote(workspace_id=ws.id, trace_id=trace_id, span_id=(data.span_id or "")[:16],
                 author=author, body=data.body.strip()[:4000])
    db.add(n); db.commit(); db.refresh(n)
    return _note_row(n)


@runs_router.delete("/notes/{nid}")
def delete_note(nid: int, db: Session = Depends(get_db),
                ws: Workspace = Depends(current_workspace)):
    n = db.get(SpanNote, nid)
    if not n or n.workspace_id != ws.id:
        raise HTTPException(404, "Note not found")
    db.delete(n); db.commit()
    return {"ok": True}


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
    return {"token": share.make_share_token(ws.id, trace_id), "trace_id": trace_id,
            "expires_in_days": share.DEFAULT_TTL_DAYS}


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
                q: str | None = None, cursor: int | None = None,
                db: Session = Depends(get_db), ws: Workspace = Depends(current_workspace)):
    """One row per trace: its root span (the decorated entrypoint), with a span count and
    total token usage (so the list is scannable at a glance). `status=failed` filters to
    failures; `window_hours=N` limits to the last N hours; `q=text` full-text-searches span
    labels and input/output content; `cursor=<id of the last row you got>` returns the next
    page (a full `limit` back means there is more)."""
    return _list_traces(db, ws, limit, status, window_hours, search=q, cursor=cursor)


# Poll cadence for the change-watcher, and a lifetime bound so a generator that somehow
# outlives its client can't leak — EventSource reconnects on its own.
_STREAM_POLL_SECONDS = 2.0
_STREAM_MAX_SECONDS = 300.0


def _latest_root_id(ws_id: int) -> int | None:
    """MAX(id) of this project's root spans — an indexed primary-key lookup."""
    from ..database import SessionLocal

    db = SessionLocal()
    try:
        return (db.query(func.max(Run.id))
                .filter(Run.workspace_id == ws_id, Run.parent_span_id == "").scalar())
    finally:
        db.close()


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


async def _watch_traces(ws_id: int, request: Request):
    """Announce new traces as they land.

    This is a *notification* channel, not a data channel: it sends the newest root-span id and
    the client refetches through its normal path. One serialization instead of two, and the
    paging and merge logic on the client keeps working untouched.

    It watches by polling MAX(id) — an indexed primary-key lookup — rather than being pushed
    from the ingest path. An in-process signal would only reach clients served by the same
    worker, and a Redis channel would make an optional dependency load-bearing for the portal.
    The win is real regardless: one cheap query per viewer every 2s replaces every viewer
    refetching the whole trace list every 5s, and updates land sooner.
    """
    last: int | None = None
    started = time.monotonic()
    while time.monotonic() - started < _STREAM_MAX_SECONDS:
        if await request.is_disconnected():
            return
        try:
            # In a threadpool, not inline: the DB driver is synchronous, and calling it
            # directly from this async generator would block the event loop for every other
            # request on the worker each time any connected client ticks.
            latest = await run_in_threadpool(_latest_root_id, ws_id)
        except Exception as exc:            # a DB blip shouldn't kill the client's connection
            log.debug("trace stream query failed: %s", exc)
            latest = last

        if last is None:
            # The first tick sets a baseline. Announcing here would make every connect look
            # like new activity and trigger a pointless refetch.
            last = latest or 0
            yield _sse({"type": "ready", "latest_id": last})
        elif latest is not None and latest > last:
            last = latest
            yield _sse({"type": "traces", "latest_id": latest})
        else:
            # Comment frame: keeps proxies and load balancers from dropping an idle stream.
            yield ": keepalive\n\n"
        await asyncio.sleep(_STREAM_POLL_SECONDS)


@runs_router.get("/traces/stream")
async def stream_traces(request: Request, ws: Workspace = Depends(current_workspace)):
    """Server-sent events announcing new traces in this project."""
    return StreamingResponse(
        _watch_traces(ws.id, request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # nginx and several proxies buffer responses by default, which turns a stream into
            # one long-delayed blob. This is the documented opt-out.
            "X-Accel-Buffering": "no",
        },
    )


@runs_router.get("/traces/{trace_id}")
def get_trace(trace_id: str, db: Session = Depends(get_db),
              ws: Workspace = Depends(current_workspace)):
    """All spans of one trace, in start order — the client rebuilds the tree from
    span_id / parent_span_id."""
    return _get_trace(db, ws, trace_id)


# ---- key-authed read API (for the MCP server / scripts; same key as ingest) ----
@router.get("/traces")
def list_traces_by_key(request: Request, limit: int = 50, status: str | None = None,
                       window_hours: int | None = None, q: str | None = None,
                       cursor: int | None = None, db: Session = Depends(get_db),
                       authorization: str | None = Header(default=None)):
    """List traces using the project key (Bearer). Backs the ProveKit MCP server so an
    agent can pull recent runs — `status=failed` surfaces just the failures to debug,
    `window_hours=N` limits to the last N hours, and `cursor=<last id>` pages further back."""
    ws = _resolve_ingest_ws(db, request, authorization)
    return _list_traces(db, ws, limit, status, window_hours, search=q, cursor=cursor)


@router.get("/traces/{trace_id}")
def get_trace_by_key(trace_id: str, request: Request, db: Session = Depends(get_db),
                     authorization: str | None = Header(default=None)):
    """Full span tree of one trace using the project key (Bearer)."""
    ws = _resolve_ingest_ws(db, request, authorization)
    return _get_trace(db, ws, trace_id)
