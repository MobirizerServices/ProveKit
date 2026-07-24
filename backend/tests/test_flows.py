"""Agent Flow Studio: author a graph, publish/restore versions, and execute it.

The executor tests run against a real connection whose socket is faked (tests/fake_provider):
the stand-in echoes its prompt, which is enough to assert that text flows from node to node,
while the request shaping and usage accounting under test stay the production path.
"""
from fastapi.testclient import TestClient

from fake_provider import openai_connection
from provekit.main import app


def _client():
    return TestClient(app, base_url="https://testserver")


def _graph(**over):
    """trigger → agent → logic → output, with the logic node branching on "refund"."""
    g = {
        "nodes": [
            {"id": "n1", "type": "trigger", "label": "New request", "position": {"x": 0, "y": 0}},
            {"id": "n2", "type": "agent", "label": "Agent", "position": {"x": 200, "y": 0},
             "config": {"model": "gpt-4o-mini", "prompt": "Reply: {{input}}"}},
            {"id": "n3", "type": "logic", "label": "Route", "position": {"x": 400, "y": 0},
             "config": {"conditions": [{"op": "contains", "value": "refund", "label": "refund"}]}},
            {"id": "n4", "type": "output", "label": "Refund path", "position": {"x": 600, "y": -80}},
            {"id": "n5", "type": "output", "label": "Default path", "position": {"x": 600, "y": 80}},
        ],
        "edges": [
            {"id": "e1", "source": "n1", "target": "n2"},
            {"id": "e2", "source": "n2", "target": "n3"},
            {"id": "e3", "source": "n3", "target": "n4", "label": "refund"},
            {"id": "e4", "source": "n3", "target": "n5", "label": "else"},
        ],
    }
    g.update(over)
    return g


def _make(c, **over):
    return c.post("/api/flows", json={"name": "support", "graph": _graph(**over)}).json()


# ---------------------------------------------------------------- CRUD

def test_create_read_and_list():
    c = _client()
    f = _make(c)
    assert f["version"] == 1 and f["published_version"] == 0
    assert len(f["graph"]["nodes"]) == 5
    assert c.get(f"/api/flows/{f['id']}").json()["name"] == "support"
    assert any(x["id"] == f["id"] for x in c.get("/api/flows").json())


def test_editing_the_graph_bumps_the_draft_but_not_the_published_pointer():
    c = _client()
    f = _make(c)
    c.post(f"/api/flows/{f['id']}/publish", json={"note": "v1"})
    g = _graph()
    g["nodes"][1]["label"] = "Renamed"
    after = c.patch(f"/api/flows/{f['id']}", json={"graph": g}).json()
    assert after["version"] == 2, "the draft moved"
    assert after["published_version"] == 1, "publishing is a separate act"


def test_delete_removes_versions_and_runs(fake_provider):
    c = _client()
    f = _make(c)
    c.post(f"/api/flows/{f['id']}/publish", json={})
    c.post(f"/api/flows/{f['id']}/run", json={"input": "hi", "connection_id": openai_connection(c)})
    assert c.delete(f"/api/flows/{f['id']}").status_code == 200
    assert c.get(f"/api/flows/{f['id']}").status_code == 404


# ---------------------------------------------------------------- versions

def test_publish_then_restore_round_trips_the_graph():
    c = _client()
    f = _make(c)
    c.post(f"/api/flows/{f['id']}/publish", json={"note": "first"})

    stripped = {"nodes": _graph()["nodes"][:2], "edges": [_graph()["edges"][0]]}
    c.patch(f"/api/flows/{f['id']}", json={"graph": stripped})
    assert len(c.get(f"/api/flows/{f['id']}").json()["graph"]["nodes"]) == 2

    restored = c.post(f"/api/flows/{f['id']}/restore/1").json()
    assert len(restored["graph"]["nodes"]) == 5, "the snapshot came back intact"

    versions = c.get(f"/api/flows/{f['id']}/versions").json()
    assert [v["version"] for v in versions] == [1]
    assert versions[0]["note"] == "first"


def test_restoring_an_unknown_version_is_404():
    c = _client()
    f = _make(c)
    assert c.post(f"/api/flows/{f['id']}/restore/9").status_code == 404


