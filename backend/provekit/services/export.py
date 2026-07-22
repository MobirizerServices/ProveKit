"""Bulk export of a project's spans as NDJSON, for S3 or a warehouse.

Traces are only half useful while they live in a tool of their own. The other half is joining
them to everything else a company measures — cost per customer, latency against deploys,
quality against a support queue — and that join happens in the warehouse, not here. So this
module's whole job is to hand the rows over in the dullest possible format: one JSON object per
line, UTF-8, newline-delimited, which every loader (Snowflake, BigQuery, DuckDB, `jq`) already
reads.

Three things shape the implementation:

- **It streams.** A project with millions of spans cannot be built into a list and serialized;
  that is an OOM on the server and a multi-minute wait before the first byte on the client. The
  export pages by primary key in bounded chunks and yields each row as it is read, so memory is
  O(chunk) no matter how large the project is. It is a plain *sync* generator on purpose:
  Starlette iterates a sync body in a threadpool, and the database driver here is synchronous,
  so this never blocks the event loop (the same reasoning as the SSE watcher in
  `routers/traces.py`, which hops to a threadpool for its query).
- **It resolves offloaded payloads.** Past a size threshold `services/payloads.py` moves a
  prompt to a blob store and leaves `{"__ref__": "sha256:…"}` in the row. Exporting that
  reference would write a pointer into someone's warehouse to bytes their warehouse cannot
  read — an export that looks complete and is not. Cost of resolving it is real and is stated
  in docs/EXPORT.md.
- **A truncated file is detectable.** The connection can drop, the database can fail mid-scan,
  and a half-written NDJSON object stream looks exactly like a complete one — the loader would
  quietly ingest a partial day. So the stream ends with a sentinel line carrying the status,
  the row count and the last id. One extra line the loader drops is a much smaller cost than a
  silent short load.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from ..database import SessionLocal
from ..models import Run, iso_utc
from . import payloads, pricing

log = logging.getLogger(__name__)

#: Rows per round trip. Bounds memory and the size of any single query; the client sees the
#: first line after one of these, not after the whole project has been read.
CHUNK = 500

#: The one key a sentinel line has, and no span record has. A loader drops lines carrying it.
SENTINEL_KEY = "_export"

#: Audit action for a bulk read. `services/audit.py` is the greppable home for action names,
#: but this one belongs to the feature that emits it and nothing else writes it.
EXPORT_ACTION = "export.traces"


def parse_ts(value: str | None) -> datetime | None:
    """Parse an ISO-8601 bound, assuming UTC when no offset is given.

    Raises on garbage rather than ignoring it. A mistyped `since` that silently degraded to "no
    filter" would hand the caller the entire project when they asked for an hour of it, and
    they would not find out until the bill or the bucket said so.
    """
    if value is None or value == "":
        return None
    text = value.strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(text)          # raises ValueError; the router maps it to 422
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _record(r: Run, resolve: bool) -> dict:
    """One span as a flat-ish warehouse row.

    `request`/`result` are carried through whole because they are the substance, and the few
    scalars a warehouse actually groups by (model, tokens, cost) are lifted alongside them so
    the common query needs no JSON extraction. They are lifted, not duplicated — the big text
    stays in `request`/`result` only, or every export would be twice the size it needs to be.
    """
    if resolve:
        req, res = payloads.resolve_row(r.request, r.result)
    else:
        req, res = dict(r.request or {}), dict(r.result or {})
    meta = res.get("meta") or {}
    usage = meta.get("usage") or {}
    model = meta.get("model") or (req.get("model") if isinstance(req, dict) else None)
    inp, out = usage.get("input_tokens") or 0, usage.get("output_tokens") or 0
    return {
        # `id` is the export's stable identity: dedupe on it after an overlapping re-export.
        "id": r.id,
        "workspace_id": r.workspace_id,
        "trace_id": r.trace_id,
        "span_id": r.span_id,
        "parent_span_id": r.parent_span_id,
        "session_id": r.session_id,
        "type": r.type,
        "label": r.label,
        "status": r.status,
        "duration_ms": r.duration_ms,
        "error": r.error,
        "created_at": iso_utc(r.created_at),
        "model": model,
        "provider": req.get("provider") if isinstance(req, dict) else None,
        "input_tokens": inp,
        "output_tokens": out,
        # Priced at the rates that applied when the span was captured, so a warehouse total
        # matches the dashboard instead of being silently re-priced by a later rate change.
        "cost_usd": pricing.estimate(model, inp, out, version=meta.get("price_version")),
        "request": req,
        "result": res,
    }


def _line(obj: dict) -> str:
    # default=str: one unexpected value type in a stored payload must not abort an export that
    # is otherwise fine. ensure_ascii=False keeps non-English prompts readable and smaller.
    return json.dumps(obj, ensure_ascii=False, default=str) + "\n"


def iter_ndjson(ws_id: int, *, since: datetime | None = None, until: datetime | None = None,
                after_id: int = 0, resolve: bool = True, limit: int = 0,
                sentinel: bool = True):
    """Yield NDJSON lines for one project's spans, oldest first.

    Keyset paging on `id`, not offset: an export of a busy project runs while ingest continues,
    and an OFFSET walk would skip or repeat rows as new ones land. Ascending order is what makes
    `after_id` a usable incremental cursor — the caller stores the last id it loaded and asks
    for what is above it next time.

    Opens its own session and closes it in `finally`. It cannot borrow the request's: since
    FastAPI 0.106 a `yield` dependency is torn down *before* a streaming body is consumed, so a
    generator holding `Depends(get_db)`'s session would be reading through a closed one.
    """
    db = SessionLocal()
    rows, cursor, status = 0, after_id, "complete"
    try:
        while True:
            take = CHUNK if limit <= 0 else min(CHUNK, limit - rows)
            if take <= 0:
                status = "limit_reached"
                break
            q = db.query(Run).filter(Run.workspace_id == ws_id, Run.id > cursor)
            if since is not None:
                q = q.filter(Run.created_at >= since)
            if until is not None:
                q = q.filter(Run.created_at < until)   # half-open, so adjacent windows can't
            batch = q.order_by(Run.id.asc()).limit(take).all()   # double-count a boundary row
            if not batch:
                break
            for r in batch:
                yield _line(_record(r, resolve))
                rows, cursor = rows + 1, r.id
            # Release the chunk. SQLAlchemy's identity map holds clean instances weakly, so
            # they usually fall away on their own — but "usually" depends on the garbage
            # collector and on nothing else keeping a reference. Dropping them here makes the
            # bound on live rows a property of this loop rather than of GC timing.
            db.expunge_all()
            if len(batch) < take:
                break
    except Exception as exc:                   # noqa: BLE001 — reported to the consumer below
        # The response is already 200 with a partial body; there is no status code left to
        # change. Saying so in the stream is the only way the consumer learns the file is short.
        log.exception("export failed for project %s after %d rows", ws_id, rows)
        if sentinel:
            yield _line({SENTINEL_KEY: {"status": "error", "rows": rows, "last_id": cursor,
                                        "error": str(exc)[:200]}})
        return
    finally:
        db.close()
    if sentinel:
        yield _line({SENTINEL_KEY: {"status": status, "rows": rows, "last_id": cursor,
                                    "resolved_payloads": resolve,
                                    "since": iso_utc(since), "until": iso_utc(until)}})


def count(db, ws_id: int, since: datetime | None = None, until: datetime | None = None,
          after_id: int = 0) -> dict:
    """How big this export would be, before committing to it.

    Deliberately only a count and the window's real edges: anything more (bytes, how many
    payloads are offloaded) means reading the rows, which is the export itself.
    """
    from sqlalchemy import func

    q = db.query(func.count(Run.id), func.min(Run.created_at), func.max(Run.created_at)) \
          .filter(Run.workspace_id == ws_id, Run.id > after_id)
    if since is not None:
        q = q.filter(Run.created_at >= since)
    if until is not None:
        q = q.filter(Run.created_at < until)
    rows, oldest, newest = q.one()
    return {"rows": rows or 0, "oldest": iso_utc(oldest) if oldest else None,
            "newest": iso_utc(newest) if newest else None}


def filename(ws_id: int) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"provekit-project-{ws_id}-{stamp}.ndjson"
