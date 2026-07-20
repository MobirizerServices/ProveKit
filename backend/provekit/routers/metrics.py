"""Metrics — aggregate numbers behind the portal dashboard: trace volume, error rate,
latency percentiles, token usage, a time series, and a per-model breakdown, over a window."""
import math
from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Run, Workspace, _now, iso_utc
from ..services.workspace import current_workspace

router = APIRouter(prefix="/api/metrics", tags=["metrics"])

_ROOT_CAP = 5000     # bound the scan for percentiles/series
_SPAN_CAP = 20000    # bound the scan for token totals


def _pct(sorted_vals: list[int], p: float) -> int:
    if not sorted_vals:
        return 0
    k = (len(sorted_vals) - 1) * p / 100
    f, c = math.floor(k), math.ceil(k)
    if f == c:
        return sorted_vals[int(k)]
    return round(sorted_vals[f] * (c - k) + sorted_vals[c] * (k - f))


def _usage_tokens(result) -> int:
    if not isinstance(result, dict):
        return 0
    u = (result.get("meta") or {}).get("usage") or {}
    return (u.get("input_tokens") or 0) + (u.get("output_tokens") or 0)


@router.get("")
def metrics(window_hours: int = 24, db: Session = Depends(get_db),
            ws: Workspace = Depends(current_workspace)):
    return compute_metrics(db, ws, window_hours)


def compute_metrics(db: Session, ws: Workspace, window_hours: int) -> dict:
    """The dashboard aggregate. Also called by the alerts evaluator, so it's a plain
    function, not just a route handler."""
    cutoff = _now() - timedelta(hours=window_hours) if window_hours > 0 else None
    by_day = window_hours == 0 or window_hours > 48

    rootq = db.query(Run).filter(Run.workspace_id == ws.id, Run.parent_span_id == "")
    if cutoff is not None:
        rootq = rootq.filter(Run.created_at >= cutoff)
    roots = rootq.order_by(Run.id.desc()).limit(_ROOT_CAP).all()

    durations = sorted(r.duration_ms or 0 for r in roots)
    errors = sum(1 for r in roots if r.status == "failed")
    count = len(roots)

    def _bucket_key(dt) -> str:
        return dt.strftime("%Y-%m-%d") if by_day else dt.strftime("%Y-%m-%dT%H:00")

    # time series: bucket roots by hour (or day for wide windows). Each bucket carries volume,
    # errors, per-bucket latency percentiles, and tokens — enough to trend all four over time.
    series: dict[str, dict] = {}
    bucket_durs: dict[str, list] = {}
    for r in roots:
        dt = r.created_at
        if dt is None:
            continue
        key = _bucket_key(dt)
        b = series.setdefault(key, {"t": key, "count": 0, "errors": 0, "tokens": 0, "p50": 0, "p95": 0})
        b["count"] += 1
        if r.status == "failed":
            b["errors"] += 1
        bucket_durs.setdefault(key, []).append(r.duration_ms or 0)

    for key, durs in bucket_durs.items():
        ds = sorted(durs)
        series[key]["p50"] = _pct(ds, 50)
        series[key]["p95"] = _pct(ds, 95)

    # token totals + per-model breakdown + per-bucket tokens, across all spans in the window
    spanq = db.query(Run.result, Run.request, Run.created_at).filter(Run.workspace_id == ws.id)
    if cutoff is not None:
        spanq = spanq.filter(Run.created_at >= cutoff)
    total_tokens = 0
    by_model: dict[str, dict] = {}
    for result, request, created in spanq.limit(_SPAN_CAP):
        tok = _usage_tokens(result)
        total_tokens += tok
        if tok and created is not None:
            b = series.get(_bucket_key(created))
            if b is not None:
                b["tokens"] += tok
        model = (request or {}).get("model") if isinstance(request, dict) else None
        if model:
            m = by_model.setdefault(model, {"model": model, "calls": 0, "tokens": 0})
            m["calls"] += 1
            m["tokens"] += tok

    # Failure breakdown: which span types fail, the most common error messages, and the
    # latest failing spans — so the dashboard answers "what's broken?", not just "how often".
    def _fail_filter(q):
        q = q.filter(Run.workspace_id == ws.id, Run.status == "failed")
        return q.filter(Run.created_at >= cutoff) if cutoff is not None else q

    fail_by_type = [
        {"type": t, "count": c}
        for t, c in _fail_filter(db.query(Run.type, func.count(Run.id)))
        .group_by(Run.type).order_by(func.count(Run.id).desc()).all()
    ]
    top_errors = [
        {"error": (e or "").splitlines()[0][:160] if e else "(no message)", "type": t, "count": c}
        for e, t, c in _fail_filter(db.query(Run.error, Run.type, func.count(Run.id)))
        .filter(Run.error != "").group_by(Run.error, Run.type)
        .order_by(func.count(Run.id).desc()).limit(6).all()
    ]
    recent_failures = [
        {"label": r.label, "type": r.type, "trace_id": r.trace_id,
         "error": (r.error or "").splitlines()[0][:160] if r.error else "",
         "at": iso_utc(r.created_at)}
        for r in _fail_filter(db.query(Run)).order_by(Run.id.desc()).limit(8).all()
    ]

    return {
        "window_hours": window_hours,
        "trace_count": count,
        "error_count": errors,
        "error_rate": round(errors / count, 4) if count else 0.0,
        "latency_p50_ms": _pct(durations, 50),
        "latency_p95_ms": _pct(durations, 95),
        "total_tokens": total_tokens,
        "series": sorted(series.values(), key=lambda b: b["t"]),
        "by_model": sorted(by_model.values(), key=lambda m: m["tokens"], reverse=True)[:10],
        "fail_by_type": fail_by_type,
        "top_errors": top_errors,
        "recent_failures": recent_failures,
        "generated_at": iso_utc(_now()),
    }
