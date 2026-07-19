"""Experiments: create, post results, per-scorer means + comparison across runs on a dataset."""
from fastapi.testclient import TestClient

from provekit.main import app


def _client():
    return TestClient(app, base_url="https://testserver")


def test_experiment_means_and_detail():
    c = _client()
    e = c.post("/api/experiments", json={"name": "run-1"}).json()
    c.post(f"/api/experiments/{e['id']}/results",
           json={"input": "q1", "output": "a", "expected": "a", "scores": {"exact_match": 1.0}})
    c.post(f"/api/experiments/{e['id']}/results",
           json={"input": "q2", "output": "b", "expected": "c", "scores": {"exact_match": 0.0}})
    detail = c.get(f"/api/experiments/{e['id']}").json()
    assert detail["result_count"] == 2
    assert detail["scorer_means"]["exact_match"] == 0.5
    assert detail["mean_score"] == 0.5
    assert len(detail["results"]) == 2


def test_compare_experiments_on_a_dataset():
    c = _client()
    ds = c.post("/api/datasets", json={"name": "cmp"}).json()
    a = c.post("/api/experiments", json={"name": "v1", "dataset_id": ds["id"]}).json()
    b = c.post("/api/experiments", json={"name": "v2", "dataset_id": ds["id"]}).json()
    c.post(f"/api/experiments/{a['id']}/results", json={"scores": {"exact_match": 0.4}})
    c.post(f"/api/experiments/{b['id']}/results", json={"scores": {"exact_match": 0.9}})
    rows = c.get("/api/experiments", params={"dataset_id": ds["id"]}).json()
    by_name = {r["name"]: r["mean_score"] for r in rows}
    assert by_name["v1"] == 0.4 and by_name["v2"] == 0.9


def test_key_authed_create_and_post_result():
    c = _client()
    key = c.post("/api/api-keys", json={"name": "sdk"}).json()["key"]
    hdr = {"Authorization": f"Bearer {key}"}
    e = c.post("/v1/experiments", headers=hdr, json={"name": "sdk-run"}).json()
    c.post(f"/v1/experiments/{e['id']}/results", headers=hdr, json={"scores": {"contains": 1.0}})
    summary = c.get(f"/v1/experiments/{e['id']}", headers=hdr).json()
    assert summary["result_count"] == 1 and summary["mean_score"] == 1.0


def test_delete_and_unknown_experiment():
    c = _client()
    e = c.post("/api/experiments", json={"name": "tmp"}).json()
    assert c.delete(f"/api/experiments/{e['id']}").json()["ok"] is True
    assert c.get(f"/api/experiments/{e['id']}").status_code == 404
