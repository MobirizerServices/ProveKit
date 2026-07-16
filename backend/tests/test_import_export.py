"""API round-trip: export a saved request / flow, import it back."""
import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _mock_conn(client) -> dict:
    return next(c for c in client.get("/api/connections").json()
                if c["config"].get("provider") == "mock")


def test_request_export_import_round_trip(client):
    conn = _mock_conn(client)
    saved = client.post("/api/requests", json={
        "name": "Demo test", "type": "prompt", "collection_id": None,
        "payload": {"type": "prompt", "connection_id": conn["id"], "model": "demo-mock",
                    "user": "hello {{who}}",
                    "assertions": [{"type": "contains", "value": "demo"}]},
    }).json()

    text = client.get(f"/api/requests/{saved['id']}/export").text
    assert "connection: Demo Assistant (mock)" in text
    assert "connection_id" not in text

    imp = client.post("/api/import", json={"content": text}).json()
    assert imp["kind"] == "test" and imp["connection_resolved"] is True
    p = imp["request"]["payload"]
    assert p["connection_id"] == conn["id"]
    assert p["user"] == "hello {{who}}"
    assert p["assertions"] == [{"type": "contains", "value": "demo"}]

    # imported request actually runs (mock provider, no key needed)
    r = client.post("/api/run", json={"request": p, "save": False}).json()
    assert r["status"] == "completed"
    assert r["assertions"][0]["ok"] is True


def test_flow_export_import_round_trip(client):
    conn = _mock_conn(client)
    flow = client.post("/api/flows", json={
        "name": "Exportable", "description": "d",
        "nodes": [
            {"id": "input", "type": "input", "position": {"x": 0, "y": 0}, "data": {}, "config": {}},
            {"id": "p", "type": "prompt", "position": {"x": 1, "y": 0}, "data": {"title": "Ask"},
             "config": {"connection_id": conn["id"], "model": "demo-mock", "user": "{{input.q}}"}},
        ],
        "edges": [{"id": "e", "source": "input", "target": "p"}],
    }).json()

    text = client.get(f"/api/flows/{flow['id']}/export").text
    assert "connection: Demo Assistant (mock)" in text and "connection_id" not in text

    imp = client.post("/api/import", json={"content": text}).json()
    assert imp["kind"] == "flow" and imp["connection_resolved"] is True
    back = client.get(f"/api/flows/{imp['flow_id']}").json()
    assert back["nodes"][1]["config"]["connection_id"] == conn["id"]


def test_import_rejects_bad_files(client):
    r = client.post("/api/import", json={"content": "version: 9\nkind: test"})
    assert r.status_code == 400 and "unsupported version" in r.json()["detail"]
