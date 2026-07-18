"""MCP tools attached to a model under test: discovery, the execute loop, dry run, caps.

The end-to-end tests drive the keyless mock provider against the real stdio MCP server in
`mcp_stdio_server.py` (a genuine subprocess), so the whole loop — model asks for a tool,
ProveKit runs it over MCP, result goes back, model answers — is exercised for real.
"""
import sys
from pathlib import Path

import anyio
import pytest
from fastapi.testclient import TestClient

from provekit.database import SessionLocal
from provekit.main import app
from provekit.models import Connection
from provekit.services import assertions as ae
from provekit.services import dispatch, tooling

SERVER = str(Path(__file__).parent / "mcp_stdio_server.py")


@pytest.fixture
def client():
    return TestClient(app, base_url="https://testserver")


@pytest.fixture
def mcp_conn(client):
    """A real stdio MCP connection (the echo server) in the caller's workspace."""
    return client.post("/api/connections", json={
        "name": "Echo (stdio)", "kind": "mcp",
        "config": {"command": sys.executable, "args": [SERVER]},
    }).json()


@pytest.fixture
def llm_conn(client):
    return next(c for c in client.get("/api/connections").json()
                if c["config"].get("provider") == "mock")


def _run(req):
    async def go():
        db = SessionLocal()
        try:
            return [ev async for ev in dispatch.run(db, req)]
        finally:
            db.close()
    return anyio.run(go)


def _nodes(evs):
    return [e["data"] for e in evs if e["type"] == "node"]


# ---- discovery / resolution ----------------------------------------------------------
def test_resolve_discovers_tools_from_the_mcp_connection(mcp_conn):
    db = SessionLocal()
    try:
        tools = tooling.resolve(db, [{"connection_id": mcp_conn["id"]}])
    finally:
        db.close()
    assert [t.name for t in tools] == ["echo"]
    assert tools[0].execute is True


def test_allowlist_narrows_the_exposed_tools(mcp_conn):
    db = SessionLocal()
    try:
        # omitted -> every tool the server offers
        assert [t.name for t in tooling.resolve(db, [{"connection_id": mcp_conn["id"]}])] == ["echo"]
        assert tooling.resolve(db, [{"connection_id": mcp_conn["id"], "tools": ["echo"]}])
        # a name the server doesn't advertise simply exposes nothing
        assert tooling.resolve(db, [{"connection_id": mcp_conn["id"], "tools": ["nope"]}]) == []
        # an EXPLICIT empty list means none — not "all". Unticking the last tool in the UI
        # sends this, and treating it as "all" handed the model every tool instead.
        assert tooling.resolve(db, [{"connection_id": mcp_conn["id"], "tools": []}]) == []
    finally:
        db.close()


def test_resolve_rejects_a_non_mcp_connection(llm_conn):
    db = SessionLocal()
    try:
        with pytest.raises(ValueError, match="not mcp"):
            tooling.resolve(db, [{"connection_id": llm_conn["id"]}])
    finally:
        db.close()


def test_resolve_is_workspace_scoped(mcp_conn):
    """Tenancy: another workspace's MCP server must not be attachable by id."""
    db = SessionLocal()
    try:
        ws = db.get(Connection, mcp_conn["id"]).workspace_id
        with pytest.raises(ValueError, match="not found"):
            tooling.resolve(db, [{"connection_id": mcp_conn["id"]}], workspace_id=ws + 999)
    finally:
        db.close()


def test_api_names_are_sanitized_and_stay_unique():
    taken = set()
    a = tooling._api_name("weird name/v2!", taken); taken.add(a)
    b = tooling._api_name("weird name/v2!", taken)
    assert a == "weird_name_v2_" and b != a          # provider-legal, and collision-free
    assert len(tooling._api_name("x" * 200, set())) <= 64