def test_publishing_an_unwalkable_graph_is_refused():
    c = _client()
    f = c.post("/api/flows", json={"name": "empty"}).json()
    r = c.post(f"/api/flows/{f['id']}/publish", json={})
    assert r.status_code == 422 and "no nodes" in r.json()["detail"]


# ---------------------------------------------------------------- execution

def test_run_walks_the_graph_and_records_every_step(fake_provider):
    c = _client()
    f = _make(c)
    run = c.post(f"/api/flows/{f['id']}/run", json={"input": "hello", "connection_id": openai_connection(c)}).json()
    assert run["status"] == "completed"
    assert [s["node_id"] for s in run["steps"]] == ["n1", "n2", "n3", "n5"]
    assert all(s["status"] == "ok" for s in run["steps"])
    assert "hello" in run["output"], "the trigger's input reached the model call"
    assert c.get(f"/api/flows/{f['id']}/runs").json()[0]["id"] == run["id"]


def test_a_matching_condition_routes_down_its_labelled_edge(fake_provider):
    c = _client()
    f = _make(c)
    run = c.post(f"/api/flows/{f['id']}/run",
                 json={"input": "I want a refund", "connection_id": openai_connection(c)}).json()
    assert run["steps"][-1]["node_id"] == "n4", "took the 'refund' edge, not 'else'"


def test_no_matching_condition_falls_through_the_else_edge(fake_provider):
    c = _client()
    f = _make(c)
    run = c.post(f"/api/flows/{f['id']}/run",
                 json={"input": "where is my order", "connection_id": openai_connection(c)}).json()
    assert run["steps"][-1]["node_id"] == "n5"


def test_knowledge_node_is_skipped_rather_than_inventing_a_document(fake_provider):
    c = _client()
    g = {
        "nodes": [
            {"id": "a", "type": "trigger", "label": "in", "position": {"x": 0, "y": 0}},
            {"id": "b", "type": "knowledge", "label": "Docs", "position": {"x": 200, "y": 0}},
        ],
        "edges": [{"id": "e", "source": "a", "target": "b"}],
    }
    f = c.post("/api/flows", json={"name": "kb", "graph": g}).json()
    run = c.post(f"/api/flows/{f['id']}/run", json={"input": "q", "connection_id": openai_connection(c)}).json()
    kb = next(s for s in run["steps"] if s["node_id"] == "b")
    assert kb["status"] == "skipped"
    assert "no retriever" in kb["note"]
    assert run["output"] == "q", "the payload passed through untouched"


def test_approval_auto_approves_and_says_so(fake_provider):
    c = _client()
    g = {
        "nodes": [
            {"id": "a", "type": "trigger", "label": "in", "position": {"x": 0, "y": 0}},
            {"id": "b", "type": "approval", "label": "Review", "position": {"x": 200, "y": 0}},
        ],
        "edges": [{"id": "e", "source": "a", "target": "b"}],
    }
    f = c.post("/api/flows", json={"name": "hitl", "graph": g}).json()
    run = c.post(f"/api/flows/{f['id']}/run", json={"input": "x", "connection_id": openai_connection(c)}).json()
    step = next(s for s in run["steps"] if s["node_id"] == "b")
    assert "auto-approved" in step["note"], "a test run must not claim a human approved"


def test_a_cycle_fails_with_the_step_cap_named_rather_than_hanging(fake_provider):
    c = _client()
    g = {
        "nodes": [
            {"id": "a", "type": "trigger", "label": "in", "position": {"x": 0, "y": 0}},
            {"id": "b", "type": "output", "label": "loop", "position": {"x": 200, "y": 0}},
        ],
        "edges": [{"id": "e1", "source": "a", "target": "b"},
                  {"id": "e2", "source": "b", "target": "a"}],
    }
    f = c.post("/api/flows", json={"name": "loopy", "graph": g}).json()
    run = c.post(f"/api/flows/{f['id']}/run", json={"input": "x", "connection_id": openai_connection(c)}).json()
    assert run["status"] == "failed"
    assert "loop" in run["error"]


