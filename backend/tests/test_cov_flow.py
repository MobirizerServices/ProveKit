"""Coverage-focused unit tests for the visual-flow engine (provekit/services/flow.py).

No real network/subprocess: prompt/tool/agent nodes call dispatch.run_collect, which we
monkeypatch with an async fake. run_stream is an async generator driven via asyncio.run.
"""
import asyncio

import pytest

from provekit.database import SessionLocal
from provekit.services import dispatch
from provekit.services import flow as engine
from provekit.services.masking import MASK


# --------------------------------------------------------------------------- helpers
def _db():
    return SessionLocal()


def _drive(gen):
    """Collect every event from an async generator into a list (deterministic)."""
    async def _run():
        out = []
        async for ev in gen:
            out.append(ev)
        return out
    return asyncio.run(_run())


def _fake_collect(result):
    async def _collect(db, req, variables=None, workspace_id=None):
        return result
    return _collect


def _capturing_collect(result, sink):
    async def _collect(db, req, variables=None, workspace_id=None):
        sink.append(req)
        return result
    return _collect


# --------------------------------------------------------------------------- _resolve
def test_resolve_empty_ref_returns_none():
    assert engine._resolve("", {"input": {"a": 1}}) is None
    assert engine._resolve(".", {"input": {}}) is None


def test_resolve_input_root_and_nested_dict():
    ctx = {"input": {"user": {"name": "ada"}}, "nodes": {}}
    assert engine._resolve("input.user.name", ctx) == "ada"


def test_resolve_node_root_and_list_index():
    ctx = {"input": {}, "nodes": {"n1": {"items": ["x", "y", "z"]}}}
    assert engine._resolve("n1.items.1", ctx) == "y"


def test_resolve_list_bad_index_valueerror_and_indexerror():
    ctx = {"input": {}, "nodes": {"n1": ["a"]}}
    assert engine._resolve("n1.notint", ctx) is None   # int() -> ValueError
    assert engine._resolve("n1.5", ctx) is None         # IndexError


def test_resolve_scalar_then_more_parts_returns_none():
    ctx = {"input": {}, "nodes": {"n1": {"val": 7}}}
    # cur becomes 7 (int, not dict/list); further part hits the else branch
    assert engine._resolve("n1.val.deeper", ctx) is None


def test_resolve_missing_node_root():
    assert engine._resolve("nope.x", {"input": {}, "nodes": {}}) is None


# --------------------------------------------------------------------------- _interp
def test_interp_non_string_passthrough():
    assert engine._interp(123, {}) == 123


def test_interp_string_value_kept_and_object_jsonified():
    ctx = {"input": {"s": "hi", "d": {"k": 1}}, "nodes": {}}
    assert engine._interp("say {{input.s}}", ctx) == "say hi"
    assert engine._interp("obj {{input.d}}", ctx) == 'obj {"k": 1}'


def test_interp_unresolved_ref_echoes_literal():
    assert engine._interp("x {{input.missing}} y", {"input": {}, "nodes": {}}) == "x {{input.missing}} y"


# --------------------------------------------------------------------------- _interp_obj
def test_interp_obj_str_list_dict_and_other():
    ctx = {"input": {"v": "V"}, "nodes": {}}
    obj = {"a": "{{input.v}}", "b": ["{{input.v}}", 3], "c": 9}
    assert engine._interp_obj(obj, ctx) == {"a": "V", "b": ["V", 3], "c": 9}
    assert engine._interp_obj(5, ctx) == 5


# --------------------------------------------------------------------------- _mask_config
def test_mask_config_non_dict_passthrough():
    assert engine._mask_config("nope") == "nope"
    assert engine._mask_config(None) is None


def test_mask_config_masks_headers_and_body_secrets():
    cfg = {"headers": {"Authorization": "Bearer supersecret", "X-Plain": "keep"},
           "api_key": "abcd1234", "plain": "visible"}
    out = engine._mask_config(cfg)
    assert out["headers"]["Authorization"].startswith(MASK)
    assert out["headers"]["X-Plain"] == "keep"
    assert out["api_key"].startswith(MASK)
    assert out["plain"] == "visible"


