"""Connection secrets beyond api_key/headers: MCP OAuth client_secret and stdio env
values must be encrypted at rest (seal_config) and masked in API responses (_public),
and must survive an edit that echoes the masked values back (update preserve)."""
from fastapi.testclient import TestClient

from agentman.main import app
from agentman.services.masking import MASK
from agentman.services.sealing import _PREFIX, seal_config, unseal_config


def test_seal_config_round_trips_oauth_and_env():
    cfg = {
        "url": "https://mcp.example/mcp",
        "oauth": {"client_id": "id", "client_secret": "super-secret", "token_url": "https://a/t"},
        "env": {"API_TOKEN": "tok-123", "MODE": "prod"},
    }
    sealed = seal_config(cfg)
    # The secret-bearing values are encrypted at rest. env values are opaque process
    # credentials, so every one is sealed (not just known-secret keys).
    assert sealed["oauth"]["client_secret"].startswith(_PREFIX)
    assert sealed["env"]["API_TOKEN"].startswith(_PREFIX)
    assert sealed["env"]["MODE"].startswith(_PREFIX)
    # Named non-secret siblings of oauth are left intact...
    assert sealed["oauth"]["client_id"] == "id"
    # ...and unseal restores the exact plaintext the application sees.
    assert unseal_config(sealed) == cfg


def test_api_masks_and_preserves_oauth_and_env():
    c = TestClient(app, base_url="https://testserver")
    created = c.post("/api/connections", json={"name": "MCP", "kind": "mcp", "config": {
        "url": "https://mcp.example/mcp",
        "oauth": {"client_id": "id", "client_secret": "super-secret", "token_url": "https://a/t"},
        "env": {"API_TOKEN": "tok-123"},
    }}).json()
    cid = created["id"]

    # The listing must never return the real secrets.
    got = next(x for x in c.get("/api/connections").json() if x["id"] == cid)
    assert got["config"]["oauth"]["client_secret"].startswith(MASK)
    assert got["config"]["env"]["API_TOKEN"].startswith(MASK)
    assert got["config"]["oauth"]["client_id"] == "id"  # non-secret preserved

    # Re-saving the masked payload (what the UI holds) must not clobber the stored secrets.
    c.put(f"/api/connections/{cid}", json={"name": "MCP", "kind": "mcp",
                                           "config": got["config"]})
    # Prove the real values still dispatch: unseal the stored config directly.
    from agentman.database import SessionLocal
    from agentman.models import Connection
    db = SessionLocal()
    try:
        stored = db.get(Connection, cid).config  # SealedJSON unseals on read
    finally:
        db.close()
    assert stored["oauth"]["client_secret"] == "super-secret"
    assert stored["env"]["API_TOKEN"] == "tok-123"
