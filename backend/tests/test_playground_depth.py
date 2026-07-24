"""Multi-span replay (#57) and tool-argument replay (#63), through the real app.

Both features live on POST /api/replay/multi, and both are only worth anything if the honest
accounting services/replay.py established survives them: an edit is allowed to change the run,
it is never allowed to make an unreliable run look like a reproduction. So most of what is
asserted here is the badging, not the output.

Every request goes through `provekit.main.app` — the routes are on the already-registered
playground router, so what these tests exercise is what a browser reaches.
"""
import json

import pytest
from fastapi.testclient import TestClient

from fake_provider import openai_connection

from provekit.database import SessionLocal
from provekit.main import app
from provekit.models import ProviderConnection, Run
from provekit.routers.playground import _args_equal


def _ws_id(c: TestClient, label: str) -> int:
    """The workspace the playground endpoints will actually run in for this client."""
    conn = c.post("/api/connections",
                  json={"provider": "openai", "label": label, "key": "sk-test-0000"}).json()
    db = SessionLocal()
    try:
        return db.get(ProviderConnection, conn["id"]).workspace_id
    finally:
        db.close()


def _msg(text: str) -> str:
    return json.dumps([{"role": "user", "content": text}])


def _seed(ws_id: int, tid: str, rows: list[dict]) -> str:
    db = SessionLocal()
    db.add_all([Run(workspace_id=ws_id, trace_id=tid, **r) for r in rows])
    db.commit(); db.close()
    return tid


def _states(trace_id: str) -> dict[str, str]:
    db = SessionLocal()
    try:
        return {s.label: (s.result.get("meta") or {}).get("replay_state")
                for s in db.query(Run).filter(Run.trace_id == trace_id).all()}
    finally:
        db.close()


def _rows(trace_id: str) -> dict[str, Run]:
    db = SessionLocal()
    try:
        return {s.label: s for s in db.query(Run).filter(Run.trace_id == trace_id).all()}
    finally:
        db.close()


# A planner → summariser flow: the shape #57 is about. The summariser's recorded input quotes
# the planner's output, so editing both at once has to thread AND respect the second edit.
def _seed_two_llm(ws_id: int, tid: str) -> str:
    return _seed(ws_id, tid, [
        dict(type="agent", label="root", span_id="r", parent_span_id="", request={}, result={}),
        dict(type="llm", label="planner", span_id="p", parent_span_id="r",
             request={"model": "gpt-4o", "input": _msg("plan the trip")},
             result={"text": "PLAN_ALPHA", "meta": {}}),
        dict(type="llm", label="summariser", span_id="s", parent_span_id="r",
             request={"model": "gpt-4o", "input": _msg("summarise PLAN_ALPHA briefly")},
             result={"text": "SUMMARY_ONE", "meta": {}}),
    ])


def test_two_prompts_edited_in_one_run(fake_provider):
    """#57: edit the planner and the summariser and get ONE branch. The summariser must run with
    the text the user typed for it — not with the planner's edit threaded over its old prompt,
    which is what a second, separate replay would have produced."""
    with TestClient(app, base_url="https://testserver") as c:
        tid = _seed_two_llm(_ws_id(c, "multi-two"), "multi2" + "0" * 26)
        r = c.post("/api/replay/multi", json={
            "origin_trace_id": tid, "connection_id": openai_connection(c),
            "edits": [
                {"span_id": "p", "kind": "llm", "model": "gpt-4o",
                 "messages": [{"role": "user", "content": "plan the trip by TRAIN"}]},
                {"span_id": "s", "kind": "llm", "model": "gpt-4o",
                 "messages": [{"role": "user", "content": "summarise in one word"}]},
            ]})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["mode"] == "reconstructed-multi" and d["edit_count"] == 2
        assert d["new_trace_id"] != tid
        assert _states(d["new_trace_id"]) == {"root": "unchanged", "planner": "live",
                                              "summariser": "live"}
        # both edits ran live in a single branch, and neither carried invalidated text
        assert d["fidelity"]["live"] == 2 and d["reliable"] is True
        assert set(d["outputs"]) == {"p", "s"}
        rows = _rows(d["new_trace_id"])
        assert "one word" in rows["summariser"].request["input"]      # the user's text, not threaded
        assert "PLAN_ALPHA" not in rows["summariser"].request["input"]
        assert all((v.result["meta"].get("replay_edited") is True)
                   for k, v in rows.items() if k in ("planner", "summariser"))