def test_provider_tool_schemas():
    t = tooling.Tool(api_name="echo", name="echo", description="d",
                     input_schema={"type": "object"}, connection_id=1, cfg={}, execute=True)
    assert tooling.for_provider([t], "anthropic")[0]["input_schema"] == {"type": "object"}
    assert tooling.for_provider([t], "openai-responses")[0]["name"] == "echo"
    assert tooling.for_provider([t], "openai")[0]["function"]["name"] == "echo"
    assert tooling.for_provider([], "openai") is None
    # a tool with no schema still has to be a legal object schema
    bare = tooling.Tool(api_name="e", name="e", description="", input_schema={}, connection_id=1,
                        cfg={}, execute=True)
    assert tooling.for_provider([bare], "anthropic")[0]["input_schema"]["type"] == "object"


# ---- the loop, end to end against a real MCP subprocess ------------------------------
def test_model_calls_an_mcp_tool_and_answers_from_the_result(llm_conn, mcp_conn):
    evs = _run({"type": "prompt", "connection_id": llm_conn["id"], "user": "ping",
                "tools": [{"connection_id": mcp_conn["id"]}]})
    nodes = _nodes(evs)
    call = next(d["tool_calls"][0] for d in nodes if d.get("tool_calls"))
    assert call["name"] == "echo"
    result = next(d["tool_result"] for d in nodes if d.get("tool_result"))
    assert result["ok"] is True and "echoed" in result["output"]
    # the model's final answer is written from the tool's real output
    text = next(e["data"]["text"] for e in evs if e["type"] == "result")
    assert "echoed" in text
    assert next(e for e in evs if e["type"] == "done")["status"] == "completed"


def test_tool_called_assertion_passes_on_a_real_mcp_call(llm_conn, mcp_conn):
    """The point of the feature: assert which tool the agent chose."""
    evs = _run({"type": "prompt", "connection_id": llm_conn["id"], "user": "ping",
                "tools": [{"connection_id": mcp_conn["id"]}]})
    res = ae.evaluate(None, [{"type": "tool_called", "value": "echo"},
                             {"type": "tool_called", "value": "never_called"}],
                      {"result": {"text": "x", "output": None, "meta": {}},
                       "events": _nodes(evs), "duration_ms": 1})
    assert [r["ok"] for r in res] == [True, False]


def test_dry_run_records_the_call_without_executing_it(llm_conn, mcp_conn):
    evs = _run({"type": "prompt", "connection_id": llm_conn["id"], "user": "ping",
                "tools": [{"connection_id": mcp_conn["id"], "execute": False}]})
    nodes = _nodes(evs)
    assert any(d.get("tool_calls") for d in nodes), "the chosen tool is still recorded"
    assert not any(d.get("tool_result") for d in nodes), "execute:false must not invoke it"
    assert any("execution is off" in str(d.get("tools_stopped", "")) for d in nodes)
    # still a clean run, so assertions can grade the decision
    assert next(e for e in evs if e["type"] == "done")["status"] == "completed"


def test_max_tool_rounds_zero_stops_before_executing(llm_conn, mcp_conn):
    evs = _run({"type": "prompt", "connection_id": llm_conn["id"], "user": "ping",
                "max_tool_rounds": 0, "tools": [{"connection_id": mcp_conn["id"]}]})
    nodes = _nodes(evs)
    assert any(d.get("tool_calls") for d in nodes)
    assert not any(d.get("tool_result") for d in nodes)
    assert any("max_tool_rounds" in str(d.get("tools_stopped", "")) for d in nodes)


def test_a_failing_tool_becomes_a_turn_not_a_dead_run(llm_conn, mcp_conn, monkeypatch):
    def boom(self, tool, args):
        raise RuntimeError("server exploded")

    monkeypatch.setattr(tooling.Runner, "call", boom)
    evs = _run({"type": "prompt", "connection_id": llm_conn["id"], "user": "ping",
                "tools": [{"connection_id": mcp_conn["id"]}]})
    result = next(d["tool_result"] for d in _nodes(evs) if d.get("tool_result"))
    assert result["ok"] is False and "server exploded" in result["error"]
    assert next(e for e in evs if e["type"] == "done")["status"] == "completed"


