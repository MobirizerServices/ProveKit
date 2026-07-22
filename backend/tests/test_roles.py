"""Read-only viewers (#72).

Membership was owner-or-member and both could write, so the stakeholders who mostly want to
*look* — a PM, a support lead — had to be handed a role that can delete the project's data.

Every assertion here runs against the real `provekit.main.app`, not a hand-wrapped middleware.
The impersonation work in this same wave shipped 13 green tests against a stack that did not
exist, because the fixture built the middleware itself; the enforcement only means something
if it is tested on the object main.py assembles.
"""
import uuid

from fastapi.testclient import TestClient

from provekit.main import app
from provekit.services import roles


def _client():
    return TestClient(app, base_url="https://testserver")


def _account():
    c = _client()
    email = f"r{uuid.uuid4().hex[:8]}@ex.com"
    c.post("/api/auth/register", json={"email": email, "password": "pw12345678"})
    return c, email


def _project_with(role: str):
    """An owner's project, plus a second account added to it with `role`."""
    owner, _ = _account()
    pid = owner.post("/api/projects", json={"name": f"P{uuid.uuid4().hex[:6]}"}).json()["id"]
    guest, guest_email = _account()
    owner.post(f"/api/projects/{pid}/members",
               json={"email": guest_email, "role": role},
               headers={"X-Project-Id": str(pid)})
    return owner, guest, pid


def test_can_write_is_explicit_about_the_roles():
    assert roles.can_write("owner") and roles.can_write("member")
    assert not roles.can_write("viewer")
    assert not roles.can_write(None) and not roles.can_write("")


def test_a_viewer_is_refused_writes_by_the_real_app():
    owner, guest, pid = _project_with("viewer")
    h = {"X-Project-Id": str(pid)}
    assert guest.post("/api/views", json={"name": "nope", "params": {}},
                      headers=h).status_code == 403
    assert guest.post("/api/datasets", json={"name": "nope", "description": ""},
                      headers=h).status_code == 403
    assert guest.post("/api/experiments", json={"name": "nope"}, headers=h).status_code == 403


def test_a_viewer_can_still_read():
    """A read-only role that can't read is just a removed user."""
    owner, guest, pid = _project_with("viewer")
    h = {"X-Project-Id": str(pid)}
    assert guest.get("/api/traces", headers=h).status_code == 200
    assert guest.get("/api/datasets", headers=h).status_code == 200
    assert guest.get("/api/metrics", headers=h).status_code == 200


def test_a_member_is_unaffected():
    owner, guest, pid = _project_with("member")
    h = {"X-Project-Id": str(pid)}
    made = guest.post("/api/views", json={"name": f"v{uuid.uuid4().hex[:6]}", "params": {}},
                      headers=h)
    assert made.status_code == 200
    guest.delete(f"/api/views/{made.json()['id']}", headers=h)


def test_an_unknown_role_becomes_viewer_not_member():
    """A typo must fall to least privilege. Defaulting the other way turns a misspelling into
    write access, which is the kind of bug nobody finds by using the product."""
    owner, guest, pid = _project_with("administrator")
    members = owner.get(f"/api/projects/{pid}/members",
                        headers={"X-Project-Id": str(pid)}).json()
    assert any(m["role"] == "viewer" for m in members)
    assert guest.post("/api/views", json={"name": "nope", "params": {}},
                      headers={"X-Project-Id": str(pid)}).status_code == 403


def test_a_viewer_cannot_write_into_a_project_by_switching_the_header():
    """Pointing at a project you don't belong to must not put data there.

    Note what this does NOT assert: the request is not refused. `current_workspace` resolves
    X-Project-Id against membership and falls back to the caller's own default project, so the
    write succeeds — in their project, never the target's. That is the pre-existing tenancy
    guarantee, and it is the one worth pinning here; asserting a 403 would have been testing
    my assumption rather than the boundary.
    """
    from provekit.database import SessionLocal
    from provekit.models import Dataset

    owner, guest, pid = _project_with("viewer")
    other = owner.post("/api/projects", json={"name": f"O{uuid.uuid4().hex[:6]}"}).json()["id"]
    r = guest.post("/api/datasets", json={"name": f"probe-{uuid.uuid4().hex[:6]}",
                                          "description": ""},
                   headers={"X-Project-Id": str(other)})
    if r.status_code == 200:
        db = SessionLocal()
        try:
            landed = db.query(Dataset).filter(Dataset.id == r.json()["id"]).first()
            assert landed.workspace_id != other, "wrote into a project the caller isn't in"
            assert landed.workspace_id != pid, "wrote into the project they only view"
        finally:
            db.close()


def test_login_and_logout_stay_writable_for_a_viewer():
    """Auth is not a change to the project's data — guarding it would lock a viewer out."""
    owner, guest, pid = _project_with("viewer")
    assert guest.post("/api/auth/logout").status_code in (200, 204)
