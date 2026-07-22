"""Automation rules (#47) and online production evals (#39).

Evaluation was entirely offline, so the dataset drifted away from real traffic and the traces
most worth learning from were the ones nobody copied across. Most of this file is about the
ways a rule engine acting on live traffic goes wrong.
"""
import pytest
from fastapi.testclient import TestClient

from provekit.main import app
from provekit.services import automation


def _client():
    return TestClient(app, base_url="https://testserver")


def _span(i, label="chat", failed=False):
    return {"name": label, "traceId": f"{i:032x}", "spanId": f"{i:016x}", "parentSpanId": "",
            "startTimeUnixNano": "1000000000", "endTimeUnixNano": "1500000000",
            "status": {"code": 2, "message": "boom"} if failed else {"code": 1},
            "attributes": [{"key": "gen_ai.request.model", "value": {"stringValue": "gpt-4o"}},
                           {"key": "gen_ai.completion", "value": {"stringValue": "an answer"}}]}


def _otlp(*s):
    return {"resourceSpans": [{"scopeSpans": [{"spans": list(s)}]}]}


# ---- validation: the failures that can't be undone later ------------------------------------

def test_an_empty_match_is_refused():
    """A rule matching everything would promote a project's entire history into a dataset on
    its first pass, and you cannot undo that by editing the rule afterwards."""
    with pytest.raises(ValueError, match="every trace"):
        automation.validate({}, "promote", target_dataset_id=1)
    with pytest.raises(ValueError, match="every trace"):
        automation.validate({"nonsense": "x"}, "promote", target_dataset_id=1)


def test_an_action_without_its_target_is_refused():
    with pytest.raises(ValueError, match="target_dataset_id"):
        automation.validate({"status": "failed"}, "promote")
    with pytest.raises(ValueError, match="scorer"):
        automation.validate({"status": "failed"}, "score", scorers=[])


def test_a_nonsensical_sample_is_refused():
    for bad in (0, -0.5, 1.5):
        with pytest.raises(ValueError, match="sample"):
            automation.validate({"status": "failed"}, "promote", target_dataset_id=1, sample=bad)


def test_validation_happens_at_save_time():
    """A rule that only reveals its problem on the background pass fails where nobody looks."""
    with _client() as c:
        assert c.post("/api/automation", json={"name": "x", "match": {},
                                               "action": "promote"}).status_code == 422


# ---- sampling ------------------------------------------------------------------------------

class _Rule:
    def __init__(self, sample, rid=1):
        self.sample, self.id = sample, rid


def test_sampling_is_deterministic_on_the_trace():
    """Random sampling would score a different subset on a re-run — and could score the same
    trace twice across retries, charging twice and writing two contradictory scores."""
    r = _Rule(0.5)
    first = [automation.sampled(r, f"trace-{i}") for i in range(200)]
    second = [automation.sampled(r, f"trace-{i}") for i in range(200)]
    assert first == second
    assert 0.3 < sum(first) / len(first) < 0.7      # roughly the requested fraction


def test_full_sample_takes_everything():
    r = _Rule(1.0)
    assert all(automation.sampled(r, f"t{i}") for i in range(50))


# ---- promote -------------------------------------------------------------------------------

def test_a_rule_promotes_only_matching_traces_and_only_new_ones():
    with _client() as c:
        did = c.post("/api/datasets", json={"name": "auto-promote", "description": ""}).json()["id"]
        # Ingested BEFORE the rule exists: a new rule must not sweep history.
        c.post("/v1/traces", json=_otlp(_span(0xA1, failed=True)))
        rule = c.post("/api/automation", json={
            "name": "failures", "match": {"status": "failed"}, "action": "promote",
            "target_dataset_id": did}).json()
        assert rule["last_run_id"] > 0             # watermark starts at the newest trace

        c.post("/v1/traces", json=_otlp(_span(0xA2, failed=True)))   # matches
        c.post("/v1/traces", json=_otlp(_span(0xA3)))                # does not
        out = c.post(f"/api/automation/{rule['id']}/run").json()
        items = c.get(f"/api/datasets/{did}").json()["items"]
    assert out["acted"] == 1
    assert len(items) == 1
    assert items[0]["meta"]["trace_id"] == f"{0xA2:032x}"


