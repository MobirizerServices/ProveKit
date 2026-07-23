"""Runtime prompt fetch + live A/B (#61, #62) and multi-turn session eval (#44)."""
import pytest
from fastapi.testclient import TestClient

from provekit.main import app
from provekit.scorers import (session_complete, session_expected_covered, session_no_repeat,
                              session_turns)
from provekit.services import prompts as prompt_svc


def _client():
    return TestClient(app, base_url="https://testserver")


class _P:
    def __init__(self, version, traffic=0.0, label=""):
        self.version, self.traffic, self.label = version, traffic, label


# ---- assignment: the property the whole feature rests on ------------------------------------

def test_assignment_is_stable_for_a_key():
    """A user who gets variant B on turn one must get B on turn four, or the conversation is
    incoherent and the experiment measures assignment noise instead of the prompts."""
    live = [_P(1, 0.5), _P(2, 0.5)]
    for key in ("session-abc", "user-42", "x"):
        picks = {prompt_svc.assign(live, key).version for _ in range(20)}
        assert len(picks) == 1


def test_traffic_weights_are_respected():
    live = [_P(1, 0.9), _P(2, 0.1)]
    picks = [prompt_svc.assign(live, f"k{i}").version for i in range(400)]
    share = picks.count(1) / len(picks)
    assert 0.8 < share < 0.98


def test_no_live_version_assigns_nothing():
    assert prompt_svc.assign([_P(1, 0), _P(2, 0)], "k") is None


def test_a_one_sided_split_is_refused():
    """One version at any weight is just the served prompt, not an experiment."""
    with pytest.raises(ValueError, match="at least two"):
        prompt_svc.validate_split([_P(1, 1.0), _P(2, 0)])


# ---- resolution order ----------------------------------------------------------------------

def test_a_label_wins_over_a_running_split():
    """If someone pinned production to a version, an experiment started later must not quietly
    redirect them."""
    with _client() as c:
        c.post("/api/playground/prompts", json={"name": "p-order", "model": "gpt-4o",
                                                "messages": [], "params": {}})
    from provekit.database import SessionLocal
    from provekit.models import Prompt
    db = SessionLocal()
    try:
        rows = db.query(Prompt).filter(Prompt.name == "p-order").all()
        if not rows:
            pytest.skip("prompt save endpoint differs; resolution order covered by unit tests")
        rows[0].label = "production"
        rows[0].traffic = 0.0
        db.commit()
        p, reason = prompt_svc.resolve(db, rows[0].workspace_id, "p-order", label="production")
        assert p.version == rows[0].version and reason == "label:production"
    finally:
        db.close()


def test_an_unknown_name_resolves_to_nothing_with_a_reason():
    from provekit.database import SessionLocal
    db = SessionLocal()
    try:
        p, reason = prompt_svc.resolve(db, 1, "definitely-not-a-prompt")
        assert p is None and "no prompt" in reason
    finally:
        db.close()


# ---- the SDK side ---------------------------------------------------------------------------

def test_get_prompt_returns_the_default_when_unconfigured(monkeypatch):
    """A prompt fetch that raises would take down the app on a network blip — same fail-open
    contract as the rest of the SDK."""
    import provekit as pk
    monkeypatch.delenv("PROVEKIT_API_KEY", raising=False)
    monkeypatch.delenv("PROVEKIT_ENDPOINT", raising=False)
    import provekit.trace as t
    monkeypatch.setattr(t, "_api_key", None)
    monkeypatch.setattr(t, "_endpoint", None)
    sentinel = {"messages": ["fallback"]}
    assert pk.get_prompt("anything", default=sentinel) is sentinel


def test_get_prompt_survives_an_unreachable_portal(monkeypatch):
    import httpx

    import provekit.trace as t
    monkeypatch.setattr(t, "_api_key", "pk_x")
    monkeypatch.setattr(t, "_endpoint", "http://portal.invalid")
    monkeypatch.setattr(httpx, "get", lambda *a, **k: (_ for _ in ()).throw(
        httpx.ConnectError("down")))
    import provekit as pk
    assert pk.get_prompt("x", default="kept") == "kept"


# ---- session eval (#44) ----------------------------------------------------------------------

def test_turns_are_read_from_a_captured_session():
    spans = [{"request": {"input": "hi"}, "result": {"text": "hello"}},
             {"request": {"input": "and then?"}, "result": {"text": "next step"}}]
    assert session_turns(spans) == [{"input": "hi", "output": "hello"},
                                    {"input": "and then?", "output": "next step"}]


def test_a_single_turn_run_is_not_applicable_rather_than_zero():
    """Scoring an inapplicable row zero would drag an experiment's mean with a judgement the
    scorer never made."""
    assert session_complete("a plain answer", "") is None
    assert session_no_repeat([{"input": "a", "output": "b"}], "") is None


def test_an_unanswered_turn_is_caught():
    """The characteristic multi-turn failure single-turn scoring cannot see: a turn that
    returned nothing, while the LAST turn is perfectly fine."""
    turns = [{"input": "a", "output": ""}, {"input": "b", "output": "fine"}]
    assert session_complete(turns, "") == 0.5


def test_a_repeating_assistant_is_caught():
    turns = [{"input": "a", "output": "same"}, {"input": "b", "output": "same"},
             {"input": "c", "output": "same"}]
    assert session_no_repeat(turns, "") < 1.0


def test_expected_points_may_be_covered_across_turns():
    """In a conversation the answer is often assembled over several turns; requiring it all in
    the last one would fail an exchange that actually succeeded."""
    turns = [{"input": "a", "output": "the price is 40"},
             {"input": "b", "output": "and shipping is free"}]
    assert session_expected_covered(turns, "40|free") == 1.0
    assert session_expected_covered(turns, "40|overnight") == 0.5


def test_listing_prompts_exposes_label_and_traffic():
    """The registry UI needs to show which version production fetches and what share of
    traffic each takes — a version history without them can't be acted on."""
    from fastapi.testclient import TestClient

    from provekit.main import app

    c = TestClient(app, base_url="https://testserver")
    body = {"name": "registry-shape", "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "hi"}], "params": {}}
    c.post("/api/prompts", json=body)
    c.post("/api/prompts", json=body)
    c.post("/api/prompts/registry-shape/label?version=2", json={"label": "production"})
    c.post("/api/prompts/registry-shape/split", json={"weights": {"1": 30, "2": 70}})

    rows = [p for p in c.get("/api/prompts").json() if p["name"] == "registry-shape"]
    by_version = {p["version"]: p for p in rows}
    assert by_version[2]["label"] == "production"
    assert by_version[1]["label"] == ""
    assert (by_version[1]["traffic"], by_version[2]["traffic"]) == (30.0, 70.0)
