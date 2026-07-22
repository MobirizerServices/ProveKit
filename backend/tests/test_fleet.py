"""Fleet health — per-tenant attribution for the operator console (roadmap #84).

Two properties matter and neither is "the endpoint returns 200":

* **The ordering is the feature.** The operator's question is "who is responsible for what the
  instance dashboard is showing me", so the tenant producing the failures must sort above an
  equally busy tenant that is fine.
* **It must not lie about the current hour.** Rollups only cover closed hours, and the hour an
  operator is actually investigating is the open one. Traffic from the last few minutes has to
  appear, or the page is useless during the incident it exists for.

Everything here goes through the real app (`provekit.main.app`) and the real router.
"""
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from provekit.config import get_settings
from provekit.database import SessionLocal
from provekit.main import app
from provekit.models import MetricRollup, ModelRollup, Run, Workspace, _now
from provekit.services import fleet, rollups
from tests.conftest import ingest_workspace_id

NOISY = 840001      # same volume as QUIET, but failing
QUIET = 840002
FRESH = 840003      # traffic only in the still-filling hour
SEEDED = (NOISY, QUIET, FRESH)


def _client():
    return TestClient(app, base_url="https://testserver")


def _fleet(c, qs=""):
    r = c.get(f"/api/admin/fleet{qs}")
    assert r.status_code == 200, r.text
    return r.json()


def _row(body, ws_id):
    return next((t for t in body["tenants"] if t["workspace_id"] == ws_id), None)


def _add(db, ws_id, at, n, failed, *, tag):
    """n root spans (traces), each with one child, at `at`."""
    for i in range(n):
        tid = f"{ws_id:08x}{tag}{i:012x}"[:32]
        root, child = f"r{ws_id}{tag}{i}"[:16], f"c{ws_id}{tag}{i}"[:16]
        db.add(Run(workspace_id=ws_id, type="agent", label=f"root-{i}",
                   status="failed" if i < failed else "completed", duration_ms=120,
                   trace_id=tid, span_id=root, parent_span_id="", created_at=at,
                   request={"input": "x" * 40}, result={"text": "y" * 40}))
        db.add(Run(workspace_id=ws_id, type="llm", label="call", status="completed",
                   duration_ms=60, trace_id=tid, span_id=child, parent_span_id=root,
                   created_at=at, request={"model": "gpt-4o"},
                   result={"meta": {"usage": {"input_tokens": 10, "output_tokens": 2}}}))


@pytest.fixture
def seeded():
    """Three tenants with a known shape, plus the rollups a live instance would already have.

    The background task in main.py folds closed hours; the fleet view deliberately does not
    build them itself (that would be a write, across every tenant, on an admin read), so the
    fixture builds them the same way the background pass does.
    """
    db = SessionLocal()
    owner = db.query(Workspace).filter(Workspace.id == ingest_workspace_id()).first()
    for ws_id in SEEDED:
        db.query(Run).filter(Run.workspace_id == ws_id).delete()
        db.query(MetricRollup).filter(MetricRollup.workspace_id == ws_id).delete()
        db.query(ModelRollup).filter(ModelRollup.workspace_id == ws_id).delete()
        if db.query(Workspace).filter(Workspace.id == ws_id).first() is None:
            db.add(Workspace(id=ws_id, name=f"fleet-{ws_id}",
                             owner_user_id=owner.owner_user_id if owner else 1))
    db.commit()

    now = _now()
    open_hour = rollups.floor_hour(now)
    # Closed hours: equal volume, only NOISY fails. Weighted to the recent half so the trend
    # column has something true to report.
    _add(db, NOISY, open_hour - timedelta(hours=5), 20, 6, tag="a")
    _add(db, NOISY, open_hour - timedelta(hours=2), 40, 12, tag="b")
    _add(db, QUIET, open_hour - timedelta(hours=5), 20, 0, tag="a")
    _add(db, QUIET, open_hour - timedelta(hours=2), 40, 0, tag="b")
    # FRESH has landed only in the hour that has no rollup yet.
    _add(db, FRESH, now, 7, 1, tag="n")
    db.commit()

    for ws_id in (NOISY, QUIET):
        for h in (5, 2):
            rollups.build_hour(db, ws_id, open_hour - timedelta(hours=h))
    db.commit()
    db.close()
    yield
    db = SessionLocal()
    for ws_id in SEEDED:
        db.query(Run).filter(Run.workspace_id == ws_id).delete()
        db.query(MetricRollup).filter(MetricRollup.workspace_id == ws_id).delete()
        db.query(ModelRollup).filter(ModelRollup.workspace_id == ws_id).delete()
    db.commit()
    db.close()


@pytest.fixture
def operator():
    s = get_settings()
    s.superuser_emails = "local@provekit"
    try:
        yield _client()
    finally:
        s.superuser_emails = ""