def test_mask_config_no_headers_key():
    out = engine._mask_config({"token": "zzzz9999", "n": 1})
    assert out["token"].startswith(MASK)
    assert "headers" not in out
    assert out["n"] == 1


# --------------------------------------------------------------------------- _trim
def test_trim_depth_limit():
    assert engine._trim("x", _d=7) == "…"


def test_trim_long_string_truncated():
    s = "a" * 2500
    r = engine._trim(s)
    assert r.endswith("…") and len(r) == 2001


def test_trim_short_string_kept():
    assert engine._trim("short") == "short"


def test_trim_dict_and_list_capped():
    big = {str(i): i for i in range(60)}
    assert len(engine._trim(big)) == 50
    biglist = list(range(60))
    assert len(engine._trim(biglist)) == 40


def test_trim_scalar_passthrough():
    assert engine._trim(42) == 42
    assert engine._trim(None) is None


# --------------------------------------------------------------------------- _adjacency / _next
def test_adjacency_groups_by_source():
    edges = [{"source": "a", "target": "b"}, {"source": "a", "target": "c"}, {"source": "b", "target": "d"}]
    adj = engine._adjacency(edges)
    assert len(adj["a"]) == 2 and len(adj["b"]) == 1


def test_next_no_branch_prefers_unconditional_then_first():
    adj = engine._adjacency([
        {"source": "a", "target": "t1", "condition": {"branch": "true"}},
        {"source": "a", "target": "t2"},
    ])
    assert engine._next(adj, "a", None) == "t2"  # unconditional wins


def test_next_no_branch_all_conditional_falls_back_to_first():
    adj = engine._adjacency([
        {"source": "a", "target": "t1", "condition": {"branch": "true"}},
    ])
    assert engine._next(adj, "a", None) == "t1"


def test_next_no_outgoing_returns_none():
    assert engine._next({}, "x", None) is None
    assert engine._next({}, "x", "true") is None


def test_next_with_branch_match_and_nomatch():
    adj = engine._adjacency([
        {"source": "a", "target": "yes", "condition": {"branch": "true"}},
        {"source": "a", "target": "no", "condition": {"branch": "false"}},
    ])
    assert engine._next(adj, "a", "true") == "yes"
    assert engine._next(adj, "a", "false") == "no"
    assert engine._next(adj, "a", "missing") is None


# --------------------------------------------------------------------------- _find_trigger
def test_find_trigger_prefers_input_with_zero_indegree():
    graph = {"nodes": [{"id": "p", "type": "prompt"}, {"id": "i", "type": "input"}],
             "edges": [{"source": "i", "target": "p"}]}
    assert engine._find_trigger(graph) == "i"


def test_find_trigger_falls_back_to_zero_indegree_non_input():
    # input node has incoming edge, so fall back to the other zero-indegree node
    graph = {"nodes": [{"id": "i", "type": "input"}, {"id": "s", "type": "prompt"}],
             "edges": [{"source": "s", "target": "i"}]}
    assert engine._find_trigger(graph) == "s"


def test_find_trigger_falls_back_to_first_node_when_all_have_indegree():
    graph = {"nodes": [{"id": "a", "type": "prompt"}, {"id": "b", "type": "prompt"}],
             "edges": [{"source": "a", "target": "b"}, {"source": "b", "target": "a"}]}
    assert engine._find_trigger(graph) == "a"


def test_find_trigger_empty_graph_returns_none():
    assert engine._find_trigger({"nodes": [], "edges": []}) is None


# --------------------------------------------------------------------------- _interp_blank
def test_interp_blank_non_string_passthrough():
    assert engine._interp_blank(10, {}) == 10