def test_second_edit_does_not_hide_divergence_from_the_first(fake_provider):
    """Two edits mean two taint sources. Editing the summariser must not launder the fact that
    its prompt still quotes a tool result the planner edit invalidated."""
    with TestClient(app, base_url="https://testserver") as c:
        tid = _seed(_ws_id(c, "multi-taint"), "multitaint" + "0" * 22, [
            dict(type="agent", label="root", span_id="r", parent_span_id="", request={}, result={}),
            dict(type="llm", label="planner", span_id="p", parent_span_id="r",
                 request={"model": "gpt-4o", "input": _msg("which city?")},
                 result={"text": "PARIS", "meta": {}}),
            dict(type="tool", label="get_weather", span_id="t", parent_span_id="r",
                 request={"input": '{"city": "PARIS"}'},
                 result={"text": "12C and raining", "meta": {}}),
            dict(type="llm", label="summariser", span_id="s", parent_span_id="r",
                 request={"model": "gpt-4o", "input": _msg("advise: 12C and raining")},
                 result={"text": "bring an umbrella", "meta": {}}),
        ])
        r = c.post("/api/replay/multi", json={
            "origin_trace_id": tid, "connection_id": openai_connection(c),
            "edits": [
                {"span_id": "p", "kind": "llm", "model": "gpt-4o",
                 "messages": [{"role": "user", "content": "which city? answer TOKYO"}]},
                # the user edits the summariser but leaves the tool's recorded result quoted in it
                {"span_id": "s", "kind": "llm", "model": "gpt-4o",
                 "messages": [{"role": "user", "content": "be terse. advise: 12C and raining"}]},
            ]})
        assert r.status_code == 200, r.text
        d = r.json()
        st = _states(d["new_trace_id"])
        assert st["planner"] == "live"
        assert st["get_weather"] == "diverged", st        # ran on PARIS, run now says TOKYO
        assert st["summariser"] == "live"                 # the user's own edit did run
        # …but it ran on a weather reading the tool would no longer have returned
        assert d["tainted_input_spans"] == ["s"]
        assert d["reliable"] is False
        assert "invalidated" in d["fidelity_warning"]
        meta = _rows(d["new_trace_id"])["summariser"].result["meta"]
        assert meta.get("replay_input_tainted") is True


def test_clean_second_edit_stays_reliable_when_nothing_diverges(fake_provider):
    """The counterweight to the test above: if the second edit drops the invalidated text, the
    branch is clean and must not be badged unreliable out of caution."""
    with TestClient(app, base_url="https://testserver") as c:
        tid = _seed(_ws_id(c, "multi-clean"), "multiclean" + "0" * 22, [
            dict(type="agent", label="root", span_id="r", parent_span_id="", request={}, result={}),
            dict(type="llm", label="planner", span_id="p", parent_span_id="r",
                 request={"model": "gpt-4o", "input": _msg("which city?")},
                 result={"text": "PARIS", "meta": {}}),
            dict(type="llm", label="summariser", span_id="s", parent_span_id="r",
                 request={"model": "gpt-4o", "input": _msg("advise about PARIS")},
                 result={"text": "walk everywhere", "meta": {}}),
        ])
        r = c.post("/api/replay/multi", json={
            "origin_trace_id": tid, "connection_id": openai_connection(c),
            "edits": [
                {"span_id": "p", "kind": "llm", "model": "gpt-4o",
                 "messages": [{"role": "user", "content": "which city? answer TOKYO"}]},
                {"span_id": "s", "kind": "llm", "model": "gpt-4o",
                 "messages": [{"role": "user", "content": "advise about TOKYO"}]},
            ]})
        d = r.json()
        assert d["reliable"] is True and d["fidelity_warning"] == ""
        assert d["tainted_input_spans"] == []


# ---- #63: tool spans ----
def _seed_tool_flow(ws_id: int, tid: str) -> str:
    return _seed(ws_id, tid, [
        dict(type="agent", label="root", span_id="r", parent_span_id="", request={}, result={}),
        dict(type="tool", label="get_weather", span_id="t", parent_span_id="r",
             request={"input": '{"city": "PARIS", "unit": "c"}'},
             result={"text": "12C and raining", "meta": {"tool": "get_weather"}}),
        dict(type="llm", label="advise", span_id="d", parent_span_id="r",
             request={"model": "gpt-4o", "input": _msg("weather is 12C and raining")},
             result={"text": "bring an umbrella", "meta": {}}),
    ])


