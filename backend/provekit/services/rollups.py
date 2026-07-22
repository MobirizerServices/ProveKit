"""Hourly pre-aggregation for the dashboard.

`/api/metrics` computed everything by reading raw spans on every request. On a busy project a
90-day window is a full scan of the largest table in the schema, on the most-loaded page in
the product — and it was worse than slow. The scan was bounded by `_ROOT_CAP` / `_SPAN_CAP`,
so past those limits the dashboard didn't get slower, it got *wrong*: a truncated sample
rendered identically to a complete one, with no indication that most of the window had been
dropped.

So: fold closed hours into a rollup row once, and read those instead. The open hour is still
computed from raw rows, because a dashboard that lags an hour behind is not a dashboard.

**Percentiles.** Averages and counts merge trivially; percentiles don't — you cannot average
two p95s and get the p95. Each bucket therefore stores a latency histogram, which *is*
mergeable, and percentiles are read off the merged histogram. Bucket edges are 2^(i/4), i.e.
about 19% apart, from 1ms to ~2M ms; with interpolation inside the bucket that is well under
the noise on any real latency figure, and unlike the old sampled scan it is honest about
covering the whole window.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import MetricRollup, ModelRollup, Run, Workspace, _now

# 4 sub-buckets per octave: fine enough that interpolated p95 error is negligible, coarse
# enough that a bucket is ~90 small integers rather than a stored sample of every duration.
_BUCKETS = 88
_EDGES = [2 ** (i / 4) for i in range(_BUCKETS)]


def bucket_index(ms: float) -> int:
    if ms <= 1:
        return 0
    return min(_BUCKETS - 1, int(math.log2(ms) * 4))


def empty_histogram() -> list[int]:
    return [0] * _BUCKETS


def add_to_histogram(hist: list[int], ms: float) -> None:
    hist[bucket_index(ms)] += 1


def merge_histograms(hists) -> list[int]:
    out = empty_histogram()
    for h in hists:
        if not h:
            continue
        for i, n in enumerate(h[:_BUCKETS]):
            out[i] += n
    return out


def percentile(hist: list[int], p: float) -> int:
    """Read a percentile off a merged histogram.

    Interpolates across the bucket's own width rather than returning its edge, which would
    quantise every latency figure on the dashboard to the same ~19% grid.
    """
    total = sum(hist)
    if not total:
        return 0
    target = (total - 1) * p / 100.0
    seen = 0
    for i, n in enumerate(hist):
        if n and seen + n > target:
            lo = _EDGES[i]
            hi = _EDGES[i + 1] if i + 1 < _BUCKETS else lo * 2
            frac = (target - seen) / n
            return int(round(lo + (hi - lo) * frac))
        seen += n
    return int(round(_EDGES[-1]))


def floor_hour(dt: datetime) -> datetime:
    return dt.replace(minute=0, second=0, microsecond=0)


def ceil_hour(dt: datetime) -> datetime:
    """The first hour boundary at or after `dt`.

    A window's start almost never lands on one, and a rollup covers a *whole* hour — so the
    hour containing the cutoff is only partly inside the window and must be read from raw rows
    instead. Rounding down here instead would silently widen a "last 24 hours" to 25.
    """
    floored = floor_hour(dt)
    return floored if floored == dt else floored + timedelta(hours=1)


def _usage_pair(result) -> tuple[int, int, bool]:
    """Mirror of metrics._usage_pair — kept here so rollup building doesn't import the router."""
    if not isinstance(result, dict):
        return 0, 0, False
    u = (result.get("meta") or {}).get("usage") or {}
    it, ot = u.get("input_tokens"), u.get("output_tokens")
    return (it or 0), (ot or 0), (it is not None or ot is not None)