def test_interp_blank_resolves_and_blanks_missing():
    ctx = {"input": {"a": "A", "obj": {"k": 2}}, "nodes": {}}
    assert engine._interp_blank("{{input.a}}", ctx) == "A"
    assert engine._interp_blank("{{input.obj}}", ctx) == '{"k": 2}'
    assert engine._interp_blank("[{{input.missing}}]", ctx) == "[]"


# --------------------------------------------------------------------------- _compare
def test_compare_exists():
    assert engine._compare("x", "", "exists") is True
    assert engine._compare("", "", "exists") is False
    assert engine._compare(None, "", "exists") is False
    assert engine._compare("null", "", "exists") is False


def test_compare_contains():
    assert engine._compare("hello world", "world", "contains") is True
    assert engine._compare("abc", "z", "contains") is False


def test_compare_equals_and_notequals():
    assert engine._compare("5", "5", "==") is True
    assert engine._compare("5", "5", "equals") is True
    assert engine._compare("a", "b", "!=") is True
    assert engine._compare("a", "a", "!=") is False


def test_compare_numeric_gt_lt():
    assert engine._compare("10", "3", ">") is True
    assert engine._compare("2", "9", "<") is True
    assert engine._compare("2", "9", ">") is False


def test_compare_numeric_unknown_op_returns_false():
    assert engine._compare("2", "9", ">=") is False  # numeric parse ok but op unhandled


def test_compare_non_numeric_operands_return_false():
    assert engine._compare("abc", "def", ">") is False  # ValueError on float()


# --------------------------------------------------------------------------- _registry_prompt
def test_registry_prompt_found_and_missing_and_workspace_filter():
    from provekit.models import Prompt
    db = _db()
    try:
        db.query(Prompt).delete()
        db.add(Prompt(workspace_id=1, key="greeting", name="Greeting", content="Hello there"))
        db.commit()
        assert engine._registry_prompt(db, "greeting", 1) == "Hello there"
        assert engine._registry_prompt(db, "greeting", 999) is None  # wrong workspace
        assert engine._registry_prompt(db, "nope", 1) is None
        assert engine._registry_prompt(db, "greeting") == "Hello there"  # no workspace filter
    finally:
        db.query(Prompt).delete()
        db.commit()
        db.close()


# --------------------------------------------------------------------------- _exec_node direct
def test_exec_node_input_returns_ctx_input():
    db = _db()
    try:
        node = {"type": "input", "config": {}}
        out, branch = asyncio.run(engine._exec_node(db, node, {"input": {"x": 1}, "nodes": {}}))
        assert out == {"x": 1} and branch is None
        # empty input -> {}
        out2, _ = asyncio.run(engine._exec_node(db, node, {"input": {}, "nodes": {}}))
        assert out2 == {}
    finally:
        db.close()


def test_exec_node_output_interpolates():
    db = _db()
    try:
        node = {"type": "output", "config": {"value": "{{input.msg}}"}}
        out, branch = asyncio.run(engine._exec_node(db, node, {"input": {"msg": "done"}, "nodes": {}}))
        assert out == {"value": "done"} and branch is None
    finally:
        db.close()


def test_exec_node_unknown_type_returns_empty():
    db = _db()
    try:
        out, branch = asyncio.run(engine._exec_node(db, {"type": "weird"}, {"input": {}, "nodes": {}}))
        assert out == {} and branch is None
    finally:
        db.close()


def test_exec_node_condition_true_and_false():
    db = _db()
    try:
        ctx = {"input": {"n": "5"}, "nodes": {}}
        node = {"type": "condition", "config": {"left": "{{input.n}}", "right": "5", "op": "=="}}
        out, branch = asyncio.run(engine._exec_node(db, node, ctx))
        assert out["result"] is True and branch == "true"
        node2 = {"type": "condition", "config": {"left": "{{input.n}}", "right": "6", "op": "=="}}
        out2, branch2 = asyncio.run(engine._exec_node(db, node2, ctx))
        assert out2["result"] is False and branch2 == "false"
    finally:
        db.close()


