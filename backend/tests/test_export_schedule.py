"""Scheduled bulk export (#93).

The cursor is the whole difficulty. Each obvious shortcut fails *quietly*: re-sending everything
grows without bound, an in-memory cursor forgets on restart, and advancing it before delivery is
accepted turns one failed POST into a permanent hole nobody is told about. These tests pin the
behaviour that avoids the last one, which is the dangerous one.
"""
import uuid

import pytest
from fastapi.testclient import TestClient

from provekit.database import SessionLocal
from provekit.main import app
from provekit.models import ExportSchedule, Run
from provekit.services import export_schedule


def _client():
    return TestClient(app, base_url="https://testserver")


def _account(c) -> int:
    email = f"x{uuid.uuid4().hex[:10]}@ex.com"
    assert c.post("/api/auth/register", json={"email": email, "password": "pw12345678"}).status_code == 200
    return c.get("/api/projects").json()[0]["id"]


def _spans(ws_id: int, n: int) -> None:
    db = SessionLocal()
    try:
        for i in range(n):
            db.add(Run(workspace_id=ws_id, trace_id=uuid.uuid4().hex[:32], span_id=f"s{i:015x}",
                       parent_span_id="", type="llm", label=f"call {i}",
                       status="completed", duration_ms=10))
        db.commit()
    finally:
        db.close()


@pytest.fixture()
def accept(monkeypatch):
    """A destination that accepts everything, recording what it got."""
    got = []

    class _R:
        status_code = 200

    def _post(url, content=None, timeout=None, headers=None):
        got.append(content.decode() if isinstance(content, bytes) else content)
        return _R()

    monkeypatch.setattr(export_schedule.httpx, "post", _post)
    monkeypatch.setattr(export_schedule.netguard, "guard_url", lambda u: None)
    return got


def _create(c, pid: int) -> dict:
    return c.post("/api/export/schedules",
                  json={"name": "warehouse", "cadence": "daily",
                        "destination_url": "https://warehouse.example/ingest"}).json()


def test_a_run_delivers_and_advances_the_cursor(accept):
    c = _client()
    pid = _account(c)
    _spans(pid, 3)
    s = _create(c, pid)
    assert s["cursor"] == 0

    body = c.post(f"/api/export/schedules/{s['id']}/run").json()
    assert body["status"] == "ok" and body["rows"] == 3
    assert body["cursor"] > 0
    assert len(accept) == 1 and accept[0].count("\n") == 3

    # A second run has nothing new and must not re-send.
    again = c.post(f"/api/export/schedules/{s['id']}/run").json()
    assert again["rows"] == 0 and len(accept) == 1


def test_only_new_rows_are_sent_on_the_next_run(accept):
    c = _client()
    pid = _account(c)
    _spans(pid, 2)
    s = _create(c, pid)
    c.post(f"/api/export/schedules/{s['id']}/run")
    _spans(pid, 3)
    second = c.post(f"/api/export/schedules/{s['id']}/run").json()
    assert second["rows"] == 3, "an incremental export re-sent old rows"


def test_a_failed_delivery_does_not_advance_the_cursor(monkeypatch):
    """The dangerous failure: advancing past data the destination never received would leave a
    permanent hole with nothing to surface it."""
    c = _client()
    pid = _account(c)
    _spans(pid, 2)
    monkeypatch.setattr(export_schedule.netguard, "guard_url", lambda u: None)

    class _R:
        status_code = 500
    monkeypatch.setattr(export_schedule.httpx, "post",
                        lambda *a, **k: _R())

    s = _create(c, pid)
    body = c.post(f"/api/export/schedules/{s['id']}/run").json()
    assert body["status"] == "failed" and body["cursor"] == 0
    assert "500" in body["error"]

    # The row records why, rather than the loop swallowing it.
    listed = c.get("/api/export/schedules").json()[0]
    assert listed["last_status"] == "failed" and "500" in listed["last_error"]

    # …and the same window is re-sent once the destination recovers.
    got = []
    class _OK:
        status_code = 200
    monkeypatch.setattr(export_schedule.httpx, "post",
                        lambda url, content=None, **k: (got.append(content), _OK())[1])
    retry = c.post(f"/api/export/schedules/{s['id']}/run").json()
    assert retry["status"] == "ok" and retry["rows"] == 2