def test_running_a_published_version_ignores_later_draft_edits(fake_provider):
    c = _client()
    f = _make(c)
    c.post(f"/api/flows/{f['id']}/publish", json={})
    # Draft now routes everything to the refund path; the published snapshot still branches.
    g = _graph()
    g["edges"][3]["label"] = "refund"
    c.patch(f"/api/flows/{f['id']}", json={"graph": g})
    run = c.post(f"/api/flows/{f['id']}/run",
                 json={"input": "where is my order", "connection_id": openai_connection(c), "version": 1}).json()
    assert run["steps"][-1]["node_id"] == "n5", "the frozen version was executed"


def test_two_triggers_is_rejected_because_the_start_is_ambiguous(fake_provider):
    c = _client()
    g = _graph()
    g["nodes"].append({"id": "n9", "type": "trigger", "label": "Other", "position": {"x": 0, "y": 200}})
    f = c.post("/api/flows", json={"name": "two-starts", "graph": g}).json()
    r = c.post(f"/api/flows/{f['id']}/run", json={"input": "x", "connection_id": openai_connection(c)})
    assert r.status_code == 422 and "more than one trigger" in r.json()["detail"]


def test_an_edge_to_a_missing_node_is_rejected(fake_provider):
    c = _client()
    g = _graph()
    g["edges"].append({"id": "e9", "source": "n1", "target": "ghost"})
    f = c.post("/api/flows", json={"name": "dangling", "graph": g}).json()
    r = c.post(f"/api/flows/{f['id']}/run", json={"input": "x", "connection_id": openai_connection(c)})
    assert r.status_code == 422 and "isn't on the canvas" in r.json()["detail"]


def test_unknown_node_type_is_rejected(fake_provider):
    c = _client()
    g = {"nodes": [{"id": "a", "type": "wormhole", "label": "?", "position": {"x": 0, "y": 0}}], "edges": []}
    f = c.post("/api/flows", json={"name": "bad", "graph": g}).json()
    r = c.post(f"/api/flows/{f['id']}/run", json={"input": "x", "connection_id": openai_connection(c)})
    assert r.status_code == 422 and "Unknown node type" in r.json()["detail"]


def test_a_model_node_with_no_connection_and_no_mock_is_422():
    c = _client()
    f = _make(c)
    r = c.post(f"/api/flows/{f['id']}/run", json={"input": "x"})
    assert r.status_code == 422


def test_flow_needs_a_name():
    c = _client()
    assert c.post("/api/flows", json={"name": "  "}).status_code == 422


# ---------------------------------------------------------------- trace linkage

def test_a_run_lands_in_the_trace_store(fake_provider):
    """A flow run that only lived in flow_runs was invisible to search, the waterfall and
    everything else that reads `runs`."""
    c = _client()
    f = _make(c)
    run = c.post(f"/api/flows/{f['id']}/run", json={"input": "hello", "connection_id": openai_connection(c)}).json()
    assert run["trace_id"], "the run reported a trace"

    spans = c.get(f"/api/traces/{run['trace_id']}").json()
    root = next(s for s in spans if not s["parent_span_id"])
    assert root["type"] == "agent" and root["label"] == "flow · support"
    assert root["result"]["meta"]["flow"] == "support"
    # one span per executed node, all parented to the root
    children = [s for s in spans if s["parent_span_id"] == root["span_id"]]
    assert len(children) == len(run["steps"])
    assert [s["label"] for s in children] == [s["label"] for s in run["steps"]]


def test_the_trace_is_listed_and_searchable_like_any_other(fake_provider):
    c = _client()
    f = _make(c)
    run = c.post(f"/api/flows/{f['id']}/run",
                 json={"input": "quicksilver-marker", "connection_id": openai_connection(c)}).json()
    listed = c.get("/api/traces?limit=50").json()
    assert any(t["trace_id"] == run["trace_id"] for t in listed), "shows up in the trace list"
    hits = c.get("/api/traces?q=quicksilver-marker&limit=50").json()
    assert any(t["trace_id"] == run["trace_id"] for t in hits), "search_text was populated"


def test_node_types_map_onto_the_span_types_the_portal_understands(fake_provider):
    c = _client()
    f = _make(c)
    run = c.post(f"/api/flows/{f['id']}/run", json={"input": "hi", "connection_id": openai_connection(c)}).json()
    spans = c.get(f"/api/traces/{run['trace_id']}").json()
    by_label = {s["label"]: s for s in spans}
    assert by_label["Agent"]["type"] == "llm", "a model call is an llm span"
    assert by_label["Route"]["type"] == "step"
    assert by_label["New request"]["type"] == "step"