def test_exec_node_prompt_uses_registry(monkeypatch):
    from provekit.models import Prompt
    db = _db()
    captured = []
    monkeypatch.setattr(dispatch, "run_collect",
                        _capturing_collect({"status": "completed", "text": "ok"}, captured))
    try:
        db.query(Prompt).delete()
        db.add(Prompt(workspace_id=1, key="sys", name="Sys", content="You are helpful"))
        db.commit()
        node = {"type": "prompt", "config": {"prompt_key": "sys", "system": "ignored", "user": "hi"}}
        out, branch = asyncio.run(engine._exec_node(db, node, {"input": {}, "nodes": {}}, None, 1))
        assert out == {"text": "ok"} and branch is None
        assert captured[0]["system"] == "You are helpful"  # registry overrode the inline system
    finally:
        db.query(Prompt).delete()
        db.commit()
        db.close()


def test_exec_node_prompt_registry_missing_keeps_inline(monkeypatch):
    db = _db()
    captured = []
    monkeypatch.setattr(dispatch, "run_collect",
                        _capturing_collect({"status": "completed", "text": "ok"}, captured))
    try:
        node = {"type": "prompt", "config": {"prompt_key": "absent", "system": "inline-sys", "user": "hi"}}
        asyncio.run(engine._exec_node(db, node, {"input": {}, "nodes": {}}, None, 1))
        assert captured[0]["system"] == "inline-sys"
    finally:
        db.close()


def test_exec_node_tool_and_agent(monkeypatch):
    db = _db()
    captured = []
    monkeypatch.setattr(dispatch, "run_collect",
                        _capturing_collect({"status": "completed", "output": {"r": 1}}, captured))
    try:
        tool = {"type": "tool", "config": {"tool": "t", "args": {"q": "{{input.q}}"}}}
        out, _ = asyncio.run(engine._exec_node(db, tool, {"input": {"q": "hi"}, "nodes": {}}))
        assert out == {"r": 1}
        assert captured[-1]["args"] == {"q": "hi"}  # args interpolated
        agent = {"type": "agent", "config": {"path": "/x/{{input.q}}", "body": {"b": "{{input.q}}"}}}
        out2, _ = asyncio.run(engine._exec_node(db, agent, {"input": {"q": "hi"}, "nodes": {}}))
        assert out2 == {"r": 1}
        assert captured[-1]["path"] == "/x/hi"
    finally:
        db.close()


def test_exec_node_prompt_failed_raises(monkeypatch):
    db = _db()
    monkeypatch.setattr(dispatch, "run_collect",
                        _fake_collect({"status": "failed", "error": "boom"}))
    try:
        node = {"type": "prompt", "config": {"user": "hi"}}
        with pytest.raises(RuntimeError, match="boom"):
            asyncio.run(engine._exec_node(db, node, {"input": {}, "nodes": {}}))
    finally:
        db.close()


def test_exec_node_tool_failed_raises_default_message(monkeypatch):
    db = _db()
    monkeypatch.setattr(dispatch, "run_collect",
                        _fake_collect({"status": "failed", "error": ""}))
    try:
        node = {"type": "tool", "config": {"tool": "t"}}
        with pytest.raises(RuntimeError, match="tool failed"):
            asyncio.run(engine._exec_node(db, node, {"input": {}, "nodes": {}}))
    finally:
        db.close()


def test_exec_node_agent_failed_raises_default_message(monkeypatch):
    db = _db()
    monkeypatch.setattr(dispatch, "run_collect",
                        _fake_collect({"status": "failed", "error": None}))
    try:
        node = {"type": "agent", "config": {}}
        with pytest.raises(RuntimeError, match="agent failed"):
            asyncio.run(engine._exec_node(db, node, {"input": {}, "nodes": {}}))
    finally:
        db.close()


