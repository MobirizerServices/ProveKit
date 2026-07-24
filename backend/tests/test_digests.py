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


# ---- delivery ------------------------------------------------------------------------------
# `send()` promises never to raise: it runs inside the scheduler's loop, so one broken
# destination must not stop everyone else's digest going out. That promise was untested.

def _digest(db, **kw):
    d = Digest(workspace_id=ingest_workspace_id(), cadence="weekly", last_sent_at=None, **kw)
    db.add(d); db.commit(); db.refresh(d)
    return d


def test_a_webhook_digest_is_delivered_and_marked_sent(monkeypatch):
    seen = {}

    def _fake(url, body):
        seen["url"], seen["body"] = url, body
        return True

    monkeypatch.setattr("provekit.services.notify.send_webhook", _fake)
    db = SessionLocal()
    try:
        d = _digest(db, webhook_url="https://hooks.example.com/x")
        assert digests.send(db, d) is True
        assert d.last_status == "sent"
        assert d.last_sent_at is not None
    finally:
        db.close()
    assert seen["url"] == "https://hooks.example.com/x"
    assert "[ProveKit]" in seen["body"]


def test_an_email_digest_is_delivered(monkeypatch):
    sent = []
    monkeypatch.setattr("provekit.services.email.send",
                        lambda to, subject, body: sent.append((to, subject)))
    db = SessionLocal()
    try:
        d = _digest(db, email="ops@example.com")
        assert digests.send(db, d) is True
        assert d.last_status == "sent"
    finally:
        db.close()
    assert sent and sent[0][0] == "ops@example.com"
    assert "ProveKit digest" in sent[0][1]


def test_a_refused_webhook_is_recorded_as_failed_but_still_rescheduled(monkeypatch):
    """The stamp moves even on failure. Without it a permanently broken destination is retried
    on every scheduler pass instead of once per window — a dead URL becomes a hot loop."""
    monkeypatch.setattr("provekit.services.notify.send_webhook", lambda url, body: False)
    db = SessionLocal()
    try:
        d = _digest(db, webhook_url="https://hooks.example.com/dead")
        assert digests.send(db, d) is False
        assert d.last_status == "delivery failed"
        assert d.last_sent_at is not None
    finally:
        db.close()


def test_a_destination_that_raises_does_not_escape_send(monkeypatch):
    """The whole point of the guard: one exploding destination inside run_due() must not
    abandon the digests queued behind it."""
    def _boom(url, body):
        raise RuntimeError("connection reset")

    monkeypatch.setattr("provekit.services.notify.send_webhook", _boom)
    db = SessionLocal()
    try:
        d = _digest(db, webhook_url="https://hooks.example.com/boom")
        assert digests.send(db, d) is False              # returned, not raised
        assert "RuntimeError" in d.last_status and "connection reset" in d.last_status
        assert d.last_sent_at is not None
    finally:
        db.close()


def test_a_digest_for_a_deleted_project_disables_itself():
    """A digest outliving its project would fail forever. It turns itself off and says why."""
    db = SessionLocal()
    try:
        d = Digest(workspace_id=10_000_000, cadence="weekly", email="x@y.co", last_sent_at=None)
        db.add(d); db.commit(); db.refresh(d)
        assert digests.send(db, d) is False
        assert d.enabled is False
        assert "no longer exists" in d.last_status
    finally:
        db.close()


def test_run_due_sends_what_is_due_and_leaves_a_fresh_digest_alone(monkeypatch):
    """Asserted as a post-condition, not as "this call sent N".

    `main.py` starts `_send_digests_forever()` in the app lifespan, and any test in the suite
    that opens a TestClient leaves that loop running — so a digest can be delivered by the
    scheduler between two lines of this test. A count is therefore not a stable number, while
    "nothing due is left unsent, and nothing inside its window is sent again" is true no matter
    who did the sending.
    """
    monkeypatch.setattr("provekit.services.notify.send_webhook", lambda url, body: True)
    db = SessionLocal()
    try:
        pending = _digest(db, webhook_url="https://hooks.example.com/pending")
        fresh = _digest(db, webhook_url="https://hooks.example.com/fresh")
        fresh.last_sent_at = datetime.now(timezone.utc)      # weekly cadence, just sent
        db.commit()
        stamp = fresh.last_sent_at

        digests.run_due(db)

        db.refresh(pending); db.refresh(fresh)
        assert pending.last_sent_at is not None, "a due digest was left unsent"
        assert pending.last_status == "sent"
        assert fresh.last_sent_at == stamp, "a digest inside its window was sent again"
    finally:
        db.close()
