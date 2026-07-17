"""Flow template gallery: search + create-from-template."""
from fastapi.testclient import TestClient

from agentman.main import app
from agentman.services import templates


def test_manifest_loaded():
    assert templates.total() > 100
    assert templates.categories()  # non-empty facet list


def test_search_filters():
    with TestClient(app) as c:
        r = c.get("/api/flows/templates?q=triage&limit=5").json()
        assert r["total"] > 100 and 0 < len(r["items"]) <= 5
        assert all("triage" in (i["name"] + i["description"] + i["category"]).lower() for i in r["items"])
        # empty query returns the (capped) gallery
        assert len(c.get("/api/flows/templates?limit=10").json()["items"]) == 10


def test_create_from_template_resolves_connection():
    with TestClient(app) as c:
        # pick any template and instantiate it
        slug = c.get("/api/flows/templates?q=answer&limit=1").json()["items"][0]["slug"]
        f = c.post("/api/flows/from-template", json={"slug": slug}).json()
        assert f["id"] and f["nodes"]
        # the prompt node's connection name resolved to the seeded mock connection id
        prompt = next((n for n in f["nodes"] if n["type"] == "prompt"), None)
        assert prompt and prompt["config"].get("connection_id")
        # and it runs
        run = c.post(f"/api/flows/{f['id']}/run/stream", json={"input": {}})
        assert any('"status": "completed"' in l for l in run.text.splitlines() if '"done"' in l)


def test_unknown_and_traversal_rejected():
    with TestClient(app) as c:
        assert c.post("/api/flows/from-template", json={"slug": "nope-nope"}).status_code == 404
        assert c.post("/api/flows/from-template", json={"slug": "../../etc/passwd"}).status_code == 404