def test_changed_tool_arguments_diverge_and_invent_nothing(fake_provider):
    """#63 + the vcr.py rule: the moment a tool's arguments change, its recorded response is
    evidence of nothing. It must be badged diverged, the taint must reach the call that reads
    it, and no substitute tool result may be invented."""
    with TestClient(app, base_url="https://testserver") as c:
        tid = _seed_tool_flow(_ws_id(c, "tool-changed"), "tooledit" + "0" * 24)
        r = c.post("/api/replay/multi", json={
            "origin_trace_id": tid, "connection_id": openai_connection(c),
            "edits": [{"span_id": "t", "kind": "tool",
                       "arguments": {"city": "TOKYO", "unit": "c"}}]})
        assert r.status_code == 200, r.text
        d = r.json()
        st = _states(d["new_trace_id"])
        assert st == {"root": "unchanged", "get_weather": "diverged", "advise": "diverged"}, st
        assert d["reliable"] is False and d["fidelity"]["live"] == 0   # nothing was executed
        rows = _rows(d["new_trace_id"])
        # the edited arguments are recorded on the span…
        assert json.loads(rows["get_weather"].request["input"])["city"] == "TOKYO"
        # …and the result is still the RECORDED one, badged — not a fabricated answer for TOKYO
        assert rows["get_weather"].result["text"] == "12C and raining"


def test_unchanged_tool_arguments_serve_the_recording(fake_provider):
    """The other half of the rule: re-submitting the same arguments is a cassette hit, so the
    recorded response still stands. Key order and whitespace must not count as a change — a round
    trip through the portal's editor re-serialises the payload."""
    with TestClient(app, base_url="https://testserver") as c:
        tid = _seed_tool_flow(_ws_id(c, "tool-same"), "toolsame" + "0" * 24)
        r = c.post("/api/replay/multi", json={
            "origin_trace_id": tid, "connection_id": openai_connection(c),
            "edits": [{"span_id": "t", "kind": "tool",
                       "arguments": '{"unit":"c",  "city":"PARIS"}'}]})   # reordered, respaced
        assert r.status_code == 200, r.text
        d = r.json()
        st = _states(d["new_trace_id"])
        assert st == {"root": "unchanged", "get_weather": "recorded", "advise": "recorded"}, st
        assert d["reliable"] is True


def test_pinned_tool_arguments_stop_an_upstream_taint_cascade(fake_provider):
    """Editing a tool's arguments back to the recorded ones is the user asserting 'assume the
    tool still saw this'. The tool is a function of its arguments, so the recording is valid
    evidence for them again and the cascade from the upstream edit stops there."""
    with TestClient(app, base_url="https://testserver") as c:
        tid = _seed(_ws_id(c, "tool-pin"), "toolpin" + "0" * 25, [
            dict(type="agent", label="root", span_id="r", parent_span_id="", request={}, result={}),
            dict(type="llm", label="pick_city", span_id="p", parent_span_id="r",
                 request={"model": "gpt-4o", "input": _msg("which city?")},
                 result={"text": "PARIS", "meta": {}}),
            dict(type="tool", label="get_weather", span_id="t", parent_span_id="r",
                 request={"input": '{"city": "PARIS"}'},
                 result={"text": "12C and raining", "meta": {}}),
        ])
        # without the tool edit the tool diverges (this is the behaviour #194 established)
        base = c.post("/api/replay/multi", json={
            "origin_trace_id": tid, "connection_id": openai_connection(c),
            "edits": [{"span_id": "p", "kind": "llm", "model": "gpt-4o",
                       "messages": [{"role": "user", "content": "which city? answer TOKYO"}]}]}).json()
        assert _states(base["new_trace_id"])["get_weather"] == "diverged"

        pinned = c.post("/api/replay/multi", json={
            "origin_trace_id": tid, "connection_id": openai_connection(c),
            "edits": [{"span_id": "p", "kind": "llm", "model": "gpt-4o",
                       "messages": [{"role": "user", "content": "which city? answer TOKYO"}]},
                      {"span_id": "t", "kind": "tool", "arguments": {"city": "PARIS"}}]}).json()
        assert _states(pinned["new_trace_id"])["get_weather"] == "recorded"
        assert pinned["reliable"] is True


def test_tool_only_edit_needs_no_provider_connection():
    """A tool edit executes nothing, so refusing it for want of a provider connection would be
    refusing a replay that cannot cost anything."""
    with TestClient(app, base_url="https://testserver") as c:
        tid = _seed_tool_flow(_ws_id(c, "tool-noconn"), "toolnoconn" + "0" * 22)
        r = c.post("/api/replay/multi", json={
            "origin_trace_id": tid,           # no provider, no connection_id
            "edits": [{"span_id": "t", "kind": "tool", "arguments": '{"city": "TOKYO"}'}]})
        assert r.status_code == 200, r.text
        assert r.json()["fidelity"]["live"] == 0


