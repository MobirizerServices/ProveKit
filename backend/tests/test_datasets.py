"""Datasets: create, add items (incl. from a trace), read by cookie and by project key, delete."""
from fastapi.testclient import TestClient

from provekit.main import app


def _client():
    return TestClient(app, base_url="https://testserver")


def test_create_add_items_and_read():
    c = _client()
    d = c.post("/api/datasets", json={"name": "qa", "description": "golden set"}).json()
    assert d["item_count"] == 0
    c.post(f"/api/datasets/{d['id']}/items", json={"input": "2+2", "expected": "4"})
    c.post(f"/api/datasets/{d['id']}/items", json={"input": "cap of France", "expected": "Paris"})
    detail = c.get(f"/api/datasets/{d['id']}").json()
    assert detail["item_count"] == 2
    assert [i["expected"] for i in detail["items"]] == ["4", "Paris"]
    listed = next(x for x in c.get("/api/datasets").json() if x["id"] == d["id"])
    assert listed["item_count"] == 2


def test_add_item_from_trace_seeds_input_and_expected():
    c = _client()
    c.post("/v1/traces", json={"resourceSpans": [{"scopeSpans": [{"spans": [{
        "name": "agent", "traceId": "t-ds", "spanId": "r", "parentSpanId": "",
        "startTimeUnixNano": "1000000000", "endTimeUnixNano": "1500000000", "status": {"code": 1},
        "attributes": [
            {"key": "gen_ai.operation.name", "value": {"stringValue": "invoke_agent"}},
            {"key": "gen_ai.input.messages", "value": {"stringValue": "hello?"}},
            {"key": "gen_ai.output.messages", "value": {"stringValue": "hi there"}}],
    }]}]}]})
    d = c.post("/api/datasets", json={"name": "from-prod"}).json()
    item = c.post(f"/api/datasets/{d['id']}/items/from-trace", json={"trace_id": "t-ds"}).json()
    assert item["input"] == "hello?" and item["expected"] == "hi there"
    assert item["meta"]["trace_id"] == "t-ds"


def test_from_trace_unknown_is_404():
    c = _client()
    d = c.post("/api/datasets", json={"name": "x"}).json()
    assert c.post(f"/api/datasets/{d['id']}/items/from-trace", json={"trace_id": "nope"}).status_code == 404


def test_key_authed_read_for_sdk():
    c = _client()
    key = c.post("/api/api-keys", json={"name": "eval"}).json()["key"]
    hdr = {"Authorization": f"Bearer {key}"}
    d = c.post("/api/datasets", json={"name": "keyset"}).json()
    c.post(f"/api/datasets/{d['id']}/items", json={"input": "a", "expected": "b"})
    ds = c.get("/v1/datasets", headers=hdr).json()
    assert any(x["id"] == d["id"] for x in ds)
    items = c.get(f"/v1/datasets/{d['id']}/items", headers=hdr).json()
    assert items[0]["input"] == "a" and items[0]["expected"] == "b"


def test_delete_item_and_dataset():
    c = _client()
    d = c.post("/api/datasets", json={"name": "tmp"}).json()
    it = c.post(f"/api/datasets/{d['id']}/items", json={"input": "x"}).json()
    assert c.delete(f"/api/datasets/{d['id']}/items/{it['id']}").json()["ok"] is True
    assert c.get(f"/api/datasets/{d['id']}").json()["item_count"] == 0
    assert c.delete(f"/api/datasets/{d['id']}").json()["ok"] is True
    assert c.get(f"/api/datasets/{d['id']}").status_code == 404