# --------------------------------------------------------------------------- _skey / pop_run
def test_skey_namespaces_by_workspace():
    assert engine._skey("abc", 7) == "7:abc"
    assert engine._skey("abc", None) == "0:abc"


def test_pop_run_absent_returns_none():
    assert engine.pop_run("does-not-exist", 42) is None


# --------------------------------------------------------------------------- run_stream: flows
def _simple_flow():
    return {
        "nodes": [
            {"id": "in", "type": "input"},
            {"id": "p", "type": "prompt", "config": {"user": "{{input.q}}"}},
            {"id": "out", "type": "output", "config": {"value": "{{p.text}}"}},
        ],
        "edges": [
            {"source": "in", "target": "p"},
            {"source": "p", "target": "out"},
        ],
    }


def test_run_stream_completes(monkeypatch):
    monkeypatch.setattr(dispatch, "run_collect",
                        _fake_collect({"status": "completed", "text": "answer"}))
    db = _db()
    try:
        evs = _drive(engine.run_stream(db, _simple_flow(), {"q": "hi"}, run_id="R1"))
    finally:
        db.close()
    assert evs[0] == {"type": "start", "run_id": "R1"}
    assert evs[-1]["type"] == "done" and evs[-1]["status"] == "completed"
    # output carries every node result
    assert evs[-1]["output"]["p"] == {"text": "answer"}
    assert evs[-1]["output"]["out"] == {"value": "answer"}


def test_run_stream_condition_true_branch(monkeypatch):
    flow = {
        "nodes": [
            {"id": "in", "type": "input"},
            {"id": "c", "type": "condition", "config": {"left": "{{input.n}}", "right": "5", "op": "=="}},
            {"id": "yes", "type": "output", "config": {"value": "T"}},
            {"id": "no", "type": "output", "config": {"value": "F"}},
        ],
        "edges": [
            {"source": "in", "target": "c"},
            {"source": "c", "target": "yes", "condition": {"branch": "true"}},
            {"source": "c", "target": "no", "condition": {"branch": "false"}},
        ],
    }
    db = _db()
    try:
        evs = _drive(engine.run_stream(db, flow, {"n": "5"}, run_id="RT"))
    finally:
        db.close()
    out = evs[-1]["output"]
    assert "yes" in out and "no" not in out


def test_run_stream_condition_false_branch(monkeypatch):
    flow = {
        "nodes": [
            {"id": "in", "type": "input"},
            {"id": "c", "type": "condition", "config": {"left": "{{input.n}}", "right": "5", "op": "=="}},
            {"id": "yes", "type": "output", "config": {"value": "T"}},
            {"id": "no", "type": "output", "config": {"value": "F"}},
        ],
        "edges": [
            {"source": "in", "target": "c"},
            {"source": "c", "target": "yes", "condition": {"branch": "true"}},
            {"source": "c", "target": "no", "condition": {"branch": "false"}},
        ],
    }
    db = _db()
    try:
        evs = _drive(engine.run_stream(db, flow, {"n": "9"}, run_id="RF"))
    finally:
        db.close()
    out = evs[-1]["output"]
    assert "no" in out and "yes" not in out


def test_run_stream_node_error_yields_failed(monkeypatch):
    monkeypatch.setattr(dispatch, "run_collect",
                        _fake_collect({"status": "failed", "error": "boom"}))
    db = _db()
    try:
        evs = _drive(engine.run_stream(db, _simple_flow(), {"q": "hi"}, run_id="RE"))
    finally:
        db.close()
    err_node = [e for e in evs if e["type"] == "node" and e.get("status") == "error"]
    assert err_node and "boom" in err_node[0]["error"]
    assert evs[-1] == {"type": "done", "status": "failed"}


