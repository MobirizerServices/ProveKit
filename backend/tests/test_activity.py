"""Project activity feed (#74).

The feed is a view over `audit_logs`, so the tests that matter are about what it *refuses* to
show. Two independent filters guard it — the workspace id and an action allowlist — and the
allowlist is the one carrying the weight, because platform actions like impersonation are
recorded against the tenant's own workspace id and scoping alone would hand them over.

The router is not registered in main.py yet (see the report / wiringNeeded), so the HTTP tests
below skip themselves until it is, rather than self-registering it and asserting on an app the
server never serves. Everything else runs against real rows written by the real endpoints.
"""
import pathlib
import uuid

import pytest
from fastapi.testclient import TestClient

from provekit.database import SessionLocal
from provekit.main import app
from provekit.models import AuditLog, Workspace
from provekit.routers import activity
from provekit.services import audit


def _client():
    return TestClient(app, base_url="https://testserver")


@pytest.fixture
def project():
    """A real project, made through the real endpoint, torn down after.

    The audit rows are cleared on the way IN, not out. Deleting a project deliberately leaves
    its audit trail behind (a record outlives its subject), and SQLite hands the freed row id
    to the next project — so without this, one test's key.create rows show up in the next
    test's feed and the assertions stop meaning anything.
    """
    c = _client()
    p = c.post("/api/projects", json={"name": f"feed-{uuid.uuid4().hex[:8]}"}).json()
    _purge(p["id"])
    yield c, p["id"]
    c.delete(f"/api/projects/{p['id']}")


def _purge(workspace_id: int) -> None:
    db = SessionLocal()
    try:
        db.query(AuditLog).filter(AuditLog.workspace_id == workspace_id).delete()
        db.commit()
    finally:
        db.close()


def _seed(workspace_id: int | None, action: str, actor_email: str = "someone@ex.com") -> int:
    """Write one raw audit row. Used for the platform actions no tenant endpoint can produce."""
    db = SessionLocal()
    try:
        row = AuditLog(workspace_id=workspace_id, actor_email=actor_email, action=action,
                       target_type="project", target_id=str(workspace_id or ""),
                       target_label="x", detail={}, ip="203.0.113.9")
        db.add(row)
        db.commit()
        return row.id
    finally:
        db.close()


def _actions(workspace_id: int, **kw) -> list[str]:
    db = SessionLocal()
    try:
        entries, _ = audit.feed(db, workspace_id, **kw)
        return [e["action"] for e in entries]
    finally:
        db.close()


# ---- what the feed shows ----

def test_a_real_settings_change_shows_up_with_who_did_it(project):
    """The whole point: rename the project, then be able to answer "who did that".
    Written by routers/projects.py through audit.record() — the feed adds no write of its own.
    """
    c, pid = project
    c.patch(f"/api/projects/{pid}", json={"name": "renamed", "retention": 5000})
    db = SessionLocal()
    try:
        entries, _ = audit.feed(db, pid)
    finally:
        db.close()
    hit = next(e for e in entries if e["action"] == audit.PROJECT_UPDATE)
    assert hit["label"] == "changed project settings"
    assert "@" in hit["actor_email"]                       # actor snapshot, not a join
    assert hit["detail"]["retention"] == 5000              # *what* changed, not just that it did


def test_key_lifecycle_is_in_the_feed(project):
    c, pid = project
    hdr = {"X-Project-Id": str(pid)}
    made = c.post("/api/api-keys", json={"name": "ci"}, headers=hdr).json()
    c.delete(f"/api/api-keys/{made['id']}", headers=hdr)
    assert _actions(pid)[:2] == [audit.KEY_REVOKE, audit.KEY_CREATE]   # newest first


def test_the_feed_never_returns_the_actor_ip(project):
    """The platform audit view keeps the IP because an incident needs it. A feed every member
    of a project can read does not, and a teammate's address is not the answer to "who
    renamed this"."""
    c, pid = project
    c.patch(f"/api/projects/{pid}", json={"name": "ip-check"})
    db = SessionLocal()
    try:
        entries, _ = audit.feed(db, pid)
    finally:
        db.close()
    assert entries and all("ip" not in e for e in entries)


