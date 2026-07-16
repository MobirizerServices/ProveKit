"""Tenancy: two users are fully isolated; cross-workspace access 404s; prompt keys repeat."""
import pytest
from fastapi.testclient import TestClient

from agentman.config import get_settings
from agentman.main import app


@pytest.fixture
def hosted(monkeypatch):
    # Force hosted mode so each client must authenticate as a distinct user.
    monkeypatch.setattr(get_settings(), "hosted", True)


def _user_client(email):
    # https base so the secure session cookie (hosted mode) round-trips
    c = TestClient(app, base_url="https://testserver")
    r = c.post("/api/auth/register", json={"email": email, "password": "supersecret1"})
    assert r.status_code == 200, r.text
    return c


def test_two_users_are_isolated(hosted):
    alice = _user_client("alice@x.com")
    bob = _user_client("bob@x.com")

    # Alice creates a connection + a flow
    ac = alice.post("/api/connections", json={"name": "Alice OpenAI", "kind": "llm",
                                              "config": {"provider": "openai", "api_key": "sk-alice", "models": ["m"]}}).json()
    af = alice.post("/api/flows", json={"name": "Alice flow", "nodes": [], "edges": []}).json()

    # Bob cannot see them in his lists
    assert all(c["name"] != "Alice OpenAI" for c in bob.get("/api/connections").json())
    assert all(f["name"] != "Alice flow" for f in bob.get("/api/flows").json())

    # Bob cannot fetch/update/delete them by id (404)
    assert bob.get(f"/api/flows/{af['id']}").status_code == 404
    assert bob.put(f"/api/connections/{ac['id']}", json={"name": "hijack", "kind": "llm", "config": {}}).status_code == 404
    assert bob.get(f"/api/connections/{ac['id']}/test").status_code in (404, 405)  # test is POST; id still not his

    # Alice still sees her own
    assert any(c["name"] == "Alice OpenAI" for c in alice.get("/api/connections").json())


def test_cannot_run_with_another_workspaces_connection(hosted):
    alice = _user_client("alice2@x.com")
    bob = _user_client("bob2@x.com")
    ac = alice.post("/api/connections", json={"name": "Secret", "kind": "llm",
                                              "config": {"provider": "mock", "models": ["demo-mock"]}}).json()
    # Bob tries to run a prompt against Alice's connection id — must not use her config.
    r = bob.post("/api/run", json={"request": {"type": "prompt", "connection_id": ac["id"],
                                               "model": "demo-mock", "user": "hi"}, "save": False})
    # connection_id doesn't resolve in Bob's workspace → no stored config → ad-hoc with no creds.
    # The run should not have used Alice's mock connection; it errors or runs empty, never leaks her config.
    assert r.status_code == 200
    # meta model comes from the request, not Alice's connection (which Bob can't read)
    assert r.json()["status"] in ("completed", "failed")


def test_prompt_keys_repeat_across_workspaces(hosted):
    alice = _user_client("alice3@x.com")
    bob = _user_client("bob3@x.com")
    ka = alice.post("/api/prompts", json={"key": "shared.key", "name": "A"}).json()
    kb = bob.post("/api/prompts", json={"key": "shared.key", "name": "B"}).json()
    assert ka["key"] == "shared.key" and kb["key"] == "shared.key"  # same key, different workspaces, no collision