def test_unreachable_mcp_server_fails_the_run_up_front(llm_conn, client):
    bad = client.post("/api/connections", json={
        "name": "Dead MCP", "kind": "mcp", "config": {"command": sys.executable, "args": ["-c", "raise SystemExit(1)"]},
    }).json()
    evs = _run({"type": "prompt", "connection_id": llm_conn["id"], "user": "ping",
                "tools": [{"connection_id": bad["id"]}]})
    assert next(e for e in evs if e["type"] == "done")["status"] == "failed"
    assert "discovery failed" in next(e["error"] for e in evs if e["type"] == "error")


def test_no_tools_attached_is_a_plain_single_turn_prompt(llm_conn):
    evs = _run({"type": "prompt", "connection_id": llm_conn["id"], "user": "hi"})
    assert not any(d.get("tool_calls") for d in _nodes(evs))
    assert next(e for e in evs if e["type"] == "result")["data"]["text"]


# ---- provider message translation ----------------------------------------------------
# A tool round looks different on every provider. These lock the shapes down, because a
# wrong one is rejected by the API at runtime, not at import.
CONV = [
    {"role": "user", "content": "stock?"},
    {"role": "assistant", "content": "checking", "tool_calls": [
        {"id": "c1", "name": "check", "args": {"sku": "A"}},
        {"id": "c2", "name": "check", "args": {"sku": "B"}}]},
    {"role": "tool", "tool_call_id": "c1", "name": "check", "content": "4"},
    {"role": "tool", "tool_call_id": "c2", "name": "check", "content": "0"},
]


def test_openai_message_translation():
    from provekit.services.providers.llm import _openai_messages
    out = _openai_messages(CONV)
    assert out[1]["tool_calls"][0]["function"] == {"name": "check", "arguments": '{"sku": "A"}'}
    assert out[1]["tool_calls"][0]["type"] == "function"
    # each result is its own role:tool message, bound by tool_call_id
    assert [m["role"] for m in out] == ["user", "assistant", "tool", "tool"]
    assert out[2] == {"role": "tool", "tool_call_id": "c1", "content": "4"}


def test_anthropic_message_translation_merges_tool_results():
    """Anthropic rejects one message per tool_result — consecutive results must share a
    single user turn, and tool_use goes in the assistant turn's content blocks."""
    from provekit.services.providers.llm import _anthropic_messages
    out = _anthropic_messages(CONV)
    assert [m["role"] for m in out] == ["user", "assistant", "user"]
    assert out[1]["content"][0] == {"type": "text", "text": "checking"}
    assert out[1]["content"][1] == {"type": "tool_use", "id": "c1", "name": "check", "input": {"sku": "A"}}
    merged = out[2]["content"]
    assert [b["tool_use_id"] for b in merged] == ["c1", "c2"], "both results share one user turn"
    assert all(b["type"] == "tool_result" for b in merged)


def test_anthropic_translation_omits_empty_assistant_text():
    from provekit.services.providers.llm import _anthropic_messages
    out = _anthropic_messages([{"role": "assistant", "content": "",
                                "tool_calls": [{"id": "c1", "name": "t", "args": {}}]}])
    assert [b["type"] for b in out[0]["content"]] == ["tool_use"]  # no empty text block


def test_responses_input_translation():
    from provekit.services.providers.llm import _responses_input
    out = _responses_input(CONV)
    assert out[0] == {"role": "user", "content": "stock?"}
    assert out[2] == {"type": "function_call", "call_id": "c1", "name": "check",
                      "arguments": '{"sku": "A"}'}
    assert out[4] == {"type": "function_call_output", "call_id": "c1", "output": "4"}


def test_tool_arguments_that_are_not_valid_json_degrade_to_empty():
    """A model can emit malformed arguments; that's a bad tool call, not a broken run."""
    from provekit.services.providers.llm import _args
    assert _args('{"a": 1}') == {"a": 1}
    assert _args("{not json") == {}
    assert _args("[1,2]") == {}   # a non-object is not usable as arguments
    assert _args("") == {}


