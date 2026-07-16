"""Health check + request-id propagation."""
from fastapi.testclient import TestClient

from agentman.main import app


def test_healthz_ok():
    with TestClient(app) as c:
        r = c.get("/healthz")
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True and body["checks"]["db"] is True


def test_request_id_header_roundtrip():
    with TestClient(app) as c:
        r = c.get("/", headers={"X-Request-ID": "abc123"})
        assert r.headers.get("X-Request-ID") == "abc123"
        # generated when absent
        r2 = c.get("/")
        assert r2.headers.get("X-Request-ID")
