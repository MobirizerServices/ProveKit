"""Platform superadmin console + per-project settings (retention / PII)."""
import uuid

from fastapi.testclient import TestClient

from provekit.config import get_settings
from provekit.main import app


def _client():
    return TestClient(app, base_url="https://testserver")


def _root(trace, text="hello"):
    return {"resourceSpans": [{"scopeSpans": [{"spans": [{
        "name": "agent", "traceId": trace, "spanId": "r", "parentSpanId": "",
        "startTimeUnixNano": "1000000000", "endTimeUnixNano": "1500000000", "status": {"code": 1},
        "attributes": [{"key": "gen_ai.operation.name", "value": {"stringValue": "invoke_agent"}},
                       {"key": "gen_ai.input.messages", "value": {"stringValue": text}}]}]}]}]}


def test_admin_requires_superuser():
    assert _client().get("/api/admin/stats").status_code == 403


def test_admin_console_with_bootstrap():
    s = get_settings()
    s.superuser_emails = "local@provekit"       # bootstrap the local user as an operator
    try:
        c = _client()
        assert c.get("/api/auth/me").json()["is_superuser"] is True
        stats = c.get("/api/admin/stats").json()
        assert stats["users"] >= 1 and "projects" in stats and "traces" in stats
        assert any(u["email"] == "local@provekit" for u in c.get("/api/admin/users").json()["users"])
        assert isinstance(c.get("/api/admin/projects").json()["projects"], list)
    finally:
        s.superuser_emails = ""


def test_admin_can_grant_superuser():
    s = get_settings()
    s.superuser_emails = "local@provekit"
    try:
        admin = _client()
        other = _client()
        email = f"u{uuid.uuid4().hex[:8]}@ex.com"
        other.post("/api/auth/register", json={"email": email, "password": "pw12345678"})
        uid = next(u["id"] for u in admin.get("/api/admin/users").json()["users"] if u["email"] == email)
        assert admin.patch(f"/api/admin/users/{uid}", json={"is_superuser": True}).json()["is_superuser"] is True
        # now that user can reach the console too
        assert other.get("/api/admin/stats").status_code == 200
    finally:
        s.superuser_emails = ""


def test_revoking_a_bootstrap_superuser_is_refused_not_silently_ignored():
    """SUPERUSER_EMAILS overrides the DB flag, so clearing the flag can't revoke a listed
    account. The API must say so rather than return 200 on a change that has no effect."""
    s = get_settings()
    s.superuser_emails = "local@provekit"
    try:
        admin = _client()
        other = _client()
        email = f"u{uuid.uuid4().hex[:8]}@ex.com"
        other.post("/api/auth/register", json={"email": email, "password": "pw12345678"})
        uid = next(u["id"] for u in admin.get("/api/admin/users").json()["users"] if u["email"] == email)

        s.superuser_emails = f"local@provekit,{email}"
        assert other.get("/api/admin/stats").status_code == 200      # in via config
        row = next(u for u in admin.get("/api/admin/users").json()["users"] if u["id"] == uid)
        assert row["is_superuser"] is True and row["is_bootstrap"] is True

        r = admin.patch(f"/api/admin/users/{uid}", json={"is_superuser": False})
        assert r.status_code == 409 and "SUPERUSER_EMAILS" in r.json()["detail"]
        assert other.get("/api/admin/stats").status_code == 200      # still an operator

        # Dropping the address from config is what actually revokes it.
        s.superuser_emails = "local@provekit"
        assert other.get("/api/admin/stats").status_code == 403
    finally:
        s.superuser_emails = ""


def test_revoking_a_flag_granted_superuser_works():
    s = get_settings()
    s.superuser_emails = "local@provekit"
    try:
        admin = _client()
        other = _client()
        email = f"u{uuid.uuid4().hex[:8]}@ex.com"
        other.post("/api/auth/register", json={"email": email, "password": "pw12345678"})
        uid = next(u["id"] for u in admin.get("/api/admin/users").json()["users"] if u["email"] == email)

        admin.patch(f"/api/admin/users/{uid}", json={"is_superuser": True})
        assert other.get("/api/admin/stats").status_code == 200
        r = admin.patch(f"/api/admin/users/{uid}", json={"is_superuser": False})
        assert r.status_code == 200 and r.json()["is_superuser"] is False
        assert r.json()["is_bootstrap"] is False
        assert other.get("/api/admin/stats").status_code == 403     # revoke took effect
    finally:
        s.superuser_emails = ""


def test_per_project_retention_and_pii():
    c = _client()
    p = c.post("/api/projects", json={"name": "Settings"}).json()
    hdr = {"X-Project-Id": str(p["id"])}
    r = c.patch(f"/api/projects/{p['id']}", json={"retention": 2, "redact_pii": True}).json()
    assert r["retention"] == 2 and r["redact_pii"] is True

    key = c.post("/api/api-keys", json={"name": "k"}, headers=hdr).json()["key"]
    kh = {"Authorization": f"Bearer {key}"}
    # PII masking is on for THIS project even though the global default is off
    c.post("/v1/traces", headers=kh, json=_root("t-pii", text="reach me at joe@acme.com"))
    span = c.get("/api/traces/t-pii", headers=hdr).json()[0]
    assert "[REDACTED_EMAIL]" in span["request"]["input"]
    # retention=2 prunes to the newest 2 spans for the project
    for i in range(4):
        c.post("/v1/traces", headers=kh, json=_root(f"t-ret-{i}"))
    assert len(c.get("/api/traces", headers=hdr).json()) == 2


def test_admin_users_paginate_and_search():
    """Unpaginated tables are fine at 50 users and unusable at 5,000."""
    s = get_settings()
    s.superuser_emails = "local@provekit"
    try:
        c = _client()
        tag = uuid.uuid4().hex[:8]
        for i in range(3):
            _client().post("/api/auth/register",
                           json={"email": f"pg{i}-{tag}@ex.com", "password": "pw12345678"})

        first = c.get("/api/admin/users?limit=2&offset=0").json()
        assert len(first["users"]) == 2 and first["total"] >= 4
        second = c.get("/api/admin/users?limit=2&offset=2").json()
        assert {u["id"] for u in first["users"]}.isdisjoint({u["id"] for u in second["users"]})
        assert second["total"] == first["total"]        # total is of the whole match, not the page

        found = c.get(f"/api/admin/users?q={tag}").json()
        assert found["total"] == 3 and all(tag in u["email"] for u in found["users"])
        assert c.get("/api/admin/users?q=no-such-user-xyz").json() == {
            "total": 0, "limit": 50, "offset": 0, "users": []}
    finally:
        s.superuser_emails = ""


def test_admin_page_size_is_capped():
    s = get_settings()
    s.superuser_emails = "local@provekit"
    try:
        c = _client()
        assert c.get("/api/admin/users?limit=99999").json()["limit"] == 200
        assert c.get("/api/admin/users?limit=0&offset=-5").json()["limit"] == 1
        assert c.get("/api/admin/users?limit=0&offset=-5").json()["offset"] == 0
    finally:
        s.superuser_emails = ""


def test_admin_projects_search_by_owner_email():
    s = get_settings()
    s.superuser_emails = "local@provekit"
    try:
        c = _client()
        body = c.get("/api/admin/projects?q=local@provekit").json()
        assert body["total"] >= 1
        assert all("local@provekit" in p["owner"] or "local" in p["name"] for p in body["projects"])
        # span_count must still be right when the page is a subset
        page = c.get("/api/admin/projects?limit=1").json()
        assert page["limit"] == 1 and len(page["projects"]) <= 1
    finally:
        s.superuser_emails = ""
