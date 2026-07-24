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
from ..models import Feedback, RetentionEvent, Run, SpanNote, Workspace, _now, iso_utc
from ..services import apikey, deploy, errors, limits, mentions, otel, pricing, redact, share, spool, usage
from ..services import payloads
from ..services import search as search_svc
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
    limits.check_ingest_rate(ws.id)   # bound bursts per project (429 when exceeded)
    # Bound the total per account. Checked before the write so an over-quota account stops
    # consuming storage, rather than being told about it afterwards.
    limits.check_span_quota(ws.owner_user_id)
    # Backpressure: if the spool is already deep, the database is not keeping up and taking
    # more work makes it worse. 503 + Retry-After is the honest answer — OTLP exporters retry
    # it, and #184's dedupe means that retry costs nothing.
    _check_ingest_backpressure()
    try:
        payload = await request.json()
    except Exception:
        return {"partialSuccess": {"rejectedSpans": 0, "errorMessage": "invalid JSON"}}
    rows = otel.ingest(payload)
    if ws.redact_pii or get_settings().redact_pii:   # per-project toggle, or the global default
        rows = [redact.scrub_run(kw) for kw in rows]
    # Stage before persisting. From here the batch survives a failed commit, a killed worker,
    # or a database that is briefly gone; the drainer replays whatever is still staged.
    entry = spool.stage(ws.id, rows)
    try:
        stored = _persist_spans(db, ws, rows)
    except Exception:
        # Left staged on purpose: the drainer owns it now. Report the failure to the exporter
        # so it doesn't treat a batch we haven't stored as delivered.
        log.exception("ingest persist failed; batch retained in spool")
        raise HTTPException(status_code=503, detail="ingest temporarily unavailable") from None
    spool.release(entry)
    if stored:
        # Count what actually landed, not what was sent: a retried batch is deduped (#184) and
        # charging for the retry would make the quota depend on network luck.
        limits.record_spans(ws.owner_user_id, len(stored))
        # The counter above gates the quota; this is the durable ledger a bill is read from
        # (#80). Same input, different lifetimes — see services/usage.py.
        usage.record(db, user_id=ws.owner_user_id, workspace_id=ws.id, rows=stored)
        _prune_runs(db, ws)           # enforce retention so the table doesn't grow forever
    return {"partialSuccess": {}}


def _check_ingest_backpressure() -> None:
    cap = get_settings().spool_max_depth
    if cap > 0 and spool.enabled() and spool.depth_cached() >= cap:
        spool.note_shed()
        raise HTTPException(status_code=503, detail="ingest backlog is full; retry shortly",
                            headers={"Retry-After": "5"})


def drain_spool(limit: int = 200) -> int:
    """Replay staged batches that never made it into the database. Returns how many entries
    were cleared.

    Safe to run repeatedly and from more than one worker: `_persist_spans` dedupes on
    (trace_id, span_id), so replaying a batch that actually did land is a no-op rather than a
    duplicate. An entry whose workspace has since been deleted is dropped — there is nowhere
    for those rows to go, and retrying it forever would block everything behind it.
    """
    from ..database import SessionLocal
    cleared = 0
    for path in spool.pending()[:limit]:
        entry = spool.load(path)
        if entry is None:
            continue                  # load() quarantined it
        db = SessionLocal()
        try:
            ws = db.query(Workspace).filter(Workspace.id == entry.get("workspace_id")).first()
            if ws is None:
                spool.release(path)
                cleared += 1
                continue
            stored = _persist_spans(db, ws, entry.get("rows") or [])
            spool.release(path)
            cleared += 1
            if stored:
                limits.record_spans(ws.owner_user_id, len(stored))
                usage.record(db, user_id=ws.owner_user_id, workspace_id=ws.id, rows=stored)
        except Exception:
            # Still broken. Leave it staged and stop the pass — if the database is down, the
            # next entry will fail the same way and hammering it helps nobody.
            db.rollback()
            log.warning("spool drain failed for %s; will retry", path.name)
            break
        finally:
            db.close()
    if cleared:
        log.info("drained %d staged ingest batch(es)", cleared)
    return cleared


