"""Named pk_ API keys: create (plaintext once) → list (never leaks plaintext) →
authenticate an ingest request → revoke → rejected."""
from fastapi.testclient import TestClient

from provekit.main import app


def _client():
    return TestClient(app, base_url="https://testserver")


def test_create_returns_plaintext_once_and_list_never_leaks_it():
    c = _client()
    created = c.post("/api/api-keys", json={"name": "ci"}).json()
    assert created["key"].startswith("pk_")
    assert created["name"] == "ci"
    assert created["prefix"] and created["key"].startswith(created["prefix"])

    listed = c.get("/api/api-keys").json()
    row = next(k for k in listed if k["id"] == created["id"])
    assert "key" not in row                      # plaintext is never retrievable again
    assert row["prefix"] == created["prefix"]
    assert row["revoked"] is False


def test_key_authenticates_trace_ingest():
    c = _client()
    key = c.post("/api/api-keys", json={"name": "tracer"}).json()["key"]
    # Auth is resolved before the body is parsed; a valid key → 200 regardless of payload.
    r = c.post("/v1/traces", json={"resourceSpans": []},
               headers={"Authorization": f"Bearer {key}"})
    assert r.status_code == 200


def test_revoked_key_is_rejected():
    c = _client()
    created = c.post("/api/api-keys", json={"name": "temp"}).json()
    key = created["key"]
    assert c.delete(f"/api/api-keys/{created['id']}").json()["ok"] is True

    r = c.post("/v1/traces", json={"resourceSpans": []},
               headers={"Authorization": f"Bearer {key}"})
    assert r.status_code == 403

    row = next(k for k in c.get("/api/api-keys").json() if k["id"] == created["id"])
    assert row["revoked"] is True                # soft-revoked: row (and history) survives


def test_unknown_key_is_rejected():
    c = _client()
    r = c.post("/v1/traces", json={"resourceSpans": []},
               headers={"Authorization": "Bearer pk_not-a-real-key"})
    assert r.status_code == 403


def test_revoke_across_workspace_is_404():
    c = _client()
    # A key id that doesn't exist in this workspace must 404, never reveal/act on it.
    assert c.delete("/api/api-keys/999999").status_code == 404
