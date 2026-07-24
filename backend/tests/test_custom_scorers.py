"""Project-defined server-side scorers (#48).

The design decision under test is that these are *rules*, not uploaded code. So the tests care
about two things: that a rule is rejected while its author is looking at it rather than silently
scoring 0.0 forever, and that the regex kind cannot be handed something pathological.
"""
import uuid

import pytest
from fastapi.testclient import TestClient

from provekit.database import SessionLocal
from provekit.main import app
from provekit.models import Feedback, Run
from provekit.services import custom_scorers


def _client():
    return TestClient(app, base_url="https://testserver")


def _account(c) -> int:
    email = f"cs{uuid.uuid4().hex[:10]}@ex.com"
    assert c.post("/api/auth/register", json={"email": email, "password": "pw12345678"}).status_code == 200
    return c.get("/api/projects").json()[0]["id"]


def _make(c, **over):
    body = {"name": f"rule_{uuid.uuid4().hex[:6]}", "kind": "contains",
            "config": {"value": "refund"}}
    body.update(over)
    return c.post("/api/evaluators/custom", json=body)


# ---- the rules themselves ----

@pytest.mark.parametrize("kind,cfg,output,expected", [
    ("contains", {"value": "refund"}, "your refund is on the way", 1.0),
    ("contains", {"value": "refund"}, "nothing relevant", 0.0),
    ("not_contains", {"value": "sorry"}, "here you go", 1.0),
    ("not_contains", {"value": "sorry"}, "sorry, no", 0.0),
    ("equals", {"value": "yes"}, "  YES ", 1.0),
    ("regex", {"pattern": r"\d{3}-\d{4}"}, "call 555-1234", 1.0),
    ("regex", {"pattern": r"\d{3}-\d{4}"}, "no number", 0.0),
    ("length_between", {"min": 2, "max": 10}, "hello", 1.0),
    ("length_between", {"min": 2, "max": 3}, "far too long", 0.0),
    ("json_path", {"path": "status", "equals": "ok"}, '{"status": "ok"}', 1.0),
    ("json_path", {"path": "status", "equals": "ok"}, '{"status": "bad"}', 0.0),
    ("json_path", {"path": "a.b", "equals": "1"}, '{"a": {"b": 1}}', 1.0),
])
def test_each_kind_scores_what_it_says(kind, cfg, output, expected):
    assert custom_scorers.evaluate(kind, custom_scorers.validate(kind, cfg), output) == expected


def test_a_rule_that_cannot_apply_returns_none_not_zero():
    """None is omitted by run_scorers. Scoring an ungradeable row 0.0 would drag an experiment
    mean by exactly as much as a real failure while looking identical to one."""
    cfg = custom_scorers.validate("json_path", {"path": "status"})
    assert custom_scorers.evaluate("json_path", cfg, "this is not json") is None


# ---- validation happens while the author is watching ----

def test_a_broken_pattern_is_refused_at_creation():
    c = _client(); _account(c)
    r = _make(c, kind="regex", config={"pattern": "(unclosed"})
    assert r.status_code == 422 and "doesn't compile" in r.json()["detail"]


def test_a_catastrophically_backtracking_pattern_is_refused():
    """Python's re has no timeout, so the only real defence is not accepting the pattern."""
    c = _client(); _account(c)
    r = _make(c, kind="regex", config={"pattern": "(a+)+$"})
    assert r.status_code == 422
    assert "backtrack" in r.json()["detail"]


def test_an_overlong_pattern_is_refused():
    c = _client(); _account(c)
    r = _make(c, kind="regex", config={"pattern": "a" * (custom_scorers.MAX_PATTERN + 1)})
    assert r.status_code == 422 and str(custom_scorers.MAX_PATTERN) in r.json()["detail"]


def test_an_empty_rule_is_refused_rather_than_matching_everything():
    c = _client(); _account(c)
    assert _make(c, kind="contains", config={"value": "   "}).status_code == 422


def test_input_is_truncated_before_matching():
    """Bounds the worst case for a regex that cannot be given a timeout."""
    cfg = custom_scorers.validate("contains", {"value": "needle"})
    haystack = ("x" * custom_scorers.MAX_INPUT) + "needle"
    assert custom_scorers.evaluate("contains", cfg, haystack) == 0.0


# ---- naming ----

def test_a_custom_scorer_cannot_shadow_a_builtin():
    c = _client(); _account(c)
    r = _make(c, name="exact_match")
    assert r.status_code == 409 and "built-in" in r.json()["detail"]


def test_names_must_be_plain_identifiers():
    c = _client(); _account(c)
    assert _make(c, name="Not A Name!").status_code == 422


