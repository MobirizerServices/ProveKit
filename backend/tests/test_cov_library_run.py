"""HTTP coverage for routers/library.py and routers/run.py.

Everything runs against the keyless mock connection ("Demo Assistant (mock)",
provider "mock", model "demo-mock") which is seeded into every workspace and needs
no network. Local mode (default) requires no auth, so a bare TestClient suffices.
"""
import pytest
import yaml
from fastapi.testclient import TestClient

from provekit.main import app


@pytest.fixture(scope="module")
def c():
    with TestClient(app) as client:
        yield client


def _mock_conn(c) -> dict:
    return next(x for x in c.get("/api/connections").json()
               if x["config"].get("provider") == "mock")


def _prompt_req(conn, user="hello world") -> dict:
    return {"type": "prompt", "connection_id": conn["id"], "model": "demo-mock", "user": user}


# --------------------------------------------------------------------------- #
# library.py — collections
# --------------------------------------------------------------------------- #
def test_collection_crud_and_request_reassign(c):
    col = c.post("/api/collections", json={"name": "Regression"}).json()
    assert col["name"] == "Regression" and col["requests"] == []

    # a request filed under the collection
    r = c.post("/api/requests", json={
        "name": "in-col", "type": "prompt", "collection_id": col["id"],
        "payload": {"type": "prompt", "user": "x"}}).json()
    assert r["collection_id"] == col["id"]

    listing = c.get("/api/collections").json()
    mine = next(x for x in listing["collections"] if x["id"] == col["id"])
    assert any(req["id"] == r["id"] for req in mine["requests"])

    # deleting the collection reassigns its requests to loose (collection_id -> None)
    assert c.delete(f"/api/collections/{col['id']}").json() == {"deleted": True}
    back = c.get(f"/api/requests/{r['id']}").json()
    assert back["collection_id"] is None
    loose = c.get("/api/collections").json()["loose"]
    assert any(req["id"] == r["id"] for req in loose)


def test_delete_missing_collection_is_noop(c):
    # non-existent id: still 200 {"deleted": True}, no crash
    assert c.delete("/api/collections/999999").json() == {"deleted": True}


def test_request_collection_id_foreign_becomes_none(c):
    # a bogus collection_id is silently dropped to None (unfiled) rather than dangling
    r = c.post("/api/requests", json={
        "name": "bad-col", "type": "prompt", "collection_id": 987654,
        "payload": {"type": "prompt", "user": "x"}}).json()
    assert r["collection_id"] is None


# --------------------------------------------------------------------------- #
# library.py — requests CRUD + export
# --------------------------------------------------------------------------- #
def test_request_crud_get_update_delete(c):
    saved = c.post("/api/requests", json={
        "name": "R1", "type": "prompt", "collection_id": None,
        "payload": {"type": "prompt", "user": "one"}}).json()
    rid = saved["id"]

    got = c.get(f"/api/requests/{rid}").json()
    assert got["name"] == "R1" and got["payload"]["user"] == "one"

    upd = c.put(f"/api/requests/{rid}", json={
        "name": "R1b", "type": "tool", "collection_id": None,
        "payload": {"type": "tool", "tool": "echo"}}).json()
    assert upd["name"] == "R1b" and upd["type"] == "tool"

    assert c.delete(f"/api/requests/{rid}").json() == {"deleted": True}
    assert c.get(f"/api/requests/{rid}").status_code == 404


def test_request_404s(c):
    assert c.get("/api/requests/424242").status_code == 404
    assert c.put("/api/requests/424242", json={
        "name": "x", "type": "prompt", "payload": {}}).status_code == 404
    # delete of a missing request is a no-op 200
    assert c.delete("/api/requests/424242").json() == {"deleted": True}


def test_export_with_and_without_connection(c):
    conn = _mock_conn(c)
    # with a connection_id -> connection name appears in the .provekit doc
    saved = c.post("/api/requests", json={
        "name": "Exp", "type": "prompt", "collection_id": None,
        "payload": {"type": "prompt", "connection_id": conn["id"], "model": "demo-mock",
                    "user": "hi"}}).json()
    text = c.get(f"/api/requests/{saved['id']}/export").text
    doc = yaml.safe_load(text)
    assert doc["kind"] == "test" and doc["connection"] == "Demo Assistant (mock)"
    assert "connection_id" not in text

    # no connection_id -> exports fine, no `connection` key
    plain = c.post("/api/requests", json={
        "name": "Exp2", "type": "prompt", "collection_id": None,
        "payload": {"type": "prompt", "user": "hi"}}).json()
    text2 = c.get(f"/api/requests/{plain['id']}/export").text
    assert "connection:" not in yaml.safe_dump(yaml.safe_load(text2))

    assert c.get("/api/requests/424242/export").status_code == 404