def test_a_failed_run_produces_a_failed_root_span(fake_provider):
    c = _client()
    g = {
        "nodes": [
            {"id": "a", "type": "trigger", "label": "in", "position": {"x": 0, "y": 0}},
            {"id": "b", "type": "output", "label": "loop", "position": {"x": 200, "y": 0}},
        ],
        "edges": [{"id": "e1", "source": "a", "target": "b"},
                  {"id": "e2", "source": "b", "target": "a"}],
    }
    f = c.post("/api/flows", json={"name": "loopy-trace", "graph": g}).json()
    run = c.post(f"/api/flows/{f['id']}/run", json={"input": "x", "connection_id": openai_connection(c)}).json()
    assert run["status"] == "failed"
    spans = c.get(f"/api/traces/{run['trace_id']}").json()
    root = next(s for s in spans if not s["parent_span_id"])
    assert root["status"] == "failed" and "loop" in root["error"]


def test_a_skipped_node_carries_its_reason_into_the_span(fake_provider):
    """Otherwise the trace would show a knowledge step that looks like it retrieved something."""
    c = _client()
    g = {
        "nodes": [
            {"id": "a", "type": "trigger", "label": "in", "position": {"x": 0, "y": 0}},
            {"id": "b", "type": "knowledge", "label": "Docs", "position": {"x": 200, "y": 0}},
        ],
        "edges": [{"id": "e", "source": "a", "target": "b"}],
    }
    f = c.post("/api/flows", json={"name": "kb-trace", "graph": g}).json()
    run = c.post(f"/api/flows/{f['id']}/run", json={"input": "q", "connection_id": openai_connection(c)}).json()
    spans = c.get(f"/api/traces/{run['trace_id']}").json()
    docs = next(s for s in spans if s["label"] == "Docs")
    assert "no retriever" in docs["result"]["meta"]["note"]