def test_two_projects_may_use_the_same_name_for_different_rules():
    """A scorer name means what *this* project defined it to mean."""
    a, b = _client(), _client()
    _account(a); _account(b)
    assert _make(a, name="tone_ok", config={"value": "please"}).status_code == 200
    assert _make(b, name="tone_ok", config={"value": "thanks"}).status_code == 200


def test_the_same_name_twice_in_one_project_is_refused():
    c = _client(); _account(c)
    assert _make(c, name="dupe_rule").status_code == 200
    assert _make(c, name="dupe_rule").status_code == 409


# ---- resolution and online eval ----

def test_resolve_mixes_builtins_and_custom_rules():
    c = _client(); pid = _account(c)
    _make(c, name="mentions_refund", config={"value": "refund"})
    db = SessionLocal()
    try:
        out = custom_scorers.resolve(db, pid, ["exact_match", "mentions_refund", "nope"])
    finally:
        db.close()
    assert out[0] == "exact_match"                 # built-in passed through untouched
    assert callable(out[1]) and out[1].__name__ == "mentions_refund"
    assert out[2] == "nope"                        # unknown left for run_scorers to skip


def test_a_custom_scorer_grades_a_live_trace_through_online_eval():
    """The actual point of the feature: online eval runs on the server, where no SDK exists to
    supply a Python scorer."""
    c = _client(); pid = _account(c)
    _make(c, name="says_refund", config={"value": "refund"})

    # The rule first: a new rule watermarks at the newest existing trace, so it acts on new
    # traffic rather than sweeping a project's whole history (routers/automation.create_rule).
    rule = c.post("/api/automation", json={
        "name": "grade", "match": {"status": "completed"}, "action": "score",
        "scorers": ["says_refund"], "sample": 1, "enabled": True}).json()

    db = SessionLocal()
    try:
        db.add(Run(workspace_id=pid, trace_id="cs" + "0" * 30, span_id="a" * 16,
                   parent_span_id="", type="agent", label="run", status="completed",
                   duration_ms=5, result={"text": "your refund is approved"}))
        db.commit()
    finally:
        db.close()

    c.post(f"/api/automation/{rule['id']}/run")

    db = SessionLocal()
    try:
        fb = (db.query(Feedback)
              .filter(Feedback.workspace_id == pid, Feedback.name == "says_refund").first())
        assert fb is not None, "the custom scorer never ran against a live trace"
        assert fb.score == 1.0 and fb.source == "eval"
    finally:
        db.close()


def test_try_scores_a_sample_before_it_is_trusted():
    c = _client(); _account(c)
    sid = _make(c, name="try_me", config={"value": "ok"}).json()["id"]
    assert c.post(f"/api/evaluators/custom/{sid}/try", json={"output": "all ok"}).json()["score"] == 1.0
    assert c.post(f"/api/evaluators/custom/{sid}/try", json={"output": "nope"}).json()["score"] == 0.0


def test_a_disabled_scorer_is_not_resolved():
    c = _client(); pid = _account(c)
    sid = _make(c, name="off_rule").json()["id"]
    c.delete(f"/api/evaluators/custom/{sid}")
    db = SessionLocal()
    try:
        assert custom_scorers.resolve(db, pid, ["off_rule"]) == ["off_rule"]
    finally:
        db.close()


# ---- the kinds that were validated but never actually run ------------------------------------

@pytest.mark.parametrize("kind,cfg,output,expected", [
    ("contains",      {"value": "policy"},                 "per the policy, yes",   1.0),
    ("contains",      {"value": "policy"},                 "no mention",            0.0),
    ("not_contains",  {"value": "sorry"},                   "here you go",          1.0),
    ("not_contains",  {"value": "sorry"},                   "sorry, I can't",       0.0),
    ("equals",        {"value": "yes"},                     "  yes  ",              1.0),
    ("equals",        {"value": "yes"},                     "yes please",           0.0),
    ("regex",         {"pattern": r"\d{3}-\d{4}"},          "call 555-0199",        1.0),
    ("regex",         {"pattern": r"\d{3}-\d{4}"},          "call me",              0.0),
    ("length_between", {"min": 3, "max": 10},               "hello",                1.0),
    ("length_between", {"min": 3, "max": 10},               "hi",                   0.0),
    ("length_between", {"min": 3, "max": 10},               "x" * 40,               0.0),
])
def test_each_kind_scores_what_it_says_it_scores(kind, cfg, output, expected):
    assert custom_scorers.evaluate(kind, custom_scorers.validate(kind, cfg), output) == expected