def test_mock_fills_required_args_from_the_user_text():
    from provekit.services.providers.llm import _mock_tool_args
    schema = {"type": "object", "required": ["q", "n", "flag"],
              "properties": {"q": {"type": "string"}, "n": {"type": "integer"}, "flag": {"type": "boolean"}}}
    assert _mock_tool_args(schema, "find the Berge") == {"q": "find the Berge", "n": 1, "flag": True}
    assert _mock_tool_args({}, "x") == {}


def test_discovery_does_not_block_the_event_loop(llm_conn, mcp_conn, monkeypatch):
    """A slow MCP server must not stall every other in-flight stream.

    Discovery is blocking (HTTP, or spawning a stdio process). If it ran on the event loop,
    one unresponsive server would freeze the whole API for its duration — the opposite of
    the async model the rest of dispatch is built on.

    The tell is the longest gap between heartbeat ticks, not the tick count: a blocked loop
    stalls for the whole discovery and then catches up, so totals look fine either way.
    """
    import time

    real = tooling.discover

    def slow(plans):
        time.sleep(0.4)  # a sluggish MCP server
        return real(plans)

    monkeypatch.setattr(tooling, "discover", slow)

    async def go():
        gaps, done = [], anyio.Event()

        async def heartbeat():
            last = time.perf_counter()
            while not done.is_set():
                await anyio.sleep(0.005)
                now = time.perf_counter()
                gaps.append(now - last)
                last = now

        async def run_it():
            db = SessionLocal()
            try:
                async for _ in dispatch.run(db, {"type": "prompt", "connection_id": llm_conn["id"],
                                                 "user": "ping",
                                                 "tools": [{"connection_id": mcp_conn["id"]}]}):
                    pass
            finally:
                db.close()
                done.set()

        async with anyio.create_task_group() as tg:
            tg.start_soon(heartbeat)
            tg.start_soon(run_it)
        return max(gaps)

    # offloaded: the loop never pauses more than a tick. On the loop: one ~0.4s freeze.
    assert anyio.run(go) < 0.3


def test_a_hallucinated_tool_name_is_fed_back_so_the_model_can_recover(llm_conn, mcp_conn, monkeypatch):
    """An invented tool name is the model's mistake, not a reason to end the run.

    It must not be conflated with `execute: false` — doing so ended the run with no answer
    and told the user "tool execution is off" on a request that never asked for a dry run.
    """
    from provekit.services.providers import llm as llm_mod

    calls = {"n": 0}
    real = llm_mod._stream_mock

    async def first_call_is_bogus(system, messages, tools=None):
        calls["n"] += 1
        if calls["n"] == 1:
            yield {"type": "tool_call", "call": {"id": "x1", "name": "no_such_tool", "args": {}}}
            return
        async for ev in real(system, messages, None):  # then answer normally
            yield ev

    monkeypatch.setattr(llm_mod, "_stream_mock", first_call_is_bogus)
    evs = _run({"type": "prompt", "connection_id": llm_conn["id"], "user": "ping",
                "tools": [{"connection_id": mcp_conn["id"]}]})
    nodes = _nodes(evs)
    res = next(d["tool_result"] for d in nodes if d.get("tool_result"))
    assert res["ok"] is False and "no_such_tool" in res["error"]
    assert "echo" in res["output"], "the model is told which tools do exist"
    assert not any(d.get("tools_stopped") for d in nodes), "an unknown name is not a dry run"
    # the run continued to a real answer instead of dying
    assert next(e for e in evs if e["type"] == "result")["data"]["text"]
    assert next(e for e in evs if e["type"] == "done")["status"] == "completed"


def test_max_tool_rounds_handling():
    from provekit.services.dispatch import _rounds
    assert _rounds(None) == 5           # absent -> default
    assert _rounds(0) == 0              # explicit 0 must survive (a plain `or 5` breaks this)
    assert _rounds(-3) == 0             # clamped
    assert _rounds(9999) == tooling.MAX_TOOL_ROUNDS
    assert _rounds("3") == 3
    with pytest.raises(ValueError, match="must be a number"):
        _rounds(None if False else "abc")