def build_hour(db: Session, workspace_id: int, hour: datetime) -> MetricRollup:
    """Aggregate one closed hour from raw spans. Idempotent: rebuilding replaces the row.

    Deliberately unbounded — this reads the hour once, ever, so there is no reason to sample
    it, and sampling is what made the old path quietly inaccurate.
    """
    nxt = hour + timedelta(hours=1)
    in_hour = (Run.workspace_id == workspace_id, Run.created_at >= hour, Run.created_at < nxt)

    hist = empty_histogram()
    traces = errors = 0
    for duration, status in db.query(Run.duration_ms, Run.status).filter(
            *in_hour, Run.parent_span_id == "").all():
        traces += 1
        if status == "failed":
            errors += 1
        add_to_histogram(hist, duration or 0)

    total_in = total_out = 0
    model_calls = usage_spans = 0
    per_model: dict[str, dict] = {}
    for result, request in db.query(Run.result, Run.request).filter(*in_hour).all():
        it, ot, reported = _usage_pair(result)
        total_in += it
        total_out += ot
        model = (request or {}).get("model") if isinstance(request, dict) else None
        if model:
            model_calls += 1
            usage_spans += 1 if reported else 0
            m = per_model.setdefault(model, {"calls": 0, "input": 0, "output": 0, "usage": 0})
            m["calls"] += 1
            m["input"] += it
            m["output"] += ot
            m["usage"] += 1 if reported else 0

    fail_by_type = dict(
        db.query(Run.type, func.count(Run.id)).filter(*in_hour, Run.status == "failed")
        .group_by(Run.type).all())

    row = (db.query(MetricRollup)
           .filter(MetricRollup.workspace_id == workspace_id, MetricRollup.bucket == hour)
           .first())
    if row is None:
        row = MetricRollup(workspace_id=workspace_id, bucket=hour)
        db.add(row)
    row.trace_count = traces
    row.error_count = errors
    row.latency_hist = hist
    row.input_tokens = total_in
    row.output_tokens = total_out
    row.model_calls = model_calls
    row.usage_spans = usage_spans
    row.fail_by_type = fail_by_type

    db.query(ModelRollup).filter(ModelRollup.workspace_id == workspace_id,
                                 ModelRollup.bucket == hour).delete()
    for model, m in per_model.items():
        db.add(ModelRollup(workspace_id=workspace_id, bucket=hour, model=model[:200],
                           calls=m["calls"], input_tokens=m["input"], output_tokens=m["output"],
                           usage_spans=m["usage"]))
    return row


def ensure_range(db: Session, workspace_id: int, start: datetime, end: datetime,
                 *, max_hours: int = 24 * 400) -> int:
    """Build whatever closed hours in [start, end) are missing. Returns how many were built.

    Called on the read path, so the first dashboard load after a gap pays to fill it and every
    load after that is cheap. Only hours that actually contain spans get a row: a project idle
    for a month shouldn't materialise 720 rows of zeroes.
    """
    start, end = floor_hour(start), floor_hour(end)
    if end <= start:
        return 0
    have = {r[0] for r in db.query(MetricRollup.bucket).filter(
        MetricRollup.workspace_id == workspace_id,
        MetricRollup.bucket >= start, MetricRollup.bucket < end).all()}

    # One grouped query tells us which hours have data at all, so we don't probe empty ones.
    populated = {floor_hour(dt) for (dt,) in db.query(Run.created_at).filter(
        Run.workspace_id == workspace_id, Run.created_at >= start, Run.created_at < end).all()}

    todo = sorted(populated - have)[:max_hours]
    for hour in todo:
        build_hour(db, workspace_id, hour)
    if todo:
        db.commit()
    return len(todo)


def backfill_all(db: Session, *, since_hours: int = 24 * 90) -> int:
    """Fill rollups for every workspace — the background pass, so a dashboard load rarely has
    to build anything itself."""
    end = floor_hour(_now())
    start = end - timedelta(hours=since_hours)
    built = 0
    for (ws_id,) in db.query(Workspace.id).all():
        built += ensure_range(db, ws_id, start, end)
    return built


def prune(db: Session, workspace_id: int, before: datetime) -> int:
    """Drop rollups older than a retention horizon."""
    n = db.query(MetricRollup).filter(MetricRollup.workspace_id == workspace_id,
                                      MetricRollup.bucket < before).delete()
    db.query(ModelRollup).filter(ModelRollup.workspace_id == workspace_id,
                                 ModelRollup.bucket < before).delete()
    return n
