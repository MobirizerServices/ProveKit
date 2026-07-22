"""Read-only "view as tenant" support sessions (#81).

The happy path is three assertions; the rest of this file is the refusals, because that is
where a support tool either is or isn't safe to hand to a support engineer.
"""
import uuid

from fastapi.testclient import TestClient

from provekit.config import get_settings
from provekit.main import app
from provekit.services import auth, impersonation


def _client():
    return TestClient(app, base_url="https://testserver")


def _guarded_client():
    """The real app.

    This used to wrap `ReadOnlyImpersonation(app)` by hand, which meant the read-only tests
    passed against a stack that did not exist — `main.py` had never registered the middleware,
    so the shipped API happily minted an API key during a session it reported as read_only.
    Testing the object main.py actually builds is the whole point; see
    test_writes_are_refused_against_the_real_app below.
    """
    return TestClient(app, base_url="https://testserver")


def _root(trace):
    return {"resourceSpans": [{"scopeSpans": [{"spans": [{
        "name": "agent", "traceId": trace, "spanId": "aa" * 8, "parentSpanId": "",
        "startTimeUnixNano": "1000000000", "endTimeUnixNano": "1500000000", "status": {"code": 1},
        "attributes": [{"key": "gen_ai.operation.name", "value": {"stringValue": "invoke_agent"}},
                       {"key": "gen_ai.input.messages", "value": {"stringValue": "hi"}}]}]}]}]}


def _tenant(client, trace_id=None):
    """A registered user with their own project, optionally holding one trace."""
    email = f"t{uuid.uuid4().hex[:8]}@ex.com"
    client.post("/api/auth/register", json={"email": email, "password": "pw12345678"})
    pid = client.post("/api/projects", json={"name": f"Acme {email[:6]}"}).json()["id"]
    if trace_id:
        key = client.post("/api/api-keys", json={"name": "k"},
                          headers={"X-Project-Id": str(pid)}).json()["key"]
        client.post("/v1/traces", headers={"Authorization": f"Bearer {key}"}, json=_root(trace_id))
    return email, pid


def test_start_and_stop_are_audited_with_actor_target_and_reason():
    """'Who looked at this customer's data, when, and why' is the whole point."""
    s = get_settings()
    s.superuser_emails = "local@provekit"
    try:
        admin, tenant = _client(), _client()
        email, pid = _tenant(tenant)

        started = admin.post("/api/admin/impersonate",
                             json={"workspace_id": pid, "reason": "ticket 4412: missing traces"})
        assert started.status_code == 200
        body = started.json()
        assert body["active"] is True and body["read_only"] is True
        assert body["workspace_id"] == pid and 0 < body["seconds_remaining"] <= 15 * 60

        # The banner the console keeps on screen: still on, and visibly counting down.
        live = admin.get("/api/admin/impersonate").json()
        assert live["active"] is True and live["workspace_id"] == pid
        assert live["owner"] == email and live["seconds_remaining"] <= body["seconds_remaining"]

        assert admin.delete("/api/admin/impersonate").json() == {
            "active": False, "workspace_id": pid, "workspace": body["workspace"]}
        assert admin.get("/api/admin/impersonate").json() == {"active": False}

        # Auditing is checked from a clean session: the console refuses operator tools while
        # impersonating, which is itself part of the contract (see the escalation test).
        entries = _client().get(f"/api/admin/audit?q={body['workspace']}").json()["entries"]
        actions = {e["action"] for e in entries}
        assert {"impersonation.start", "impersonation.stop"} <= actions
        start = next(e for e in entries if e["action"] == "impersonation.start")
        assert start["actor_email"] == "local@provekit"      # the operator, never the tenant
        assert start["target_label"] == body["workspace"] and start["target_id"] == str(pid)
        assert start["detail"]["reason"] == "ticket 4412: missing traces"
        assert start["ip"] == "testclient"                   # where from, not just who
    finally:
        s.superuser_emails = ""


def test_only_a_superuser_can_start_one():
    tenant, victim = _client(), _client()
    _email, pid = _tenant(victim)
    _tenant(tenant)
    r = tenant.post("/api/admin/impersonate", json={"workspace_id": pid, "reason": "curious"})
    assert r.status_code == 403


def test_impersonated_reads_show_the_tenants_traces():
    s = get_settings()
    s.superuser_emails = "local@provekit"
    try:
        admin, tenant = _client(), _client()
        trace = uuid.uuid4().hex
        _email, pid = _tenant(tenant, trace_id=trace)

        admin.post("/api/admin/impersonate", json={"workspace_id": pid, "reason": "support call"})
        rows = admin.get("/api/admin/impersonate/traces").json()
        assert [r["trace_id"] for r in rows] == [trace]
        spans = admin.get(f"/api/admin/impersonate/traces/{trace}").json()
        assert spans and spans[0]["request"]["input"] == "hi"
        assert admin.get(f"/api/admin/impersonate/traces/{uuid.uuid4().hex}").status_code == 404
    finally:
        s.superuser_emails = ""


