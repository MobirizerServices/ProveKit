"""Scheduled digests (#71).

Alerts answer "is something broken now". A digest answers the slower question — did anything
drift this week — which is only visible by comparing a window against the one before it.
"""
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from provekit.database import SessionLocal
from provekit.main import app
from provekit.models import Digest, Workspace
from provekit.services import digests

from conftest import ingest_workspace_id


def _client():
    return TestClient(app, base_url="https://testserver")


# ---- scheduling ---------------------------------------------------------------------------

def test_a_never_sent_digest_is_due_immediately():
    """Otherwise configuring one produces nothing for a week and looks broken."""
    db = SessionLocal()
    try:
        ws_id = ingest_workspace_id()
        d = Digest(workspace_id=ws_id, cadence="weekly", email="a@b.co", last_sent_at=None)
        db.add(d); db.commit()
        assert any(x.id == d.id for x in digests.due(db))
        db.delete(d); db.commit()
    finally:
        db.close()


def test_a_recent_digest_is_not_due_and_a_stale_one_is():
    db = SessionLocal()
    try:
        ws_id = ingest_workspace_id()
        now = datetime.now(timezone.utc)
        fresh = Digest(workspace_id=ws_id, cadence="daily", email="a@b.co",
                       last_sent_at=now - timedelta(hours=2))
        stale = Digest(workspace_id=ws_id, cadence="daily", email="a@b.co",
                       last_sent_at=now - timedelta(hours=30))
        db.add_all([fresh, stale]); db.commit()
        ids = {x.id for x in digests.due(db, now=now)}
        assert stale.id in ids and fresh.id not in ids
        db.delete(fresh); db.delete(stale); db.commit()
    finally:
        db.close()


def test_a_missed_window_sends_late_rather_than_never():
    """Driven by last_sent_at, not a cron expression: an instance down over the boundary must
    still send. A digest nobody received is indistinguishable from nothing to report."""
    db = SessionLocal()
    try:
        ws_id = ingest_workspace_id()
        long_ago = datetime.now(timezone.utc) - timedelta(days=30)
        d = Digest(workspace_id=ws_id, cadence="weekly", email="a@b.co", last_sent_at=long_ago)
        db.add(d); db.commit()
        assert any(x.id == d.id for x in digests.due(db))
        db.delete(d); db.commit()
    finally:
        db.close()


def test_a_disabled_digest_is_never_due():
    db = SessionLocal()
    try:
        ws_id = ingest_workspace_id()
        d = Digest(workspace_id=ws_id, cadence="daily", email="a@b.co", enabled=False)
        db.add(d); db.commit()
        assert not any(x.id == d.id for x in digests.due(db))
        db.delete(d); db.commit()
    finally:
        db.close()


# ---- content ------------------------------------------------------------------------------

def test_no_baseline_reports_no_comparison_rather_than_a_fake_one():
    """A project with nothing in the previous window has no denominator. Reporting an infinite
    increase from zero would be a fabricated trend."""
    assert digests._delta(10, 0) is None
    assert digests._delta(10, 5) == 100.0
    assert digests._delta(5, 10) == -50.0


def test_render_marks_a_missing_baseline_explicitly():
    summary = {"project": "P", "cadence": "weekly", "window_hours": 168, "traces": 3,
               "traces_delta_pct": None, "errors": 0, "error_rate": 0.0,
               "error_rate_delta_pct": None, "tokens": 0, "tokens_delta_pct": None,
               "latency_p95_ms": 0, "top_errors": [], "has_baseline": False}
    text = digests.render(summary)
    assert "no comparison available" in text
    assert "—" in text                      # deltas rendered as absent, not as 0%


def test_build_produces_a_comparable_summary():
    db = SessionLocal()
    try:
        ws_id = ingest_workspace_id()
        ws = db.query(Workspace).filter(Workspace.id == ws_id).first()
        s = digests.build(db, ws, "weekly")
        assert s["window_hours"] == 168
        assert {"traces", "errors", "error_rate", "tokens", "has_baseline"} <= set(s)
    finally:
        db.close()


# ---- API ----------------------------------------------------------------------------------

def test_a_digest_with_nowhere_to_go_is_refused():
    """It would sit there looking configured and deliver nothing."""
    with _client() as c:
        assert c.post("/api/digests", json={"cadence": "weekly"}).status_code == 422


def test_an_unknown_cadence_is_refused():
    with _client() as c:
        assert c.post("/api/digests", json={"cadence": "hourly",
                                            "email": "a@b.co"}).status_code == 422


def test_a_digest_webhook_is_ssrf_guarded():
    with _client() as c:
        r = c.post("/api/digests", json={"cadence": "weekly",
                                         "webhook_url": "http://169.254.169.254/x"})
        assert r.status_code == 422


def test_preview_shows_the_content_without_sending_or_rescheduling():
    """Configuring a weekly digest and waiting a week to learn whether it's useful is a bad
    loop."""
    with _client() as c:
        made = c.post("/api/digests", json={"cadence": "daily", "email": "a@b.co"}).json()
        body = c.post(f"/api/digests/{made['id']}/preview").json()
        assert "text" in body and body["summary"]["window_hours"] == 24
        again = [d for d in c.get("/api/digests").json() if d["id"] == made["id"]][0]
        assert again["last_sent_at"] is None     # preview must not consume the window
        c.delete(f"/api/digests/{made['id']}")