def test_null_max_tool_rounds_is_a_clear_error_not_a_typeerror(llm_conn):
    """A client serializing an unset field as null used to crash with `int() argument...`."""
    evs = _run({"type": "prompt", "connection_id": llm_conn["id"], "user": "hi",
                "max_tool_rounds": "abc"})
    err = next(e["error"] for e in evs if e["type"] == "error")
    assert "max_tool_rounds must be a number" in err


def test_usage_is_summed_across_turns_including_nested_breakdowns():
    from provekit.services.dispatch import _add_usage
    a = {"input_tokens": 10, "output_tokens": 2,
         "input_tokens_details": {"cached_tokens": 4}, "model": "m"}
    b = {"input_tokens": 20, "output_tokens": 3,
         "input_tokens_details": {"cached_tokens": 6}, "model": "m"}
    out = _add_usage(_add_usage({}, a), b)
    assert out["input_tokens"] == 30 and out["output_tokens"] == 5
    # the nested breakdown must track its parent, not report only the last turn
    assert out["input_tokens_details"]["cached_tokens"] == 10
    assert out["model"] == "m"  # non-numeric values are carried, not summed


def test_the_runner_reuses_one_session_per_connection(mcp_conn):
    """A session per call would re-handshake, respawn stdio, and re-fetch an OAuth token
    on every round of the loop."""
    db = SessionLocal()
    try:
        tools = tooling.resolve(db, [{"connection_id": mcp_conn["id"]}])
    finally:
        db.close()
    runner = tooling.Runner()
    try:
        assert "echoed" in runner.call(tools[0], {"a": 1})
        assert "echoed" in runner.call(tools[0], {"a": 2})   # same live session, no respawn
        assert len(runner._open) == 1
    finally:
        runner.close()
    assert runner._open == {}


# --- real-provider tool loop: two rounds of realistic SSE through the whole dispatch loop ---
# The mock-provider tests above never exercise the message TRANSLATION back to a provider.
# These drive dispatch with real-shaped OpenAI / Anthropic / Responses SSE: round 1 asks for
# a tool, dispatch runs it over a real MCP subprocess, round 2 answers. We capture the
# round-2 REQUEST body and assert the assistant tool-call turn and the tool-result turn were
# translated into the exact shape each API requires — the bug a live call would catch.
class _MultiRoundHTTP:
    """Serve queued SSE per `client.stream()` call and record each request body. astream
    builds a fresh AsyncClient per round, so state is shared here across rounds."""
    def __init__(self, rounds):
        self.rounds = list(rounds)
        self.bodies = []

    def factory(self):
        outer = self

        class _Stream:
            def __init__(self, lines): self._lines = lines; self.status_code = 200
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def aiter_lines(self):
                for ln in self._lines:
                    yield ln
            async def aread(self): return b""

        class _Client:
            def __init__(self, *a, **k): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            def stream(self, *a, **k):
                outer.bodies.append(k.get("json"))
                return _Stream(outer.rounds.pop(0) if outer.rounds else ["data: [DONE]"])
        return _Client


