"""Fleet health — which tenant is filling this instance's database, and which is breaking it.

The instance dashboard tells an operator *that* volume or errors moved; it never says who
moved them. This module answers the attribution question, and it has to answer it on an
instance with many tenants and a `runs` table that may hold hundreds of millions of spans. An
admin page that takes the database down while someone investigates an incident is worse than
no admin page, so every read here is bounded:

* volume, errors and trend come from `metric_rollups` (services/rollups.py) — one grouped
  query over a table with one small row per tenant-hour, never a scan of raw spans;
* the still-filling hour, which rollups don't cover and which is exactly the hour an operator
  is investigating, comes from a tail scan bounded by primary key to the newest
  `OPEN_SCAN_ROWS` rows — and reports `partial_open_hour` when even that wasn't far enough,
  because a silently truncated aggregate is the failure mode rollups.py was written to kill;
* storage and freshness come from one per-tenant sample of the newest `SAMPLE_SPANS` rows,
  read backwards through `ix_runs_ws_created`, and taken only for the tenants actually
  returned — not for every tenant on the instance.

Byte figures are estimates and say so. `metric_rollups` counts *traces*, not spans, and the
schema has no per-tenant byte counter, so size is extrapolated from the sample. An estimate
labelled as an estimate is worth more to an operator mid-incident than an exact number that
costs a full scan of the largest table in the schema.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import Text, case, cast, func
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import MetricRollup, Run, User, Workspace, _now, iso_utc
from . import rollups

DEFAULT_WINDOW_HOURS = 24
MAX_WINDOW_HOURS = 24 * 7          # a week of hourly rollups per tenant is still a small read
DEFAULT_LIMIT = 20
MAX_LIMIT = 50                     # each returned tenant costs one extra sample query

# The newest N rows are enough to cover the open hour on any instance ingesting under ~50k
# spans/hour. Past that the page stays fast and admits it is looking at part of the hour.
OPEN_SCAN_ROWS = 50_000
# Enough rows to average out payload size and spans-per-trace; small enough that 50 tenants of
# it is a few thousand tiny rows. Lengths are computed in SQL so no payload leaves the database.
SAMPLE_SPANS = 200

# Errors outweigh volume: the tenant responsible for half the instance's failures is the answer
# to "what am I looking at", even when a quieter tenant sends more traces.
_ERROR_WEIGHT = 0.7
_VOLUME_WEIGHT = 0.3


def _aware(dt: datetime | None) -> datetime | None:
    """SQLite hands stored timestamps back naive; they were written in UTC (models._now)."""
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _payload_length():
    """Approximate stored size of one span, in characters.

    `length()` over the text form of the payload columns, summed in SQL so the JSON itself
    never crosses the wire. It ignores row headers, indexes and TOAST/page overhead, so it is
    a floor on real disk usage rather than a disk-accounting figure — which is the right shape
    for "who is filling the database", where the ranking matters more than the absolute.
    """
    cols = (Run.request, Run.result, Run.error, Run.search_text, Run.label)
    expr = None
    for col in cols:
        piece = func.coalesce(func.length(cast(col, Text)), 0)
        expr = piece if expr is None else expr + piece
    return expr


def _rollup_window(db: Session, roll_start: datetime, open_hour: datetime,
                   recent_start: datetime) -> dict[int, dict]:
    """Per-tenant closed-hour totals for the window, split into its two halves.

    One grouped query over `metric_rollups`. Cost is (tenants with traffic) x (window hours)
    small rows — independent of how many spans those hours contained, which is the whole
    reason this table exists.
    """
    recent = case((MetricRollup.bucket >= recent_start, MetricRollup.trace_count), else_=0)
    recent_err = case((MetricRollup.bucket >= recent_start, MetricRollup.error_count), else_=0)
    rows = (db.query(MetricRollup.workspace_id,
                     func.sum(MetricRollup.trace_count),
                     func.sum(MetricRollup.error_count),
                     func.sum(recent),
                     func.sum(recent_err))
            .filter(MetricRollup.bucket >= roll_start, MetricRollup.bucket < open_hour)
            .group_by(MetricRollup.workspace_id).all())
    return {ws: {"traces": t or 0, "errors": e or 0,
                 "recent_traces": rt or 0, "recent_errors": re_ or 0}
            for ws, t, e, rt, re_ in rows}


def _open_hour(db: Session, open_hour: datetime) -> tuple[dict[int, dict], bool]:
    """Per-tenant counts for the hour still filling, plus whether the scan reached far enough.

    Bounded by primary key rather than by `created_at`: there is no index on `created_at`
    alone, so filtering on it would scan the table. Ids are assigned in roughly insert order,
    so the newest `OPEN_SCAN_ROWS` ids are a superset of the open hour on any instance ingesting
    less than that per hour. Concurrency and retention gaps only ever make the scanned range
    *smaller*, and the boundary probe below catches the case where it was too small.
    """
    max_id = db.query(func.max(Run.id)).scalar() or 0
    floor_id = max(0, max_id - OPEN_SCAN_ROWS)
    rows = (db.query(Run.workspace_id, func.count(Run.id),
                     func.sum(case((Run.status == "failed", 1), else_=0)))
            .filter(Run.id > floor_id, Run.created_at >= open_hour, Run.parent_span_id == "")
            .group_by(Run.workspace_id).all())
    live = {ws: {"traces": n or 0, "errors": e or 0} for ws, n, e in rows}

    partial = False
    if floor_id > 0:
        # The oldest row inside the scanned range. If even that one is already inside the open
        # hour, rows older than it were excluded by the id bound and the hour is under-counted.
        oldest = (db.query(Run.created_at).filter(Run.id > floor_id)
                  .order_by(Run.id).limit(1).scalar())
        partial = oldest is not None and _aware(oldest) >= open_hour
    return live, partial


def _lifetime_traces(db: Session, ids: list[int]) -> dict[int, int]:
    """Traces each listed tenant has ever had rolled up — the base for the size estimate."""
    if not ids:
        return {}
    rows = (db.query(MetricRollup.workspace_id, func.sum(MetricRollup.trace_count))
            .filter(MetricRollup.workspace_id.in_(ids))
            .group_by(MetricRollup.workspace_id).all())
    return {ws: n or 0 for ws, n in rows}


def _sample(db: Session, workspace_id: int) -> dict:
    """One backwards walk of `ix_runs_ws_created` for a single tenant.

    Serves three answers at once, which is why it is a single query and not three: the first
    row's timestamp is the exact last-ingest time, the mean length is bytes-per-span, and the
    number of distinct traces in the sample is the span fan-out used to turn rolled-up trace
    counts into span counts.
    """
    rows = (db.query(Run.created_at, Run.trace_id, _payload_length())
            .filter(Run.workspace_id == workspace_id)
            .order_by(Run.created_at.desc()).limit(SAMPLE_SPANS).all())
    if not rows:
        return {"last_ingest_at": None, "bytes_per_span": 0.0, "spans_per_trace": 1.0,
                "sampled_spans": 0}

    total_len = sum(int(length or 0) for _, _, length in rows)
    # Rows written outside OTLP ingest (replays, evals) carry no trace id; each is its own
    # unit rather than one giant pseudo-trace.
    traces: dict[str, int] = {}
    loose = 0
    for _at, trace_id, _length in rows:
        if trace_id:
            traces[trace_id] = traces.get(trace_id, 0) + 1
        else:
            loose += 1
    if len(traces) > 1:
        # The oldest trace in the sample is cut off by the LIMIT, so counting its spans would
        # drag the fan-out estimate down. Drop it rather than under-count every tenant.
        traces.pop(list(traces)[-1], None)
    groups = len(traces) + loose
    counted = sum(traces.values()) + loose
    return {
        "last_ingest_at": _aware(rows[0][0]),
        "bytes_per_span": total_len / len(rows),
        "spans_per_trace": (counted / groups) if groups else 1.0,
        "sampled_spans": len(rows),
    }


def _blame(traces: int, errors: int, tot_traces: int, tot_errors: int) -> float:
    """How much of what the instance dashboard is showing belongs to this tenant.

    The ordering has to answer "who is responsible for what I am seeing", so it ranks by share
    of the instance's own totals — not by growth. A tenant that went from 3 traces to 9 has a
    200% trend and no responsibility for anything; ranking on trend would put it above the one
    producing 80% of the failures. Trend is reported as a column, not used as the sort key.
    """
    e = (errors / tot_errors) if tot_errors else 0.0
    v = (traces / tot_traces) if tot_traces else 0.0
    if not tot_errors:
        return v
    return _ERROR_WEIGHT * e + _VOLUME_WEIGHT * v


def _trend_pct(recent: int, prior: int) -> float | None:
    """Percent change between the window's two halves. None when there is no baseline —
    a jump from zero is not "infinity percent", it is a tenant that just started."""
    if prior <= 0:
        return None
    return round((recent - prior) * 100.0 / prior, 1)


def snapshot(db: Session, *, window_hours: int = DEFAULT_WINDOW_HOURS,
             limit: int = DEFAULT_LIMIT) -> dict:
    """Per-tenant ingest volume, error share, size and freshness, worst tenant first."""
    from ..observability import ingest_health

    window_hours = max(2, min(int(window_hours or DEFAULT_WINDOW_HOURS), MAX_WINDOW_HOURS))
    limit = max(1, min(int(limit or DEFAULT_LIMIT), MAX_LIMIT))

    now = _now()
    open_hour = rollups.floor_hour(now)
    # The window is `window_hours` long *including* the hour still filling, so "last 24 hours"
    # means 23 rolled-up hours plus live rows — not 24 closed hours ending an hour ago.
    roll_start = open_hour - timedelta(hours=window_hours - 1)
    half = max(1, window_hours // 2)
    recent_start = open_hour - timedelta(hours=half - 1)

    rolled = _rollup_window(db, roll_start, open_hour, recent_start)
    live, partial = _open_hour(db, open_hour)

    totals: dict[int, dict] = {}
    for ws_id in set(rolled) | set(live):
        r = rolled.get(ws_id, {"traces": 0, "errors": 0, "recent_traces": 0, "recent_errors": 0})
        live_row = live.get(ws_id, {"traces": 0, "errors": 0})
        traces = r["traces"] + live_row["traces"]
        errors = r["errors"] + live_row["errors"]
        recent = r["recent_traces"] + live_row["traces"]   # the open hour is the recent half
        totals[ws_id] = {"traces": traces, "errors": errors, "recent_traces": recent,
                         "prior_traces": traces - recent}

    tot_traces = sum(t["traces"] for t in totals.values())
    tot_errors = sum(t["errors"] for t in totals.values())
    for t in totals.values():
        t["blame"] = _blame(t["traces"], t["errors"], tot_traces, tot_errors)

    ranked = sorted(totals.items(),
                    key=lambda kv: (-kv[1]["blame"], -kv[1]["traces"], kv[0]))
    page = ranked[:limit]
    ids = [ws_id for ws_id, _ in page]

    names = {w.id: w for w in db.query(Workspace).filter(Workspace.id.in_(ids)).all()} if ids else {}
    owners = dict(db.query(Workspace.id, User.email)
                  .join(User, User.id == Workspace.owner_user_id)
                  .filter(Workspace.id.in_(ids)).all()) if ids else {}
    lifetime = _lifetime_traces(db, ids)
    default_retention = get_settings().runs_retention

    tenants = []
    for ws_id, t in page:
        ws = names.get(ws_id)
        s = _sample(db, ws_id)
        per_span = s["bytes_per_span"]
        fanout = max(1.0, s["spans_per_trace"])
        keep = (ws.retention if ws and ws.retention and ws.retention > 0
                else default_retention)
        # Retention prunes to the newest `keep` spans, so a tenant's resident rows can never
        # exceed it however many traces its rollups have counted over the months.
        est_spans = lifetime.get(ws_id, 0) * fanout
        resident_spans = min(est_spans, float(keep)) if keep and keep > 0 else est_spans
        last = s["last_ingest_at"]
        tenants.append({
            "workspace_id": ws_id,
            "name": ws.name if ws else f"#{ws_id}",
            "owner": owners.get(ws_id, ""),
            "traces": t["traces"],
            "errors": t["errors"],
            "error_rate": round(t["errors"] / t["traces"], 4) if t["traces"] else 0.0,
            "error_share": round(t["errors"] / tot_errors, 4) if tot_errors else 0.0,
            "volume_share": round(t["traces"] / tot_traces, 4) if tot_traces else 0.0,
            "blame": round(t["blame"], 4),
            "recent_traces": t["recent_traces"],
            "prior_traces": t["prior_traces"],
            "trend_pct": _trend_pct(t["recent_traces"], t["prior_traces"]),
            "spans_per_trace": round(fanout, 2),
            "bytes_per_span": round(per_span),
            "ingest_bytes": round(t["traces"] * fanout * per_span),
            "storage_bytes": round(resident_spans * per_span),
            "retention_spans": keep,
            "sampled_spans": s["sampled_spans"],
            "last_ingest_at": iso_utc(last),
            "ingest_age_seconds": round((now - last).total_seconds(), 1) if last else None,
        })

    return {
        "window_hours": window_hours,
        "generated_at": iso_utc(now),
        "open_hour": iso_utc(open_hour),
        "rollups_from": iso_utc(roll_start),
        # True when the instance ingested more than OPEN_SCAN_ROWS spans this hour, so the
        # live part of every figure below is a floor. Never leave this implicit.
        "partial_open_hour": partial,
        "approximate": True,
        "limit": limit,
        "total": len(ranked),
        "instance": {
            "tenants_active": len(ranked),
            "traces": tot_traces,
            "errors": tot_errors,
            "error_rate": round(tot_errors / tot_traces, 4) if tot_traces else 0.0,
            # The same block /healthz reports, so the fleet table sits next to the reason an
            # operator opened it: backlog is instance-wide, blame is per-tenant.
            "ingest": ingest_health(),
        },
        "tenants": tenants,
    }
