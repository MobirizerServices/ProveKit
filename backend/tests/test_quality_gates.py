"""Two gates that decline to guess (#41, #49).

A threshold gate fails a build when the mean dips, which on twenty examples it does by chance.
A quality alert that reads an unmeasured metric as 0.0 pages someone about a number the product
refuses to show on screen. Both failures look like diligence and are noise, and both are what
these tests pin against.
"""
import uuid
from datetime import timedelta

from fastapi.testclient import TestClient

from provekit.database import SessionLocal
from provekit.main import app
from provekit.models import Feedback, Workspace, _now
from provekit.routers import alerts as alerts_router


def _client():
    return TestClient(app, base_url="https://testserver")


def _account(c) -> tuple[int, dict]:
    email = f"q{uuid.uuid4().hex[:10]}@ex.com"
    assert c.post("/api/auth/register", json={"email": email, "password": "pw12345678"}).status_code == 200
    pid = c.get("/api/projects").json()[0]["id"]
    key = c.post("/api/workspace/ingest-key").json()["ingest_key"]
    return pid, {"Authorization": f"Bearer {key}"}


def _experiment(c, kh, dsid, scores: list[float], name: str) -> int:
    eid = c.post("/v1/experiments", json={"name": name, "dataset_id": dsid}, headers=kh).json()["id"]
    for i, v in enumerate(scores):
        c.post(f"/v1/experiments/{eid}/results",
               json={"item_id": i, "input": f"q{i}", "output": "o", "expected": "e",
                     "scores": {"acc": v}}, headers=kh)
    return eid


# ---------------------------------------------------------------- #41 the significance gate

def test_compare_is_reachable_with_a_project_key():
    """The gate lives in CI, which has a key and no browser session. Without this door the
    significance test existed only behind a cookie — useless exactly where it matters."""
    c = _client()
    _account(c)
    _, kh = _account(c)
    dsid = c.post("/api/datasets", json={"name": "d"}).json()["id"]
    a = _experiment(c, kh, dsid, [1.0, 1.0, 0.0, 1.0], "base")
    b = _experiment(c, kh, dsid, [1.0, 0.0, 0.0, 1.0], "cand")

    r = c.get(f"/v1/experiments/{b}/compare/{a}", headers=kh)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "acc" in body["scorers"] and "comparable" in body


def test_the_portal_and_the_key_door_return_the_same_verdict():
    """A gate that judged by different arithmetic from the dashboard would be a second opinion
    nobody asked for."""
    c = _client()
    _, kh = _account(c)
    dsid = c.post("/api/datasets", json={"name": "d"}).json()["id"]
    a = _experiment(c, kh, dsid, [1.0, 1.0, 0.0], "base")
    b = _experiment(c, kh, dsid, [0.0, 1.0, 0.0], "cand")

    portal = c.get(f"/api/experiments/{b}/compare/{a}").json()
    keyed = c.get(f"/v1/experiments/{b}/compare/{a}", headers=kh).json()
    assert portal["scorers"] == keyed["scorers"]
    assert portal["comparable"] == keyed["comparable"]


def test_a_small_dip_is_reported_as_not_significant():
    """The whole point: a couple of points on a handful of examples is chance, and a gate that
    blocks on it gets its threshold loosened until it blocks nothing."""
    c = _client()
    _, kh = _account(c)
    dsid = c.post("/api/datasets", json={"name": "d"}).json()["id"]
    base = [1.0] * 8 + [0.0] * 2
    cand = [1.0] * 7 + [0.0] * 3          # one example worse
    a = _experiment(c, kh, dsid, base, "base")
    b = _experiment(c, kh, dsid, cand, "cand")

    # Baseline first, candidate second — the order the gate uses, so delta reads as "how the
    # candidate moved" rather than the reverse.
    r = c.get(f"/v1/experiments/{a}/compare/{b}", headers=kh).json()["scorers"]["acc"]
    assert r["delta"] is not None and r["delta"] < 0, "the mean did drop"
    assert r["significant"] is False, "a one-example drop must not read as a real regression"