def _persist_spans(db: Session, ws: Workspace, rows: list[dict]) -> list[dict]:
    """Store spans we haven't seen before; return the ones that landed.

    The rows (not just a count) because usage metering prices what was *actually stored* — a
    deduped retry must not bill twice (#80).

    An OTLP exporter retries on 5xx and replays the *whole* batch, so the same span arrives
    more than once in normal operation. A duplicate is not an error to report back — the
    exporter did the right thing — it's a row we must not write twice. The `uq_run_span` index
    is the actual guarantee; this filter keeps the common retry off the failure path.

    Identity is (trace_id, span_id): OTel scopes span-id uniqueness to a trace, so two traces
    may legitimately reuse one and both must be kept.
    """
    if not rows:
        return []
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
        return []
    for kw in fresh:
        db.add(Run(workspace_id=ws.id, search_text=search_svc.text_for(kw),
                     **payloads.offload_row(kw)))
    try:
        db.commit()
        return fresh
    except IntegrityError:
        # Concurrent retries of the same batch raced past the filter above. Re-apply row by
        # row so the spans that genuinely are new still land instead of the batch being lost.
        db.rollback()
        landed: list[dict] = []
        for kw in fresh:
            try:
                with db.begin_nested():
                    db.add(Run(workspace_id=ws.id, search_text=search_svc.text_for(kw),
                     **payloads.offload_row(kw)))
            except IntegrityError:
                continue              # the other request stored it; nothing to do
            landed.append(kw)
        db.commit()
        return landed


def _prune_runs(db: Session, ws: Workspace) -> None:
    """Keep only the newest N spans for a project (its own retention, or the global default).

    Records what it deleted. Silent pruning made "my trace is missing" indistinguishable from
    "my trace never arrived" — a config question and an instrumentation bug, chased very
    differently, with nothing in the product to tell them apart.
    """
    keep = ws.retention if ws.retention and ws.retention > 0 else get_settings().runs_retention
    if keep <= 0:
        return
    # Note: this is a per-project row cap and stays row-based even when the table is
    # partitioned, because a partition spans every tenant — dropping one to enforce ONE
    # project's cap would delete other projects' retained data. Partition drops
    # (services/partitions.drop_before) enforce the instance-wide time horizon instead; the
    # two are complementary, not alternatives.
    stale = [r.id for r in db.query(Run.id).filter(Run.workspace_id == ws.id)
             .order_by(Run.id.desc()).offset(keep).all()]
    if stale:
        db.query(Run).filter(Run.id.in_(stale)).delete(synchronize_session=False)
        _record_retention(db, ws, len(stale), keep)
        db.commit()


def _record_retention(db: Session, ws: Workspace, deleted: int, keep: int) -> None:
    """Add to this hour's deletion tally. Coalesced because pruning runs on nearly every
    ingest, and a row per prune would be a write-amplification problem of its own."""
    now = _now()
    bucket = now.replace(minute=0, second=0, microsecond=0)
    row = (db.query(RetentionEvent)
           .filter(RetentionEvent.workspace_id == ws.id, RetentionEvent.bucket == bucket)
           .first())
    if row is None:
        row = RetentionEvent(workspace_id=ws.id, bucket=bucket, deleted=0, keep=keep)
        db.add(row)
    row.deleted += deleted
    row.keep = keep
    row.last_at = now


