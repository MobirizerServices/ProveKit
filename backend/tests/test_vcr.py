"""Recorded-response replay (#54), live tool re-execution (#53), and the allowlist (#55).

The standard these have to meet is the one #194 set for the server side: a replay may be
incomplete, but it may never present a value it invented as a faithful reproduction.
"""
import pytest
from fastapi.testclient import TestClient

import provekit as pk
from provekit import vcr
from provekit.main import app


@pytest.fixture(autouse=True)
def _no_leaked_session():
    yield
    vcr._state.session = None


def _entry(tool, args=(), kwargs=None, output="", status="completed", error=""):
    return {"tool": tool, "input": vcr._canonical(args, kwargs or {}),
            "output": output, "status": status, "error": error}


@pk.tool
def weather(city):
    return f"LIVE:{city}"


@pk.tool
def search(q, limit=3):
    return f"LIVE-SEARCH:{q}:{limit}"


def test_recorded_mode_serves_the_recording_and_never_calls_the_tool():
    cassette = [_entry("weather", ("paris",), output="12C and raining")]
    r = pk.replay("t", lambda: weather("paris"), cassette=cassette)
    assert r.result == "12C and raining"      # not "LIVE:paris" — the tool did not run
    assert r.hits == 1 and r.reliable


def test_a_miss_is_refused_in_recorded_mode():
    """Deterministic and side-effect-free is the contract; silently calling out would break
    both, so a miss is an error rather than a fallback."""
    with pytest.raises(vcr.ReplayMiss):
        pk.replay("t", lambda: weather("paris"), cassette=[])


def test_changed_arguments_are_served_but_reported_as_diverged():
    """The failure #194 was about, on this side of the wire: a tool whose input changed would
    not have returned its recorded result. Serving it anyway and calling the run faithful is
    exactly the confident-wrong-answer this feature exists to expose."""
    cassette = [_entry("weather", ("paris",), output="12C and raining")]
    r = pk.replay("t", lambda: weather("tokyo"), cassette=cassette)
    assert r.result == "12C and raining"      # the replay can continue...
    assert r.diverged and not r.reliable      # ...but it is not evidence of anything


def test_live_mode_calls_the_real_tool_on_a_miss():
    r = pk.replay("t", lambda: weather("tokyo"), cassette=[], mode="live")
    assert r.result == "LIVE:tokyo"
    assert r.live_calls and not r.reliable    # faithful to the tool, not to the recording


def test_dry_run_executes_nothing_and_says_what_it_would_have_called():
    r = pk.replay("t", lambda: weather("tokyo"), cassette=[], mode="dry-run")
    assert r.result is vcr.NOT_EXECUTED
    assert any("weather" in m for m in r.misses)
    assert not r.reliable


def test_allowlist_blocks_an_unlisted_tool_in_live_mode():
    """Replay must not be able to fire a production side effect twice just because it missed."""
    with pytest.raises(vcr.ReplayMiss, match="allowlist"):
        pk.replay("t", lambda: weather("tokyo"), cassette=[], mode="live", allow={"search"})

    r = pk.replay("t", lambda: weather("tokyo"), cassette=[], mode="live", allow={"weather"})
    assert r.result == "LIVE:tokyo"


def test_repeated_calls_replay_in_recorded_order():
    """A tool called twice with different arguments must get its own answer each time, in the
    order it originally ran."""
    cassette = [_entry("weather", ("paris",), output="paris-weather"),
                _entry("weather", ("tokyo",), output="tokyo-weather")]
    r = pk.replay("t", lambda: [weather("paris"), weather("tokyo")], cassette=cassette)
    assert r.result == ["paris-weather", "tokyo-weather"]
    assert r.hits == 2 and r.reliable


def test_keyword_arguments_are_part_of_the_key():
    cassette = [_entry("search", ("agents",), {"limit": 5}, output="five results")]
    r = pk.replay("t", lambda: search("agents", limit=5), cassette=cassette)
    assert r.result == "five results" and r.reliable


def test_a_recorded_failure_is_reproduced_as_a_failure():
    """Reproducing a run means reproducing the error, not quietly succeeding where it didn't."""
    cassette = [_entry("weather", ("paris",), status="failed", error="upstream 503")]
    with pytest.raises(RuntimeError, match="upstream 503"):
        pk.replay("t", lambda: weather("paris"), cassette=cassette)


def test_unused_recordings_are_reported():
    """A path the replay never took is worth seeing — it usually means the run diverged."""
    cassette = [_entry("weather", ("paris",), output="a"), _entry("search", ("x",), output="b")]
    r = pk.replay("t", lambda: weather("paris"), cassette=cassette)
    assert r.unused == ["search"]


def test_tools_run_normally_outside_a_replay():
    assert weather("berlin") == "LIVE:berlin"


def test_nested_replay_is_refused():
    """Sharing one cassette between an inner and outer run would mix up both accountings."""
    with pytest.raises(RuntimeError, match="already active"):
        pk.replay("t", lambda: pk.replay("t2", lambda: None, cassette=[]), cassette=[])


def test_session_is_cleared_even_when_the_target_raises():
    with pytest.raises(ValueError):
        pk.replay("t", lambda: (_ for _ in ()).throw(ValueError("boom")), cassette=[])
    assert weather("berlin") == "LIVE:berlin"        # not still intercepted


def test_bad_mode_is_rejected():
    with pytest.raises(ValueError):
        pk.replay("t", lambda: None, cassette=[], mode="sideways")


def test_registered_tools_are_listed():
    assert {"weather", "search"} <= set(vcr.registered_tools())


# -- the server half -------------------------------------------------------------------------

def test_cassette_endpoint_returns_recorded_tool_calls():
    """The SDK can only replay what the portal will hand back."""
    with TestClient(app) as client:
        key = client.post("/api/workspace/ingest-key").json()["ingest_key"]
        span = {"name": "get_weather", "traceId": "7c" * 16, "spanId": "7d" * 8,
                "startTimeUnixNano": "1000000000", "endTimeUnixNano": "1500000000",
                "status": {"code": 1},
                "attributes": [
                    {"key": "gen_ai.tool.name", "value": {"stringValue": "get_weather"}},
                    {"key": "gen_ai.operation.name", "value": {"stringValue": "execute_tool"}},
                    {"key": "input.value", "value": {"stringValue": "paris"}},
                    {"key": "output.value", "value": {"stringValue": "12C and raining"}},
                ]}
        bare = TestClient(app)
        bare.cookies.clear()
        r = bare.post("/v1/traces", json={"resourceSpans": [{"scopeSpans": [{"spans": [span]}]}]},
                      headers={"Authorization": f"Bearer {key}"})
        assert r.status_code == 200
        got = bare.get(f"/v1/traces/{'7c' * 16}/cassette",
                       headers={"Authorization": f"Bearer {key}"}).json()
    assert got["trace_id"] == "7c" * 16
    assert len(got["entries"]) == 1
    entry = got["entries"][0]
    assert entry["tool"] == "get_weather"
    assert "paris" in entry["input"]
    assert entry["output"] == "12C and raining"


def test_cassette_of_an_unknown_trace_is_empty_not_an_error():
    with TestClient(app) as client:
        key = client.post("/api/workspace/ingest-key").json()["ingest_key"]
        bare = TestClient(app)
        bare.cookies.clear()
        got = bare.get(f"/v1/traces/{'00' * 16}/cassette",
                       headers={"Authorization": f"Bearer {key}"}).json()
    assert got["entries"] == []
