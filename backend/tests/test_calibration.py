"""Judge calibration: agreement, Cohen's kappa, confusion matrix, disagreements.

These assert the *statistics*, not that the code runs. A wrong kappa is worse than no kappa —
it is a credibility claim for a judge nobody checked. The load-bearing case is the last one in
the first block: a judge that always says "good" on a mostly-good dataset scores high
agreement and must score kappa 0.
"""
from types import SimpleNamespace

from fastapi.testclient import TestClient

from provekit.main import app
from provekit.services import calibration


def _fb(i, trace_id, source, *, score=None, value="", name="", comment=""):
    return SimpleNamespace(id=i, trace_id=trace_id, source=source, score=score, value=value,
                           name=name, comment=comment)


def _pairs(human_labels, judge_labels):
    """One human row and one judge row per trace, from two equal-length label lists."""
    rows = []
    for i, (h, j) in enumerate(zip(human_labels, judge_labels)):
        t = f"t{i}"
        rows.append(_fb(2 * i + 1, t, "human", value="up" if h else "down"))
        rows.append(_fb(2 * i + 2, t, "eval", score=1.0 if j else 0.0, name="llm_judge"))
    return rows


# ---------------------------------------------------------------- the statistics


def test_perfect_disagreement_and_perfect_agreement():
    n = calibration.MIN_LABELLED_N
    half = [True] * (n // 2) + [False] * (n - n // 2)
    same = calibration.calibrate(_pairs(half, half))
    assert same["n"] == n and same["agreement"] == 1.0 and same["kappa"] == 1.0
    assert same["verdict"] == "almost perfect" and same["caution"] == ""

    opposite = calibration.calibrate(_pairs(half, [not x for x in half]))
    assert opposite["agreement"] == 0.0 and opposite["kappa"] == -1.0
    assert opposite["verdict"] == "none"


def test_kappa_matches_a_hand_computed_value():
    """20 traces: 12 both pass, 3 human-pass/judge-fail, 2 human-fail/judge-pass, 3 both fail.

    po = 15/20 = 0.75. Human pass 15/20 = 0.75, judge pass 14/20 = 0.70.
    pe = .75*.70 + .25*.30 = .600 → kappa = (.75-.60)/.40 = 0.375.
    """
    human = [True] * 15 + [False] * 5
    judge = [True] * 12 + [False] * 3 + [True] * 2 + [False] * 3
    r = calibration.calibrate(_pairs(human, judge))
    assert r["confusion"] == {"both_pass": 12, "human_pass_judge_fail": 3,
                             "human_fail_judge_pass": 2, "both_fail": 3}
    assert r["agreement"] == 0.75
    assert abs(r["kappa"] - 0.375) < 1e-9
    assert r["verdict"] == "fair"
    assert abs(r["false_pass_rate"] - 2 / 5) < 1e-9    # 2 of the 5 traces people failed
    assert abs(r["false_fail_rate"] - 3 / 15) < 1e-9   # 3 of the 15 they passed


def test_a_judge_that_always_says_good_scores_zero_kappa():
    """The whole reason kappa is here: 90% agreement, no information."""
    human = [True] * 18 + [False] * 2
    r = calibration.calibrate(_pairs(human, [True] * 20))
    assert r["agreement"] == 0.9              # looks great
    assert r["kappa"] == 0.0                  # and is worth nothing
    assert r["verdict"] == "none"
    assert "chance" in r["caution"]
    assert r["false_pass_rate"] == 1.0        # it passed every trace a person failed


def test_kappa_is_undefined_when_nobody_ever_used_the_other_class():
    """Both sides say pass to everything: agreement 1.0, and kappa cannot be computed —
    reporting 1.0 here would certify a judge that has never been tested."""
    r = calibration.calibrate(_pairs([True] * 20, [True] * 20))
    assert r["agreement"] == 1.0
    assert r["kappa"] is None
    assert r["verdict"] == ""
    assert "undefined" in r["caution"]


def test_perfect_agreement_on_all_fails_is_also_undefined():
    """The mirror case: every trace is a fail and the judge caught all of them. Still one class
    on both sides, so there is still nothing for chance correction to work with."""
    r = calibration.calibrate(_pairs([False] * 20, [False] * 20))
    assert r["kappa"] is None and "undefined" in r["caution"]


# ---------------------------------------------------------------- the refusal


def test_a_handful_of_labels_gets_counts_but_no_verdict():
    """Four labels cannot calibrate anything. The counts and the cases are still returned —
    those are facts; the rates are the part that would get quoted."""
    r = calibration.calibrate(_pairs([True, True, False, True], [True, False, False, True]))
    assert r["n"] == 4 and r["sufficient"] is False
    assert r["agreement"] is None and r["kappa"] is None and r["verdict"] == ""
    assert r["false_pass_rate"] is None and r["false_fail_rate"] is None
    assert str(calibration.MIN_LABELLED_N) in r["caution"]
    assert r["confusion"]["human_pass_judge_fail"] == 1
    assert r["disagreement_count"] == 1        # you can still go read the case


def test_one_below_the_floor_still_refuses():
    n = calibration.MIN_LABELLED_N - 1
    r = calibration.calibrate(_pairs([True] * n, [True] * n))
    assert r["sufficient"] is False and r["kappa"] is None


# ---------------------------------------------------------------- pairing rules


def test_traces_labelled_by_only_one_side_are_reported_not_counted():
    rows = _pairs([True] * 20, [True] * 19 + [False])
    rows.append(_fb(900, "human-only", "human", value="up"))
    rows.append(_fb(901, "judge-only", "eval", score=1.0))
    r = calibration.calibrate(rows)
    assert r["n"] == 20
    assert r["coverage"] == {"human_labelled": 21, "judge_scored": 21, "both": 20,
                             "human_only": 1, "judge_only": 1, "unusable_rows": 0}


def test_the_latest_human_label_is_the_standing_one():
    """A reviewer who changes their mind means the later row — not the average of both."""
    rows = _pairs([False] * 20, [True] * 20)
    rows.append(_fb(5000, "t0", "human", value="up"))      # t0 relabelled: fail -> pass
    r = calibration.calibrate(rows)
    assert r["confusion"]["both_pass"] == 1
    assert r["confusion"]["human_fail_judge_pass"] == 19


def test_comment_only_rows_are_unusable_never_a_failing_label():
    rows = _pairs([True] * 20, [True] * 19 + [False])
    rows.append(_fb(800, "t0", "human", comment="looks odd, not sure"))
    r = calibration.calibrate(rows)
    assert r["coverage"]["unusable_rows"] == 1
    assert r["n"] == 20 and r["confusion"]["both_pass"] == 19


def test_pass_at_threshold_moves_the_judge_label():
    rows = []
    for i in range(20):
        rows.append(_fb(2 * i + 1, f"t{i}", "human", value="up"))
        rows.append(_fb(2 * i + 2, f"t{i}", "eval", score=0.6))
    assert calibration.calibrate(rows, pass_at=0.5)["agreement"] == 1.0
    assert calibration.calibrate(rows, pass_at=0.9)["agreement"] == 0.0


def test_name_filters_select_one_judge_among_several():
    rows = _pairs([True] * 20, [True] * 20)                 # name="llm_judge" on the judge rows
    for i in range(20):
        rows.append(_fb(3000 + i, f"t{i}", "eval", score=0.0, name="exact_match"))
    strict = calibration.calibrate(rows, judge_name="llm_judge")
    assert strict["confusion"]["both_pass"] == 20
    other = calibration.calibrate(rows, judge_name="exact_match")
    assert other["confusion"]["human_pass_judge_fail"] == 20


def test_no_feedback_at_all_is_a_refusal_not_a_crash():
    r = calibration.calibrate([])
    assert r["n"] == 0 and r["kappa"] is None and r["sufficient"] is False
    assert r["disagreements"] == []


# ---------------------------------------------------------------- disagreements


def test_disagreements_lead_with_the_lenient_ones_and_carry_the_context():
    human = [True] * 10 + [False] * 10
    judge = [False] + [True] * 9 + [True] + [False] * 9   # t0 harsh, t10 lenient
    rows = _pairs(human, judge)
    rows.append(_fb(7000, "t10", "human", value="down", comment="hallucinated the citation"))
    r = calibration.calibrate(rows)
    assert r["disagreement_count"] == 2
    first = r["disagreements"][0]
    assert first["trace_id"] == "t10" and first["direction"] == "judge_too_lenient"
    assert first["human_label"] == "fail" and first["judge_score"] == 1.0
    assert first["human_comment"] == "hallucinated the citation"
    assert r["disagreements"][1]["direction"] == "judge_too_harsh"


def test_the_disagreement_list_is_capped_and_says_so():
    n = 60
    r = calibration.calibrate(_pairs([True] * n, [False] * n), limit=10)
    assert r["disagreement_count"] == n and len(r["disagreements"]) == 10
    assert r["truncated"] is True


# ---------------------------------------------------------------- the endpoint


def _client():
    return TestClient(app, base_url="https://testserver")


def _span(trace):
    return {"name": "agent", "traceId": trace, "spanId": "a" * 16,
            "startTimeUnixNano": "1000000000", "endTimeUnixNano": "1500000000",
            "status": {"code": 1},
            "attributes": [{"key": "gen_ai.operation.name", "value": {"stringValue": "invoke_agent"}}]}


def test_endpoint_measures_the_judge_over_stored_feedback():
    # Distinct annotation names, and both filters passed: every test in the suite shares this
    # workspace, so anything less would measure other tests' feedback too.
    c = _client()
    for i in range(calibration.MIN_LABELLED_N):
        trace = f"cal-{i}"
        c.post("/v1/traces", json={"resourceSpans": [{"scopeSpans": [{"spans": [_span(trace)]}]}]})
        # 18 good, 2 bad — and a judge that says "good" to all of them.
        c.post(f"/api/traces/{trace}/feedback",
               json={"name": "cal-thumbs", "value": "up" if i < 18 else "down"})
        c.post(f"/api/traces/{trace}/feedback",
               json={"name": "cal-judge", "score": 1.0, "source": "eval"})

    r = c.get("/api/experiments/judge-calibration",
              params={"judge_name": "cal-judge", "human_name": "cal-thumbs"}).json()
    assert r["n"] == calibration.MIN_LABELLED_N and r["sufficient"] is True
    assert r["agreement"] == 0.9 and r["kappa"] == 0.0
    assert r["confusion"]["human_fail_judge_pass"] == 2
    assert [d["direction"] for d in r["disagreements"]] == ["judge_too_lenient"] * 2


def test_endpoint_refuses_a_verdict_on_a_thin_workspace():
    """A fresh workspace has no labels; the endpoint must say so rather than return 0.0."""
    c = _client()
    key = c.post("/api/api-keys", json={"name": "cal"}).json()["key"]
    hdr = {"Authorization": f"Bearer {key}"}
    trace = "cal-thin"
    c.post("/v1/traces", headers=hdr,
           json={"resourceSpans": [{"scopeSpans": [{"spans": [_span(trace)]}]}]})
    c.post(f"/v1/traces/{trace}/feedback", headers=hdr, json={"name": "thin-thumbs", "value": "up"})
    c.post(f"/v1/traces/{trace}/feedback", headers=hdr,
           json={"name": "thin-judge", "score": 0.9, "source": "eval"})

    r = c.get("/v1/experiments/judge-calibration", headers=hdr,
              params={"judge_name": "thin-judge", "human_name": "thin-thumbs"}).json()
    assert r["n"] == 1 and r["sufficient"] is False
    assert r["kappa"] is None and r["verdict"] == ""
    assert str(calibration.MIN_LABELLED_N) in r["caution"]


def test_calibration_path_is_not_swallowed_by_the_experiment_id_route():
    """The literal segment must win over /{eid}; a 422 here means the routes are misordered."""
    c = _client()
    assert c.get("/api/experiments/judge-calibration").status_code == 200
