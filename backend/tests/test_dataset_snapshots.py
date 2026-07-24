"""Dataset snapshot history (#45).

Version counters and fingerprints already told you *that* a dataset changed and *whether* two
runs saw the same data. Neither could answer "what did v3 contain?", which is the question any
experiment old enough to be worth re-checking eventually raises.
"""
import uuid

from fastapi.testclient import TestClient

from provekit.main import app
from provekit.services import datasets as datasets_svc


def _client():
    return TestClient(app, base_url="https://testserver")


def _dataset(c, name: str = "") -> int:
    return c.post("/api/datasets", json={"name": name or f"ds{uuid.uuid4().hex[:6]}"}).json()["id"]


def test_each_change_stores_the_contents_it_produced():
    c = _client()
    did = _dataset(c)
    c.post(f"/api/datasets/{did}/items", json={"input": "one", "expected": "1"})
    c.post(f"/api/datasets/{did}/items", json={"input": "two", "expected": "2"})

    hist = c.get(f"/api/datasets/{did}/versions").json()
    versions = [v["version"] for v in hist["versions"]]
    assert versions == sorted(versions, reverse=True), "newest first"
    assert len(versions) == 2, hist
    assert hist["live_version"] == versions[0]

    # The older snapshot holds one item; the newer holds both. That is the whole point: the
    # earlier version is not retroactively rewritten by the later edit.
    older, newer = sorted(versions)
    a = c.get(f"/api/datasets/{did}/versions/{older}").json()
    b = c.get(f"/api/datasets/{did}/versions/{newer}").json()
    assert a["item_count"] == 1 and [i["input"] for i in a["items"]] == ["one"]
    assert b["item_count"] == 2 and [i["input"] for i in b["items"]] == ["one", "two"]


def test_deleting_an_item_is_recorded_as_its_own_version():
    c = _client()
    did = _dataset(c)
    first = c.post(f"/api/datasets/{did}/items", json={"input": "keep"}).json()
    doomed = c.post(f"/api/datasets/{did}/items", json={"input": "gone"}).json()
    c.delete(f"/api/datasets/{did}/items/{doomed['id']}")

    hist = c.get(f"/api/datasets/{did}/versions").json()
    live = hist["live_version"]
    now = c.get(f"/api/datasets/{did}/versions/{live}").json()
    assert [i["input"] for i in now["items"]] == ["keep"]
    # …and the version that still had it is retrievable, which is what makes an old experiment
    # re-checkable rather than merely labelled.
    had_both = c.get(f"/api/datasets/{did}/versions/{live - 1}").json()
    assert {i["input"] for i in had_both["items"]} == {"keep", "gone"}
    assert first["id"] in {i["id"] for i in had_both["items"]}


def test_snapshot_fingerprint_matches_what_an_experiment_pins():
    """An experiment records a fingerprint; the snapshot must carry the same one, or the pin
    can't be resolved back to contents."""
    c = _client()
    did = _dataset(c)
    c.post(f"/api/datasets/{did}/items", json={"input": "x", "expected": "y"})
    live = c.get(f"/api/datasets/{did}/version").json()
    snap = c.get(f"/api/datasets/{did}/versions/{live['version']}").json()
    assert snap["fingerprint"] == live["fingerprint"] != ""


def test_a_version_with_no_snapshot_says_which_ones_exist():
    c = _client()
    did = _dataset(c)
    c.post(f"/api/datasets/{did}/items", json={"input": "only"})
    r = c.get(f"/api/datasets/{did}/versions/9999")
    assert r.status_code == 404
    d = r.json()["detail"]
    # Names both causes and the call that lists what is retrievable.
    assert "pruned" in d and f"/api/datasets/{did}/versions" in d


def test_history_reports_its_own_cap():
    """A pruned history must not read as the dataset's whole life."""
    c = _client()
    did = _dataset(c)
    c.post(f"/api/datasets/{did}/items", json={"input": "a"})
    hist = c.get(f"/api/datasets/{did}/versions").json()
    assert hist["retained"] == datasets_svc.MAX_SNAPSHOTS
    assert hist["oldest_retained"] == min(v["version"] for v in hist["versions"])
