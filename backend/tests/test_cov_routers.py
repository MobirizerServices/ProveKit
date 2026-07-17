"""Coverage-focused router/service tests.

Targets the missing lines in routers/connections, services/otel and the tail ends of
routers/deployments, prompts, flows, runtime, traces. Nothing here hits the network:
httpx and the MCP/a2a/agent provider builders are monkeypatched.
"""
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from agentman.main import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _mock_conn(client) -> dict:
    """The seeded keyless 'Demo Assistant (mock)' llm connection."""
    return next(c for c in client.get("/api/connections").json()
                if c["config"].get("provider") == "mock")


# --------------------------------------------------------------------------- #
# connections: CRUD + masking (_public / has_key) + update preserve
# --------------------------------------------------------------------------- #
def test_connections_crud_and_masking(client):
    # create an llm connection with a real key + secret header + oauth + env
    created = client.post("/api/connections", json={
        "name": "OpenAI-ish", "kind": "llm",
        "config": {
            "provider": "openai", "base_url": "https://api.openai.com/v1",
            "api_key": "sk-supersecretvalue",
            "headers": {"Authorization": "Bearer tok-abc", "X-Public": "plain"},
            "oauth": {"client_id": "cid", "client_secret": "oauth-secret", "token_url": "https://a/t"},
            "env": {"API_TOKEN": "env-secret"},
        },
    }).json()
    cid = created["id"]

    # _public masks the api_key and sets has_key; secret header masked, plain untouched
    cfg = created["config"]
    assert cfg["api_key"].startswith("•") and cfg["has_key"] is True
    assert cfg["headers"]["Authorization"].startswith("•")
    assert cfg["headers"]["X-Public"] == "plain"
    assert cfg["oauth"]["client_secret"].startswith("•")
    assert cfg["oauth"]["client_id"] == "cid"
    assert cfg["env"]["API_TOKEN"].startswith("•")

    # listing round-trips through _public too
    listed = next(x for x in client.get("/api/connections").json() if x["id"] == cid)
    assert listed["config"]["has_key"] is True

    # update echoing the masked values back preserves the stored secrets
    client.put(f"/api/connections/{cid}", json={
        "name": "OpenAI-renamed", "kind": "llm", "config": listed["config"],
    })
    from agentman.database import SessionLocal
    from agentman.models import Connection
    db = SessionLocal()
    try:
        stored = db.get(Connection, cid).config
    finally:
        db.close()
    assert stored["api_key"] == "sk-supersecretvalue"
    assert stored["headers"]["Authorization"] == "Bearer tok-abc"
    assert stored["oauth"]["client_secret"] == "oauth-secret"
    assert stored["env"]["API_TOKEN"] == "env-secret"

    # update with a fresh key overwrites the stored one, and clears has_key echo
    client.put(f"/api/connections/{cid}", json={
        "name": "OpenAI-renamed", "kind": "llm",
        "config": {"provider": "openai", "api_key": "sk-brand-new-key", "has_key": True},
    })
    db = SessionLocal()
    try:
        stored = db.get(Connection, cid).config
    finally:
        db.close()
    assert stored["api_key"] == "sk-brand-new-key" and "has_key" not in stored

    # delete
    assert client.delete(f"/api/connections/{cid}").json() == {"deleted": True}
    assert all(x["id"] != cid for x in client.get("/api/connections").json())
    # deleting again (gone) still returns deleted:True (no-op path)
    assert client.delete(f"/api/connections/{cid}").json() == {"deleted": True}


def test_update_missing_connection_404(client):
    r = client.put("/api/connections/999999", json={"name": "x", "kind": "llm", "config": {}})
    assert r.status_code == 404


# --------------------------------------------------------------------------- #
# connections: POST /{cid}/test  (llm mock / llm http / mcp / a2a / agent)
# --------------------------------------------------------------------------- #
def test_test_connection_llm_mock(client):
    mock = _mock_conn(client)
    r = client.post(f"/api/connections/{mock['id']}/test").json()
    assert r["ok"] is True and "Demo agent" in r["detail"]


def _make(client, name, kind, config):
    return client.post("/api/connections", json={"name": name, "kind": kind, "config": config}).json()


def test_test_connection_llm_no_key_and_no_base(client):
    c = _make(client, "openai-nokey", "llm", {"provider": "openai", "base_url": "https://api.openai.com/v1"})
    assert client.post(f"/api/connections/{c['id']}/test").json()["detail"] == "No API key set"
    # a provider with no default base and no base_url set → "No base URL set"
    c2 = _make(client, "custom-nobase", "llm", {"provider": "custom", "api_key": "k"})
    assert client.post(f"/api/connections/{c2['id']}/test").json()["detail"] == "No base URL set"