# ---- what the feed must not show ----

def test_platform_rows_stay_out_even_when_they_carry_this_workspace_id(project):
    """Impersonation is recorded against the tenant's own workspace_id (routers/admin.py), so
    scoping by workspace alone would have leaked it. The allowlist is what keeps it out."""
    c, pid = project
    _seed(pid, "impersonation.start", actor_email="operator@platform.example")
    _seed(pid, audit.SUPERUSER_GRANT, actor_email="operator@platform.example")
    assert _actions(pid) == []


def test_platform_rows_with_no_workspace_are_invisible(project):
    c, pid = project
    _seed(None, audit.SUPERUSER_GRANT)
    assert not any(a == audit.SUPERUSER_GRANT for a in _actions(pid))


def test_another_tenants_activity_is_invisible(project):
    c, pid = project
    other = c.post("/api/projects", json={"name": "neighbour"}).json()["id"]
    _purge(other)
    c.patch(f"/api/projects/{other}", json={"name": "theirs"})
    try:
        assert _actions(pid) == []
        assert _actions(other) != []
    finally:
        c.delete(f"/api/projects/{other}")


def test_the_action_filter_cannot_be_used_to_ask_for_a_platform_action(project):
    """The filter narrows the allowlist; it never widens it."""
    c, pid = project
    _seed(pid, "impersonation.start")
    assert _actions(pid, action="impersonation.start") == []


def test_impersonation_is_excluded_on_purpose_not_by_accident():
    """Guards the decision itself: if someone later adds these to the allowlist meaning to be
    transparent, they should do it deliberately (and decide whether to name the operator),
    not by widening a set while adding something else."""
    for action in ("impersonation.start", "impersonation.stop",
                   audit.SUPERUSER_GRANT, audit.SUPERUSER_REVOKE, audit.PROJECT_DELETE):
        assert action not in audit.TENANT_VISIBLE


# ---- paging ----

def test_keyset_paging_walks_the_whole_feed_without_repeats(project):
    c, pid = project
    hdr = {"X-Project-Id": str(pid)}
    for i in range(5):
        c.post("/api/api-keys", json={"name": f"k{i}"}, headers=hdr)
    db = SessionLocal()
    try:
        seen, cursor = [], None
        for _ in range(10):                       # bounded: a cursor bug must not hang the suite
            page, cursor = audit.feed(db, pid, limit=2, cursor=cursor)
            seen += [e["id"] for e in page]
            if cursor is None:
                break
    finally:
        db.close()
    assert len(seen) == 5 and len(set(seen)) == 5
    assert seen == sorted(seen, reverse=True)


def test_limit_is_clamped_not_trusted(project):
    """`limit` is a query parameter; unbounded, it is a way to ask the database for the whole
    table, and zero would page forever one empty page at a time."""
    c, pid = project
    hdr = {"X-Project-Id": str(pid)}
    for i in range(3):
        c.post("/api/api-keys", json={"name": f"k{i}"}, headers=hdr)
    db = SessionLocal()
    try:
        assert len(audit.feed(db, pid, limit=10**6)[0]) == 3      # capped, still correct
        assert len(audit.feed(db, pid, limit=0)[0]) == 3          # 0 reads as unset → default
        assert len(audit.feed(db, pid, limit=-5)[0]) == 1         # floored to one row
    finally:
        db.close()


# ---- honesty about coverage ----

def test_every_visible_action_has_human_phrasing():
    """A missing label renders as a raw dotted string in the UI."""
    assert not [a for a in audit.TENANT_VISIBLE if a not in audit.LABELS]


def test_unwired_actions_really_are_unwired():
    """`UNWIRED` is published to the UI as "not yet recorded". If someone adds the record()
    call at its source, this fails and tells them to move the name out of the set — which is
    the only thing keeping that published list from becoming a lie."""
    src = pathlib.Path(audit.__file__).parent.parent
    names = {v: k for k, v in vars(audit).items() if isinstance(v, str) and k.isupper()}
    blob = "\n".join(p.read_text() for p in src.rglob("*.py")
                     if p.name != "audit.py" and "migrations" not in p.parts)
    still_unwired = [a for a in audit.UNWIRED if f"audit.{names[a]}" not in blob]
    assert sorted(still_unwired) == sorted(audit.UNWIRED), (
        f"these are recorded now — take them out of audit.UNWIRED: "
        f"{sorted(set(audit.UNWIRED) - set(still_unwired))}")


