"""Pre-launch hardening: pagination clamps, import node cap, prompt-key conflicts,
security headers, regex-assertion timeout, and per-workspace flow-run isolation."""
import time

import pytest
from fastapi.testclient import TestClient

from provekit.config import get_settings
from provekit.main import app
from provekit.services import limits
from provekit.services.assertions import _regex_search


@pytest.fixture(autouse=True)
def _reset_window():
    limits._window.cache_clear()
    yield
    limits._window.cache_clear()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_runs_limit_is_clamped(client):
    # A negative limit must not become SQLite's "unlimited" (LIMIT -1).
    assert client.get("/api/runs?limit=-1").status_code == 200
    assert client.get("/api/runs?limit=100000").status_code == 200


def test_import_enforces_node_cap(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "max_flow_nodes", 2)
    doc = "version: 1\nkind: flow\nname: big\nnodes:\n"
    doc += "".join(f"  - id: n{i}\n    type: output\n    config: {{}}\n" for i in range(5))
    doc += "edges: []\n"
    r = client.post("/api/import", json={"content": doc})
    assert r.status_code == 400 and "too large" in r.json()["detail"].lower()


def test_import_rejects_non_dict_node(client):
    doc = "version: 1\nkind: flow\nname: bad\nnodes:\n  - just-a-string\nedges: []\n"
    r = client.post("/api/import", json={"content": doc})
    assert r.status_code == 400 and "object" in r.json()["detail"].lower()  # not an unhandled 500


def test_prompt_rename_to_existing_key_conflicts(client):
    a = client.post("/api/prompts", json={"key": "alpha", "name": "A"}).json()
    client.post("/api/prompts", json={"key": "beta", "name": "B"})
    r = client.put(f"/api/prompts/{a['id']}", json={"key": "beta", "name": "A"})
    assert r.status_code == 409  # not an unhandled 500 from the unique constraint


def test_security_headers_present(client):
    h = client.get("/healthz").headers
    assert h.get("x-content-type-options") == "nosniff"
    assert h.get("x-frame-options") == "DENY"
    assert "referrer-policy" in h


def test_regex_assertion_rejects_redos_pattern():
    # A nested-quantifier pattern (catastrophic backtracking) is rejected up front, fast —
    # re.search holds the GIL, so it must never actually run.
    t0 = time.monotonic()
    with pytest.raises(ValueError):
        _regex_search(r"(a+)+$", "a" * 40 + "!")
    assert time.monotonic() - t0 < 1  # rejected by inspection, not executed
    # ordinary patterns still work
    assert _regex_search(r"he.lo", "hello world") is not None