def test_impersonation_does_not_widen_the_ordinary_apis():
    """Support mode is a separate, explicitly read-only surface. `current_workspace` never looks
    at the claim, so /api/traces keeps resolving to the operator's *own* project — an operator
    cannot quietly turn their normal session into the tenant's."""
    s = get_settings()
    s.superuser_emails = "local@provekit"
    try:
        admin, tenant = _client(), _client()
        trace = uuid.uuid4().hex
        _email, pid = _tenant(tenant, trace_id=trace)

        admin.post("/api/admin/impersonate", json={"workspace_id": pid, "reason": "support call"})
        assert admin.get("/api/admin/impersonate/traces").json()          # visible here
        own = admin.get("/api/traces").json()
        assert trace not in [r["trace_id"] for r in own]                  # and only here
        assert admin.get("/api/traces", headers={"X-Project-Id": str(pid)}).status_code == 200
        assert trace not in [r["trace_id"] for r in
                             admin.get("/api/traces", headers={"X-Project-Id": str(pid)}).json()]
    finally:
        s.superuser_emails = ""


def test_writes_are_refused_while_impersonating():
    """READ ONLY, enforced server-side for every method on every route — not hidden in the UI."""
    s = get_settings()
    s.superuser_emails = "local@provekit"
    try:
        admin, tenant = _guarded_client(), _client()
        _email, pid = _tenant(tenant)
        assert admin.post("/api/projects", json={"name": "before"}).status_code == 200

        admin.post("/api/admin/impersonate", json={"workspace_id": pid, "reason": "ticket 9"})
        for method, path, kwargs in [
            ("post", "/api/projects", {"json": {"name": "during"}}),
            ("patch", f"/api/projects/{pid}", {"json": {"name": "renamed"}}),
            ("delete", f"/api/projects/{pid}", {}),
            ("post", "/api/api-keys", {"json": {"name": "k"}}),
            ("post", "/v1/traces", {"json": _root(uuid.uuid4().hex)}),
        ]:
            r = getattr(admin, method)(path, **kwargs)
            assert r.status_code == 403, f"{method.upper()} {path} was not refused"
            assert "read-only" in r.json()["detail"]

        # Stopping is the one write that must always get through, or support mode has no exit.
        assert admin.delete("/api/admin/impersonate").status_code == 200
        assert admin.post("/api/projects", json={"name": "after"}).status_code == 200
    finally:
        s.superuser_emails = ""


def test_impersonating_does_not_grant_operator_actions():
    """The escalation this feature could introduce: using support mode to run superuser tools.
    Refused in the router itself, independently of the middleware."""
    s = get_settings()
    s.superuser_emails = "local@provekit"
    try:
        admin, tenant = _client(), _client()
        email, pid = _tenant(tenant)
        uid = next(u["id"] for u in admin.get("/api/admin/users").json()["users"]
                   if u["email"] == email)

        admin.post("/api/admin/impersonate", json={"workspace_id": pid, "reason": "ticket 9"})
        grant = admin.patch(f"/api/admin/users/{uid}", json={"is_superuser": True})
        assert grant.status_code == 403 and "impersonating" in grant.json()["detail"]
        assert admin.get("/api/admin/stats").status_code == 403
        # ...including starting a *second* impersonation from inside the first.
        assert admin.post("/api/admin/impersonate",
                          json={"workspace_id": pid, "reason": "again"}).status_code == 403
        assert admin.delete("/api/admin/impersonate").status_code == 200
        assert admin.get("/api/admin/stats").status_code == 200
    finally:
        s.superuser_emails = ""


def test_a_revoked_operator_loses_an_in_flight_session():
    s = get_settings()
    s.superuser_emails = "local@provekit"
    admin, tenant = _client(), _client()
    try:
        _email, pid = _tenant(tenant)
        admin.post("/api/admin/impersonate", json={"workspace_id": pid, "reason": "ticket 9"})
        assert admin.get("/api/admin/impersonate/traces").status_code == 200
        s.superuser_emails = ""                       # access revoked mid-session
        assert admin.get("/api/admin/impersonate/traces").status_code == 403
    finally:
        s.superuser_emails = ""


def test_an_expired_session_reads_nothing():
    """The deadline is the token's own exp, so an expired support session isn't a session at
    all — there is no claim left to replay."""
    s = get_settings()
    s.superuser_emails = "local@provekit"
    try:
        admin, tenant = _client(), _client()
        _email, pid = _tenant(tenant)
        me = admin.get("/api/auth/me").json()

        class _U:                                     # the operator, as issue() needs them
            id, token_version = me["id"], 0
        expired = impersonation.issue(_U(), pid, -1)
        assert impersonation.claim_from_token(expired) is None
        admin.cookies.set(auth.COOKIE, expired)
        assert admin.get("/api/admin/impersonate/traces").status_code == 403
        assert admin.get("/api/admin/impersonate").json() == {"active": False}
    finally:
        s.superuser_emails = ""


