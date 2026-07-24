"""Metrics — aggregate numbers behind the portal dashboard: trace volume, error rate,
latency percentiles, token usage, a time series, and a per-model breakdown, over a window."""
import math
from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import doctor
from ..database import get_db
from ..models import MetricRollup, ModelRollup, Run, Workspace, _now, iso_utc
from ..services import pricing, rollups
from ..services.workspace import current_workspace

router = APIRouter(prefix="/api/metrics", tags=["metrics"])
# Separate router: a rate card is not a metric, and it is not tenant data. Deliberately
# unauthenticated — it contains published vendor prices and nothing about any workspace.
pricing_router = APIRouter(prefix="/api/pricing", tags=["pricing"])


# Same reasoning as the rate card: a published catalogue, not tenant data, and the portal
# should read it rather than keep a second copy that drifts (#30).
coverage_router = APIRouter(prefix="/api/coverage", tags=["coverage"])


@coverage_router.get("")
def instrumentation_coverage():
    """What ProveKit can auto-instrument, served so the portal stops maintaining a copy (#30).

    Deliberately the catalogue only. The *local* answer — which of these are installed and
    actually instrumented — depends on the user's virtualenv, on a machine this server has
    never seen, and is what `provekit doctor` reports. Inferring "you aren't instrumenting
    langchain" from an absence of langchain spans would be a guess: a project that simply
    doesn't use langchain looks identical.
    """
    return {"libraries": doctor.coverage_catalog(),
            "local_answer": "provekit doctor"}


@pricing_router.get("")
def price_table(version: str | None = None):
    """The rate table, so a client can price tokens without keeping its own copy.

    `version` re-derives a historical cost card: spans carry `meta.price_version`, and asking
    for that version returns the rates that were in force when the span was captured.
    """
    return pricing.as_dict(version)


def _usage_pair(result) -> tuple[int, int, bool]:
    """(input, output, did the provider actually report usage).

    Input and output are priced 3–5x apart, so the split has to survive to the client. It used
    to be flattened to a total and the dashboard guessed 50/50 — which is wrong by a wide
    margin on anything input-heavy like RAG, while rendering exactly like a measured number.

    The third value separates "reported zero" from "reported nothing", so a cost built from
    partial data can be labelled instead of quietly under-reporting.
    """
    if not isinstance(result, dict):
        return 0, 0, False
    u = (result.get("meta") or {}).get("usage") or {}
    it, ot = u.get("input_tokens"), u.get("output_tokens")
    return (it or 0), (ot or 0), (it is not None or ot is not None)


@router.get("")
def metrics(window_hours: int = 24, db: Session = Depends(get_db),
            ws: Workspace = Depends(current_workspace)):
    return compute_metrics(db, ws, window_hours)


