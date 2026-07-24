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
