"""Pending project invites (#73).

Inviting someone who hadn't signed up yet used to be a 404 — the owner was told "no such
account" and left with no record that the person had been asked, no way to cancel it, and no way
to tell a typo from an address that simply hadn't registered.
"""
import uuid
from datetime import timedelta

from fastapi.testclient import TestClient

from provekit.database import SessionLocal
from provekit.main import app
from provekit.models import ProjectInvite, WorkspaceMember, _now
from provekit.services import invites


def _client():
    return TestClient(app, base_url="https://testserver")


def _owner(c) -> tuple[str, int]:
    email = f"own{uuid.uuid4().hex[:8]}@ex.com"
    assert c.post("/api/auth/register", json={"email": email, "password": "pw12345678"}).status_code == 200
    return email, c.get("/api/projects").json()[0]["id"]


def test_inviting_an_unregistered_address_records_a_pending_invite():
    c = _client()
    _owner(c)
    pid = c.get("/api/projects").json()[0]["id"]
    addr = f"new{uuid.uuid4().hex[:8]}@ex.com"

    r = c.post(f"/api/projects/{pid}/members", json={"email": addr, "role": "member"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user_id"] is None and body["status"] == "pending" and body["expires_at"]

    listed = c.get(f"/api/projects/{pid}/invites").json()
    assert [i["email"] for i in listed] == [addr]
    assert listed[0]["status"] == "pending" and listed[0]["role"] == "member"


def test_signing_up_consumes_the_invitation():
    c = _client()
    owner_email, pid = _owner(c)
    addr = f"joins{uuid.uuid4().hex[:8]}@ex.com"
    c.post(f"/api/projects/{pid}/members", json={"email": addr, "role": "member"})

    # A brand-new account for that address joins the project on registration.
    c2 = _client()
    assert c2.post("/api/auth/register", json={"email": addr, "password": "pw12345678"}).status_code == 200
    joined = [p["id"] for p in c2.get("/api/projects").json()]
    assert pid in joined, f"invited project not joined: {joined}"

    # …and the invitation is consumed rather than left to match forever.
    assert c.get(f"/api/projects/{pid}/invites").json() == []
    db = SessionLocal()
    try:
        inv = (db.query(ProjectInvite)
               .filter(ProjectInvite.workspace_id == pid, ProjectInvite.email == addr).first())
        assert inv is not None and inv.accepted_at is not None
    finally:
        db.close()


def test_an_expired_invitation_does_not_grant_access():
    c = _client()
    _owner(c)
    pid = c.get("/api/projects").json()[0]["id"]
    addr = f"late{uuid.uuid4().hex[:8]}@ex.com"
    c.post(f"/api/projects/{pid}/members", json={"email": addr})

    db = SessionLocal()
    try:
        inv = (db.query(ProjectInvite)
               .filter(ProjectInvite.workspace_id == pid, ProjectInvite.email == addr).first())
        inv.expires_at = _now() - timedelta(days=1)
        db.commit()
    finally:
        db.close()

    assert c.get(f"/api/projects/{pid}/invites").json()[0]["status"] == "expired"

    c2 = _client()
    c2.post("/api/auth/register", json={"email": addr, "password": "pw12345678"})
    assert pid not in [p["id"] for p in c2.get("/api/projects").json()]
    db = SessionLocal()
    try:
        # Left visible, not silently deleted: the owner should see it lapsed.
        assert (db.query(WorkspaceMember)
                .filter(WorkspaceMember.workspace_id == pid).count()) == 1
    finally:
        db.close()


def test_revoking_an_invitation_stops_it_being_accepted():
    c = _client()
    _owner(c)
    pid = c.get("/api/projects").json()[0]["id"]
    addr = f"revk{uuid.uuid4().hex[:8]}@ex.com"
    inv_id = c.post(f"/api/projects/{pid}/members", json={"email": addr}).json()["invite_id"]

    assert c.delete(f"/api/projects/{pid}/invites/{inv_id}").status_code == 200
    assert c.get(f"/api/projects/{pid}/invites").json() == []

    c2 = _client()
    c2.post("/api/auth/register", json={"email": addr, "password": "pw12345678"})
    assert pid not in [p["id"] for p in c2.get("/api/projects").json()]


def test_re_inviting_refreshes_rather_than_duplicating():
    c = _client()
    _owner(c)
    pid = c.get("/api/projects").json()[0]["id"]
    addr = f"again{uuid.uuid4().hex[:8]}@ex.com"
    first = c.post(f"/api/projects/{pid}/members", json={"email": addr, "role": "viewer"}).json()
    second = c.post(f"/api/projects/{pid}/members", json={"email": addr, "role": "member"}).json()
    assert first["invite_id"] == second["invite_id"]
    listed = c.get(f"/api/projects/{pid}/invites").json()
    assert len(listed) == 1 and listed[0]["role"] == "member"


def test_an_unknown_role_on_an_invite_falls_back_to_the_least_privilege():
    """Same rule as membership: a typo must not become write access."""
    c = _client()
    _owner(c)
    pid = c.get("/api/projects").json()[0]["id"]
    addr = f"typo{uuid.uuid4().hex[:8]}@ex.com"
    body = c.post(f"/api/projects/{pid}/members", json={"email": addr, "role": "administrator"}).json()
    assert body["role"] == "viewer"


def test_invite_email_failure_never_loses_the_invitation(monkeypatch):
    c = _client()
    _owner(c)                      # register first: signup sends its own verification mail
    pid = c.get("/api/projects").json()[0]["id"]
    monkeypatch.setattr("provekit.services.email.send",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("smtp down")))
    addr = f"nomail{uuid.uuid4().hex[:8]}@ex.com"
    r = c.post(f"/api/projects/{pid}/members", json={"email": addr})
    assert r.status_code == 200
    assert c.get(f"/api/projects/{pid}/invites").json()[0]["email"] == addr


def test_status_helper_reads_the_row():
    inv = ProjectInvite(email="x@y.z", expires_at=_now() + timedelta(days=1))
    assert invites.status_of(inv) == "pending"
    inv.expires_at = _now() - timedelta(seconds=1)
    assert invites.status_of(inv) == "expired"
    inv.accepted_at = _now()
    assert invites.status_of(inv) == "accepted"