def test_a_failed_trace_write_does_not_fail_the_run(monkeypatch, fake_provider):
    """The flow really did execute; reporting it as failed because bookkeeping broke would be
    a lie about the run."""
    from provekit.services import flow_trace

    monkeypatch.setattr(flow_trace, "spans_for",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    c = _client()
    f = _make(c)
    run = c.post(f"/api/flows/{f['id']}/run", json={"input": "hi", "connection_id": openai_connection(c)}).json()
    assert run["status"] == "completed"
    assert run["trace_id"] == "", "no trace, and the run says so rather than pretending"


def test_deleting_a_project_removes_its_flows_versions_and_runs(fake_provider):
    """Project deletion enumerates tenant models by hand (SQLite won't cascade). A flow left
    behind would point at a workspace that no longer exists — the sample project promises to be
    disposable, and an orphaned flow breaks that."""
    import uuid

    from provekit.database import SessionLocal
    from provekit.models import Flow, FlowRun, FlowVersion, User

    email = f"flow-del-{uuid.uuid4().hex[:8]}@example.com"
    c = _client()
    assert c.post("/api/auth/register",
                  json={"email": email, "password": "hunter2hunter2"}).status_code == 200
    f = _make(c)
    c.post(f"/api/flows/{f['id']}/publish", json={})
    c.post(f"/api/flows/{f['id']}/run", json={"input": "hi", "connection_id": openai_connection(c)})

    s = SessionLocal()
    try:
        ws_id = s.query(Flow).filter(Flow.id == f["id"]).one().workspace_id
        assert s.query(FlowVersion).filter(FlowVersion.workspace_id == ws_id).count() == 1
        assert s.query(FlowRun).filter(FlowRun.workspace_id == ws_id).count() == 1
    finally:
        s.close()

    assert c.delete(f"/api/projects/{ws_id}").status_code == 200

    s = SessionLocal()
    try:
        assert s.query(Flow).filter(Flow.workspace_id == ws_id).count() == 0
        assert s.query(FlowVersion).filter(FlowVersion.workspace_id == ws_id).count() == 0
        assert s.query(FlowRun).filter(FlowRun.workspace_id == ws_id).count() == 0
    finally:
        s.close()


# ---------------------------------------------------------------- spend + token guards

def test_each_model_node_meters_its_spend(monkeypatch, fake_provider):
    """A flow can chain several model calls behind one spend-cap check at run start. If those
    calls don't record spend, the executor bills past a cap the playground and replay respect —
    the check that gated the run never sees what the run then spent."""
    from provekit.routers import flows as fl

    seen: list[float] = []
    monkeypatch.setattr(fl.limits, "record_spend", lambda ws_id, usd: seen.append(usd))
    c = _client()
    # two model nodes in a row, so we can count the metered calls
    g = {
        "nodes": [
            {"id": "a", "type": "trigger", "label": "in", "position": {"x": 0, "y": 0}},
            {"id": "b", "type": "agent", "label": "A", "position": {"x": 1, "y": 0},
             "config": {"model": "gpt-4o", "prompt": "{{input}}"}},
            {"id": "d", "type": "model", "label": "B", "position": {"x": 2, "y": 0},
             "config": {"model": "gpt-4o", "prompt": "{{input}}"}},
        ],
        "edges": [{"id": "e1", "source": "a", "target": "b"},
                  {"id": "e2", "source": "b", "target": "d"}],
    }
    f = c.post("/api/flows", json={"name": "billed", "graph": g}).json()
    r = c.post(f"/api/flows/{f['id']}/run", json={"input": "hi", "connection_id": openai_connection(c)})
    assert r.status_code == 200
    assert len(seen) == 2, "one record_spend per model node, not zero"


def test_a_node_cannot_ask_for_more_than_the_token_ceiling(monkeypatch, fake_provider):
    """The playground clamps max_tokens so one edit can't run an unbounded completion; a flow
    node has to be clamped the same way or it's an escape hatch around the ceiling."""
    from provekit.routers import flows as fl

    captured: dict = {}

    async def spy(provider, model, messages, params, **kw):
        captured["max_tokens"] = params.get("max_tokens")
        return {"output": "ok", "usage": {"input_tokens": 1, "output_tokens": 1}}

    monkeypatch.setattr(fl, "complete", spy)
    c = _client()
    g = {
        "nodes": [
            {"id": "a", "type": "trigger", "label": "in", "position": {"x": 0, "y": 0}},
            {"id": "b", "type": "agent", "label": "A", "position": {"x": 1, "y": 0},
             "config": {"model": "gpt-4o", "prompt": "{{input}}", "params": {"max_tokens": 1_000_000}}},
        ],
        "edges": [{"id": "e", "source": "a", "target": "b"}],
    }
    f = c.post("/api/flows", json={"name": "greedy", "graph": g}).json()
    c.post(f"/api/flows/{f['id']}/run", json={"input": "hi", "connection_id": openai_connection(c)})
    assert captured["max_tokens"] == fl._MAX_TOKENS_CAP


def test_a_run_is_refused_once_the_spend_cap_is_already_reached(monkeypatch, fake_provider):
    """The run-start check still holds: a project already over its cap can't start a flow."""
    from provekit.config import get_settings
    from provekit.routers import flows as fl
    from provekit.services import limits

    c = _client()
    f = _make(c)
    get_settings.cache_clear(); limits._window.cache_clear()
    monkeypatch.setenv("PLAYGROUND_MONTHLY_USD_CAP", "0.01")
    get_settings.cache_clear()
    # push this project over the cap, then a run must be refused with 402
    limits.record_spend(_ws_of(c, f["id"]), 0.05)
    r = c.post(f"/api/flows/{f['id']}/run", json={"input": "x", "connection_id": openai_connection(c)})
    assert r.status_code == 402
    get_settings.cache_clear(); limits._window.cache_clear()
    monkeypatch.delenv("PLAYGROUND_MONTHLY_USD_CAP", raising=False)
    get_settings.cache_clear()


def _ws_of(c, flow_id: int) -> int:
    from provekit.database import SessionLocal
    from provekit.models import Flow
    s = SessionLocal()
    try:
        return s.query(Flow).filter(Flow.id == flow_id).one().workspace_id
    finally:
        s.close()