# ---- validation / accounting ----
def test_multi_replay_validation(fake_provider):
    with TestClient(app, base_url="https://testserver") as c:
        tid = _seed_two_llm(_ws_id(c, "multi-valid"), "multivalid" + "0" * 22)
        base = {"origin_trace_id": tid, "connection_id": openai_connection(c)}
        one = {"span_id": "p", "kind": "llm", "messages": [{"role": "user", "content": "hi"}]}

        assert c.post("/api/replay/multi", json={**base, "edits": []}).status_code == 422
        assert c.post("/api/replay/multi", json={**base, "edits": [one, one]}).status_code == 422
        assert c.post("/api/replay/multi", json={
            **base, "edits": [{"span_id": "p", "kind": "llm", "messages": []}]}).status_code == 422
        assert c.post("/api/replay/multi", json={
            **base, "edits": [{"span_id": "t", "kind": "tool"}]}).status_code == 422
        assert c.post("/api/replay/multi", json={
            **base, "edits": [{**one, "kind": "sql"}]}).status_code == 422
        assert c.post("/api/replay/multi", json={**base, "edits": [one] * 9}).status_code == 422
        # a span id that isn't in the trace is a 404, not a silently ignored edit
        assert c.post("/api/replay/multi", json={
            **base, "edits": [{**one, "span_id": "nope"}]}).status_code == 404
        assert c.post("/api/replay/multi", json={
            "origin_trace_id": "missing", "connection_id": openai_connection(c), "edits": [one]}).status_code == 404


def test_multi_replay_meters_spend_and_the_cap_stops_it(monkeypatch, fake_provider):
    """Metering is per live call, not per request: N edits are N provider calls, and a cap that
    is only checked at admission is a cap one request walks straight past."""
    from provekit.config import get_settings
    from provekit.routers import playground as pg
    from provekit.services import limits

    with TestClient(app, base_url="https://testserver") as c:
        tid = _seed_two_llm(_ws_id(c, "multi-spend"), "multispend" + "0" * 22)
        edits = [{"span_id": "p", "kind": "llm", "model": "gpt-4o",
                  "messages": [{"role": "user", "content": "plan by TRAIN"}]},
                 {"span_id": "s", "kind": "llm", "model": "gpt-4o",
                  "messages": [{"role": "user", "content": "one word"}]}]

        seen: list[float] = []
        monkeypatch.setattr(pg.limits, "record_spend", lambda ws_id, usd: seen.append(usd))
        r = c.post("/api/replay/multi", json={"origin_trace_id": tid, "connection_id": openai_connection(c),
                                              "edits": edits})
        assert r.status_code == 200, r.text
        assert len(seen) == 2          # one metered call per LLM edit
        monkeypatch.undo()

        # now trip the cap between the two calls: the second must be refused, not billed
        get_settings.cache_clear(); limits._window.cache_clear()
        monkeypatch.setenv("PLAYGROUND_MONTHLY_USD_CAP", "0.000001")
        get_settings.cache_clear()
        calls = {"n": 0}
        real = pg.complete

        async def counting(*a, **k):
            calls["n"] += 1
            return await real(*a, **k)

        monkeypatch.setattr(pg, "complete", counting)
        try:
            r2 = c.post("/api/replay/multi", json={"origin_trace_id": tid, "connection_id": openai_connection(c),
                                                   "edits": edits})
            assert r2.status_code == 402, r2.text
            # the first call was made and billed; the cap then refused the second mid-run, which
            # an admission-time-only check could not have done
            assert calls["n"] == 1
        finally:
            monkeypatch.undo()
            get_settings.cache_clear(); limits._window.cache_clear()


@pytest.mark.parametrize("a,b,same", [
    ('{"city": "PARIS"}', '{"city":"PARIS"}', True),           # whitespace only
    ('{"a": 1, "b": 2}', '{"b": 2, "a": 1}', True),            # key order only
    ('{"city": "PARIS"}', '{"city": "TOKYO"}', False),
    ("  plain  ", "plain", True),                              # non-JSON arguments
    ("plain", "other", False),
    ('{"broken', '{"broken', True),                            # unparseable, compared as text
])
def test_args_equal_compares_meaning_not_bytes(a, b, same):
    assert _args_equal(a, b) is same
