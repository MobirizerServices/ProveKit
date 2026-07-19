"""Metrics — aggregate numbers behind the portal dashboard: trace volume, error rate,
latency percentiles, token usage, a time series, and a per-model breakdown, over a window."""
import math
from datetime import timedelta

from fastapi import APIRouter, Depends
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
    cutoff = _now() - timedelta(hours=window_hours) if window_hours > 0 else None
    by_day = window_hours == 0 or window_hours > 48

    rootq = db.query(Run).filter(Run.workspace_id == ws.id, Run.parent_span_id == "")
    if cutoff is not None:
        rootq = rootq.filter(Run.created_at >= cutoff)
    roots = rootq.order_by(Run.id.desc()).limit(_ROOT_CAP).all()

    durations = sorted(r.duration_ms or 0 for r in roots)
    errors = sum(1 for r in roots if r.status == "failed")
    count = len(roots)

    # time series: bucket roots by hour (or day for wide windows)
    series: dict[str, dict] = {}
    for r in roots:
        dt = r.created_at
        if dt is None:
            continue
        key = dt.strftime("%Y-%m-%d") if by_day else dt.strftime("%Y-%m-%dT%H:00")
        b = series.setdefault(key, {"t": key, "count": 0, "errors": 0})
        b["count"] += 1
        if r.status == "failed":
            b["errors"] += 1

    # token totals + per-model breakdown, across all spans in the window
    spanq = db.query(Run.result, Run.request).filter(Run.workspace_id == ws.id)
    if cutoff is not None:
        spanq = spanq.filter(Run.created_at >= cutoff)
    total_tokens = 0
    by_model: dict[str, dict] = {}
    for result, request in spanq.limit(_SPAN_CAP):
        tok = _usage_tokens(result)
        total_tokens += tok
        model = (request or {}).get("model") if isinstance(request, dict) else None
        if model:
            m = by_model.setdefault(model, {"model": model, "calls": 0, "tokens": 0})
            m["calls"] += 1
            m["tokens"] += tok

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
        "generated_at": iso_utc(_now()),
    }