def test_test_connection_llm_http_variants(client, monkeypatch):
    import agentman.routers.connections as conn

    captured = {}

    def fake_get(url, headers=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        code = captured.get("code", 200)
        payload = captured.get("json", {"data": [{"id": "m1"}, {"id": "m2"}]})
        return httpx.Response(code, json=payload)

    monkeypatch.setattr(conn.httpx, "get", fake_get)

    # openai with a key → Bearer header, 200 with models → count reported
    c = _make(client, "openai-ok", "llm",
              {"provider": "openai", "base_url": "https://api.openai.com/v1", "api_key": "sk-x"})
    r = client.post(f"/api/connections/{c['id']}/test").json()
    assert r["ok"] is True and "2 models" in r["detail"]
    assert captured["url"].endswith("/models") and captured["headers"]["Authorization"] == "Bearer sk-x"

    # anthropic branch → x-api-key + version header, 200 with empty data → "Authenticated"
    captured["json"] = {"data": []}
    ca = _make(client, "anthropic-ok", "llm", {"provider": "anthropic", "api_key": "ant-key"})
    ra = client.post(f"/api/connections/{ca['id']}/test").json()
    assert ra["ok"] is True and "Authenticated" in ra["detail"]
    assert captured["headers"]["x-api-key"] == "ant-key"
    assert captured["headers"]["anthropic-version"] == "2023-06-01"

    # 401 rejected
    captured["code"] = 401
    r401 = client.post(f"/api/connections/{c['id']}/test").json()
    assert r401["ok"] is False and "401/403" in r401["detail"]

    # some other status code
    captured["code"] = 500
    r500 = client.post(f"/api/connections/{c['id']}/test").json()
    assert r500["ok"] is False and "500" in r500["detail"]


def test_test_connection_mcp(client, monkeypatch):
    import agentman.routers.connections as conn

    class FakeMCP:
        def __init__(self, *a, **k):
            pass

        def list_tools(self):
            return [{"name": "t1"}, {"name": "t2"}]

    monkeypatch.setattr(conn, "MCPSession", FakeMCP)

    # no url and no command → early "No server URL or command set"
    empty = _make(client, "mcp-empty", "mcp", {})
    assert client.post(f"/api/connections/{empty['id']}/test").json() == {
        "ok": False, "detail": "No server URL or command set"}

    # http mcp → tools discovered
    c = _make(client, "mcp-http", "mcp", {"url": "https://mcp.example/mcp"})
    r = client.post(f"/api/connections/{c['id']}/test").json()
    assert r["ok"] is True and "2 tools" in r["detail"]

    # single-tool wording (no plural s)
    monkeypatch.setattr(FakeMCP, "list_tools", lambda self: [{"name": "only"}])
    r1 = client.post(f"/api/connections/{c['id']}/test").json()
    assert "1 tool discovered" in r1["detail"]

    # exception from the provider → caught, ok:False
    def boom(self):
        raise RuntimeError("mcp down")
    monkeypatch.setattr(FakeMCP, "list_tools", boom)
    rb = client.post(f"/api/connections/{c['id']}/test").json()
    assert rb["ok"] is False and "Unreachable" in rb["detail"]


def test_test_connection_a2a(client, monkeypatch):
    from agentman.services.providers import a2a_client

    monkeypatch.setattr(a2a_client, "fetch_card",
                        lambda base, headers=None: {"name": "Booker", "_version": "1.0"})

    # no base_url → early return
    empty = _make(client, "a2a-empty", "a2a", {})
    assert client.post(f"/api/connections/{empty['id']}/test").json()["detail"] == "No base URL set"

    c = _make(client, "a2a-ok", "a2a", {"base_url": "https://agent.example"})
    r = client.post(f"/api/connections/{c['id']}/test").json()
    assert r["ok"] is True and "Booker" in r["detail"] and "A2A 1.0" in r["detail"]


def test_test_connection_agent(client, monkeypatch):
    import agentman.routers.connections as conn
    monkeypatch.setattr(conn.httpx, "get", lambda url, headers=None, timeout=None: httpx.Response(204))

    empty = _make(client, "agent-empty", "agent", {})
    assert client.post(f"/api/connections/{empty['id']}/test").json()["detail"] == "No base URL set"

    c = _make(client, "agent-ok", "agent",
              {"base_url": "https://svc.example", "headers": {"Authorization": "Bearer z"}})
    r = client.post(f"/api/connections/{c['id']}/test").json()
    assert r["ok"] is True and "HTTP 204" in r["detail"]


# --------------------------------------------------------------------------- #
# connections: POST /{cid}/authenticate
# --------------------------------------------------------------------------- #
def test_authenticate_stores_header(client, monkeypatch):
    import agentman.routers.connections as conn

    def fake_request(method, url, json=None, timeout=None):
        assert method == "POST" and url.endswith("/api/auth/login")
        return httpx.Response(200, json={"token": "jwt-token-123456789"},
                              request=httpx.Request(method, url))

    monkeypatch.setattr(conn.httpx, "request", fake_request)

    c = _make(client, "agent-auth", "agent", {"base_url": "https://svc.example"})
    r = client.post(f"/api/connections/{c['id']}/authenticate",
                    json={"body": {"user": "u", "pass": "p"}}).json()
    assert r["ok"] is True and r["header"] == "Authorization"

    # the token is now stored as an Authorization header on the connection
    from agentman.database import SessionLocal
    from agentman.models import Connection
    db = SessionLocal()
    try:
        stored = db.get(Connection, c["id"]).config
    finally:
        db.close()
    assert stored["headers"]["Authorization"] == "Bearer jwt-token-123456789"


def test_authenticate_error_paths(client, monkeypatch):
    import agentman.routers.connections as conn

    # not an agent connection
    llm = _mock_conn(client)
    assert client.post(f"/api/connections/{llm['id']}/authenticate", json={}).status_code == 400

    # agent with no base_url → 400
    nobase = _make(client, "agent-nobase", "agent", {})
    assert client.post(f"/api/connections/{nobase['id']}/authenticate", json={}).status_code == 400

    c = _make(client, "agent-auth2", "agent", {"base_url": "https://svc.example"})

    # login request raises → 502
    def boom(*a, **k):
        raise httpx.ConnectError("refused")
    monkeypatch.setattr(conn.httpx, "request", boom)
    assert client.post(f"/api/connections/{c['id']}/authenticate", json={}).status_code == 502

    # login ok but no token at token_path → 400
    monkeypatch.setattr(conn.httpx, "request",
                        lambda method, url, **k: httpx.Response(200, json={"nope": 1},
                                                                request=httpx.Request(method, url)))
    r = client.post(f"/api/connections/{c['id']}/authenticate", json={"token_path": "token"})
    assert r.status_code == 400 and "No token found" in r.json()["detail"]


# --------------------------------------------------------------------------- #
# connections: GET /{cid}/tools and /{cid}/agent-card
# --------------------------------------------------------------------------- #
def test_list_tools(client, monkeypatch):
    import agentman.routers.connections as conn

    class FakeMCP:
        def __init__(self, *a, **k):
            pass

        def list_tools(self):
            return [{"name": "search"}]

    monkeypatch.setattr(conn, "MCPSession", FakeMCP)

    # wrong kind → 400
    llm = _mock_conn(client)
    assert client.get(f"/api/connections/{llm['id']}/tools").status_code == 400

    # mcp with no url/command → 400
    empty = _make(client, "mcp-empty2", "mcp", {})
    assert client.get(f"/api/connections/{empty['id']}/tools").status_code == 400

    # stdio command variant (exercises the command branch of _mcp_from_cfg)
    c = _make(client, "mcp-stdio", "mcp", {"command": "run-me", "args": ["x"], "env": {"K": "v"}})
    r = client.get(f"/api/connections/{c['id']}/tools").json()
    assert r["tools"] == [{"name": "search"}]

    # provider raises → 502
    def boom(self):
        raise RuntimeError("down")
    monkeypatch.setattr(FakeMCP, "list_tools", boom)
    assert client.get(f"/api/connections/{c['id']}/tools").status_code == 502


def test_agent_card(client, monkeypatch):
    from agentman.services.providers import a2a_client

    # wrong kind → 400
    llm = _mock_conn(client)
    assert client.get(f"/api/connections/{llm['id']}/agent-card").status_code == 400

    # a2a with no base_url → 400
    nobase = _make(client, "a2a-nobase", "a2a", {})
    assert client.get(f"/api/connections/{nobase['id']}/agent-card").status_code == 400

    c = _make(client, "a2a-card", "a2a", {"base_url": "https://agent.example"})
    monkeypatch.setattr(a2a_client, "fetch_card",
                        lambda base, headers=None: {"name": "Booker", "_version": "1.0"})
    r = client.get(f"/api/connections/{c['id']}/agent-card").json()
    assert r["card"]["name"] == "Booker"

    # fetch_card raises → 502
    def boom(*a, **k):
        raise RuntimeError("no card")
    monkeypatch.setattr(a2a_client, "fetch_card", boom)
    assert client.get(f"/api/connections/{c['id']}/agent-card").status_code == 502


def test_connection_not_found_scoping(client):
    assert client.post("/api/connections/999999/test").status_code == 404
    assert client.get("/api/connections/999999/tools").status_code == 404


def test_guard_url_blocked_returns_400(client, monkeypatch):
    """_guard_url turns a BlockedURL from netguard into a 400 for the caller."""
    import agentman.routers.connections as conn
    from agentman.services.netguard import BlockedURL

    def blocked(url):
        raise BlockedURL("blocked host")
    monkeypatch.setattr(conn, "guard_url", blocked)

    c = _make(client, "a2a-blocked", "a2a", {"base_url": "https://internal.local"})
    # /agent-card surfaces the 400 straight from _guard_url
    r = client.get(f"/api/connections/{c['id']}/agent-card")
    assert r.status_code == 400 and "blocked host" in r.json()["detail"]


# --------------------------------------------------------------------------- #
# otel: emit_run
# --------------------------------------------------------------------------- #
class _Run:
    def __init__(self, type="chat", label="lbl", status="completed", result=None):
        self.type = type
        self.label = label
        self.status = status
        self.result = result


def test_emit_run_disabled_without_endpoint(monkeypatch):
    from agentman.config import get_settings
    from agentman.services import otel
    monkeypatch.setattr(get_settings(), "otel_export_url", "")
    # should return early without importing httpx / posting anything
    otel.emit_run(_Run())  # no exception


def test_emit_run_posts_span_with_attrs(monkeypatch):
    import httpx as _httpx
    from agentman.config import get_settings
    from agentman.services import otel

    monkeypatch.setattr(get_settings(), "otel_export_url", "https://collector.example/v1/traces")
    monkeypatch.setattr("agentman.services.netguard.guard_url", lambda u: None)

    posted = {}

    def fake_post(url, json=None, timeout=None, follow_redirects=None):
        posted["url"] = url
        posted["body"] = json
        return _httpx.Response(200)

    monkeypatch.setattr(_httpx, "post", fake_post)

    run = _Run(type="chat", label="hello", status="completed",
               result={"meta": {"provider": "openai", "model": "gpt-4o",
                                 "usage": {"input_tokens": 5, "output_tokens": 3}}})
    otel.emit_run(run)

    span = posted["body"]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
    keys = {a["key"]: a["value"] for a in span["attributes"]}
    assert keys["gen_ai.operation.name"]["stringValue"] == "chat"
    assert keys["gen_ai.provider.name"]["stringValue"] == "openai"
    assert keys["gen_ai.request.model"]["stringValue"] == "gpt-4o"
    assert keys["gen_ai.usage.input_tokens"]["intValue"] == 5
    assert keys["gen_ai.usage.output_tokens"]["intValue"] == 3
    assert span["status"]["code"] == 1  # completed


def test_emit_run_failed_status_and_minimal_meta(monkeypatch):
    import httpx as _httpx
    from agentman.config import get_settings
    from agentman.services import otel

    monkeypatch.setattr(get_settings(), "otel_export_url", "https://collector.example/v1/traces")
    monkeypatch.setattr("agentman.services.netguard.guard_url", lambda u: None)
    posted = {}
    monkeypatch.setattr(_httpx, "post",
                        lambda url, json=None, **k: posted.setdefault("body", json) or _httpx.Response(200))

    # no meta at all → only the operation.name attr, status failed → code 2
    run = _Run(type="tool", label=None, status="failed", result=None)
    otel.emit_run(run)
    span = posted["body"]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
    assert span["name"] == "tool"  # label falls back to type
    assert span["status"]["code"] == 2
    assert len(span["attributes"]) == 1


def test_emit_run_swallows_exceptions(monkeypatch):
    import httpx as _httpx
    from agentman.config import get_settings
    from agentman.services import otel

    monkeypatch.setattr(get_settings(), "otel_export_url", "https://collector.example/v1/traces")
    monkeypatch.setattr("agentman.services.netguard.guard_url", lambda u: None)

    def boom(*a, **k):
        raise _httpx.ConnectError("collector down")
    monkeypatch.setattr(_httpx, "post", boom)
    # best-effort: must NOT raise
    otel.emit_run(_Run(result={"meta": {"model": "m"}}))


# --------------------------------------------------------------------------- #
# prompts: create-dedup + update rename/409 + delete
# --------------------------------------------------------------------------- #
def test_prompts_crud_and_dedup(client):
    # create; key derived from name via _slug
    a = client.post("/api/prompts", json={"name": "My Prompt", "content": "hi"}).json()
    assert a["key"] == "my-prompt"

    # create with same derived key → deduped with -2 suffix
    b = client.post("/api/prompts", json={"name": "My Prompt"}).json()
    assert b["key"] == "my-prompt-2"

    # listing
    keys = [p["key"] for p in client.get("/api/prompts").json()]
    assert "my-prompt" in keys and "my-prompt-2" in keys

    # update content (no rename)
    up = client.put(f"/api/prompts/{a['id']}", json={"name": "My Prompt", "content": "bye"}).json()
    assert up["content"] == "bye"

    # rename onto an existing key → 409
    clash = client.put(f"/api/prompts/{a['id']}",
                       json={"key": "my-prompt-2", "name": "My Prompt"})
    assert clash.status_code == 409

    # rename to a fresh key → ok
    ok = client.put(f"/api/prompts/{a['id']}", json={"key": "renamed", "name": "My Prompt"}).json()
    assert ok["key"] == "renamed"

    # update missing → 404
    assert client.put("/api/prompts/999999", json={"name": "x"}).status_code == 404

    # delete
    assert client.delete(f"/api/prompts/{a['id']}").json() == {"deleted": True}
    assert client.delete("/api/prompts/999999").json() == {"deleted": True}


def test_prompt_slug_empty_fallback(client):
    # a name with no slug-able chars falls back to "prompt"
    p = client.post("/api/prompts", json={"name": "!!!"}).json()
    assert p["key"] == "prompt"


# --------------------------------------------------------------------------- #
# deployments: list / get / runs / stats / deactivate / rollback + 404s
# --------------------------------------------------------------------------- #
def _deploy_flow(client) -> dict:
    conn = _mock_conn(client)
    f = client.post("/api/flows", json={
        "name": "Cov bot",
        "nodes": [
            {"id": "input", "type": "input", "position": {"x": 0, "y": 0}, "data": {}, "config": {}},
            {"id": "ask", "type": "prompt", "position": {"x": 1, "y": 0}, "data": {},
             "config": {"connection_id": conn["id"], "model": "demo-mock", "user": "{{input.question}}"}},
            {"id": "out", "type": "output", "position": {"x": 2, "y": 0}, "data": {}, "config": {"value": "{{ask.text}}"}},
        ],
        "edges": [{"id": "e1", "source": "input", "target": "ask"}, {"id": "e2", "source": "ask", "target": "out"}],
    }).json()
    return client.post("/api/deployments", json={"flow_id": f["id"]}).json()


def test_deployment_list_and_get_and_404s(client):
    dep = _deploy_flow(client)
    slug = dep["slug"]

    listed = client.get("/api/deployments").json()
    row = next(r for r in listed if r["slug"] == slug)
    assert row["versions"] == 1 and row["url"].endswith(f"/v1/d/{slug}")

    got = client.get(f"/api/deployments/{slug}").json()
    assert got["slug"] == slug and len(got["versions"]) == 1

    # 404s across all slug endpoints
    assert client.get("/api/deployments/nope").status_code == 404
    assert client.get("/api/deployments/nope/runs").status_code == 404
    assert client.get("/api/deployments/nope/stats").status_code == 404
    assert client.post("/api/deployments/nope/deactivate").status_code == 404
    assert client.post("/api/deployments/nope/rollback", json={"version": 1}).status_code == 404

    # deploy against a missing flow → 404
    assert client.post("/api/deployments", json={"flow_id": 999999}).status_code == 404


def test_deployment_runs_stats_empty(client):
    dep = _deploy_flow(client)
    slug = dep["slug"]
    # no invocations yet → empty runs, zeroed stats (pct with empty durs → 0)
    assert client.get(f"/api/deployments/{slug}/runs").json() == []
    stats = client.get(f"/api/deployments/{slug}/stats").json()
    assert stats == {"invocations": 0, "failed": 0, "error_rate": 0.0, "p50_ms": 0, "p95_ms": 0}


def test_deployment_rollback_bad_version(client):
    dep = _deploy_flow(client)
    slug = dep["slug"]
    # existing slug but no such version → 404 "Version not found"
    r = client.post(f"/api/deployments/{slug}/rollback", json={"version": 99})
    assert r.status_code == 404 and "Version not found" in r.json()["detail"]


def test_deployment_redeploy_deactivate_rollback_and_stats(client):
    dep = _deploy_flow(client)
    key, slug = dep["api_key"], dep["slug"]
    flow_id = client.get(f"/api/deployments/{slug}").json()["flow_id"]

    # redeploy the same flow → bumps to v2, deactivates the prior active row (47-49)
    dep2 = client.post("/api/deployments", json={"flow_id": flow_id}).json()
    assert dep2["version"] == 2 and "api_key" not in dep2

    # produce runs so stats percentiles use real durations (123)
    for _ in range(4):
        client.post(f"/v1/d/{slug}", headers={"X-API-Key": key}, json={"question": "hi"})
    stats = client.get(f"/api/deployments/{slug}/stats").json()
    assert stats["invocations"] == 4 and stats["p95_ms"] >= 0 and stats["p50_ms"] >= 0

    # rollback to v1 → returns that version, makes it active (150-153)
    rb = client.post(f"/api/deployments/{slug}/rollback", json={"version": 1}).json()
    assert rb["version"] == 1
    assert client.get(f"/api/deployments/{slug}").json()["version"] == 1

    # deactivate all versions (134-137) → invoke now 410
    assert client.post(f"/api/deployments/{slug}/deactivate").json() == {"ok": True}
    assert client.post(f"/v1/d/{slug}", headers={"X-API-Key": key}, json={}).status_code == 410


# --------------------------------------------------------------------------- #
# flows: node-types, from-template, export, run/stream, continue/stream
# --------------------------------------------------------------------------- #
def test_flow_node_types(client):
    nt = client.get("/api/flows/node-types").json()
    assert isinstance(nt, dict) and nt


def test_flow_list_templates_and_crud(client):
    # searchable template gallery (line 40)
    tpl = client.get("/api/flows/templates?q=banking&limit=5").json()
    assert tpl["total"] and "items" in tpl and "categories" in tpl

    # create → list (79) → update (115-119) → delete (124-127)
    f = client.post("/api/flows", json={"name": "CRUD flow", "nodes": [], "edges": []}).json()
    listed = client.get("/api/flows").json()
    assert any(x["id"] == f["id"] for x in listed)

    up = client.put(f"/api/flows/{f['id']}",
                    json={"name": "CRUD flow v2", "description": "d",
                          "nodes": [{"id": "input", "type": "input", "config": {}}], "edges": []}).json()
    assert up["name"] == "CRUD flow v2" and up["description"] == "d"

    # update missing → 404
    assert client.put("/api/flows/999999", json={"name": "x"}).status_code == 404

    assert client.delete(f"/api/flows/{f['id']}").json() == {"deleted": True}
    assert client.delete("/api/flows/999999").json() == {"deleted": True}  # no-op path


def test_flow_from_template_and_export(client):
    from agentman.services import templates
    slug = next(it["slug"] for it in templates.search("", 20)
                if (templates.load(it["slug"]) or {}).get("kind") == "flow")
    f = client.post("/api/flows/from-template", json={"slug": slug}).json()
    assert f["id"] and f["nodes"]

    # export returns the round-trippable text file
    exp = client.get(f"/api/flows/{f['id']}/export")
    assert exp.status_code == 200 and exp.text

    # unknown template → 404
    assert client.post("/api/flows/from-template", json={"slug": "does-not-exist"}).status_code == 404


def test_flow_get_404_and_export_404(client):
    assert client.get("/api/flows/999999").status_code == 404
    assert client.get("/api/flows/999999/export").status_code == 404


def test_flow_run_stream(client):
    conn = _mock_conn(client)
    f = client.post("/api/flows", json={
        "name": "Streamer",
        "nodes": [
            {"id": "input", "type": "input", "position": {"x": 0, "y": 0}, "data": {}, "config": {}},
            {"id": "ask", "type": "prompt", "position": {"x": 1, "y": 0}, "data": {},
             "config": {"connection_id": conn["id"], "model": "demo-mock", "user": "{{input.question}}"}},
            {"id": "out", "type": "output", "position": {"x": 2, "y": 0}, "data": {}, "config": {"value": "{{ask.text}}"}},
        ],
        "edges": [{"id": "e1", "source": "input", "target": "ask"}, {"id": "e2", "source": "ask", "target": "out"}],
    }).json()

    with client.stream("POST", f"/api/flows/{f['id']}/run/stream",
                       json={"input": {"question": "hello"}}) as r:
        assert r.status_code == 200
        body = "".join(r.iter_text())
    assert "[DONE]" in body

    # continue on an expired/unknown run_id → 409
    c409 = client.post(f"/api/flows/{f['id']}/continue/stream",
                       json={"run_id": "nope", "node_id": "ask"})
    assert c409.status_code == 409


def test_flow_continue_stream_resumes(client):
    conn = _mock_conn(client)
    f = client.post("/api/flows", json={
        "name": "Breakpointed",
        "nodes": [
            {"id": "input", "type": "input", "position": {"x": 0, "y": 0}, "data": {}, "config": {}},
            {"id": "ask", "type": "prompt", "position": {"x": 1, "y": 0}, "data": {},
             "config": {"connection_id": conn["id"], "model": "demo-mock", "user": "{{input.question}}"}},
            {"id": "out", "type": "output", "position": {"x": 2, "y": 0}, "data": {}, "config": {"value": "{{ask.text}}"}},
        ],
        "edges": [{"id": "e1", "source": "input", "target": "ask"}, {"id": "e2", "source": "ask", "target": "out"}],
    }).json()

    # break before 'ask' so the run pauses and stashes a resumable ctx
    run_id = None
    with client.stream("POST", f"/api/flows/{f['id']}/run/stream",
                       json={"input": {"question": "hi"}, "breakpoints": ["ask"]}) as r:
        assert r.status_code == 200
        for line in r.iter_lines():
            if not line or not line.startswith("data: ") or line == "data: [DONE]":
                continue
            ev = json.loads(line[len("data: "):])
            run_id = run_id or ev.get("run_id")
            if ev.get("type") in ("paused", "breakpoint"):
                run_id = ev.get("run_id", run_id)
    assert run_id, "expected a run_id from the paused stream"

    with client.stream("POST", f"/api/flows/{f['id']}/continue/stream",
                       json={"run_id": run_id, "node_id": "ask"}) as r:
        assert r.status_code == 200
        body = "".join(r.iter_text())
    assert "[DONE]" in body


def test_flow_max_nodes_guard(client, monkeypatch):
    from agentman.config import get_settings
    monkeypatch.setattr(get_settings(), "max_flow_nodes", 1)
    r = client.post("/api/flows", json={"name": "big", "nodes": [{"id": "a"}, {"id": "b"}], "edges": []})
    assert r.status_code == 400 and "too large" in r.json()["detail"]


# --------------------------------------------------------------------------- #
# runtime: public invoke edge cases (410 for deactivated, 404 unknown, rate limit)
# --------------------------------------------------------------------------- #
def test_runtime_rate_limit(client, monkeypatch):
    from agentman.config import get_settings
    dep = _deploy_flow(client)
    monkeypatch.setattr(get_settings(), "rate_limit_per_min", 1)
    key, slug = dep["api_key"], dep["slug"]
    first = client.post(f"/v1/d/{slug}", headers={"X-API-Key": key}, json={"question": "hi"})
    assert first.status_code == 200
    second = client.post(f"/v1/d/{slug}", headers={"X-API-Key": key}, json={"question": "hi"})
    assert second.status_code == 429


def test_runtime_invalid_json_body(client):
    dep = _deploy_flow(client)
    # send a non-JSON body → parsing swallowed, treated as {} and still runs
    r = client.post(
        f"/v1/d/{dep['slug']}",
        headers={"X-API-Key": dep["api_key"], "Content-Type": "application/json"},
        content=b"not json",
    )
    assert r.status_code == 200


def test_runtime_stream(client):
    dep = _deploy_flow(client)
    with client.stream("POST", f"/v1/d/{dep['slug']}?stream=1",
                       headers={"X-API-Key": dep["api_key"]}, json={"question": "hi"}) as r:
        assert r.status_code == 200
        body = "".join(r.iter_text())
    assert "[DONE]" in body


def test_runtime_resolve_410_and_404(client):
    dep = _deploy_flow(client)
    key, slug = dep["api_key"], dep["slug"]
    # deactivate → slug exists but no active row → 410 (lines 31-32, 34)
    client.post(f"/api/deployments/{slug}/deactivate")
    assert client.post(f"/v1/d/{slug}", headers={"X-API-Key": key}, json={}).status_code == 410
    # never existed → 404
    assert client.post("/v1/d/never-existed", headers={"X-API-Key": key}, json={}).status_code == 404


def test_runtime_bad_key_403(client):
    dep = _deploy_flow(client)
    # active deployment, wrong/missing key → 403 (line 34)
    assert client.post(f"/v1/d/{dep['slug']}", json={}).status_code == 403
    assert client.post(f"/v1/d/{dep['slug']}", headers={"X-API-Key": "agm_bad"}, json={}).status_code == 403


def test_runtime_rate_limit_disabled(client, monkeypatch):
    from agentman.config import get_settings
    monkeypatch.setattr(get_settings(), "rate_limit_per_min", 0)  # disabled → _rate_ok True (line 41)
    dep = _deploy_flow(client)
    r = client.post(f"/v1/d/{dep['slug']}", headers={"X-API-Key": dep["api_key"]}, json={"question": "hi"})
    assert r.status_code == 200


def test_runtime_timeout(client, monkeypatch):
    """Snapshot run exceeding the deployment timeout → 504, run persisted as failed (87-99)."""
    import anyio
    from agentman.config import get_settings
    from agentman.services import deploy as deploy_svc

    dep = _deploy_flow(client)
    monkeypatch.setattr(get_settings(), "deployment_timeout_s", 0.05)

    async def _slow(session, snapshot, flow_input, workspace_id, stream=False):
        await anyio.sleep(0.5)
        yield {"type": "done", "status": "completed"}
    monkeypatch.setattr(deploy_svc, "run_snapshot", _slow)

    r = client.post(f"/v1/d/{dep['slug']}", headers={"X-API-Key": dep["api_key"]}, json={})
    assert r.status_code == 504 and "timeout" in r.json()["detail"]


# --------------------------------------------------------------------------- #
# traces: invalid JSON body path
# --------------------------------------------------------------------------- #
def test_traces_invalid_json(client):
    r = client.post("/v1/traces", headers={"Content-Type": "application/json"}, content=b"{not json")
    assert r.status_code == 200
    assert r.json()["partialSuccess"]["errorMessage"] == "invalid JSON"


def test_traces_bad_bearer_key(client):
    bare = TestClient(app)
    bare.cookies.clear()
    r = bare.post("/v1/traces", json={"resourceSpans": []},
                  headers={"Authorization": "Bearer agm_wrong"})
    assert r.status_code == 403  # line 28/29 invalid ingest key


def _otlp_span(model="gpt-4o", completion="ok"):
    return {"resourceSpans": [{"scopeSpans": [{"spans": [{
        "name": "chat",
        "startTimeUnixNano": "1000000000", "endTimeUnixNano": "1500000000",
        "status": {"code": 1},
        "attributes": [
            {"key": "gen_ai.request.model", "value": {"stringValue": model}},
            {"key": "gen_ai.completion", "value": {"stringValue": completion}},
        ],
    }]}]}]}


def test_traces_ingest_persists_via_bearer_key(client):
    # mint a workspace ingest key (rotate_ingest_key, lines 62-65)
    key = client.post("/api/workspace/ingest-key").json()["ingest_key"]
    assert key.startswith("agm_")

    bare = TestClient(app)
    bare.cookies.clear()
    before = len(client.get("/api/runs?limit=100").json())
    # ingest via bearer key → persists gen_ai spans (lines 42-52)
    r = bare.post("/v1/traces", json=_otlp_span(),
                  headers={"Authorization": f"Bearer {key}"})
    assert r.status_code == 200 and r.json()["partialSuccess"] == {}
    assert len(client.get("/api/runs?limit=100").json()) == before + 1


def test_traces_ingest_via_session_cookie(client):
    # no bearer → falls back to the session cookie path
    before = len(client.get("/api/runs?limit=100").json())
    r = client.post("/v1/traces", json=_otlp_span(completion="hey"))
    assert r.status_code == 200
    assert len(client.get("/api/runs?limit=100").json()) == before + 1


# --------------------------------------------------------------------------- #
# otel: ingest / map_span (direct, so this file is self-sufficient for otel.py)
# --------------------------------------------------------------------------- #
def test_otel_ingest_maps_genai_span():
    from agentman.services import otel
    rows = otel.ingest(_otlp_span(model="claude", completion="done"))
    assert len(rows) == 1 and rows[0]["result"]["meta"]["model"] == "claude"
    assert rows[0]["result"]["text"] == "done" and rows[0]["status"] == "completed"


def test_otel_ingest_ignores_non_genai():
    from agentman.services import otel
    span = {"resourceSpans": [{"scopeSpans": [{"spans": [{
        "name": "GET /x", "attributes": [{"key": "http.method", "value": {"stringValue": "GET"}}]}]}]}]}
    assert otel.ingest(span) == []


def test_otel_attr_value_types_and_failed_status():
    from agentman.services import otel
    span = {
        "name": "tool", "startTimeUnixNano": "0", "endTimeUnixNano": "0",
        "status": {"code": 2, "message": "boom"},
        "attributes": [
            {"key": "gen_ai.request.model", "value": {"stringValue": "m"}},
            {"key": "gen_ai.operation.name", "value": {"stringValue": "execute_tool"}},
            {"key": "gen_ai.tool.name", "value": {"stringValue": "search"}},  # meta['tool'] (94)
            {"key": "gen_ai.usage.input_tokens", "value": {"intValue": "9"}},
            {"key": "gen_ai.usage.output_tokens", "value": {"intValue": "4"}},  # usage out (83)
            {"key": "flag", "value": {"boolValue": True}},
            {"key": "ratio", "value": {"doubleValue": 1.5}},
            # non-string message → _as_text json.dumps path (57-60)
            {"key": "gen_ai.output.messages", "value": {"arrayValue": {"values": [{"stringValue": "a"}]}}},
            {"key": "kv", "value": {"kvlistValue": {"values": [{"key": "k", "value": {"stringValue": "v"}}]}}},
            {"key": "unknown", "value": {"bytesValue": "x"}},  # _attr_value → None (38)
        ],
    }
    row = otel.map_span(span)
    assert row["status"] == "failed" and row["error"] == "boom"
    assert row["result"]["meta"]["usage"] == {"input_tokens": 9, "output_tokens": 4}
    assert row["result"]["meta"]["tool"] == "search"
    # completion was an array → json-serialized text
    assert row["result"]["text"] == json.dumps(["a"])


def test_otel_as_text_unserializable():
    from agentman.services import otel
    # a value json.dumps can't handle exercises the except branch → str() fallback
    assert otel._as_text({1, 2}) == str({1, 2})