def test_fleet_requires_superuser():
    assert _client().get("/api/admin/fleet").status_code == 403


def test_the_failing_tenant_outranks_an_equally_busy_healthy_one(seeded, operator):
    """Both tenants sent 60 traces. Only one of them is what the operator is looking at."""
    body = _fleet(operator, "?limit=50")
    order = [t["workspace_id"] for t in body["tenants"]]
    assert order.index(NOISY) < order.index(QUIET)

    noisy, quiet = _row(body, NOISY), _row(body, QUIET)
    assert noisy["traces"] == 60 and quiet["traces"] == 60
    assert noisy["errors"] == 18 and quiet["errors"] == 0
    assert noisy["error_rate"] == pytest.approx(0.3, abs=1e-3)
    assert quiet["error_rate"] == 0.0
    assert noisy["blame"] > quiet["blame"]
    # The share columns are what let the UI say "this tenant is N% of what you're seeing".
    assert 0 < noisy["error_share"] <= 1 and 0 < noisy["volume_share"] <= 1


def test_traffic_in_the_still_filling_hour_is_counted(seeded, operator):
    """FRESH has no rollup row at all — it exists only in raw spans from minutes ago. If the
    view read rollups alone it would report a tenant that is actively ingesting as silent."""
    body = _fleet(operator, "?limit=50")
    fresh = _row(body, FRESH)
    assert fresh is not None, "a tenant ingesting right now must appear"
    assert fresh["traces"] == 7 and fresh["errors"] == 1
    assert fresh["last_ingest_at"] and fresh["ingest_age_seconds"] < 300
    assert body["partial_open_hour"] is False


def test_trend_compares_the_two_halves_of_the_window(seeded, operator):
    """20 traces five hours ago, 40 two hours ago — a rise the operator should see named."""
    body = _fleet(operator, "?limit=50&window_hours=8")
    noisy = _row(body, NOISY)
    assert noisy["prior_traces"] == 20 and noisy["recent_traces"] == 40
    assert noisy["trend_pct"] == pytest.approx(100.0)
    # A tenant with no baseline reports no trend rather than an infinite one.
    assert _row(body, FRESH)["trend_pct"] is None


def test_size_estimate_is_labelled_and_bounded_by_retention(seeded, operator):
    """Storage is extrapolated from a bounded sample, so it must say it is approximate — and
    it must respect the retention that caps how much a tenant can actually occupy."""
    body = _fleet(operator, "?limit=50")
    assert body["approximate"] is True
    noisy = _row(body, NOISY)
    assert noisy["bytes_per_span"] > 0 and noisy["sampled_spans"] > 0
    assert noisy["spans_per_trace"] == pytest.approx(2.0, abs=0.2)   # one child per root
    assert noisy["ingest_bytes"] > 0
    assert noisy["retention_spans"] == get_settings().runs_retention

    db = SessionLocal()
    db.query(Workspace).filter(Workspace.id == NOISY).update({"retention": 10})
    db.commit()
    db.close()
    try:
        capped = _row(_fleet(operator, "?limit=50"), NOISY)
        assert capped["retention_spans"] == 10
        # 60 traces x ~2 spans is well past a 10-span cap, so the estimate must be clamped.
        assert capped["storage_bytes"] <= 10 * capped["bytes_per_span"] + 1
        assert capped["storage_bytes"] < noisy["storage_bytes"]
    finally:
        db = SessionLocal()
        db.query(Workspace).filter(Workspace.id == NOISY).update({"retention": 0})
        db.commit()
        db.close()


def test_paging_and_window_are_clamped(operator):
    """This is an admin page on an instance that may have thousands of tenants; an unbounded
    `limit` would turn one careless URL into a per-tenant sample query per row."""
    body = _fleet(operator, "?limit=99999&window_hours=99999")
    assert body["limit"] == fleet.MAX_LIMIT
    assert body["window_hours"] == fleet.MAX_WINDOW_HOURS
    assert len(body["tenants"]) <= fleet.MAX_LIMIT
    tight = _fleet(operator, "?limit=-3&window_hours=1")
    assert tight["limit"] == 1 and tight["window_hours"] == 2
    assert len(tight["tenants"]) <= 1


def test_instance_block_carries_the_ingest_backlog(seeded, operator):
    """The fleet table sits next to the reason someone opened it: /healthz's ingest block is
    instance-wide, this page says which tenant is behind it."""
    body = _fleet(operator, "?limit=50")
    inst = body["instance"]
    assert "spool" in inst["ingest"]
    assert inst["traces"] >= 127 and inst["errors"] >= 19
    assert inst["tenants_active"] >= 3
    assert body["total"] >= len(body["tenants"])
    # Shares are shares *of the instance*, not of the returned page.
    for t in body["tenants"]:
        assert t["volume_share"] <= 1.0 and t["error_share"] <= 1.0