_OPENAI = {
    "provider": "openai",
    "round1": [
        'data: {"choices":[{"delta":{"role":"assistant","content":null,"tool_calls":[{"index":0,"id":"call_1","type":"function","function":{"name":"echo","arguments":"{\\"x\\": 1}"}}]}}]}',
        'data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}]}',
        "data: [DONE]",
    ],
    "round2": ['data: {"choices":[{"delta":{"content":"Result received."}}]}', "data: [DONE]"],
}
_ANTHROPIC = {
    "provider": "anthropic",
    "round1": [
        'data: {"type":"message_start","message":{"usage":{"input_tokens":3}}}',
        'data: {"type":"content_block_start","index":0,"content_block":{"type":"tool_use","id":"toolu_1","name":"echo"}}',
        'data: {"type":"content_block_delta","index":0,"delta":{"type":"input_json_delta","partial_json":"{\\"x\\": 1}"}}',
        'data: {"type":"content_block_stop","index":0}',
        'data: {"type":"message_delta","delta":{"stop_reason":"tool_use"},"usage":{"output_tokens":5}}',
    ],
    "round2": [
        'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Result received."}}',
        'data: {"type":"message_delta","delta":{"stop_reason":"end_turn"}}',
    ],
}
_RESPONSES = {
    "provider": "openai-responses",
    "round1": [
        'data: {"type":"response.output_item.done","item":{"type":"function_call","call_id":"fc_1","name":"echo","arguments":"{\\"x\\": 1}"}}',
        'data: {"type":"response.completed","response":{"usage":{"input_tokens":5,"output_tokens":2}}}',
    ],
    "round2": [
        'data: {"type":"response.output_text.delta","delta":"Result received."}',
        'data: {"type":"response.completed","response":{"usage":{"input_tokens":6,"output_tokens":3}}}',
    ],
}


def _assert_openai_roundtrip(body):
    msgs = body["messages"]
    asst = next(m for m in msgs if m.get("role") == "assistant" and m.get("tool_calls"))
    tc = asst["tool_calls"][0]
    assert tc["id"] == "call_1" and tc["type"] == "function" and tc["function"]["name"] == "echo"
    tool = next(m for m in msgs if m.get("role") == "tool")
    assert tool["tool_call_id"] == "call_1" and "echoed" in tool["content"]


def _assert_anthropic_roundtrip(body):
    msgs = body["messages"]
    asst = next(m for m in msgs if m["role"] == "assistant" and isinstance(m["content"], list))
    tu = next(b for b in asst["content"] if b["type"] == "tool_use")
    assert tu["id"] == "toolu_1" and tu["name"] == "echo"
    usr = next(m for m in msgs if m["role"] == "user" and isinstance(m.get("content"), list)
               and any(b.get("type") == "tool_result" for b in m["content"]))
    tr = next(b for b in usr["content"] if b["type"] == "tool_result")
    assert tr["tool_use_id"] == "toolu_1" and "echoed" in str(tr["content"])


def _assert_responses_roundtrip(body):
    inp = body["input"]
    fc = next(i for i in inp if i.get("type") == "function_call")
    assert fc["call_id"] == "fc_1" and fc["name"] == "echo"
    fco = next(i for i in inp if i.get("type") == "function_call_output")
    assert fco["call_id"] == "fc_1" and "echoed" in fco["output"]


@pytest.mark.parametrize("spec,check", [
    (_OPENAI, _assert_openai_roundtrip),
    (_ANTHROPIC, _assert_anthropic_roundtrip),
    (_RESPONSES, _assert_responses_roundtrip),
], ids=["openai", "anthropic", "responses"])
def test_real_provider_tool_loop_translates_the_round_trip(spec, check, mcp_conn, monkeypatch):
    from provekit.services.providers import llm
    http = _MultiRoundHTTP([spec["round1"], spec["round2"]])
    monkeypatch.setattr(llm.httpx, "AsyncClient", http.factory())

    evs = _run({"type": "prompt", "provider": spec["provider"], "api_key": "k", "model": "m",
                "user": "call echo", "tools": [{"connection_id": mcp_conn["id"]}]})

    # the model's tool call ran against the real MCP subprocess...
    result = next(d["tool_result"] for d in _nodes(evs) if d.get("tool_result"))
    assert result["name"] == "echo" and result["ok"] is True and "echoed" in result["output"]
    # ...round 2 answered, and its usage summed on top of round 1 (two model calls, one total)
    assert next(e for e in evs if e["type"] == "result")["data"]["text"] == "Result received."
    assert next(e for e in evs if e["type"] == "done")["status"] == "completed"
    # the crux: round 2's request body carried the correctly-translated turns for this API
    assert len(http.bodies) == 2, "expected exactly two model calls (tool round + answer)"
    check(http.bodies[1])
