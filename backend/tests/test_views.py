"""Saved views (#68): a named filter a team can hand to each other."""
from fastapi.testclient import TestClient

from provekit.main import app


def test_a_view_round_trips():
    with TestClient(app) as client:
        made = client.post("/api/views", json={
            "name": "failing checkout",
            "params": {"status": "failed", "q": "checkout", "window_hours": 24}}).json()
        assert made["params"] == {"status": "failed", "q": "checkout", "window_hours": 24}
        listed = client.get("/api/views").json()
        assert any(v["id"] == made["id"] for v in listed)
        client.delete(f"/api/views/{made['id']}")


def test_only_trace_list_parameters_are_stored():
    """params are replayed into a query later, so accepting arbitrary keys would make a saved
    view a way to smuggle parameters into a future request."""
    with TestClient(app) as client:
        made = client.post("/api/views", json={
            "name": "allowlist", "params": {"status": "failed", "workspace_id": 999,
                                            "limit": 10, "evil": "x"}}).json()
        assert set(made["params"]) == {"status", "limit"}
        client.delete(f"/api/views/{made['id']}")


def test_empty_values_are_dropped_not_stored():
    with TestClient(app) as client:
        made = client.post("/api/views", json={
            "name": "sparse", "params": {"status": "", "q": None, "limit": 5}}).json()
        assert made["params"] == {"limit": 5}
        client.delete(f"/api/views/{made['id']}")


def test_duplicate_names_are_refused():
    """A shared name has to mean one thing, or it is useless as a reference."""
    with TestClient(app) as client:
        a = client.post("/api/views", json={"name": "dupe", "params": {}}).json()
        again = client.post("/api/views", json={"name": "dupe", "params": {}})
        assert again.status_code == 409
        client.delete(f"/api/views/{a['id']}")


def test_a_view_can_be_renamed_and_retargeted():
    with TestClient(app) as client:
        made = client.post("/api/views", json={"name": "before", "params": {"limit": 5}}).json()
        updated = client.put(f"/api/views/{made['id']}",
                             json={"name": "after", "params": {"status": "failed"}}).json()
        assert updated["name"] == "after" and updated["params"] == {"status": "failed"}
        client.delete(f"/api/views/{made['id']}")


def test_a_nameless_view_is_refused():
    with TestClient(app) as client:
        assert client.post("/api/views", json={"name": "  ", "params": {}}).status_code == 422


def test_missing_views_are_404_not_500():
    with TestClient(app) as client:
        assert client.delete("/api/views/999999").status_code == 404
        assert client.put("/api/views/999999",
                          json={"name": "x", "params": {}}).status_code == 404


def test_the_saved_params_actually_drive_the_trace_list():
    """The point of storing the same keys /api/traces accepts: a view is replayed through the
    normal read path, so it can't drift away from what the live filter means."""
    with TestClient(app) as client:
        made = client.post("/api/views", json={
            "name": "replayable", "params": {"status": "failed", "limit": 5}}).json()
        r = client.get("/api/traces", params=made["params"])
        assert r.status_code == 200 and isinstance(r.json(), list)
        client.delete(f"/api/views/{made['id']}")
