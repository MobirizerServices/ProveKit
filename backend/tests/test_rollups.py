"""Hourly rollups behind the dashboard.

The property that matters is equivalence: reading pre-aggregated hours must produce the same
answer as reading the raw spans. A rollup that is fast and subtly wrong is worse than the scan
it replaced, because nothing about the dashboard would look different.
"""
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from provekit.database import SessionLocal
from provekit.main import app
from provekit.models import MetricRollup, ModelRollup, Run, Workspace, _now
from provekit.routers.metrics import compute_metrics
from provekit.services import rollups

WS = 909090


@pytest.fixture
def seeded():
    """A project whose spans are spread over the last few days — i.e. mostly closed hours,
    which is the case the old code path capped and this one rolls up."""
    db = SessionLocal()
    db.query(Run).filter(Run.workspace_id == WS).delete()
    db.query(MetricRollup).filter(MetricRollup.workspace_id == WS).delete()
    db.query(ModelRollup).filter(ModelRollup.workspace_id == WS).delete()
    ws = db.query(Workspace).filter(Workspace.id == WS).first()
    if ws is None:
        owner = db.query(Workspace).first()
        ws = Workspace(id=WS, name="rollup-test", owner_user_id=owner.owner_user_id if owner else 1)
        db.add(ws)
    now = _now()
    sid = 0                                     # span ids must be unique per (ws, trace)
    for h in range(1, 73):                      # 72 closed hours back
        at = rollups.floor_hour(now) - timedelta(hours=h)
        for i in range(5):
            failed = (h + i) % 11 == 0
            tid = f"{h:016x}{i:016x}"
            sid += 1
            root_span = f"{sid:016x}"
            sid += 1
            child_span = f"{sid:016x}"
            db.add(Run(workspace_id=WS, type="agent", label=f"root-{h}-{i}",
                       status="failed" if failed else "completed",
                       duration_ms=100 + (h * 7 + i * 13) % 900,
                       trace_id=tid, span_id=root_span,
                       parent_span_id="", created_at=at + timedelta(minutes=i),
                       request={}, result={}))
            db.add(Run(workspace_id=WS, type="llm", label="call",
                       status="completed", duration_ms=50,
                       trace_id=tid, span_id=child_span, parent_span_id=root_span,
                       created_at=at + timedelta(minutes=i),
                       request={"model": "gpt-4o" if i % 2 else "claude-sonnet-5"},
                       result={"meta": {"usage": {"input_tokens": 100 + i,
                                                  "output_tokens": 10 + i}}}))
    db.commit()
    db.close()
    yield WS
    db = SessionLocal()
    db.query(Run).filter(Run.workspace_id == WS).delete()
    db.query(MetricRollup).filter(MetricRollup.workspace_id == WS).delete()
    db.query(ModelRollup).filter(ModelRollup.workspace_id == WS).delete()
    db.commit()
    db.close()


def _raw_truth(db, hours: int) -> dict:
    """Compute the same numbers straight from raw spans — the reference the rollups must match."""
    cutoff = _now() - timedelta(hours=hours)
    roots = db.query(Run).filter(Run.workspace_id == WS, Run.parent_span_id == "",
                                 Run.created_at >= cutoff).all()
    spans = db.query(Run).filter(Run.workspace_id == WS, Run.created_at >= cutoff).all()
    tokens = 0
    for s in spans:
        u = ((s.result or {}).get("meta") or {}).get("usage") or {}
        tokens += (u.get("input_tokens") or 0) + (u.get("output_tokens") or 0)
    return {"traces": len(roots),
            "errors": sum(1 for r in roots if r.status == "failed"),
            "tokens": tokens}


def test_rollups_match_a_raw_scan(seeded):
    """The whole contract, in one assertion set."""
    db = SessionLocal()
    try:
        ws = db.query(Workspace).filter(Workspace.id == WS).first()
        m = compute_metrics(db, ws, 48)
        truth = _raw_truth(db, 48)
        assert m["trace_count"] == truth["traces"]
        assert m["error_count"] == truth["errors"]
        assert m["total_tokens"] == truth["tokens"]
    finally:
        db.close()


