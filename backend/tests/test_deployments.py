"""Deployments: publish a flow, invoke by slug with the API key, version + rollback, auth."""
import pytest
from fastapi.testclient import TestClient

from agentman.main import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _mock_flow(client) -> dict:
    conn = next(c for c in client.get("/api/connections").json() if c["config"].get("provider") == "mock")
    return client.post("/api/flows", json={
        "name": "Deployable bot",
        "nodes": [
            {"id": "input", "type": "input", "position": {"x": 0, "y": 0}, "data": {}, "config": {"sample": {"question": "hi"}}},
            {"id": "ask", "type": "prompt", "position": {"x": 1, "y": 0}, "data": {"title": "Ask"},
             "config": {"connection_id": conn["id"], "model": "demo-mock", "user": "{{input.question}}"}},
            {"id": "out", "type": "output", "position": {"x": 2, "y": 0}, "data": {"title": "Answer"}, "config": {"value": "{{ask.text}}"}},
        ],
        "edges": [{"id": "e1", "source": "input", "target": "ask"}, {"id": "e2", "source": "ask", "target": "out"}],
    }).json()


def test_deploy_then_invoke(client):
    f = _mock_flow(client)
    dep = client.post("/api/deployments", json={"flow_id": f["id"]}).json()
    assert dep["slug"] and dep["version"] == 1 and "api_key" in dep and dep["url"].endswith(f"/v1/d/{dep['slug']}")
    key = dep["api_key"]

    # invoke with the key → runs the snapshot, returns the output node's value
    r = client.post(f"/v1/d/{dep['slug']}", headers={"X-API-Key": key},
                    json={"question": "what is an AI agent?"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "completed" and isinstance(body["output"], str) and body["output"]


def test_invoke_requires_valid_key(client):
    f = _mock_flow(client)
    dep = client.post("/api/deployments", json={"flow_id": f["id"]}).json()
    assert client.post(f"/v1/d/{dep['slug']}", json={}).status_code == 403          # no key
    assert client.post(f"/v1/d/{dep['slug']}", headers={"X-API-Key": "agm_wrong"}, json={}).status_code == 403
    assert client.post("/v1/d/nonexistent", headers={"X-API-Key": "x"}, json={}).status_code == 404


def test_redeploy_snapshots_and_bumps_version(client):
    f = _mock_flow(client)
    dep = client.post("/api/deployments", json={"flow_id": f["id"]}).json()
    key, slug = dep["api_key"], dep["slug"]

    # edit the flow AFTER deploying
    client.put(f"/api/flows/{f['id']}", json={**f, "name": "Deployable bot", "nodes": f["nodes"][:1], "edges": []})
    # old deployment still runs the OLD snapshot (3 nodes) — invoke still works
    assert client.post(f"/v1/d/{slug}", headers={"X-API-Key": key}, json={"question": "hi"}).status_code == 200

    dep2 = client.post("/api/deployments", json={"flow_id": f["id"]}).json()
    assert dep2["version"] == 2 and dep2["slug"] == slug and "api_key" not in dep2  # key carried, not reshown

    detail = client.get(f"/api/deployments/{slug}").json()
    assert detail["version"] == 2 and len(detail["versions"]) == 2


def test_logs_and_stats(client):
    f = _mock_flow(client)
    dep = client.post("/api/deployments", json={"flow_id": f["id"]}).json()
    key, slug = dep["api_key"], dep["slug"]
    for _ in range(3):
        client.post(f"/v1/d/{slug}", headers={"X-API-Key": key}, json={"question": "hi"})

    runs = client.get(f"/api/deployments/{slug}/runs").json()
    assert len(runs) == 3 and all(r["status"] == "completed" for r in runs)

    stats = client.get(f"/api/deployments/{slug}/stats").json()
    assert stats["invocations"] == 3 and stats["error_rate"] == 0.0
    assert "p95_ms" in stats and stats["p50_ms"] >= 0


def test_deactivate_and_rollback(client):
    f = _mock_flow(client)
    dep = client.post("/api/deployments", json={"flow_id": f["id"]}).json()
    key, slug = dep["api_key"], dep["slug"]
    client.post("/api/deployments", json={"flow_id": f["id"]})  # v2

    client.post(f"/api/deployments/{slug}/deactivate")
    assert client.post(f"/v1/d/{slug}", headers={"X-API-Key": key}, json={}).status_code == 410  # gone

    client.post(f"/api/deployments/{slug}/rollback", json={"version": 1})
    assert client.post(f"/v1/d/{slug}", headers={"X-API-Key": key}, json={"question": "hi"}).status_code == 200


def test_deployment_timeout(client, monkeypatch):
    from agentman.config import get_settings
    from agentman.services import deploy as deploy_svc
    f = _mock_flow(client)
    dep = client.post("/api/deployments", json={"flow_id": f["id"]}).json()
    monkeypatch.setattr(get_settings(), "deployment_timeout_s", 0.05)

    # make the snapshot run hang longer than the timeout
    import anyio
    async def _slow(session, snapshot, flow_input, workspace_id, stream=False):
        await anyio.sleep(0.5)
        yield {"type": "done", "status": "completed"}
    monkeypatch.setattr(deploy_svc, "run_snapshot", _slow)

    r = client.post(f"/v1/d/{dep['slug']}", headers={"X-API-Key": dep["api_key"]}, json={})
    assert r.status_code == 504 and "timeout" in r.json()["detail"]


def _mock_flow_tagged(client, tag: str) -> dict:
    """A deployable flow whose output node stamps `tag`, so different versions produce
    visibly different output — otherwise v1 and v2 snapshots are byte-identical and 'which
    version served' is untestable."""
    conn = next(c for c in client.get("/api/connections").json() if c["config"].get("provider") == "mock")
    return client.post("/api/flows", json={
        "name": "Versioned bot",
        "nodes": [
            {"id": "input", "type": "input", "position": {"x": 0, "y": 0}, "data": {}, "config": {"sample": {"question": "hi"}}},
            {"id": "ask", "type": "prompt", "position": {"x": 1, "y": 0}, "data": {"title": "Ask"},
             "config": {"connection_id": conn["id"], "model": "demo-mock", "user": "{{input.question}}"}},
            {"id": "out", "type": "output", "position": {"x": 2, "y": 0}, "data": {"title": "Answer"},
             "config": {"value": f"{tag}: " + "{{ask.text}}"}},
        ],
        "edges": [{"id": "e1", "source": "input", "target": "ask"}, {"id": "e2", "source": "ask", "target": "out"}],
    }).json()


def test_rollback_and_redeploy_serve_the_right_version_output(client):
    """The runtime must serve the snapshot of the version that is actually live — not merely
    return 200. Every other test deploys v1/v2 from an unedited flow (identical snapshots), so
    a runtime that served the wrong version would still pass. Here v1 and v2 differ visibly."""
    f = _mock_flow_tagged(client, "V1")
    dep = client.post("/api/deployments", json={"flow_id": f["id"]}).json()
    key, slug = dep["api_key"], dep["slug"]

    def invoke():
        r = client.post(f"/v1/d/{slug}", headers={"X-API-Key": key}, json={"question": "hi"})
        assert r.status_code == 200, r.text
        return r.json()["output"]

    assert invoke().startswith("V1:")  # v1 is live

    # edit the flow to stamp V2, then redeploy → v2 becomes the live version
    v2_nodes = [{**n, "config": ({**n["config"], "value": "V2: {{ask.text}}"} if n["id"] == "out" else n["config"])}
                for n in f["nodes"]]
    client.put(f"/api/flows/{f['id']}", json={"name": "Versioned bot", "nodes": v2_nodes, "edges": f["edges"]})
    dep2 = client.post("/api/deployments", json={"flow_id": f["id"]}).json()
    assert dep2["version"] == 2
    assert invoke().startswith("V2:"), "redeploy must serve the NEW version's snapshot, not v1"

    # rollback to v1 → the runtime must serve v1's snapshot again, not the latest
    client.post(f"/api/deployments/{slug}/rollback", json={"version": 1})
    assert invoke().startswith("V1:"), "after rollback the runtime must serve the rolled-back version"