def test_case_insensitive_by_default_and_sensitive_on_request():
    cfg = custom_scorers.validate("contains", {"value": "Policy"})
    assert custom_scorers.evaluate("contains", cfg, "the policy") == 1.0
    strict = custom_scorers.validate("contains", {"value": "Policy", "case_sensitive": True})
    assert custom_scorers.evaluate("contains", strict, "the policy") == 0.0
    assert custom_scorers.evaluate("contains", strict, "the Policy") == 1.0


def test_a_json_path_rule_reads_into_the_document():
    cfg = custom_scorers.validate("json_path", {"path": "result.status", "equals": "ok"})
    assert custom_scorers.evaluate("json_path", cfg, '{"result": {"status": "ok"}}') == 1.0
    assert custom_scorers.evaluate("json_path", cfg, '{"result": {"status": "bad"}}') == 0.0
    # present-at-all, when no `equals` is configured
    any_cfg = custom_scorers.validate("json_path", {"path": "result.status"})
    assert custom_scorers.evaluate("json_path", any_cfg, '{"result": {"status": "x"}}') == 1.0


def test_a_json_path_rule_indexes_into_a_list():
    cfg = custom_scorers.validate("json_path", {"path": "items.1.id", "equals": "b"})
    assert custom_scorers.evaluate("json_path", cfg, '{"items": [{"id":"a"},{"id":"b"}]}') == 1.0


def test_a_rule_that_cannot_apply_returns_nothing_rather_than_zero():
    """The distinction the whole design rests on: an ungradeable row scored 0.0 drags an
    experiment mean exactly as hard as a real failure, while looking identical to one."""
    cfg = custom_scorers.validate("json_path", {"path": "result.status"})
    assert custom_scorers.evaluate("json_path", cfg, "this is prose, not JSON") is None
    # a path that simply isn't there IS a judgement — the output was gradeable and missed
    assert custom_scorers.evaluate("json_path", cfg, '{"other": 1}') == 0.0


def test_an_unknown_kind_evaluates_to_nothing():
    assert custom_scorers.evaluate("telepathy", {}, "anything") is None


def test_a_pattern_that_stopped_compiling_declines_instead_of_raising():
    """Rules are validated at creation, but a stored row predates whatever rule tightened last.
    It must decline rather than take down the evaluation run it is part of."""
    assert custom_scorers.evaluate("regex", {"pattern": "([unclosed"}, "text") is None


def test_the_regex_kind_is_truncated_too_not_just_contains():
    """The existing truncation test covers `contains`. `regex` is the kind that actually needs
    it — `re` has no timeout, so bounding the input is the only defence available."""
    cfg = custom_scorers.validate("regex", {"pattern": "needle"})
    far_past_the_limit = ("x" * (custom_scorers.MAX_INPUT + 500)) + "needle"
    assert custom_scorers.evaluate("regex", cfg, far_past_the_limit) == 0.0


def test_a_compiled_rule_never_raises_into_the_run():
    """`compile_row` is handed to run_scorers. One bad rule must cost its own score, not the
    whole evaluation."""
    class _Row:
        name, kind, config = "boom", "length_between", {"min": "not-a-number", "max": 5}

    scorer = custom_scorers.compile_row(_Row())
    assert scorer.__name__ == "boom"
    assert scorer("anything") is None


def test_resolve_mixes_builtins_and_project_rules(tmp_path):
    """A built-in name passes through untouched; a project's own name becomes its callable."""
    db = SessionLocal()
    try:
        from conftest import ingest_workspace_id
        ws = ingest_workspace_id()
        name = f"cites_{uuid.uuid4().hex[:6]}"
        from provekit.models import CustomScorer
        db.add(CustomScorer(workspace_id=ws, name=name, kind="contains",
                            config={"value": "policy"}, enabled=True))
        db.commit()

        out = custom_scorers.resolve(db, ws, ["json_valid", name])
        assert out[0] == "json_valid", "a built-in must pass through by name"
        assert callable(out[1]) and out[1]("per the policy") == 1.0

        # a name this project never defined stays a name — resolution is not a lookup failure
        assert custom_scorers.resolve(db, ws, ["nothing_defined"]) == ["nothing_defined"]
        assert custom_scorers.resolve(db, ws, []) == []
    finally:
        db.close()


def test_a_disabled_rule_is_not_resolved():
    """Disabling is how you stop a misfiring scorer without losing its definition."""
    db = SessionLocal()
    try:
        from conftest import ingest_workspace_id
        from provekit.models import CustomScorer
        ws = ingest_workspace_id()
        name = f"off_{uuid.uuid4().hex[:6]}"
        db.add(CustomScorer(workspace_id=ws, name=name, kind="contains",
                            config={"value": "x"}, enabled=False))
        db.commit()
        assert custom_scorers.resolve(db, ws, [name]) == [name]
    finally:
        db.close()