@ws_router.get("/retention")
def retention_status(db: Session = Depends(get_db), ws: Workspace = Depends(current_workspace)):
    """The answer to "where did my trace go?" — the policy, what's still here, and what was
    deleted recently."""
    keep = ws.retention if ws.retention and ws.retention > 0 else get_settings().runs_retention
    stored = db.query(func.count(Run.id)).filter(Run.workspace_id == ws.id).scalar() or 0
    oldest = db.query(func.min(Run.created_at)).filter(Run.workspace_id == ws.id).scalar()
    events = (db.query(RetentionEvent).filter(RetentionEvent.workspace_id == ws.id)
              .order_by(RetentionEvent.bucket.desc()).limit(48).all())
    return {
        "keep": keep,                       # 0 = unlimited
        "stored_spans": stored,
        # Nothing older than this exists any more — the single most useful fact when a trace
        # someone remembers seeing is no longer in the list.
        "oldest_retained_at": iso_utc(oldest) if oldest else None,
        "pruned_total": sum(e.deleted for e in events),
        "recent": [{"at": iso_utc(e.bucket), "deleted": e.deleted, "keep": e.keep,
                    "last_at": iso_utc(e.last_at)} for e in events],
    }


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
    req, res = payloads.resolve_row(r.request, r.result)
    return {"id": r.id, "type": r.type, "label": r.label, "request": req,
            "result": res, "status": r.status, "duration_ms": r.duration_ms,
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
        match_tids = [t for (t,) in db.query(Run.trace_id).filter(
            Run.workspace_id == ws.id,
            search_svc.clause(db, search)).distinct().limit(_SEARCH_MATCH_CAP).all()]
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
    cost: dict = {}
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
            # Priced from the input/output split each span reports — the same estimate the
            # dashboard uses. Accumulated here because this loop already visits every span, so
            # a Cost column costs nothing extra to serve. None until a span reports usage.
            c = pricing.estimate(meta.get("model"), u.get("input_tokens"), u.get("output_tokens"))
            if c:
                cost[tid] = (cost.get(tid) or 0) + c
            if meta.get("model") and tid not in models:   # first model seen in the trace
                models[tid] = meta["model"]
    return [{"id": r.id, "trace_id": r.trace_id, "label": r.label, "type": r.type,
             "status": r.status, "duration_ms": r.duration_ms,
             "span_count": counts.get(r.trace_id, 1) if r.trace_id else 1,
             "tokens": tokens.get(r.trace_id, 0), "cost": cost.get(r.trace_id), "session_id": r.session_id,
             "model": models.get(r.trace_id),
             # True when this row is standing in for a root that never arrived, so the client
             # can say "ended unexpectedly" rather than present a partial run as a whole one.
             "incomplete": r.id in stand_ins,
             "created_at": iso_utc(r.created_at)} for r in roots]


def _span_rows(spans: list) -> list[dict]:
    """Serialize spans for the trace view, inflating any offloaded payload (#20).

    This is the detail view, which is where someone actually reads a prompt — the trace LIST
    deliberately does not go through here, so listing traces never touches the blob store.
    """
    out = []
    for s in spans:
        req, res = payloads.resolve_row(s.request, s.result)
        out.append({"id": s.id, "span_id": s.span_id, "parent_span_id": s.parent_span_id,
                    "type": s.type, "label": s.label, "status": s.status,
                    "duration_ms": s.duration_ms, "request": req, "result": res,
                    "error": s.error, "session_id": s.session_id,
                    "created_at": iso_utc(s.created_at)})
    return out


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


# ---- per-span collaboration notes: threads, @mentions, resolve (#65) ----
class _NoteIn(BaseModel):
    span_id: str = ""
    body: str
    #: Reply to this note. A reply to a reply is flattened onto the same root thread.
    parent_id: int | None = None


def _note_row(n: SpanNote) -> dict:
    return {"id": n.id, "trace_id": n.trace_id, "span_id": n.span_id, "author": n.author,
            "body": n.body, "parent_id": n.parent_id, "mentions": n.mentions or [],
            "resolved_at": iso_utc(n.resolved_at) if n.resolved_at else None,
            "resolved_by": n.resolved_by or "",
            "created_at": iso_utc(n.created_at)}


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

    parent_id, span_id = None, (data.span_id or "")[:16]
    if data.parent_id is not None:
        parent = db.get(SpanNote, data.parent_id)
        if not parent or parent.workspace_id != ws.id or parent.trace_id != trace_id:
            raise HTTPException(404, errors.not_in_project(
                "note to reply to", f"GET /api/traces/{trace_id}/notes"))
        # Flatten: a reply always hangs off the note that opened the thread, and inherits the
        # span it was written against so a reply can't drift onto a different node.
        parent_id = parent.parent_id or parent.id
        span_id = parent.span_id

    body = data.body.strip()[:4000]
    mentioned = mentions.resolve(db, ws.id, body)
    n = SpanNote(workspace_id=ws.id, trace_id=trace_id, span_id=span_id, author=author,
                 body=body, parent_id=parent_id, mentions=mentioned)
    db.add(n); db.commit(); db.refresh(n)
    # After the commit: the note is saved whether or not anyone can be told about it.
    mentions.notify(db, ws.id, mentioned, author=author, trace_id=trace_id, body=body,
                    origin=str(request.base_url).rstrip("/"))
    return _note_row(n)


class _ResolveIn(BaseModel):
    resolved: bool = True


@runs_router.post("/notes/{nid}/resolve")
def resolve_note(nid: int, data: _ResolveIn, request: Request, db: Session = Depends(get_db),
                 ws: Workspace = Depends(current_workspace)):
    """Mark a thread settled — or reopen it. Resolving is not deleting: the thread stays readable,
    because the reasoning in it is usually the most valuable thing attached to the trace."""
    n = db.get(SpanNote, nid)
    if not n or n.workspace_id != ws.id:
        raise HTTPException(404, "Note not found")
    if n.parent_id:                      # resolve the thread, not one message inside it
        n = db.get(SpanNote, n.parent_id) or n
    if data.resolved:
        who = ""
        try:
            who = (get_current_user(request, db).name or "")[:120]
        except Exception:
            pass
        n.resolved_at, n.resolved_by = _now(), who
    else:
        n.resolved_at, n.resolved_by = None, ""
    db.commit(); db.refresh(n)
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
    # allow_masked: this route applies the mask on the way out, so it is allowed to resolve a
    # masked token. verify_share_token refuses one by default, which is what keeps a reader
    # that predates masking from serving the payloads a link's author asked to withhold.
    resolved = share.verify_share_token(token, allow_masked=True)
    if not resolved:
        raise HTTPException(404, "Invalid or expired share link")
    ws_id, trace_id = resolved
    spans = _trace_spans(db, ws_id, trace_id)
    if not spans:
        raise HTTPException(404, "Trace not found")
    # Masked server-side, never hidden in the client: the withheld text must not be in this
    # response body at all, or the link still hands it to anyone who opens devtools.
    return share.mask_span_rows(_span_rows(spans), token)


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


@router.get("/traces/{trace_id}/cassette")
def get_trace_cassette(trace_id: str, request: Request, db: Session = Depends(get_db),
                       authorization: str | None = Header(default=None)):
    """Every tool call this trace made, with the response it got — a cassette for replay.

    Portal-side replay can re-run LLM calls but not tools: ProveKit doesn't own them, so a run
    whose behaviour depends on a tool result diverges from reality (#194 makes that visible
    rather than silently wrong). The SDK *does* own them, and this is the missing half — hand
    the recorded responses back to the process that has the tools, and a replay can be
    deterministic, free and side-effect-free.

    Ordered by span id so a sequential fallback match (the same tool called twice with
    different arguments) replays in the order it originally happened.
    """
    ws = _resolve_ingest_ws(db, request, authorization)
    spans = (db.query(Run)
             .filter(Run.workspace_id == ws.id, Run.trace_id == trace_id, Run.type == "tool")
             .order_by(Run.id.asc()).all())
    entries = []
    for s in spans:
        meta = (s.result or {}).get("meta") or {}
        entries.append({
            "span_id": s.span_id,
            "tool": meta.get("tool") or s.label or "",
            "input": ((s.request or {}).get("input") or ""),
            "output": (s.result or {}).get("text") or "",
            "status": s.status,
            "error": s.error or "",
            "duration_ms": s.duration_ms,
        })
    return {"trace_id": trace_id, "entries": entries}