def test_a_multi_day_window_still_matches_raw(seeded):
    """Equivalence has to hold across many closed hours, not just a couple — this is the shape
    that used to be a capped scan of the raw table."""
    db = SessionLocal()
    try:
        ws = db.query(Workspace).filter(Workspace.id == WS).first()
        m = compute_metrics(db, ws, 72)
        truth = _raw_truth(db, 72)
        assert m["trace_count"] == truth["traces"] >= 71 * 5
        assert m["error_count"] == truth["errors"]
        assert m["total_tokens"] == truth["tokens"]
    finally:
        db.close()


def test_the_window_edge_is_not_widened_to_the_hour(seeded):
    """A rollup covers a whole hour, but "last 48 hours" must not quietly become 49. The hour
    the cutoff lands in is read from raw rows for exactly this reason."""
    db = SessionLocal()
    try:
        ws = db.query(Workspace).filter(Workspace.id == WS).first()
        assert compute_metrics(db, ws, 48)["trace_count"] == _raw_truth(db, 48)["traces"]
        assert compute_metrics(db, ws, 24)["trace_count"] == _raw_truth(db, 24)["traces"]
    finally:
        db.close()


def test_second_load_reuses_rollups(seeded):
    """The point of pre-aggregation: the first load builds, the rest read."""
    db = SessionLocal()
    try:
        ws = db.query(Workspace).filter(Workspace.id == WS).first()
        compute_metrics(db, ws, 72)
        built = db.query(MetricRollup).filter(MetricRollup.workspace_id == WS).count()
        assert built >= 70
        # A second load of the same window must build nothing new.
        start = rollups.ceil_hour(_now() - timedelta(hours=72))
        assert rollups.ensure_range(db, WS, start, rollups.floor_hour(_now())) == 0
    finally:
        db.close()


def test_rebuilding_an_hour_is_idempotent(seeded):
    """Rollups are rebuilt after a backfill or a repair; doing so must not double the numbers."""
    db = SessionLocal()
    try:
        hour = rollups.floor_hour(_now()) - timedelta(hours=5)
        first = rollups.build_hour(db, WS, hour)
        db.commit()
        counts = (first.trace_count, first.input_tokens, first.output_tokens)
        again = rollups.build_hour(db, WS, hour)
        db.commit()
        assert (again.trace_count, again.input_tokens, again.output_tokens) == counts
        assert db.query(MetricRollup).filter(MetricRollup.workspace_id == WS,
                                             MetricRollup.bucket == hour).count() == 1
        assert db.query(ModelRollup).filter(ModelRollup.workspace_id == WS,
                                            ModelRollup.bucket == hour).count() == 2
    finally:
        db.close()


def test_per_model_totals_survive_aggregation(seeded):
    db = SessionLocal()
    try:
        ws = db.query(Workspace).filter(Workspace.id == WS).first()
        m = compute_metrics(db, ws, 72)
        models = {row["model"]: row for row in m["by_model"]}
        assert set(models) == {"gpt-4o", "claude-sonnet-5"}
        for row in models.values():
            assert row["input_tokens"] + row["output_tokens"] == row["tokens"]
            assert row["input_tokens"] > row["output_tokens"]     # as seeded
        assert sum(r["calls"] for r in models.values()) == _raw_truth(db, 72)["traces"]
    finally:
        db.close()


# -- histogram ---------------------------------------------------------------------------

def test_histogram_percentiles_track_the_exact_ones():
    """Percentiles are read off a merged histogram because they don't average. The bucket
    layout has to be fine enough that the number on the dashboard is still the right number."""
    values = list(range(1, 2001))
    h = rollups.empty_histogram()
    for v in values:
        rollups.add_to_histogram(h, v)
    for p, exact in ((50, 1000), (95, 1900), (99, 1980)):
        got = rollups.percentile(h, p)
        assert abs(got - exact) / exact < 0.10, f"p{p}: {got} vs {exact}"


def test_histograms_merge():
    """A day bucket is 24 hourly histograms; merging must equal aggregating the raw values."""
    a, b = rollups.empty_histogram(), rollups.empty_histogram()
    for v in range(1, 501):
        rollups.add_to_histogram(a, v)
    for v in range(501, 1001):
        rollups.add_to_histogram(b, v)
    merged = rollups.merge_histograms([a, b])
    direct = rollups.empty_histogram()
    for v in range(1, 1001):
        rollups.add_to_histogram(direct, v)
    assert merged == direct
    assert sum(merged) == 1000


def test_percentile_of_nothing_is_zero():
    assert rollups.percentile(rollups.empty_histogram(), 95) == 0