# --------------------------------------------------------------------------- #
# library.py — /api/import  (test kind)
# --------------------------------------------------------------------------- #
def test_import_test_resolves_connection_and_dataset(c):
    conn = _mock_conn(c)
    doc = {
        "version": 1, "kind": "test", "name": "Imp test",
        "connection": "Demo Assistant (mock)",
        "request": {"type": "prompt", "model": "demo-mock", "user": "{{q}}"},
        "assertions": [{"type": "contains", "value": "demo"}],
        "dataset": [{"name": "row a", "variables": {"q": "hello"}}],
    }
    imp = c.post("/api/import", json={"content": yaml.safe_dump(doc)}).json()
    assert imp["kind"] == "test" and imp["connection_resolved"] is True
    assert imp["request"]["payload"]["connection_id"] == conn["id"]
    assert imp["request"]["payload"]["assertions"] == [{"type": "contains", "value": "demo"}]
    assert imp["dataset_id"] is not None


def test_import_test_unresolved_connection(c):
    # connection name that doesn't exist in this workspace -> imports, needs re-pick
    doc = {
        "version": 1, "kind": "test", "name": "Unresolved",
        "connection": "Nonexistent Conn",
        "request": {"type": "prompt", "model": "demo-mock", "user": "hi"},
    }
    imp = c.post("/api/import", json={"content": yaml.safe_dump(doc)}).json()
    assert imp["kind"] == "test" and imp["connection_resolved"] is False
    assert "connection_id" not in imp["request"]["payload"]


def test_import_test_no_connection_name(c):
    # no connection at all -> connection_resolved True (nothing to resolve)
    doc = {
        "version": 1, "kind": "test", "name": "NoConn",
        "request": {"type": "tool", "tool": "echo", "args": {}},
    }
    imp = c.post("/api/import", json={"content": yaml.safe_dump(doc)}).json()
    assert imp["kind"] == "test" and imp["connection_resolved"] is True
    assert imp["dataset_id"] is None


def test_import_into_collection(c):
    col = c.post("/api/collections", json={"name": "ImpCol"}).json()
    doc = {
        "version": 1, "kind": "test", "name": "Into col",
        "request": {"type": "prompt", "model": "demo-mock", "user": "hi"},
    }
    imp = c.post("/api/import", json={"content": yaml.safe_dump(doc),
                                      "collection_id": col["id"]}).json()
    assert imp["request"]["collection_id"] == col["id"]


def test_import_bad_yaml_and_version(c):
    # unsupported version -> 400 from testfile.load
    r = c.post("/api/import", json={"content": "version: 9\nkind: test"})
    assert r.status_code == 400 and "unsupported version" in r.json()["detail"]
    # not valid YAML mapping
    r2 = c.post("/api/import", json={"content": "just a string"})
    assert r2.status_code == 400


# --------------------------------------------------------------------------- #
# library.py — /api/import  (flow kind)
# --------------------------------------------------------------------------- #
def test_import_flow_resolves_connection(c):
    conn = _mock_conn(c)
    doc = {
        "version": 1, "kind": "flow", "name": "Imp flow", "description": "d",
        "nodes": [
            {"id": "input", "type": "input", "position": {"x": 0, "y": 0}, "data": {}, "config": {}},
            {"id": "p", "type": "prompt", "position": {"x": 1, "y": 0}, "data": {},
             "config": {"connection": "Demo Assistant (mock)", "model": "demo-mock", "user": "{{input.q}}"}},
        ],
        "edges": [{"id": "e", "source": "input", "target": "p"}],
    }
    imp = c.post("/api/import", json={"content": yaml.safe_dump(doc)}).json()
    assert imp["kind"] == "flow" and imp["connection_resolved"] is True
    back = c.get(f"/api/flows/{imp['flow_id']}").json()
    assert back["nodes"][1]["config"]["connection_id"] == conn["id"]