def test_a_bounded_open_hour_scan_admits_when_it_was_bounded(seeded, operator, monkeypatch):
    """The open hour is read from a tail of the newest ids, not a `created_at` scan. On an
    instance ingesting more than that per hour the count is a floor — and the failure mode
    rollups.py exists to prevent is a truncated aggregate that renders like a complete one."""
    monkeypatch.setattr(fleet, "OPEN_SCAN_ROWS", 1)
    body = _fleet(operator, "?limit=50")
    assert body["partial_open_hour"] is True


def test_a_tenant_whose_spans_were_pruned_still_reports_its_volume(operator):
    """Retention deletes spans; the rollups outlive them. The tenant must still show the
    traffic it produced, and report no size rather than a wrong one."""
    ws_id = 840004
    db = SessionLocal()
    owner = db.query(Workspace).filter(Workspace.id == ingest_workspace_id()).first()
    db.query(Run).filter(Run.workspace_id == ws_id).delete()
    db.query(MetricRollup).filter(MetricRollup.workspace_id == ws_id).delete()
    if db.query(Workspace).filter(Workspace.id == ws_id).first() is None:
        db.add(Workspace(id=ws_id, name="pruned",
                         owner_user_id=owner.owner_user_id if owner else 1))
    db.add(MetricRollup(workspace_id=ws_id,
                        bucket=rollups.floor_hour(_now()) - timedelta(hours=1),
                        trace_count=30, error_count=3, latency_hist=[]))
    db.commit()
    db.close()
    try:
        row = _row(_fleet(operator, "?limit=50"), ws_id)
        assert row is not None and row["name"] == "pruned"
        assert row["traces"] == 30 and row["errors"] == 3
        assert row["last_ingest_at"] is None and row["ingest_age_seconds"] is None
        assert row["sampled_spans"] == 0 and row["bytes_per_span"] == 0
        assert row["storage_bytes"] == 0 and row["ingest_bytes"] == 0
    finally:
        db = SessionLocal()
        db.query(MetricRollup).filter(MetricRollup.workspace_id == ws_id).delete()
        db.commit()
        db.close()


def test_rows_with_no_trace_id_are_sized_one_by_one(operator):
    """Replays and eval rows are written outside OTLP ingest and carry no trace id. Treating
    them as one giant trace would inflate the fan-out and every size estimate built on it."""
    ws_id = 840005
    db = SessionLocal()
    owner = db.query(Workspace).filter(Workspace.id == ingest_workspace_id()).first()
    db.query(Run).filter(Run.workspace_id == ws_id).delete()
    if db.query(Workspace).filter(Workspace.id == ws_id).first() is None:
        db.add(Workspace(id=ws_id, name="loose",
                         owner_user_id=owner.owner_user_id if owner else 1))
    for i in range(3):
        db.add(Run(workspace_id=ws_id, type="agent", label=f"replay-{i}", status="completed",
                   duration_ms=10, trace_id="", span_id="", parent_span_id="",
                   created_at=_now(), request={"input": "z" * 30}, result={}))
    db.commit()
    db.close()
    try:
        row = _row(_fleet(operator, "?limit=50"), ws_id)
        assert row is not None and row["traces"] == 3
        assert row["spans_per_trace"] == 1.0
        assert row["bytes_per_span"] > 0
    finally:
        db = SessionLocal()
        db.query(Run).filter(Run.workspace_id == ws_id).delete()
        db.commit()
        db.close()


def test_blame_falls_back_to_volume_on_a_healthy_instance():
    """With nothing failing anywhere, "who am I looking at" is purely a volume question —
    and the error term must not divide by zero to get there."""
    assert fleet._blame(30, 0, 100, 0) == pytest.approx(0.3)
    assert fleet._blame(0, 0, 0, 0) == 0.0
    # Errors dominate once there are any: a tenth of the volume, all of the failures.
    assert fleet._blame(10, 5, 100, 5) > fleet._blame(90, 0, 100, 5)
    assert fleet._aware(None) is None
    db = SessionLocal()
    try:
        assert fleet._lifetime_traces(db, []) == {}
    finally:
        db.close()


def test_an_impersonating_operator_cannot_use_the_fleet_view(seeded, operator):
    """Support mode is a tenant's view; operator tools stay operator tools (see
    require_superuser). Asserted through the real app, not a hand-wrapped stack."""
    ws = ingest_workspace_id()
    started = operator.post("/api/admin/impersonate",
                            json={"workspace_id": ws, "reason": "checking a report"})
    assert started.status_code == 200, started.text
    try:
        assert operator.get("/api/admin/fleet").status_code == 403
    finally:
        operator.delete("/api/admin/impersonate")
    assert operator.get("/api/admin/fleet").status_code == 200
