"""Quotas: rate limit (429), dataset cap, max_tokens clamp, run retention."""
import pytest
from fastapi.testclient import TestClient

from agentman.config import get_settings
from agentman.main import app
from agentman.services import limits


@pytest.fixture(autouse=True)
def _reset_window():
    limits._window.cache_clear()
    yield
    limits._window.cache_clear()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _mock_req(conn_id):
    return {"type": "prompt", "connection_id": conn_id, "model": "demo-mock", "user": "hi"}


def test_rate_limit_returns_429(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "rate_limit_per_min", 3)
    conn = next(c for c in client.get("/api/connections").json() if c["config"].get("provider") == "mock")
    req = _mock_req(conn["id"])
    statuses = [client.post("/api/run", json={"request": req, "save": False}).status_code for _ in range(5)]
    assert statuses.count(200) == 3 and statuses.count(429) == 2
    # the 429 carries Retry-After
    r = client.post("/api/run", json={"request": req, "save": False})
    assert r.status_code == 429 and "Retry-After" in r.headers


def test_dataset_cap(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "dataset_max_rows", 2)
    conn = next(c for c in client.get("/api/connections").json() if c["config"].get("provider") == "mock")
    rows = [{"name": f"r{i}", "variables": {}} for i in range(5)]
    r = client.post("/api/dataset/run", json={"request": _mock_req(conn["id"]), "rows": rows})
    assert r.status_code == 400 and "too large" in r.json()["detail"]


def test_max_tokens_clamped(monkeypatch):
    monkeypatch.setattr(get_settings(), "max_tokens_cap", 256)
    req = {"type": "prompt", "max_tokens": 9999}
    limits.clamp_max_tokens(req)
    assert req["max_tokens"] == 256


def test_prune_runs_keeps_last_n(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "runs_retention", 3)
    monkeypatch.setattr(get_settings(), "rate_limit_per_min", 0)  # disable during the loop
    conn = next(c for c in client.get("/api/connections").json() if c["config"].get("provider") == "mock")
    for _ in range(6):
        client.post("/api/run", json={"request": _mock_req(conn["id"]), "save": True})
    assert len(client.get("/api/runs?limit=100").json()) <= 3