def test_import_flow_unresolved_connection(c):
    doc = {
        "version": 1, "kind": "flow", "name": "Unresolved flow",
        "nodes": [
            {"id": "p", "type": "prompt", "position": {"x": 0, "y": 0}, "data": {},
             "config": {"connection": "No Such Conn"}},
        ],
        "edges": [],
    }
    imp = c.post("/api/import", json={"content": yaml.safe_dump(doc)}).json()
    assert imp["kind"] == "flow" and imp["connection_resolved"] is False


def test_import_flow_node_cap_400(c, monkeypatch):
    from provekit.config import get_settings
    monkeypatch.setattr(get_settings(), "max_flow_nodes", 2)
    nodes = [{"id": f"n{i}", "type": "input", "position": {"x": 0, "y": 0}, "data": {}, "config": {}}
             for i in range(3)]
    doc = {"version": 1, "kind": "flow", "name": "Too big", "nodes": nodes, "edges": []}
    r = c.post("/api/import", json={"content": yaml.safe_dump(doc)})
    assert r.status_code == 400 and "too large" in r.json()["detail"].lower()


def test_import_flow_non_dict_node_400(c):
    # a node that isn't a mapping -> 400. Build YAML by hand since load() only checks
    # that nodes is a list.
    text = "version: 1\nkind: flow\nname: bad\nnodes:\n  - not-a-dict\nedges: []\n"
    r = c.post("/api/import", json={"content": text})
    assert r.status_code == 400 and "each node must be an object" in r.json()["detail"]


def test_import_collection_id_cross_workspace_dropped(c):
    # a collection_id that isn't a real collection is validated to None (unfiled).
    doc = {
        "version": 1, "kind": "test", "name": "x",
        "request": {"type": "prompt", "model": "demo-mock", "user": "hi"},
    }
    imp = c.post("/api/import", json={"content": yaml.safe_dump(doc),
                                      "collection_id": 555555}).json()
    assert imp["request"]["collection_id"] is None


# --------------------------------------------------------------------------- #
# library.py — environments
# --------------------------------------------------------------------------- #
def test_environment_crud_and_single_active(c):
    e1 = c.post("/api/environments", json={
        "name": "dev", "variables": {"a": "1"}, "is_active": True}).json()
    e2 = c.post("/api/environments", json={
        "name": "prod", "variables": {"b": "2"}, "is_active": False}).json()

    listing = c.get("/api/environments").json()
    assert {e1["id"], e2["id"]} <= {e["id"] for e in listing}

    # activating e2 deactivates e1 (only one active in the workspace)
    upd = c.put(f"/api/environments/{e2['id']}", json={
        "name": "prod", "variables": {"b": "2"}, "is_active": True}).json()
    assert upd["is_active"] is True
    fresh = {e["id"]: e for e in c.get("/api/environments").json()}
    assert fresh[e1["id"]]["is_active"] is False
    assert fresh[e2["id"]]["is_active"] is True

    # deactivate so later run tests don't inherit unexpected variables
    c.put(f"/api/environments/{e2['id']}", json={
        "name": "prod", "variables": {}, "is_active": False})

    assert c.delete(f"/api/environments/{e1['id']}").json() == {"deleted": True}
    assert c.delete(f"/api/environments/{e2['id']}").json() == {"deleted": True}


def test_environment_404s_and_noop_delete(c):
    assert c.put("/api/environments/424242", json={
        "name": "x", "variables": {}, "is_active": False}).status_code == 404
    assert c.delete("/api/environments/424242").json() == {"deleted": True}


# --------------------------------------------------------------------------- #
# library.py — datasets
# --------------------------------------------------------------------------- #
def test_dataset_crud(c):
    d = c.post("/api/datasets", json={
        "name": "DS", "rows": [{"name": "r1", "variables": {"q": "a"}}]}).json()
    assert d["name"] == "DS" and len(d["rows"]) == 1

    assert any(x["id"] == d["id"] for x in c.get("/api/datasets").json())

    upd = c.put(f"/api/datasets/{d['id']}", json={
        "name": "DS2", "rows": []}).json()
    assert upd["name"] == "DS2" and upd["rows"] == []

    assert c.delete(f"/api/datasets/{d['id']}").json() == {"deleted": True}


