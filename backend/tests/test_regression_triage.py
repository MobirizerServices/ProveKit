"""Row-level triage between two experiments: which rows regressed, not just by how much.

The behaviour worth protecting here is the refusals — a diff that silently pairs unrelated
rows is worse than no diff, because it reads as evidence.
"""
from fastapi.testclient import TestClient

from provekit.main import app


def _client():
    return TestClient(app, base_url="https://testserver")


def _run(c, name, dataset_id, rows):
    """An experiment scored over {item_id: scores} (or {item_id: (scores, input, output)})."""
    e = c.post("/api/experiments", json={"name": name, "dataset_id": dataset_id}).json()
    for item_id, spec in rows.items():
        scores, inp, out = spec if isinstance(spec, tuple) else (spec, f"q{item_id}", "o")
        c.post(f"/api/experiments/{e['id']}/results",
               json={"item_id": item_id, "input": inp, "output": out, "expected": "gold",
                     "scores": scores})
    return e


def _triage(c, a, b, **params):
    r = c.get(f"/api/experiments/{a['id']}/triage/{b['id']}", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_triage_names_the_rows_that_broke_worst_first():
    c = _client()
    d = c.post("/api/datasets", json={"name": "triage"}).json()
    a = _run(c, "before", d["id"], {1: {"acc": 1.0}, 2: {"acc": 1.0}, 3: {"acc": 0.9}, 4: {"acc": 0.2}})
    # item 2 falls off a cliff (and crosses pass→fail), item 3 dips, item 4 recovers.
    b = _run(c, "after", d["id"], {1: {"acc": 1.0}, 2: {"acc": 0.0}, 3: {"acc": 0.6}, 4: {"acc": 0.8}})

    t = _triage(c, a, b)
    assert t["comparable"] is True and t["pairing"]["paired"] == 4
    acc = t["scorers"]["acc"]
    assert acc["regressed_count"] == 2 and acc["improved_count"] == 1 and acc["unchanged"] == 1
    assert [r["item_id"] for r in acc["regressed"]] == [2, 3]     # worst first
    assert acc["regressed"][0]["delta"] == -1.0
    assert acc["pass_to_fail"] == 1 and acc["regressed"][0]["crossed"] == "pass_to_fail"
    assert acc["fail_to_pass"] == 1 and acc["improved"][0]["item_id"] == 4
    # The row carries enough context to act on without a second request.
    assert acc["regressed"][0]["input"] == "q2" and acc["regressed"][0]["expected"] == "gold"


def test_a_break_outranks_a_bigger_dip():
    """A pass that became a fail is the thing to look at, even when a dip moved further."""
    c = _client()
    d = c.post("/api/datasets", json={"name": "rank"}).json()
    a = _run(c, "before", d["id"], {1: {"acc": 1.0}, 2: {"acc": 0.45}})
    b = _run(c, "after", d["id"], {1: {"acc": 0.4}, 2: {"acc": 0.0}})   # item 2 drops further
    acc = _triage(c, a, b)["scorers"]["acc"]
    assert [r["item_id"] for r in acc["regressed"]] == [1, 2]
    assert acc["pass_to_fail"] == 1


def test_pass_threshold_is_configurable():
    c = _client()
    d = c.post("/api/datasets", json={"name": "thresh"}).json()
    a = _run(c, "before", d["id"], {1: {"acc": 0.8}})
    b = _run(c, "after", d["id"], {1: {"acc": 0.6}})
    assert _triage(c, a, b)["scorers"]["acc"]["pass_to_fail"] == 0          # both pass at 0.5
    assert _triage(c, a, b, pass_at=0.7)["scorers"]["acc"]["pass_to_fail"] == 1


def test_triage_refuses_to_diff_across_datasets():
    c = _client()
    d1 = c.post("/api/datasets", json={"name": "ds-1"}).json()
    d2 = c.post("/api/datasets", json={"name": "ds-2"}).json()
    a = _run(c, "x", d1["id"], {1: {"acc": 1.0}, 2: {"acc": 1.0}})
    b = _run(c, "y", d2["id"], {1: {"acc": 0.0}, 2: {"acc": 0.0}})
    t = _triage(c, a, b)
    assert t["comparable"] is False and t["scorers"] == {}
    assert "different datasets" in t["warning"]


def test_rows_missing_from_one_side_are_reported_not_paired_by_position():
    c = _client()
    d = c.post("/api/datasets", json={"name": "gaps"}).json()
    a = _run(c, "before", d["id"], {1: {"acc": 1.0}, 2: {"acc": 1.0}})
    b = _run(c, "after", d["id"], {2: {"acc": 1.0}, 3: {"acc": 0.0}})
    t = _triage(c, a, b)
    assert t["pairing"] == {"paired": 1, "drifted": 0, "only_in_a": 1, "only_in_b": 1,
                            "no_item_id": 0, "duplicate_item_id": 0}
    # Item 1 (1.0) must not be lined up against item 3 (0.0) and called a regression.
    assert t["scorers"]["acc"]["regressed_count"] == 0
    assert any("only in A" in n for n in t["notes"])


def test_an_edited_dataset_item_is_dropped_not_diffed():
    """Same item id, different input — the example changed, so the scores aren't comparable."""
    c = _client()
    d = c.post("/api/datasets", json={"name": "drift"}).json()
    a = _run(c, "before", d["id"], {1: ({"acc": 1.0}, "old question", "o")})
    b = _run(c, "after", d["id"], {1: ({"acc": 0.0}, "rewritten question", "o")})
    t = _triage(c, a, b)
    assert t["pairing"]["drifted"] == 1 and t["comparable"] is False
    assert t["scorers"] == {} and "changed between them" in " ".join(t["notes"])


def test_rows_without_item_ids_are_skipped_with_a_note():
    c = _client()
    a = c.post("/api/experiments", json={"name": "no-ids-a"}).json()
    b = c.post("/api/experiments", json={"name": "no-ids-b"}).json()
    for e, s in ((a, 1.0), (b, 0.0)):
        c.post(f"/api/experiments/{e['id']}/results", json={"input": "q", "scores": {"acc": s}})
    t = _triage(c, a, b)
    assert t["comparable"] is False and t["pairing"]["no_item_id"] == 2
    assert any("paired by position" in n for n in t["notes"])


def test_an_item_scored_twice_in_a_run_is_ambiguous_and_skipped():
    c = _client()
    d = c.post("/api/datasets", json={"name": "dupes"}).json()
    a = c.post("/api/experiments", json={"name": "dup", "dataset_id": d["id"]}).json()
    for s in (1.0, 0.5):
        c.post(f"/api/experiments/{a['id']}/results",
               json={"item_id": 1, "input": "q1", "scores": {"acc": s}})
    b = _run(c, "after", d["id"], {1: {"acc": 0.0}})
    t = _triage(c, a, b)
    assert t["pairing"]["duplicate_item_id"] == 1 and t["comparable"] is False
    assert any("more than once" in n for n in t["notes"])


def test_a_scorer_only_one_run_ran_is_counted_not_treated_as_a_drop():
    c = _client()
    d = c.post("/api/datasets", json={"name": "scorers"}).json()
    a = _run(c, "before", d["id"], {1: {"acc": 1.0}})
    b = _run(c, "after", d["id"], {1: {"acc": 1.0, "tone": 0.3}})
    t = _triage(c, a, b)
    assert t["scorers"]["acc"]["unchanged"] == 1
    tone = t["scorers"]["tone"]
    assert tone["scored_only_in_b"] == 1 and tone["regressed_count"] == 0
    # A scorer that stopped running is a gap in B, not a drop to zero.
    back = _triage(c, b, a)["scorers"]["tone"]
    assert back["scored_only_in_a"] == 1 and back["regressed_count"] == 0


def test_non_numeric_scores_do_not_become_zeros():
    c = _client()
    d = c.post("/api/datasets", json={"name": "labels"}).json()
    a = _run(c, "before", d["id"], {1: {"verdict": "good", "acc": 1.0}})
    b = _run(c, "after", d["id"], {1: {"verdict": "bad", "acc": 1.0}})
    v = _triage(c, a, b)["scorers"]["verdict"]
    assert v["regressed_count"] == 0 and v["improved_count"] == 0 and v["unchanged"] == 0


def test_long_lists_are_truncated_but_counts_stay_exact():
    c = _client()
    d = c.post("/api/datasets", json={"name": "big"}).json()
    a = _run(c, "before", d["id"], {i: {"acc": 1.0} for i in range(1, 12)})
    b = _run(c, "after", d["id"], {i: {"acc": 0.0} for i in range(1, 12)})
    acc = _triage(c, a, b, limit=3)["scorers"]["acc"]
    assert acc["regressed_count"] == 11 and len(acc["regressed"]) == 3
    assert acc["truncated"] is True


def test_triage_is_scoped_to_the_project():
    c = _client()
    a = c.post("/api/experiments", json={"name": "scoped"}).json()
    assert c.get(f"/api/experiments/{a['id']}/triage/999999").status_code == 404
