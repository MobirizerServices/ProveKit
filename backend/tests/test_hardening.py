"""Production hardening: per-project trace-ingest rate limiting and retention pruning."""
from fastapi.testclient import TestClient

from provekit.config import get_settings
from provekit.database import SessionLocal
from provekit.main import app
from provekit.models import Run, User, Workspace
from provekit.routers.traces import _prune_runs
from provekit.services import limits


def test_ingest_rate_limit_trips_at_the_endpoint(monkeypatch):
    monkeypatch.setattr(get_settings(), "ingest_rate_per_min", 2)
    limits._window.cache_clear()
    c = TestClient(app, base_url="https://testserver")
    payload = {"resourceSpans": []}
    assert c.post("/v1/traces", json=payload).status_code == 200
    assert c.post("/v1/traces", json=payload).status_code == 200
    r = c.post("/v1/traces", json=payload)          # 3rd request exceeds the limit of 2
    assert r.status_code == 429 and "Retry-After" in r.headers
    limits._window.cache_clear()


def test_ingest_rate_disabled_is_a_noop(monkeypatch):
    monkeypatch.setattr(get_settings(), "ingest_rate_per_min", 0)
    assert limits.check_ingest_rate(12345) is None


def test_retention_keeps_only_the_newest_n(monkeypatch):
    monkeypatch.setattr(get_settings(), "runs_retention", 3)
    db = SessionLocal()
    try:
        u = User(email="ret@x.com", name="r")
        db.add(u); db.commit(); db.refresh(u)
        w = Workspace(name="ret-ws", owner_user_id=u.id)
        db.add(w); db.commit(); db.refresh(w)
        for i in range(5):
            db.add(Run(workspace_id=w.id, type="llm", label=f"r{i}"))
        db.commit()
        assert db.query(Run).filter(Run.workspace_id == w.id).count() == 5

        _prune_runs(db, w.id)
        assert db.query(Run).filter(Run.workspace_id == w.id).count() == 3   # newest 3 survive

        monkeypatch.setattr(get_settings(), "runs_retention", 0)             # disabled → no-op
        _prune_runs(db, w.id)
        assert db.query(Run).filter(Run.workspace_id == w.id).count() == 3
    finally:
        db.close()