def test_dataset_404s_and_noop_delete(c):
    assert c.put("/api/datasets/424242", json={"name": "x", "rows": []}).status_code == 404
    assert c.delete("/api/datasets/424242").json() == {"deleted": True}


# --------------------------------------------------------------------------- #
# run.py — POST /api/run
# --------------------------------------------------------------------------- #
def test_run_once_no_save(c):
    conn = _mock_conn(c)
    r = c.post("/api/run", json={"request": _prompt_req(conn, "hello there"),
                                 "save": False}).json()
    assert r["status"] == "completed"
    assert r["result"]["text"]  # mock streamed some text
    assert r["assertions"] == []


def test_run_once_save_and_appears_in_history(c):
    conn = _mock_conn(c)
    r = c.post("/api/run", json={"request": _prompt_req(conn, "please help"),
                                 "save": True}).json()
    assert r["status"] == "completed"
    runs = c.get("/api/runs").json()
    assert runs and runs[0]["type"] == "prompt"


def test_run_once_with_assertions_attached_to_run(c):
    conn = _mock_conn(c)
    req = _prompt_req(conn, "hello world")
    req["assertions"] = [{"type": "contains", "value": "demo"}]
    r = c.post("/api/run", json={"request": req, "save": True}).json()
    assert r["assertions"] and r["assertions"][0]["ok"] is True
    # the assertion is persisted onto the run result
    detail = c.get(f"/api/runs/{c.get('/api/runs').json()[0]['id']}").json()
    assert detail["result"].get("assertions")


def test_run_tool_failure_labels_and_persists(c):
    # A tool run with no MCP url raises inside dispatch (no network) -> a "failed" run.
    # Exercises _label's tool branch and the error-event path in _apply, and persists.
    r = c.post("/api/run", json={
        "request": {"type": "tool", "tool": "echo", "args": {}}, "save": True}).json()
    assert r["status"] == "failed"
    # persisted with a tool: label
    detail = c.get(f"/api/runs/{c.get('/api/runs').json()[0]['id']}").json()
    assert detail["type"] == "tool" and detail["label"].startswith("tool:")
    assert detail["error"]


def test_run_agent_masks_secrets_on_persist(c):
    # An agent run with no base_url raises before any network call -> "failed".
    # The persisted request goes through _sanitize: api_key dropped, secret headers +
    # body fields masked. Exercises _label's agent branch and _sanitize masking.
    req = {
        "type": "agent", "method": "POST", "path": "/chat",
        "api_key": "sk-should-be-dropped",
        "headers": {"Authorization": "Bearer supersecrettoken", "X-Trace": "keep-me"},
        "body": {"prompt": "hi", "password": "hunter2"},
    }
    r = c.post("/api/run", json={"request": req, "save": True}).json()
    assert r["status"] == "failed"
    detail = c.get(f"/api/runs/{c.get('/api/runs').json()[0]['id']}").json()
    assert detail["label"].startswith("POST /chat")
    stored = detail["request"]
    assert "api_key" not in stored  # dropped entirely
    assert stored["headers"]["Authorization"].startswith("••••")  # masked
    assert stored["headers"]["X-Trace"] == "keep-me"  # non-secret kept
    assert stored["body"]["password"].startswith("••••")  # body secret masked
    assert stored["body"]["prompt"] == "hi"


def test_run_unknown_type_fails(c):
    # unknown request type -> dispatch raises -> error event -> failed run.
    # save=True so _persist/_label run: _label's final `t or "run"` fallback is exercised.
    r = c.post("/api/run", json={"request": {"type": "mystery"}, "save": True}).json()
    assert r["status"] == "failed"
    detail = c.get(f"/api/runs/{c.get('/api/runs').json()[0]['id']}").json()
    assert detail["label"] == "mystery"


# --------------------------------------------------------------------------- #
# run.py — POST /api/run/stream  (SSE)
# --------------------------------------------------------------------------- #
def test_run_stream_sse(c):
    conn = _mock_conn(c)
    req = _prompt_req(conn, "hello world")
    req["assertions"] = [{"type": "contains", "value": "demo"}]
    with c.stream("POST", "/api/run/stream", json={"request": req, "save": True}) as resp:
        assert resp.status_code == 200
        body = "".join(resp.iter_text())
    assert "data:" in body
    assert '"type": "delta"' in body
    assert '"type": "assert"' in body  # assertions emitted mid-stream
    assert "[DONE]" in body


