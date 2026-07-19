"""Multiple projects: CRUD, membership, and X-Project-Id switching (tenant isolation)."""
import uuid

from fastapi.testclient import TestClient

from provekit.main import app


def _client():
    return TestClient(app, base_url="https://testserver")


def _register(c) -> str:
    email = f"u{uuid.uuid4().hex[:10]}@ex.com"
    assert c.post("/api/auth/register", json={"email": email, "password": "pw12345678"}).status_code == 200
    return email


def _root_span(trace):
    return {"name": "agent", "traceId": trace, "spanId": "r", "parentSpanId": "",
            "startTimeUnixNano": "1000000000", "endTimeUnixNano": "1500000000", "status": {"code": 1},
            "attributes": [{"key": "gen_ai.operation.name", "value": {"stringValue": "invoke_agent"}}]}


def test_create_list_rename_delete():
    c = _client()
    before = {p["id"] for p in c.get("/api/projects").json()}
    p = c.post("/api/projects", json={"name": "Alpha"}).json()
    assert p["role"] == "owner"
    ids = {x["id"]: x for x in c.get("/api/projects").json()}
    assert p["id"] in ids and any(x["is_default"] for x in ids.values())
    assert c.patch(f"/api/projects/{p['id']}", json={"name": "Alpha-2"}).json()["name"] == "Alpha-2"
    assert c.delete(f"/api/projects/{p['id']}").json()["ok"] is True
    after = {x["id"] for x in c.get("/api/projects").json()}
    assert p["id"] not in after and before <= after


def test_x_project_id_isolates_data():
    c = _client()
    p = c.post("/api/projects", json={"name": "Scoped"}).json()
    hdr = {"X-Project-Id": str(p["id"])}
    # a key minted under the project belongs to it; ingest with it lands in the project
    key = c.post("/api/api-keys", json={"name": "k"}, headers=hdr).json()["key"]
    c.post("/v1/traces", headers={"Authorization": f"Bearer {key}"},
           json={"resourceSpans": [{"scopeSpans": [{"spans": [_root_span("t-scoped")]}]}]})
    # visible when the project is selected…
    assert any(t["trace_id"] == "t-scoped" for t in c.get("/api/traces", headers=hdr).json())
    # …and NOT in the default project
    assert not any(t["trace_id"] == "t-scoped" for t in c.get("/api/traces").json())


def test_members_add_list_remove():
    owner = _client()                       # the local user owns the project
    other = _client()
    other_email = _register(other)
    p = owner.post("/api/projects", json={"name": "Team"}).json()

    added = owner.post(f"/api/projects/{p['id']}/members", json={"email": other_email}).json()
    assert added["role"] == "member"
    assert len(owner.get(f"/api/projects/{p['id']}/members").json()) == 2
    # the invited user now sees the project
    assert any(x["id"] == p["id"] for x in other.get("/api/projects").json())
    # remove them
    assert owner.delete(f"/api/projects/{p['id']}/members/{added['user_id']}").json()["ok"] is True
    assert len(owner.get(f"/api/projects/{p['id']}/members").json()) == 1


def test_guards():
    owner = _client()
    p = owner.post("/api/projects", json={"name": "Guarded"}).json()
    # unknown email → 404
    assert owner.post(f"/api/projects/{p['id']}/members", json={"email": "nobody@ex.com"}).status_code == 404
    # a different (registered) user is not a member → project is hidden (404) on mutate
    stranger = _client()
    _register(stranger)
    assert stranger.patch(f"/api/projects/{p['id']}", json={"name": "x"}).status_code == 404
    # can't remove the last owner (the local user themselves)
    me = next(m for m in owner.get(f"/api/projects/{p['id']}/members").json() if m["role"] == "owner")
    assert owner.delete(f"/api/projects/{p['id']}/members/{me['user_id']}").status_code == 400