def test_run_stream_breakpoint_pause_then_resume(monkeypatch):
    monkeypatch.setattr(dispatch, "run_collect",
                        _fake_collect({"status": "completed", "text": "answer"}))
    db = _db()
    try:
        # break on the prompt node
        evs = _drive(engine.run_stream(db, _simple_flow(), {"q": "hi"},
                                       breakpoints={"p"}, run_id="RB", workspace_id=3))
        pause = evs[-1]
        assert pause["type"] == "pause" and pause["node_id"] == "p" and pause["reason"] == "breakpoint"
        # resume: pop the stored ctx and start_at the paused node
        saved = engine.pop_run("RB", 3)
        assert saved is not None
        evs2 = _drive(engine.run_stream(db, _simple_flow(), {"q": "hi"},
                                        breakpoints={"p"}, start_at="p", ctx=saved,
                                        run_id="RB", workspace_id=3))
        # resuming ONTO the breakpoint node does not re-pause; it runs to completion
        assert evs2[-1]["type"] == "done" and evs2[-1]["status"] == "completed"
        # popped run is gone
        assert engine.pop_run("RB", 3) is None
    finally:
        db.close()


def test_run_stream_single_step_pauses(monkeypatch):
    monkeypatch.setattr(dispatch, "run_collect",
                        _fake_collect({"status": "completed", "text": "answer"}))
    db = _db()
    try:
        evs = _drive(engine.run_stream(db, _simple_flow(), {"q": "hi"},
                                       single_step=True, run_id="RS", workspace_id=None))
        pause = evs[-1]
        assert pause["type"] == "pause" and pause["reason"] == "step"
        # the input node ran, then it paused pointing at the next node
        assert pause["node_id"] == "p"
        assert engine.pop_run("RS") is not None
    finally:
        db.close()


def test_run_stream_max_steps_cycle_errors(monkeypatch):
    monkeypatch.setattr(dispatch, "run_collect",
                        _fake_collect({"status": "completed", "text": "x"}))
    # a→b→a cycle (no condition branches) blows the step budget
    flow = {
        "nodes": [
            {"id": "a", "type": "prompt", "config": {"user": "hi"}},
            {"id": "b", "type": "prompt", "config": {"user": "hi"}},
        ],
        "edges": [
            {"source": "a", "target": "b"},
            {"source": "b", "target": "a"},
        ],
    }
    db = _db()
    try:
        evs = _drive(engine.run_stream(db, flow, {}, start_at="a", run_id="RC"))
    finally:
        db.close()
    err = [e for e in evs if e["type"] == "error"]
    assert err and "budget" in err[0]["error"]
    assert evs[-1] == {"type": "done", "status": "failed"}


def test_run_stream_masks_config_headers_in_node_input(monkeypatch):
    captured = []
    monkeypatch.setattr(dispatch, "run_collect",
                        _capturing_collect({"status": "completed", "output": {"ok": 1}}, captured))
    flow = {
        "nodes": [
            {"id": "a", "type": "agent",
             "config": {"path": "/p", "headers": {"Authorization": "Bearer topsecret"},
                        "body": {"token": "sekret99"}}},
        ],
        "edges": [],
    }
    db = _db()
    try:
        evs = _drive(engine.run_stream(db, flow, {}, run_id="RM"))
    finally:
        db.close()
    node_ok = [e for e in evs if e["type"] == "node" and e.get("status") == "ok"][0]
    inp = node_ok["input"]
    assert inp["headers"]["Authorization"].startswith(MASK)
    assert inp["body"]["token"].startswith(MASK)
    assert inp["path"] == "/p"  # non-secret preserved


def test_run_stream_missing_node_breaks_to_completion(monkeypatch):
    # An edge points to a target that isn't in nodes -> nodes.get returns None -> break -> done.
    flow = {
        "nodes": [{"id": "in", "type": "input"}],
        "edges": [{"source": "in", "target": "ghost"}],
    }
    db = _db()
    try:
        evs = _drive(engine.run_stream(db, flow, {"q": 1}, run_id="RG"))
    finally:
        db.close()
    assert evs[-1]["type"] == "done" and evs[-1]["status"] == "completed"