def test_an_edited_dataset_makes_the_comparison_refuse():
    """No p-value rescues a delta measured over different material."""
    c = _client()
    _, kh = _account(c)
    dsid = c.post("/api/datasets", json={"name": "d"}).json()["id"]
    c.post(f"/api/datasets/{dsid}/items", json={"input": "one", "expected": "1"})
    a = _experiment(c, kh, dsid, [1.0, 1.0], "base")
    c.post(f"/api/datasets/{dsid}/items", json={"input": "two", "expected": "2"})   # edited
    b = _experiment(c, kh, dsid, [0.0, 0.0], "cand")

    body = c.get(f"/v1/experiments/{b}/compare/{a}", headers=kh).json()
    assert body["comparable"] is False
    assert "not directly comparable" in body["warning"]


# ---------------------------------------------------------------- #49 judge drift alerts

def test_quality_metrics_are_accepted_by_the_alert_api():
    c = _client()
    _account(c)
    r = c.post("/api/alerts", json={"name": "judge drift", "metric": "judge_kappa",
                                    "comparator": "lt", "threshold": 0.4, "window_hours": 24})
    assert r.status_code == 200, r.text
    assert r.json()["metric"] == "judge_kappa"


def test_an_unmeasurable_judge_never_fires_an_alert():
    """Calibration refuses to publish a kappa below MIN_LABELLED_N. An alerting path that read
    that as 0.0 would page someone about a number the product declines to state on screen."""
    c = _client()
    pid, _kh = _account(c)
    db = SessionLocal()
    try:
        # A couple of pairs — well under the minimum calibration will report on.
        for i in range(2):
            t = f"{uuid.uuid4().hex[:24]}{i:08d}"
            db.add(Feedback(workspace_id=pid, trace_id=t, name="j", score=1.0, source="eval"))
            db.add(Feedback(workspace_id=pid, trace_id=t, name="review", score=0.0, source="human"))
        db.commit()
        vals = alerts_router._quality_metrics(db, db.get(Workspace, pid), 24)
    finally:
        db.close()
    assert vals["judge_kappa"] is None, "kappa must be withheld below the calibration minimum"

    c.post("/api/alerts", json={"metric": "judge_kappa", "comparator": "lt", "threshold": 0.9})
    fired = c.post("/api/alerts/evaluate").json()
    assert not [f for f in (fired.get("fired") or []) if f.get("metric") == "judge_kappa"], \
        "an alert fired on a metric the product refuses to report"


def test_online_eval_scores_are_watchable():
    """The other half of drift: the judge still agrees with humans, but quality itself fell."""
    c = _client()
    pid, _kh = _account(c)
    db = SessionLocal()
    try:
        for i in range(4):
            db.add(Feedback(workspace_id=pid, trace_id=f"{uuid.uuid4().hex[:32]}",
                            name="j", score=0.2, source="eval"))
        db.commit()
        ws = db.get(Workspace, pid)
        vals = alerts_router._quality_metrics(db, ws, 24)
    finally:
        db.close()
    assert vals["eval_mean_score"] is not None
    assert abs(vals["eval_mean_score"] - 0.2) < 1e-6


def test_scores_outside_the_window_are_not_counted():
    c = _client()
    pid, _kh = _account(c)
    db = SessionLocal()
    try:
        old = Feedback(workspace_id=pid, trace_id=uuid.uuid4().hex[:32], name="j",
                       score=1.0, source="eval")
        old.created_at = _now() - timedelta(days=9)
        db.add(old)
        db.add(Feedback(workspace_id=pid, trace_id=uuid.uuid4().hex[:32], name="j",
                        score=0.0, source="eval"))
        db.commit()
        ws = db.get(Workspace, pid)
        vals = alerts_router._quality_metrics(db, ws, 24)
    finally:
        db.close()
    assert vals["eval_mean_score"] == 0.0, "a score from last week is not this window's quality"


def test_an_unknown_metric_still_lists_what_is_accepted():
    c = _client()
    _account(c)
    r = c.post("/api/alerts", json={"metric": "vibes", "threshold": 1})
    assert r.status_code == 422
    assert "judge_kappa" in r.json()["detail"]