def test_run_stream_no_save(c):
    conn = _mock_conn(c)
    with c.stream("POST", "/api/run/stream",
                  json={"request": _prompt_req(conn, "quick"), "save": False}) as resp:
        assert resp.status_code == 200
        body = "".join(resp.iter_text())
    assert "[DONE]" in body


# --------------------------------------------------------------------------- #
# run.py — POST /api/dataset/run
# --------------------------------------------------------------------------- #
def test_dataset_run_two_rows(c):
    conn = _mock_conn(c)
    req = _prompt_req(conn, "{{q}}")
    req["assertions"] = [{"type": "contains", "value": "demo"}]
    body = c.post("/api/dataset/run", json={
        "request": req,
        "rows": [
            {"name": "first", "variables": {"q": "hello"}},
            {"variables": {"q": "world"}},  # unnamed -> defaults to "row 2"
        ],
    }).json()
    assert body["summary"]["total"] == 2
    assert len(body["rows"]) == 2
    assert body["rows"][1]["name"] == "row 2"
    # both mock replies contain "demo" -> both pass
    assert body["summary"]["passed"] == 2


def test_dataset_run_no_assertions_uses_status(c):
    conn = _mock_conn(c)
    body = c.post("/api/dataset/run", json={
        "request": _prompt_req(conn, "hi"),
        "rows": [{"variables": {}}],
    }).json()
    assert body["summary"]["total"] == 1
    # no assertions -> pass keyed off completed status
    assert body["rows"][0]["pass"] is True


# --------------------------------------------------------------------------- #
# run.py — GET /api/runs  &  GET /api/runs/{id}
# --------------------------------------------------------------------------- #
def test_runs_limit_clamped(c):
    conn = _mock_conn(c)
    c.post("/api/run", json={"request": _prompt_req(conn), "save": True})
    # negative limit clamps to >=1 (SQLite would treat -1 as unlimited otherwise)
    neg = c.get("/api/runs?limit=-1").json()
    assert isinstance(neg, list) and len(neg) >= 1
    # huge limit clamps to 200
    big = c.get("/api/runs?limit=100000").json()
    assert len(big) <= 200


def test_get_run_200_and_404(c):
    conn = _mock_conn(c)
    c.post("/api/run", json={"request": _prompt_req(conn), "save": True})
    rid = c.get("/api/runs").json()[0]["id"]
    got = c.get(f"/api/runs/{rid}").json()
    assert got["id"] == rid and "result" in got and "request" in got
    assert c.get("/api/runs/999999").status_code == 404


def test_dataset_run_mixed_pass_and_fail(c):
    """The whole point of a dataset run is finding the rows that fail — yet every other
    dataset test has every row passing, so the failing half (per-row pass=False,
    summary.passed < total) was never exercised end to end."""
    conn = _mock_conn(c)
    req = _prompt_req(conn, "{{q}}")
    req["assertions"] = [{"type": "contains", "value": "urgent"}]
    body = c.post("/api/dataset/run", json={
        "request": req,
        "rows": [
            {"name": "escalation", "variables": {"q": "urgent refund please"}},  # mock replies "urgent…"
            {"name": "chit-chat", "variables": {"q": "what is an AI agent"}},     # generic reply, no "urgent"
        ],
    }).json()

    assert body["summary"] == {"passed": 1, "total": 2}, "one row must fail"
    by_name = {r["name"]: r for r in body["rows"]}
    assert by_name["escalation"]["pass"] is True
    assert by_name["chit-chat"]["pass"] is False
    # the failing row still RAN — a failed row must not abort the batch or go unexecuted
    assert by_name["chit-chat"]["status"] == "completed" and by_name["chit-chat"]["text"]
    # per-row isolation: each row's output reflects its OWN input, no bleed
    assert "urgent" in by_name["escalation"]["text"]
    assert "urgent" not in by_name["chit-chat"]["text"]
    assert by_name["chit-chat"]["assertions"][0]["ok"] is False
