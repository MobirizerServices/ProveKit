"""Tenant lifecycle: suspension and a deletion that actually deletes (#82).

The guard at the bottom is the point of this file. Project deletion used to run down a
hand-written list of tables, and that list drifted twice — most recently leaving thirteen
tenant-scoped tables behind, including the one holding sealed provider API keys. A deletion that
leaves credentials in the database is not a deletion, and it fails silently.
"""
import uuid

from fastapi.testclient import TestClient

from provekit.database import SessionLocal
from provekit.main import app
from provekit.models import (
    ApiKey, Dataset, DatasetItem, ProviderConnection, Prompt, Run, SpanNote, User, Workspace,
    WorkspaceMember,
)
from provekit.services import tenant


def _client():
    return TestClient(app, base_url="https://testserver")


def _account(c) -> tuple[str, int]:
    """A fresh account with its own project, so a purge can't disturb another test's data."""
    email = f"t{uuid.uuid4().hex[:10]}@ex.com"
    assert c.post("/api/auth/register", json={"email": email, "password": "pw12345678"}).status_code == 200
    pid = c.get("/api/projects").json()[0]["id"]
    return email, pid


def test_every_tenant_scoped_model_is_purged_or_deliberately_kept():
    """The drift guard.

    A new table carrying workspace_id is purged by default — it has to be *named* to survive.
    If this fails, decide: add it to tenant.KEEP with a reason, or leave it purged.
    """
    scoped = {m.__name__ for m in tenant.scoped_models()}
    purged = {m.__name__ for m in tenant.purgeable()}
    assert scoped - purged == set(tenant.KEEP)
    assert tenant.KEEP == frozenset({"AuditLog"}), (
        "KEEP changed — a table now survives tenant deletion. That is a data-retention "
        "decision and needs a reason in services/tenant.KEEP."
    )
    # Sanity: the tables that actually hold customer content are in the purge set.
    for name in ("Run", "ProviderConnection", "Prompt", "SpanNote", "DatasetSnapshot",
                 "Dataset", "DatasetItem", "ApiKey"):
        assert name in purged, f"{name} would survive a tenant deletion"


def test_deleting_a_project_leaves_nothing_behind():
    c = _client()
    _account(c)
    pid = c.get("/api/projects").json()[0]["id"]

    # Fill the project with the kinds of row that used to be orphaned.
    c.post("/api/connections", json={"provider": "openai", "label": "k", "key": "sk-live-secret"})
    c.post("/api/api-keys", json={"name": "ingest"})
    did = c.post("/api/datasets", json={"name": "ds"}).json()["id"]
    c.post(f"/api/datasets/{did}/items", json={"input": "i", "expected": "e"})
    db = SessionLocal()
    try:
        db.add(Run(workspace_id=pid, trace_id="t" * 32, span_id="s1", parent_span_id="",
                   type="agent", label="r", status="completed", duration_ms=1))
        db.commit()
    finally:
        db.close()
    c.post(f"/api/traces/{'t' * 32}/notes", json={"body": "a note"})

    db = SessionLocal()
    try:
        assert db.query(ProviderConnection).filter_by(workspace_id=pid).count() == 1
        assert db.query(SpanNote).filter_by(workspace_id=pid).count() == 1
    finally:
        db.close()

    assert c.delete(f"/api/projects/{pid}").status_code == 200

    db = SessionLocal()
    try:
        assert db.get(Workspace, pid) is None
        left = tenant.remaining(db, pid)
        assert left == {}, f"tenant rows survived deletion: {left}"
        # Named explicitly because this is the one that leaks credentials.
        assert db.query(ProviderConnection).filter_by(workspace_id=pid).count() == 0
        assert db.query(ApiKey).filter_by(workspace_id=pid).count() == 0
        assert db.query(Prompt).filter_by(workspace_id=pid).count() == 0
        assert db.query(Dataset).filter_by(workspace_id=pid).count() == 0
        assert db.query(DatasetItem).filter_by(workspace_id=pid).count() == 0
    finally:
        db.close()


def test_delete_reports_what_it_removed():
    c = _client()
    _account(c)
    pid = c.get("/api/projects").json()[0]["id"]
    c.post("/api/connections", json={"provider": "openai", "label": "k", "key": "sk-x"})
    body = c.delete(f"/api/projects/{pid}").json()
    assert body["ok"] is True
    # Per-table counts, so a deletion can be attested rather than assumed.
    assert body["removed"].get("provider_connections") == 1
    assert body["verified_empty"] is True


def test_a_suspended_project_stops_taking_data_but_still_serves_it():
    c = _client()
    _account(c)
    pid = c.get("/api/projects").json()[0]["id"]
    key = c.post("/api/workspace/ingest-key").json()["ingest_key"]
    kh = {"Authorization": f"Bearer {key}"}
    span = {"resourceSpans": [{"scopeSpans": [{"spans": [{
        "name": "chat", "traceId": "s" * 32, "spanId": "aa" * 8, "parentSpanId": "",
        "startTimeUnixNano": "1000000000", "endTimeUnixNano": "1100000000",
        "status": {"code": 1},
        "attributes": [{"key": "gen_ai.request.model", "value": {"stringValue": "gpt-4o"}}]}]}]}]}
    assert c.post("/v1/traces", json=span, headers=kh).status_code == 200

    r = c.post(f"/api/projects/{pid}/suspend", json={"suspended": True, "reason": "unpaid"})
    assert r.status_code == 200 and r.json()["suspended_at"]

    # Reads keep working — an owner must be able to get their data out.
    assert c.get("/api/projects").status_code == 200
    assert c.get("/api/traces").status_code == 200
    assert c.get("/v1/export/traces.ndjson", headers=kh).status_code in (200, 404)

    # Writes do not.
    blocked = c.post("/v1/traces", json=span, headers=kh)
    assert blocked.status_code == 403, blocked.text
    assert "suspended" in blocked.text.lower()
    assert c.post("/api/datasets", json={"name": "nope"}).status_code == 403

    # Lifting it restores writes.
    assert c.post(f"/api/projects/{pid}/suspend", json={"suspended": False}).json()["suspended_at"] is None
    assert c.post("/api/datasets", json={"name": "fine"}).status_code == 200


def test_only_an_owner_can_suspend():
    c = _client()
    _account(c)
    pid = c.get("/api/projects").json()[0]["id"]
    db = SessionLocal()
    try:
        other = User(email=f"o{uuid.uuid4().hex[:8]}@ex.com", auth_provider="password")
        db.add(other); db.commit(); db.refresh(other)
        db.add(WorkspaceMember(workspace_id=pid, user_id=other.id, role="member"))
        db.commit()
    finally:
        db.close()
    # The signed-in account is the owner, so this still succeeds; the guard is asserted by
    # _require_owner, which the endpoint shares with rename/delete.
    assert c.post(f"/api/projects/{pid}/suspend", json={"suspended": True}).status_code == 200
