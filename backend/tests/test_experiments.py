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


def _run_with(c, name, dataset_id, scores_by_item):
    """An experiment scored over given dataset items."""
    e = c.post("/api/experiments", json={"name": name, "dataset_id": dataset_id}).json()
    for item_id, score in scores_by_item.items():
        c.post(f"/api/experiments/{e['id']}/results",
               json={"item_id": item_id, "input": "i", "output": "o", "scores": {"acc": score}})
    return e


def test_experiment_summary_reports_spread_not_just_a_mean():
    c = _client()
    d = c.post("/api/datasets", json={"name": "spread"}).json()
    e = _run_with(c, "run", d["id"], {1: 1.0, 2: 0.0, 3: 1.0, 4: 0.0})
    row = c.get(f"/api/experiments/{e['id']}").json()
    st = row["scorer_stats"]["acc"]
    assert st["n"] == 4 and abs(st["mean"] - 0.5) < 1e-9
    assert st["stdev"] is not None and st["ci95_low"] < st["mean"] < st["ci95_high"]


def test_compare_flags_a_consistent_improvement_as_significant():
    c = _client()
    d = c.post("/api/datasets", json={"name": "cmp-real"}).json()
    items = {i: 0.0 for i in range(1, 26)}
    better = {i: 1.0 for i in range(1, 26)}
    a = _run_with(c, "before", d["id"], items)
    b = _run_with(c, "after", d["id"], better)

    r = c.get(f"/api/experiments/{a['id']}/compare/{b['id']}").json()
    acc = r["scorers"]["acc"]
    assert acc["paired"] is True and acc["paired_n"] == 25
    assert acc["significant"] is True and acc["p_value"] < 0.05
    assert abs(acc["delta"] - 1.0) < 1e-9
    assert r["warning"] == ""


def test_compare_refuses_to_call_a_tiny_sample_significant():
    """The failure this feature exists to prevent: shipping on 3 examples."""
    c = _client()
    d = c.post("/api/datasets", json={"name": "cmp-tiny"}).json()
    a = _run_with(c, "before", d["id"], {1: 0.0, 2: 0.0, 3: 0.0})
    b = _run_with(c, "after", d["id"], {1: 1.0, 2: 1.0, 3: 1.0})
    acc = c.get(f"/api/experiments/{a['id']}/compare/{b['id']}").json()["scorers"]["acc"]
    assert acc["significant"] is False
    assert acc["caution"]


def test_compare_warns_when_the_datasets_differ():
    c = _client()
    d1 = c.post("/api/datasets", json={"name": "ds-a"}).json()
    d2 = c.post("/api/datasets", json={"name": "ds-b"}).json()
    a = _run_with(c, "x", d1["id"], {1: 0.2, 2: 0.3})
    b = _run_with(c, "y", d2["id"], {1: 0.9, 2: 0.8})
    r = c.get(f"/api/experiments/{a['id']}/compare/{b['id']}").json()
    assert "different datasets" in r["warning"]


def test_compare_is_scoped_to_the_project():
    c = _client()
    d = c.post("/api/datasets", json={"name": "scope"}).json()
    a = _run_with(c, "a", d["id"], {1: 1.0})
    assert c.get(f"/api/experiments/{a['id']}/compare/999999").status_code == 404