def test_a_never_run_schedule_is_due_immediately():
    """Otherwise creating one appears to do nothing for a whole cadence, which reads as broken."""
    c = _client()
    pid = _account(c)
    s = _create(c, pid)
    db = SessionLocal()
    try:
        ids = [x.id for x in export_schedule.due(db)]
        assert s["id"] in ids
    finally:
        db.close()


def test_a_disabled_schedule_is_never_due():
    c = _client()
    pid = _account(c)
    s = _create(c, pid)
    db = SessionLocal()
    try:
        row = db.get(ExportSchedule, s["id"])
        row.enabled = False
        db.commit()
        assert s["id"] not in [x.id for x in export_schedule.due(db)]
    finally:
        db.close()


def test_destination_must_survive_the_ssrf_guard():
    c = _client()
    _account(c)
    r = c.post("/api/export/schedules",
               json={"cadence": "daily", "destination_url": "http://169.254.169.254/latest/meta-data"})
    assert r.status_code == 422
    assert "webhook_url was rejected" in r.json()["detail"] or "rejected" in r.json()["detail"]


def test_an_unknown_cadence_is_refused_by_name():
    c = _client()
    _account(c)
    r = c.post("/api/export/schedules",
               json={"cadence": "fortnightly", "destination_url": "https://ok.example/x"})
    assert r.status_code == 422 and "daily" in r.json()["detail"]


def test_one_failing_destination_does_not_stop_the_pass(monkeypatch):
    c = _client()
    pid = _account(c)
    _spans(pid, 1)
    monkeypatch.setattr(export_schedule.netguard, "guard_url", lambda u: None)
    good = _create(c, pid)
    bad = c.post("/api/export/schedules",
                 json={"cadence": "daily", "destination_url": "https://bad.example/x"}).json()

    def _post(url, content=None, **k):
        if "bad.example" in url:
            raise RuntimeError("connection refused")
        class _R:
            status_code = 200
        return _R()
    monkeypatch.setattr(export_schedule.httpx, "post", _post)

    db = SessionLocal()
    try:
        assert export_schedule.run_due(db) >= 2
        rows = {r.id: r for r in db.query(ExportSchedule).all()}
        assert rows[bad["id"]].last_status == "failed"
        assert rows[good["id"]].last_status == "ok"
    finally:
        db.close()


def test_two_workers_cannot_run_the_same_schedule(accept):
    """Replaying an ingest batch is idempotent, so the spool drainer is safe under N workers.
    A scheduled export is not: both would deliver the same window and double-count it."""
    c = _client()
    pid = _account(c)
    _spans(pid, 2)
    sid = _create(c, pid)["id"]

    a, b = SessionLocal(), SessionLocal()
    try:
        row_a, row_b = a.get(ExportSchedule, sid), b.get(ExportSchedule, sid)
        assert export_schedule.claim(a, row_a) is True
        assert export_schedule.claim(b, row_b) is False, "two workers claimed one schedule"
        export_schedule.release(a, row_a)
        # Released, so the next worker can take it.
        assert export_schedule.claim(b, b.get(ExportSchedule, sid)) is True
    finally:
        a.close(); b.close()


def test_an_expired_claim_is_reclaimable():
    """A worker killed mid-run must not strand the schedule until someone notices."""
    from datetime import timedelta
    from provekit.models import _now
    c = _client()
    pid = _account(c)
    sid = _create(c, pid)["id"]
    db = SessionLocal()
    try:
        row = db.get(ExportSchedule, sid)
        row.claimed_until = _now() - timedelta(minutes=1)      # a dead worker's lease
        db.commit()
        assert export_schedule.claim(db, db.get(ExportSchedule, sid)) is True
    finally:
        db.close()