def compute_metrics(db: Session, ws: Workspace, window_hours: int) -> dict:
    """The dashboard aggregate. Also called by the alerts evaluator, so it's a plain
    function, not just a route handler.

    Closed hours are read from pre-aggregated rollups (services/rollups.py); only the current,
    still-filling hour is computed from raw spans. Before this, every load re-scanned raw rows
    for the whole window and capped the scan — so a wide window didn't just cost more, it
    quietly returned a partial answer that looked complete.
    """
    now = _now()
    cutoff = now - timedelta(hours=window_hours) if window_hours > 0 else None
    by_day = window_hours == 0 or window_hours > 48
    open_hour = rollups.floor_hour(now)

    # Rollups cover only *whole* hours that fall entirely inside the window. The hour the
    # cutoff lands in, and the hour still filling now, are read from raw rows — otherwise a
    # "last 48 hours" would quietly include part of a 49th.
    if cutoff is None:
        first = (db.query(func.min(Run.created_at))
                 .filter(Run.workspace_id == ws.id).scalar())
        roll_start = rollups.floor_hour(first) if first else open_hour
        live_ranges = [(open_hour, None)]
    else:
        roll_start = min(rollups.ceil_hour(cutoff), open_hour)
        live_ranges = [(cutoff, roll_start)] if cutoff < roll_start else []
        live_ranges.append((max(open_hour, cutoff), None))
    rollups.ensure_range(db, ws.id, roll_start, open_hour)

    def _bucket_key(dt) -> str:
        return dt.strftime("%Y-%m-%d") if by_day else dt.strftime("%Y-%m-%dT%H:00")

    # Each series bucket keeps a mergeable histogram; percentiles are read off it at the end.
    # A day bucket is many hourly rollups, and p95 is not the mean of hourly p95s.
    series: dict[str, dict] = {}
    hists: dict[str, list[int]] = {}

    def _bucket(key: str) -> dict:
        b = series.setdefault(key, {"t": key, "count": 0, "errors": 0, "tokens": 0,
                                    "p50": 0, "p95": 0})
        hists.setdefault(key, rollups.empty_histogram())
        return b

    total_hist = rollups.empty_histogram()
    count = errors = 0
    total_in = total_out = 0
    model_calls = usage_spans = 0
    by_model: dict[str, dict] = {}
    fail_by_type_counts: dict[str, int] = {}

    def _model_row(model: str) -> dict:
        return by_model.setdefault(model, {"model": model, "calls": 0, "tokens": 0,
                                           "input_tokens": 0, "output_tokens": 0,
                                           "usage_spans": 0})

    # ---- closed hours, from rollups -------------------------------------------------------
    rolled = db.query(MetricRollup).filter(
        MetricRollup.workspace_id == ws.id,
        MetricRollup.bucket >= roll_start, MetricRollup.bucket < open_hour).all()
    for r in rolled:
        key = _bucket_key(r.bucket)
        b = _bucket(key)
        b["count"] += r.trace_count
        b["errors"] += r.error_count
        b["tokens"] += r.input_tokens + r.output_tokens
        hists[key] = rollups.merge_histograms([hists[key], r.latency_hist or []])
        total_hist = rollups.merge_histograms([total_hist, r.latency_hist or []])
        count += r.trace_count
        errors += r.error_count
        total_in += r.input_tokens
        total_out += r.output_tokens
        model_calls += r.model_calls
        usage_spans += r.usage_spans
        for t, n in (r.fail_by_type or {}).items():
            fail_by_type_counts[t] = fail_by_type_counts.get(t, 0) + n

    for mr in db.query(ModelRollup).filter(
            ModelRollup.workspace_id == ws.id,
            ModelRollup.bucket >= roll_start, ModelRollup.bucket < open_hour).all():
        m = _model_row(mr.model)
        m["calls"] += mr.calls
        m["input_tokens"] += mr.input_tokens
        m["output_tokens"] += mr.output_tokens
        m["tokens"] += mr.input_tokens + mr.output_tokens
        m["usage_spans"] += mr.usage_spans
        key = _bucket_key(mr.bucket)
        if key in series and (mr.input_tokens or mr.output_tokens):
            bm = series[key].setdefault("by_model", {})
            prev = bm.get(mr.model) or {"input_tokens": 0, "output_tokens": 0}
            prev["input_tokens"] += mr.input_tokens
            prev["output_tokens"] += mr.output_tokens
            bm[mr.model] = prev

    # ---- the partial edges, live -----------------------------------------------------------
    # At most two ranges — the tail of the hour the cutoff lands in, and the hour still
    # filling now — so each is bounded by construction and needs no cap.
    def _window(q, lo, hi):
        q = q.filter(Run.workspace_id == ws.id, Run.created_at >= lo)
        return q.filter(Run.created_at < hi) if hi is not None else q

    for lo, hi in live_ranges:
        for duration, status, created in _window(
                db.query(Run.duration_ms, Run.status, Run.created_at)
                .filter(Run.parent_span_id == ""), lo, hi).all():
            key = _bucket_key(created or now)
            b = _bucket(key)
            b["count"] += 1
            count += 1
            if status == "failed":
                b["errors"] += 1
                errors += 1
            rollups.add_to_histogram(hists[key], duration or 0)
            rollups.add_to_histogram(total_hist, duration or 0)

        for result, request, created in _window(
                db.query(Run.result, Run.request, Run.created_at), lo, hi).all():
            in_tok, out_tok, reported = _usage_pair(result)
            tok = in_tok + out_tok
            total_in += in_tok
            total_out += out_tok
            model = (request or {}).get("model") if isinstance(request, dict) else None
            key = _bucket_key(created or now)
            if tok and key in series:
                series[key]["tokens"] += tok
                if model:
                    bm = series[key].setdefault("by_model", {})
                    prev = bm.get(model) or {"input_tokens": 0, "output_tokens": 0}
                    prev["input_tokens"] += in_tok
                    prev["output_tokens"] += out_tok
                    bm[model] = prev
            if model:
                model_calls += 1
                usage_spans += 1 if reported else 0
                m = _model_row(model)
                m["calls"] += 1
                m["tokens"] += tok
                m["input_tokens"] += in_tok
                m["output_tokens"] += out_tok
                m["usage_spans"] += 1 if reported else 0

    for key, b in series.items():
        b["p50"] = rollups.percentile(hists[key], 50)
        b["p95"] = rollups.percentile(hists[key], 95)

    total_tokens = total_in + total_out

    # Failure breakdown: which span types fail, the most common error messages, and the
    # latest failing spans — so the dashboard answers "what's broken?", not just "how often".
    def _fail_filter(q):
        q = q.filter(Run.workspace_id == ws.id, Run.status == "failed")
        return q.filter(Run.created_at >= cutoff) if cutoff is not None else q

    # Counts come from the rollups (which already carry per-type failures for closed hours)
    # plus the open hour, so this stays correct over a 90-day window without a grouped scan.
    for lo, hi in live_ranges:
        q = _fail_filter(db.query(Run.type, func.count(Run.id))).filter(Run.created_at >= lo)
        if hi is not None:
            q = q.filter(Run.created_at < hi)
        for t, c in q.group_by(Run.type).all():
            fail_by_type_counts[t] = fail_by_type_counts.get(t, 0) + c
    fail_by_type = [{"type": t, "count": c} for t, c in
                    sorted(fail_by_type_counts.items(), key=lambda kv: kv[1], reverse=True)]

    # These two stay raw: error *messages* are high-cardinality and not worth rolling up, and
    # both are small limited queries covered by ix_runs_ws_status_created (#18).
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
        "latency_p50_ms": rollups.percentile(total_hist, 50),
        "latency_p95_ms": rollups.percentile(total_hist, 95),
        "total_tokens": total_tokens,
        # How much of the cost estimate rests on real data: model calls that reported usage
        # vs. all model calls. A figure derived from 40% coverage should not be shown as though
        # it were the bill.
        "usage_coverage": {"reported": usage_spans, "model_calls": model_calls},
        "series": sorted(series.values(), key=lambda b: b["t"]),
        "by_model": sorted(by_model.values(), key=lambda m: m["tokens"], reverse=True)[:10],
        "fail_by_type": fail_by_type,
        "top_errors": top_errors,
        "recent_failures": recent_failures,
        "generated_at": iso_utc(_now()),
    }