def test_impersonation_token_is_an_ordinary_session():
    """One credential, not two: the claim rides inside the normal signed session, so
    `auth.read_token` still resolves it to the operator. If these ever drift apart, the
    impersonating cookie has become a second way to be authenticated."""
    class _U:
        id, token_version = 4242, 7
    token = impersonation.issue(_U(), 9, 600)
    assert auth.read_token(token) == (4242, 7)
    assert auth.read_token(token, purpose="reset") is None
    claim = impersonation.claim_from_token(token)
    assert claim.user_id == 4242 and claim.workspace_id == 9
    assert 0 < claim.seconds_remaining <= 600
    # A plain session carries no claim, and neither does junk.
    assert impersonation.claim_from_token(auth.make_token(4242, ver=7)) is None
    assert impersonation.claim_from_token("not.a.token") is None
    assert impersonation.claim_from_token("") is None


def test_duration_is_bounded_and_a_reason_is_required():
    s = get_settings()
    s.superuser_emails = "local@provekit"
    try:
        admin, tenant = _client(), _client()
        _email, pid = _tenant(tenant)
        assert admin.post("/api/admin/impersonate",
                          json={"workspace_id": pid, "reason": "x" * 4,
                                "minutes": impersonation.MAX_MINUTES + 1}).status_code == 422
        assert admin.post("/api/admin/impersonate",
                          json={"workspace_id": pid, "reason": ""}).status_code == 422
        assert admin.post("/api/admin/impersonate",
                          json={"workspace_id": 10_000_000, "reason": "gone"}).status_code == 404
        assert admin.get("/api/admin/impersonate").json() == {"active": False}   # none started
        assert admin.delete("/api/admin/impersonate").status_code == 403
    finally:
        s.superuser_emails = ""


def test_status_survives_the_project_being_deleted():
    s = get_settings()
    s.superuser_emails = "local@provekit"
    try:
        admin, tenant = _client(), _client()
        _email, pid = _tenant(tenant)
        admin.post("/api/admin/impersonate", json={"workspace_id": pid, "reason": "ticket 9"})
        tenant.delete(f"/api/projects/{pid}")
        assert admin.get("/api/admin/impersonate").json() == {"active": False}
        assert admin.get("/api/admin/impersonate/traces").status_code == 404
    finally:
        s.superuser_emails = ""


def test_writes_are_refused_against_the_real_app():
    """The property that has to hold on the object main.py builds, not on a hand-wrapped one.

    A verifier disproved the original claim by minting a real API key during a session the
    API reported as `read_only: true`. The middleware is registered in main.py now, and this
    asserts it there — if someone removes that line, this fails.
    """
    s = get_settings()
    s.superuser_emails = "local@provekit"
    try:
        admin, tenant = _client(), _client()
        _, pid = _tenant(tenant)
        assert admin.post("/api/admin/impersonate",
                          json={"workspace_id": pid, "reason": "ticket 1"}).status_code == 200

        # Exactly the calls the verifier got 200s for.
        assert admin.post("/api/projects", json={"name": "nope"}).status_code == 403
        assert admin.post("/api/api-keys", json={"name": "nope"}).status_code == 403
        assert admin.post("/api/views", json={"name": "nope", "params": {}}).status_code == 403
        # ...and a read still works, or the mode would be useless.
        assert admin.get("/api/admin/impersonate").json()["active"] is True
        # The exit must never be blocked by the guard it installs.
        assert admin.delete("/api/admin/impersonate").status_code == 200
        # Once stopped, the operator can write again.
        made = admin.post("/api/views", json={"name": f"after-{uuid.uuid4().hex[:6]}",
                                              "params": {}})
        assert made.status_code == 200
        admin.delete(f"/api/views/{made.json()['id']}")
    finally:
        s.superuser_emails = ""


def test_the_status_endpoint_does_not_promise_what_it_cannot_enforce():
    """read_only: true is an assertion about the server's behaviour. It was being returned by
    an app that did not enforce it, which is worse than not having the field."""
    s = get_settings()
    s.superuser_emails = "local@provekit"
    try:
        admin, tenant = _client(), _client()
        _, pid = _tenant(tenant)
        body = admin.post("/api/admin/impersonate",
                          json={"workspace_id": pid, "reason": "ticket 2"}).json()
        assert body["read_only"] is True
        assert admin.post("/api/views", json={"name": "x", "params": {}}).status_code == 403
        admin.delete("/api/admin/impersonate")
    finally:
        s.superuser_emails = ""
