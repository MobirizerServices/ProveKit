"""Experiment reproducibility (#52): a result you can still re-derive months later.

Without a pin, an experiment is a number with no provenance — nobody can say which dataset
contents, which model or which scorers produced it, so it can be quoted but never checked.
"""
from fastapi.testclient import TestClient

from provekit.main import app


def _dataset(client, name):
    return client.post("/api/datasets", json={"name": name, "description": ""}).json()["id"]


def test_an_experiment_pins_the_data_it_ran_over():
    with TestClient(app) as client:
        did = _dataset(client, "pinned-run")
        client.post(f"/api/datasets/{did}/items", json={"input": "a", "expected": "b"})
        made = client.post("/api/experiments", json={
            "name": "run-1", "dataset_id": did,
            "config": {"model": "gpt-4o", "params": {"temperature": 0}, "scorers": ["exact"]},
        }).json()
    assert made["dataset_version"] >= 1
    assert len(made["dataset_fingerprint"]) == 32
    assert made["config"]["model"] == "gpt-4o"


def test_the_pin_is_readable_back_off_the_experiment():
    with TestClient(app) as client:
        did = _dataset(client, "readback")
        client.post(f"/api/datasets/{did}/items", json={"input": "x", "expected": "y"})
        eid = client.post("/api/experiments", json={
            "name": "run-2", "dataset_id": did, "config": {"model": "claude-sonnet-5"}}).json()["id"]
        listed = [e for e in client.get("/api/experiments").json() if e["id"] == eid][0]
    assert listed["dataset_fingerprint"] and listed["config"]["model"] == "claude-sonnet-5"


def test_an_experiment_without_a_dataset_records_no_pin():
    """Honest absence beats a fabricated one — 0 reads as unrecorded."""
    with TestClient(app) as client:
        made = client.post("/api/experiments", json={"name": "no-dataset"}).json()
    assert made["dataset_version"] == 0 and made["dataset_fingerprint"] == ""


def test_editing_the_dataset_between_runs_makes_them_not_comparable():
    """The case that actually bites: the SAME dataset, changed between two runs. It used to
    produce a confident delta that was an artefact of the edit, with nothing to say so."""
    with TestClient(app) as client:
        did = _dataset(client, "drifting")
        client.post(f"/api/datasets/{did}/items", json={"input": "q1", "expected": "a1"})
        a = client.post("/api/experiments", json={"name": "before", "dataset_id": did}).json()
        client.post(f"/api/datasets/{did}/items", json={"input": "q2", "expected": "a2"})
        b = client.post("/api/experiments", json={"name": "after", "dataset_id": did}).json()
        cmp = client.get(f"/api/experiments/{a['id']}/compare/{b['id']}").json()
    assert a["dataset_fingerprint"] != b["dataset_fingerprint"]
    assert "not directly comparable" in cmp["warning"]
    assert "changed between these runs" in cmp["warning"]


def test_two_runs_over_untouched_data_compare_cleanly():
    with TestClient(app) as client:
        did = _dataset(client, "stable-compare")
        client.post(f"/api/datasets/{did}/items", json={"input": "q", "expected": "a"})
        a = client.post("/api/experiments", json={"name": "run-a", "dataset_id": did}).json()
        b = client.post("/api/experiments", json={"name": "run-b", "dataset_id": did}).json()
        cmp = client.get(f"/api/experiments/{a['id']}/compare/{b['id']}").json()
    assert cmp["warning"] == ""


def test_different_datasets_still_warn():
    with TestClient(app) as client:
        d1, d2 = _dataset(client, "left"), _dataset(client, "right")
        a = client.post("/api/experiments", json={"name": "l", "dataset_id": d1}).json()
        b = client.post("/api/experiments", json={"name": "r", "dataset_id": d2}).json()
        cmp = client.get(f"/api/experiments/{a['id']}/compare/{b['id']}").json()
    assert "different datasets" in cmp["warning"]
