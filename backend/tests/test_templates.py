"""Flow template gallery: search + create-from-template."""
from fastapi.testclient import TestClient

from provekit.main import app
from provekit.services import templates


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


def test_featured_showcase():
    """The curated featured set is a fixed size, real (present in the manifest), all
    runnable-keyless (reference the mock), and every entry is a distinct pattern+domain."""
    feat = templates.featured()
    assert len(feat) == len(templates._FEATURED)  # every curated slug resolved
    manifest_slugs = {m["slug"] for m in templates._manifest()}
    assert all(f["slug"] in manifest_slugs for f in feat)
    # distinct patterns AND distinct domains — the point is a varied showcase, not 8 of one
    assert len({f["category"] for f in feat}) == len(feat)
    assert len({f["name"].split(" · ")[0] for f in feat}) == len(feat)


def test_featured_survives_a_missing_slug(monkeypatch):
    """A renamed/removed template must not break the picker — the bad slug is skipped."""
    monkeypatch.setattr(templates, "_FEATURED",
                        templates._FEATURED[:2] + ["this-template-was-removed"])
    feat = templates.featured()
    assert [f["slug"] for f in feat] == templates._FEATURED[:2]


def test_templates_endpoint_exposes_featured():
    with TestClient(app) as c:
        r = c.get("/api/flows/templates").json()
        assert len(r["featured"]) == len(templates._FEATURED)
        assert r["featured"][0]["slug"] == templates._FEATURED[0]
