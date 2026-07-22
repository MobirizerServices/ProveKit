"""Dataset versioning, fingerprints and splits (#45), and the pins that make an experiment
re-derivable (#52).

The problem: an experiment compares against another experiment, and that is only meaningful if
both saw the same data. Nothing enforced it, so a dataset edited between two runs produced a
"regression" that was an artefact of the edit — with nothing on screen to say so.
"""
import pytest
from fastapi.testclient import TestClient

from provekit.database import SessionLocal
from provekit.main import app
from provekit.models import Dataset, DatasetItem
from provekit.services import datasets as ds


@pytest.fixture
def dataset():
    with TestClient(app) as client:
        d = client.post("/api/datasets", json={"name": "versioning", "description": ""}).json()
        yield client, d["id"]


def _add(client, did, inp, exp=""):
    return client.post(f"/api/datasets/{did}/items",
                       json={"input": inp, "expected": exp}).json()


# -- version counter -------------------------------------------------------------------------

def test_a_new_dataset_starts_at_version_one(dataset):
    client, did = dataset
    assert client.get(f"/api/datasets/{did}/version").json()["version"] == 1


def test_every_content_change_bumps_the_version(dataset):
    """A dataset that changed without bumping reports itself unchanged — the exact silent
    invalidation this exists to prevent. Add and delete both count."""
    client, did = dataset
    _add(client, did, "a")
    v1 = client.get(f"/api/datasets/{did}/version").json()["version"]
    item = _add(client, did, "b")
    v2 = client.get(f"/api/datasets/{did}/version").json()["version"]
    client.delete(f"/api/datasets/{did}/items/{item['id']}")
    v3 = client.get(f"/api/datasets/{did}/version").json()["version"]
    assert v1 < v2 < v3


# -- fingerprint -----------------------------------------------------------------------------

def test_fingerprint_changes_with_content(dataset):
    client, did = dataset
    _add(client, did, "first")
    before = client.get(f"/api/datasets/{did}/version").json()["fingerprint"]
    _add(client, did, "second")
    after = client.get(f"/api/datasets/{did}/version").json()["fingerprint"]
    assert before != after and len(before) == 32


def test_fingerprint_is_stable_for_unchanged_content(dataset):
    client, did = dataset
    _add(client, did, "stable")
    a = client.get(f"/api/datasets/{did}/version").json()["fingerprint"]
    b = client.get(f"/api/datasets/{did}/version").json()["fingerprint"]
    assert a == b


def test_empty_datasets_fingerprint_consistently(dataset):
    client, did = dataset
    assert client.get(f"/api/datasets/{did}/version").json()["fingerprint"]


# -- splits ----------------------------------------------------------------------------------

def test_items_are_unassigned_by_default(dataset):
    """Existing datasets must keep meaning "the whole set" — silently splitting them would
    change what every saved experiment was measured over."""
    client, did = dataset
    assert _add(client, did, "x")["split"] == ""


def test_split_is_deterministic(dataset):
    """Hash-based, not random: re-splitting must not move examples across the boundary and
    invalidate every earlier comparison."""
    client, did = dataset
    for i in range(40):
        _add(client, did, f"item-{i}")
    first = client.post(f"/api/datasets/{did}/split", json={"ratio": 0.25}).json()["counts"]
    second = client.post(f"/api/datasets/{did}/split", json={"ratio": 0.25}).json()["counts"]
    assert first == second
    assert first["train"] + first["test"] == 40
    assert 4 <= first["test"] <= 16          # ~25%, allowing for hash lumpiness at n=40


def test_a_different_seed_gives_a_different_split(dataset):
    client, did = dataset
    for i in range(40):
        _add(client, did, f"item-{i}")
    a = client.post(f"/api/datasets/{did}/split", json={"ratio": 0.25, "seed": 1}).json()
    db = SessionLocal()
    split_a = {i.id: i.split for i in
               db.query(DatasetItem).filter(DatasetItem.dataset_id == did).all()}
    db.close()
    client.post(f"/api/datasets/{did}/split", json={"ratio": 0.25, "seed": 2})
    db = SessionLocal()
    split_b = {i.id: i.split for i in
               db.query(DatasetItem).filter(DatasetItem.dataset_id == did).all()}
    db.close()
    assert a["counts"]["train"] + a["counts"]["test"] == 40
    assert split_a != split_b


def test_an_invalid_ratio_is_rejected(dataset):
    client, did = dataset
    assert client.post(f"/api/datasets/{did}/split", json={"ratio": 0}).status_code == 422
    assert client.post(f"/api/datasets/{did}/split", json={"ratio": 1}).status_code == 422


def test_splitting_bumps_the_version(dataset):
    """A split changes what an experiment over "the test set" would measure, so it is a
    content change like any other."""
    client, did = dataset
    for i in range(10):
        _add(client, did, f"i{i}")
    before = client.get(f"/api/datasets/{did}/version").json()["version"]
    client.post(f"/api/datasets/{did}/split", json={"ratio": 0.3})
    assert client.get(f"/api/datasets/{did}/version").json()["version"] > before


# -- comparability ---------------------------------------------------------------------------

class _Exp:
    def __init__(self, dataset_id, version, fp):
        self.dataset_id, self.dataset_version, self.dataset_fingerprint = dataset_id, version, fp


def test_same_fingerprint_is_comparable():
    ok, why = ds.comparable(_Exp(1, 3, "abc"), _Exp(1, 3, "abc"))
    assert ok and why == ""


def test_changed_dataset_is_not_comparable():
    ok, why = ds.comparable(_Exp(1, 3, "abc"), _Exp(1, 5, "def"))
    assert not ok and "changed between these runs" in why


def test_different_datasets_are_not_comparable():
    ok, why = ds.comparable(_Exp(1, 3, "abc"), _Exp(2, 3, "abc"))
    assert not ok and "different datasets" in why


def test_an_unrecorded_pin_is_unknown_not_assumed_fine():
    """"We can't tell" and "they match" are different answers. Conflating them is how a bad
    comparison gets trusted."""
    ok, why = ds.comparable(_Exp(1, 0, ""), _Exp(1, 3, "abc"))
    assert not ok and "predates dataset versioning" in why


def test_pin_reports_what_an_experiment_should_record(dataset):
    client, did = dataset
    _add(client, did, "pinned")
    db = SessionLocal()
    try:
        p = ds.pin(db, did)
        assert p["dataset_version"] >= 1 and len(p["dataset_fingerprint"]) == 32
        assert ds.pin(db, None) == {"dataset_version": 0, "dataset_fingerprint": ""}
    finally:
        db.close()