def test_coverage_gaps_are_named_and_labelled():
    gaps = audit.coverage_gaps()
    assert {g["action"] for g in gaps} == set(audit.UNWIRED)
    assert all(g["label"] != g["action"] for g in gaps)      # phrased, not a dotted string
    assert audit.DATASET_ITEM_PROMOTE in {g["action"] for g in gaps}


# ---- HTTP surface (skipped until the router is registered in main.py) ----

def _registered() -> bool:
    return any(getattr(r, "path", "") == "/api/activity" for r in app.routes)


def test_the_handler_returns_the_scoped_shape(project):
    """Calls the handler as a plain function, with the dependencies it would have been given.

    Be clear about what this does and does not prove: it pins the response shape and that the
    handler scopes to the workspace it is handed. It does NOT prove `/api/activity` is served
    — the router isn't in main.py yet. The `needs_wiring` tests below are the ones that prove
    that, and they skip themselves until it is, rather than mounting the router here and
    reporting a route the server doesn't actually have.
    """
    c, pid = project
    c.patch(f"/api/projects/{pid}", json={"name": "handler"})
    db = SessionLocal()
    try:
        body = activity.list_activity(db=db, ws=db.get(Workspace, pid))
    finally:
        db.close()
    assert [e["action"] for e in body["entries"]] == [audit.PROJECT_UPDATE]
    assert body["next_cursor"] is None
    assert {g["action"] for g in body["not_yet_recorded"]} == set(audit.UNWIRED)


needs_wiring = pytest.mark.skipif(
    not _registered(),
    reason="routers/activity.py is not registered: add app.include_router(activity.router) "
           "to provekit/main.py")


@needs_wiring
def test_endpoint_is_scoped_to_the_selected_project(project):
    c, pid = project
    c.patch(f"/api/projects/{pid}", json={"name": "http"})
    body = c.get("/api/activity", headers={"X-Project-Id": str(pid)}).json()
    assert [e["action"] for e in body["entries"]] == [audit.PROJECT_UPDATE]
    assert body["next_cursor"] is None
    assert {g["action"] for g in body["not_yet_recorded"]} == set(audit.UNWIRED)


@needs_wiring
def test_a_viewer_may_read_the_feed(project):
    """It is a GET, so `current_workspace` admits a read-only member. Who changed the
    retention policy is not a privileged question inside your own project."""
    c, pid = project
    email = f"v{uuid.uuid4().hex[:8]}@ex.com"
    guest = _client()
    guest.post("/api/auth/register", json={"email": email, "password": "pw12345678"})
    c.post(f"/api/projects/{pid}/members", json={"email": email, "role": "viewer"})
    assert guest.get("/api/activity", headers={"X-Project-Id": str(pid)}).status_code == 200


@needs_wiring
def test_the_endpoint_refuses_a_project_you_are_not_in(project):
    """X-Project-Id is only a request; a non-member falls back to their own default project,
    so the outsider sees their own (empty) feed rather than the target's."""
    c, pid = project
    c.patch(f"/api/projects/{pid}", json={"name": "private"})
    outsider = _client()
    outsider.post("/api/auth/register",
                  json={"email": f"o{uuid.uuid4().hex[:8]}@ex.com", "password": "pw12345678"})
    body = outsider.get("/api/activity", headers={"X-Project-Id": str(pid)}).json()
    # Asserted as "none of these rows belong to the target", not "empty": the suite shares one
    # database, so an outsider's own default project legitimately carries rows from earlier
    # tests. `== []` passed only by accident of ordering and would have hidden a real leak
    # behind a fixture change.
    from provekit.database import SessionLocal
    from provekit.models import AuditLog
    db = SessionLocal()
    try:
        seen = {r.workspace_id for r in db.query(AuditLog)
                .filter(AuditLog.id.in_([e["id"] for e in body["entries"]] or [-1])).all()}
    finally:
        db.close()
    assert pid not in seen, "an outsider read the target project's activity"
