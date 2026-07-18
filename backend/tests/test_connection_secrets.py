"""Connection secrets beyond api_key/headers: MCP OAuth client_secret and stdio env
values must be encrypted at rest (seal_config) and masked in API responses (_public),
and must survive an edit that echoes the masked values back (update preserve)."""
from fastapi.testclient import TestClient

from provekit.main import app
from provekit.services.masking import MASK
from provekit.services.sealing import _PREFIX, seal_config, unseal_config


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
    from provekit.database import SessionLocal
    from provekit.models import Connection
    db = SessionLocal()
    try:
        stored = db.get(Connection, cid).config  # SealedJSON unseals on read
    finally:
        db.close()
    assert stored["oauth"]["client_secret"] == "super-secret"
    assert stored["env"]["API_TOKEN"] == "tok-123"


def _stored_config(cid: int) -> dict:
    from provekit.database import SessionLocal
    from provekit.models import Connection
    db = SessionLocal()
    try:
        return db.get(Connection, cid).config  # SealedJSON unseals on read
    finally:
        db.close()


def test_renaming_an_env_key_drops_the_mask_instead_of_storing_it():
    """A masked value is a placeholder, never a credential.

    Renaming an env key in the UI (without retyping its value) sends the mask under a key
    that has no stored counterpart. Defaulting to the sent value would seal the literal
    "••••n123" as the credential, and the MCP process would fail with a garbage token.
    """
    c = TestClient(app, base_url="https://testserver")
    cid = c.post("/api/connections", json={"name": "Stdio", "kind": "mcp", "config": {
        "command": "srv", "env": {"API_TOKEN": "tok-123", "MODE": "prod"},
    }}).json()["id"]
    masked = next(x for x in c.get("/api/connections").json() if x["id"] == cid)["config"]

    # rename API_TOKEN -> TOKEN, echoing back the mask the UI is displaying
    renamed = {"TOKEN": masked["env"]["API_TOKEN"], "MODE": masked["env"]["MODE"]}
    c.put(f"/api/connections/{cid}", json={"name": "Stdio", "kind": "mcp",
                                          "config": {**masked, "env": renamed}})

    stored = _stored_config(cid)
    assert not any(str(v).startswith(MASK) for v in stored["env"].values()), \
        f"a mask was persisted as a credential: {stored['env']}"
    assert "TOKEN" not in stored["env"]  # unrecoverable → dropped, so the user retypes it
    assert stored["env"]["MODE"] == "prod"  # the unchanged key still round-trips


def test_creating_a_connection_never_stores_a_masked_value():
    """Duplicating a connection round-trips a GET response into POST; masks must not stick."""
    c = TestClient(app, base_url="https://testserver")
    cid = c.post("/api/connections", json={"name": "Orig", "kind": "mcp", "config": {
        "url": "https://mcp.example/mcp",
        "oauth": {"client_id": "id", "client_secret": "super-secret", "token_url": "https://a/t"},
        "env": {"API_TOKEN": "tok-123"},
    }}).json()["id"]
    masked = next(x for x in c.get("/api/connections").json() if x["id"] == cid)["config"]

    dup = c.post("/api/connections", json={"name": "Copy", "kind": "mcp", "config": masked}).json()
    stored = _stored_config(dup["id"])
    assert stored["oauth"]["client_secret"] == ""       # blanked, not the mask
    assert not stored["env"]                            # dropped, not the mask
    assert stored["url"] == "https://mcp.example/mcp"   # non-secrets still copied
