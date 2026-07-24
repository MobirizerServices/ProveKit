"""Collaboration notes: replies, @mentions and resolve (#65).

Notes used to be flat and silent — no way to answer one, no way to say a question was settled,
and no way for the person who could answer it to find out it existed.
"""
import uuid

from fastapi.testclient import TestClient

from provekit.database import SessionLocal
from provekit.main import app
from provekit.models import ProviderConnection, Run, User, WorkspaceMember
from provekit.services import mentions


def _client():
    return TestClient(app, base_url="https://testserver")


def _ws_id(c) -> int:
    """The workspace these portal calls actually land in.

    Not `Workspace.first()`: once other tests in the suite have created workspaces that returns
    some other tenant, and these tests then pass alone and fail in the suite having asserted
    nothing. Creating a row through the API and reading its workspace back is the reliable way.
    """
    conn = c.post("/api/connections",
                  json={"provider": "openai", "label": f"nt{uuid.uuid4().hex[:6]}",
                        "key": "sk-test-0000"}).json()
    db = SessionLocal()
    try:
        return db.get(ProviderConnection, conn["id"]).workspace_id
    finally:
        db.close()


def _trace(c) -> tuple[str, int]:
    """A trace in the workspace these portal calls land in."""
    tid = uuid.uuid4().hex[:32]
    ws_id = _ws_id(c)
    db = SessionLocal()
    try:
        db.add(Run(workspace_id=ws_id, trace_id=tid, span_id="s1", parent_span_id="",
                   type="agent", label="noted", status="completed", duration_ms=10))
        db.commit()
        return tid, ws_id
    finally:
        db.close()


def test_a_reply_joins_the_thread_it_answers():
    c = _client()
    tid, _ = _trace(c)
    root = c.post(f"/api/traces/{tid}/notes", json={"span_id": "s1", "body": "why is this slow?"}).json()
    reply = c.post(f"/api/traces/{tid}/notes",
                   json={"span_id": "s1", "body": "retrieval, see the tool span", "parent_id": root["id"]}).json()
    assert reply["parent_id"] == root["id"]

    # A reply to a reply flattens onto the same root rather than nesting without limit.
    deep = c.post(f"/api/traces/{tid}/notes",
                  json={"body": "agreed", "parent_id": reply["id"]}).json()
    assert deep["parent_id"] == root["id"]
    # …and inherits the span, so an answer can't drift onto a different node.
    assert deep["span_id"] == root["span_id"] == "s1"


def test_replying_to_a_note_from_another_trace_is_refused():
    c = _client()
    a, _ = _trace(c)
    b, _ = _trace(c)
    root = c.post(f"/api/traces/{a}/notes", json={"body": "on trace a"}).json()
    r = c.post(f"/api/traces/{b}/notes", json={"body": "wrong thread", "parent_id": root["id"]})
    assert r.status_code == 404


def test_resolving_settles_the_thread_without_deleting_it():
    c = _client()
    tid, _ = _trace(c)
    root = c.post(f"/api/traces/{tid}/notes", json={"body": "is this expected?"}).json()
    reply = c.post(f"/api/traces/{tid}/notes", json={"body": "yes", "parent_id": root["id"]}).json()

    done = c.post(f"/api/notes/{root['id']}/resolve", json={"resolved": True}).json()
    assert done["resolved_at"] and done["id"] == root["id"]

    # Resolving from inside the thread settles the thread, not the single message.
    c.post(f"/api/notes/{root['id']}/resolve", json={"resolved": False})
    via_reply = c.post(f"/api/notes/{reply['id']}/resolve", json={"resolved": True}).json()
    assert via_reply["id"] == root["id"] and via_reply["resolved_at"]

    # The reasoning survives — resolve is not delete.
    bodies = [n["body"] for n in c.get(f"/api/traces/{tid}/notes").json()]
    assert "is this expected?" in bodies and "yes" in bodies

    reopened = c.post(f"/api/notes/{root['id']}/resolve", json={"resolved": False}).json()
    assert reopened["resolved_at"] is None and reopened["resolved_by"] == ""


def test_only_real_members_are_mentioned():
    """A mention of someone who can't open the trace is not a mention — it is plain text."""
    c = _client()
    ws_id = _ws_id(c)
    db = SessionLocal()
    try:
        member = User(email=f"ana{uuid.uuid4().hex[:6]}@corp.example", name="Ana Real",
                      auth_provider="password")
        db.add(member); db.commit(); db.refresh(member)
        db.add(WorkspaceMember(workspace_id=ws_id, user_id=member.id, role="member"))
        db.commit()
        handle = member.email.split("@")[0]

        got = mentions.resolve(db, ws_id, f"@{handle} can you look? cc @nobody-here")
        assert got == [member.email], got
        # The display name works too, and a repeat doesn't double-notify.
        assert mentions.resolve(db, ws_id, f"@AnaReal @{handle}") == [member.email]
        assert mentions.resolve(db, ws_id, "no mentions at all") == []
    finally:
        db.close()


def test_a_mention_is_stored_on_the_note(monkeypatch):
    sent = []
    monkeypatch.setattr("provekit.services.email.send",
                        lambda to, subject, body: sent.append((to, subject)))
    c = _client()
    tid, ws_id = _trace(c)
    db = SessionLocal()
    try:
        u = User(email=f"bo{uuid.uuid4().hex[:6]}@corp.example", name="Bo", auth_provider="password")
        db.add(u); db.commit(); db.refresh(u)
        db.add(WorkspaceMember(workspace_id=ws_id, user_id=u.id, role="member")); db.commit()
        handle = u.email.split("@")[0]
    finally:
        db.close()

    note = c.post(f"/api/traces/{tid}/notes", json={"body": f"@{handle} thoughts?"}).json()
    assert note["mentions"] == [u.email]
    assert sent and sent[0][0] == u.email


def test_a_failing_notification_never_loses_the_note(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("smtp down")
    monkeypatch.setattr("provekit.services.email.send", boom)
    c = _client()
    tid, ws_id = _trace(c)
    db = SessionLocal()
    try:
        u = User(email=f"cy{uuid.uuid4().hex[:6]}@corp.example", name="Cy", auth_provider="password")
        db.add(u); db.commit(); db.refresh(u)
        db.add(WorkspaceMember(workspace_id=ws_id, user_id=u.id, role="member")); db.commit()
        handle = u.email.split("@")[0]
    finally:
        db.close()

    r = c.post(f"/api/traces/{tid}/notes", json={"body": f"@{handle} still saved"})
    assert r.status_code == 200, r.text
    assert r.json()["mentions"] == [u.email]
    assert "still saved" in [n["body"] for n in c.get(f"/api/traces/{tid}/notes").json()][0]