def test_promotion_is_idempotent():
    """Re-running must not add a second copy — that would quietly weight one example twice in
    every experiment afterwards."""
    with _client() as c:
        did = c.post("/api/datasets", json={"name": "auto-idem", "description": ""}).json()["id"]
        rule = c.post("/api/automation", json={
            "name": "all-failures", "match": {"status": "failed"}, "action": "promote",
            "target_dataset_id": did}).json()
        c.post("/v1/traces", json=_otlp(_span(0xB1, failed=True)))
        c.post(f"/api/automation/{rule['id']}/run")
        # Rewind the watermark so the same trace is considered again.
        from provekit.database import SessionLocal
        from provekit.models import AutomationRule
        from provekit.models import Run
        db = SessionLocal()
        row = db.query(Run).filter(Run.trace_id == f"{0xB1:032x}").first()
        r = db.get(AutomationRule, rule["id"]); r.last_run_id = row.id - 1
        db.commit(); db.close()
        c.post(f"/api/automation/{rule['id']}/run")
        items = c.get(f"/api/datasets/{did}").json()["items"]
    # Exactly one copy of THIS trace: rewinding could legitimately pull in other failures.
    assert len([i for i in items if i["meta"].get("trace_id") == f"{0xB1:032x}"]) == 1


def test_a_new_rule_does_not_sweep_history():
    """The surprise this avoids: a `score` rule created today firing a judge call against every
    trace the project has ever captured."""
    with _client() as c:
        c.post("/v1/traces", json=_otlp(_span(0xC1, failed=True)))
        did = c.post("/api/datasets", json={"name": "auto-nosweep", "description": ""}).json()["id"]
        rule = c.post("/api/automation", json={
            "name": "fresh", "match": {"status": "failed"}, "action": "promote",
            "target_dataset_id": did}).json()
        out = c.post(f"/api/automation/{rule['id']}/run").json()
        items = c.get(f"/api/datasets/{did}").json()["items"]
    assert out["acted"] == 0 and items == []


# ---- score (online evals, #39) --------------------------------------------------------------

def test_a_score_rule_writes_feedback_against_the_live_trace():
    """The eval loop that needs no ground truth: it judges what actually shipped."""
    with _client() as c:
        rule = c.post("/api/automation", json={
            "name": "online", "match": {"status": "failed"}, "action": "score",
            "scorers": ["json_valid"]}).json()
        tid = f"{0xD1:032x}"
        c.post("/v1/traces", json=_otlp(_span(0xD1, failed=True)))
        c.post(f"/api/automation/{rule['id']}/run")
        fb = c.get(f"/api/traces/{tid}/feedback").json()
    names = {f["name"] for f in fb}
    assert "json_valid" in names
    assert all(f["source"] == "eval" for f in fb if f["name"] == "json_valid")


def test_a_trace_is_not_scored_twice():
    with _client() as c:
        rule = c.post("/api/automation", json={
            "name": "online-idem", "match": {"status": "failed"}, "action": "score",
            "scorers": ["json_valid"]}).json()
        tid = f"{0xD2:032x}"
        c.post("/v1/traces", json=_otlp(_span(0xD2, failed=True)))
        c.post(f"/api/automation/{rule['id']}/run")
        from provekit.database import SessionLocal
        from provekit.models import AutomationRule
        from provekit.models import Run
        db = SessionLocal()
        row = db.query(Run).filter(Run.trace_id == tid).first()
        r = db.get(AutomationRule, rule["id"]); r.last_run_id = row.id - 1
        db.commit(); db.close()
        c.post(f"/api/automation/{rule['id']}/run")
        fb = [f for f in c.get(f"/api/traces/{tid}/feedback").json() if f["name"] == "json_valid"]
    assert len(fb) == 1


# ---- matching ------------------------------------------------------------------------------

def test_match_conditions_are_anded():
    class R:
        match = {"status": "failed", "label_contains": "checkout"}

    class Root:
        status, label, type, search_text = "failed", "checkout agent", "agent", ""

    assert automation.matches(R(), Root())
    Root.label = "billing agent"
    assert not automation.matches(R(), Root())
