"""SCIM 2.0 provisioning (#78) — with most of the weight on the deprovisioning path.

Two layers, on purpose:

* **Service-level tests** drive `services/scim.py` against a real session, and are the ones
  that assert what deactivation actually revokes. Where a claim is about the *rest* of the
  app believing the revocation (a session cookie dying, a login being refused), the assertion
  goes through `provekit.main.app` — the real application — rather than restating the service's
  own behaviour back at itself.
* **Handler tests** call the functions in `routers/scim.py` directly, as functions. They show
  the endpoints delegate to the service and shape their responses correctly. They deliberately
  do NOT show the endpoints are reachable — no app is constructed, nothing is mounted.
* **HTTP-level tests** hit `/scim/v2/...` on that same real app. `routers/scim.py` is NOT
  registered in `main.py` by this change (main.py is owned elsewhere this wave), so they skip
  with that reason rather than passing against a router this test file mounted itself. A green
  HTTP test over a self-registered router proves nothing about the shipped app, and this file
  will not pretend otherwise: until the wiring line lands, reachability is untested.
"""
import json
import secrets
import uuid

import pytest
from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient

from provekit.config import get_settings
from provekit.database import SessionLocal
from provekit.main import app
from provekit.models import ApiKey, User, Workspace, WorkspaceMember
from provekit.routers import scim as scim_router
from provekit.services import apikey, auth, deploy, email, scim
from provekit.services.workspace import is_member


class _FakeRequest:
    """Just the one thing `require_scim` reads. A real Request needs an ASGI scope, and
    building one here would be more fiction than this is."""

    def __init__(self, authorization: str):
        self.headers = {"authorization": authorization}

SCIM_WIRED = any(str(getattr(r, "path", "")).startswith(scim.BASE_PATH) for r in app.routes)
requires_wiring = pytest.mark.skipif(
    not SCIM_WIRED,
    reason="routers/scim.py is not registered in provekit.main — add "
           "`app.include_router(scim.router)` (see docs/SCIM.md). Not self-registering it here: "
           "that would test a router the deployed app does not serve.")


def _email(tag: str) -> str:
    return f"{tag}-{uuid.uuid4().hex[:10]}@example.com"


@pytest.fixture
def db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def tenant(db, monkeypatch):
    """A project with one owner, plus a SCIM token scoped to exactly that project."""
    owner = User(email=_email("owner"), name="Owner", password_hash=auth.hash_password("ownerpw123"))
    db.add(owner); db.commit(); db.refresh(owner)
    ws = Workspace(name="SCIM tenant", owner_user_id=owner.id)
    db.add(ws); db.commit(); db.refresh(ws)
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=owner.id, role="owner")); db.commit()
    token = secrets.token_urlsafe(24)
    monkeypatch.setenv(scim.TOKENS_ENV, f"{ws.id}:{token}")
    return scim.ScimContext(workspace=ws), token, owner


@pytest.fixture
def sent(monkeypatch):
    box = []
    monkeypatch.setattr(email, "send", lambda to, subject, body: box.append((to, subject, body)))
    return box


def _member(db, ctx, *, role="member", password="joiner123") -> User:
    u = User(email=_email("staff"), name="Staff", password_hash=auth.hash_password(password))
    db.add(u); db.commit(); db.refresh(u)
    db.add(WorkspaceMember(workspace_id=ctx.workspace_id, user_id=u.id, role=role)); db.commit()
    return u


# ---------------------------------------------------------------- authentication
def test_scim_is_off_until_a_token_is_configured(db, monkeypatch):
    monkeypatch.delenv(scim.TOKENS_ENV, raising=False)
    with pytest.raises(scim.ScimError) as exc:
        scim.authenticate(db, "Bearer anything")
    assert exc.value.status_code == 401
    assert scim.TOKENS_ENV in str(exc.value.detail)      # the message names the fix


def test_token_resolves_to_exactly_one_project(db, tenant):
    ctx, token, _ = tenant
    assert scim.authenticate(db, f"Bearer {token}").workspace_id == ctx.workspace_id
    assert scim.authenticate(db, f"bearer {token}").workspace_id == ctx.workspace_id


@pytest.mark.parametrize("header", [None, "", "Basic abc", "Bearer wrong-token", "Bearer "])
def test_bad_or_missing_credentials_are_401(db, tenant, header):
    with pytest.raises(scim.ScimError) as exc:
        scim.authenticate(db, header)
    assert exc.value.status_code == 401


def test_a_project_api_key_is_not_a_scim_token(db, tenant):
    """The whole reason SCIM has its own credential: a `pk_` key is minted by any member and
    lives in CI, and provisioning can delete people."""
    ctx, _, _ = tenant
    plaintext, key_hash, prefix = apikey.mint()
    db.add(ApiKey(workspace_id=ctx.workspace_id, name="ci", prefix=prefix, key_hash=key_hash))
    db.commit()
    # the key really is live for the ingest path...
    assert apikey.resolve_workspace(db, plaintext).id == ctx.workspace_id
    # ...and useless against SCIM.
    with pytest.raises(scim.ScimError) as exc:
        scim.authenticate(db, f"Bearer {plaintext}")
    assert exc.value.status_code == 401


def test_workspace_ingest_key_is_not_a_scim_token(db, tenant):
    ctx, _, _ = tenant
    raw = "ingest-" + secrets.token_urlsafe(16)
    ctx.workspace.ingest_key_hash = deploy.hash_key(raw)
    db.commit()
    with pytest.raises(scim.ScimError):
        scim.authenticate(db, f"Bearer {raw}")


def test_token_for_a_deleted_project_is_rejected(db, monkeypatch):
    monkeypatch.setenv(scim.TOKENS_ENV, "99999999:tok")
    with pytest.raises(scim.ScimError) as exc:
        scim.authenticate(db, "Bearer tok")
    assert exc.value.status_code == 401


def test_malformed_token_config_entries_are_ignored(monkeypatch):
    monkeypatch.setenv(scim.TOKENS_ENV, " , nonsense, 7:good , 8: , :x ,9:also ")
    assert scim.configured_pairs() == [(7, "good"), (9, "also")]


# ---------------------------------------------------------------- deprovisioning
def test_deactivate_kills_an_already_issued_session_cookie(db, tenant, monkeypatch):
    """The point of the feature. A session is a signed cookie, not a database lookup, so a
    deactivation that only deletes a membership row leaves the leaver's open tab working."""
    ctx, _, _ = tenant
    monkeypatch.setattr(get_settings(), "hosted", True)   # no local-user fallback on a dead cookie
    c = TestClient(app, base_url="https://testserver")
    address = _email("leaver")
    assert c.post("/api/auth/register", json={"email": address, "password": "leaverpw123"}).status_code == 200
    assert c.get("/api/auth/me").json()["email"] == address

    user = db.query(User).filter(User.email == address).first()
    db.add(WorkspaceMember(workspace_id=ctx.workspace_id, user_id=user.id, role="member")); db.commit()

    scim.set_active(db, ctx, user, False)

    assert c.get("/api/auth/me").status_code == 401       # the cookie they already held is dead


def test_deactivate_blocks_login_and_self_service_recovery(db, tenant, sent):
    """Sessions die, and the account cannot be re-entered: `routers/auth.login` 401s on an
    empty password hash and `routers/auth.forgot` refuses to email a reset link for one."""
    ctx, _, _ = tenant
    user = _member(db, ctx, password="staffpw1234")
    c = TestClient(app, base_url="https://testserver")
    assert c.post("/api/auth/login", json={"email": user.email, "password": "staffpw1234"}).status_code == 200

    scim.set_active(db, ctx, user, False)

    assert c.post("/api/auth/login", json={"email": user.email, "password": "staffpw1234"}).status_code == 401
    sent.clear()
    assert c.post("/api/auth/forgot", json={"email": user.email}).status_code == 200
    assert sent == []                                     # no reset link, so no way back in


def test_deactivate_ends_project_membership(db, tenant):
    ctx, _, _ = tenant
    user = _member(db, ctx)
    assert is_member(db, ctx.workspace_id, user.id) is not None
    scim.set_active(db, ctx, user, False)
    assert is_member(db, ctx.workspace_id, user.id) is None


def test_deactivate_bumps_token_version_even_with_no_membership(db, tenant):
    """Idempotent: a connector that re-sends `active:false` must not error, and must still
    revoke anything issued since."""
    ctx, _, _ = tenant
    user = _member(db, ctx)
    scim.set_active(db, ctx, user, False)
    first = user.token_version
    scim.set_active(db, ctx, user, False)
    assert user.token_version == first + 1


def test_deactivated_user_is_listed_inactive_and_is_not_a_stranger(db, tenant):
    """The connector reads the user back after deactivating. It must find them, reported
    inactive — and `never provisioned here` must stay distinguishable from `deprovisioned`."""
    ctx, _, _ = tenant
    user = _member(db, ctx)
    outsider = User(email=_email("outsider"), password_hash=auth.hash_password("outsider12"))
    db.add(outsider); db.commit(); db.refresh(outsider)

    scim.set_active(db, ctx, user, False)

    found, role = scim.find(db, ctx, str(user.id))
    assert found.id == user.id and role == ""
    assert scim.user_resource(found, workspace_id=ctx.workspace_id, role=role)["active"] is False
    assert scim.is_deactivated_for(user, ctx.workspace_id) is True
    assert scim.is_deactivated_for(outsider, ctx.workspace_id) is False
    with pytest.raises(scim.ScimError) as exc:
        scim.find(db, ctx, str(outsider.id))              # 404, not 403: no address probing
    assert exc.value.status_code == 404


def test_delete_forgets_the_user_entirely(db, tenant):
    ctx, _, _ = tenant
    user = _member(db, ctx)
    scim.deactivate(db, ctx, user, forget=True)
    assert user.auth_provider == scim.DEACTIVATED
    assert user.password_hash == ""
    with pytest.raises(scim.ScimError) as exc:
        scim.find(db, ctx, str(user.id))
    assert exc.value.status_code == 404


def test_the_last_owner_cannot_be_deprovisioned(db, tenant):
    ctx, _, owner = tenant
    with pytest.raises(scim.ScimError) as exc:
        scim.set_active(db, ctx, owner, False)
    assert exc.value.status_code == 400 and exc.value.scim_type == "mutability"
    assert is_member(db, ctx.workspace_id, owner.id) is not None
    assert owner.password_hash                            # nothing was half-applied
    # Promote a second owner and the same call goes through.
    second = _member(db, ctx, role="owner")
    scim.set_active(db, ctx, owner, False)
    assert is_member(db, ctx.workspace_id, owner.id) is None
    assert is_member(db, ctx.workspace_id, second.id) is not None


def test_a_second_project_keeps_its_own_person(db, tenant, monkeypatch):
    """The SCIM token is scoped to one project. Deprovisioning from it removes access there
    and signs the person out everywhere (one session, one cookie) — but must not disable an
    account that still legitimately belongs to another tenant."""
    ctx, _, _ = tenant
    other_owner = User(email=_email("other"), password_hash=auth.hash_password("otherpw123"))
    db.add(other_owner); db.commit(); db.refresh(other_owner)
    other = Workspace(name="Other tenant", owner_user_id=other_owner.id)
    db.add(other); db.commit(); db.refresh(other)

    shared = _member(db, ctx, password="sharedpw123")
    db.add(WorkspaceMember(workspace_id=other.id, user_id=shared.id, role="member")); db.commit()

    scim.set_active(db, ctx, shared, False)

    assert is_member(db, ctx.workspace_id, shared.id) is None      # gone from this tenant
    assert is_member(db, other.id, shared.id) is not None          # still in the other one
    assert shared.password_hash                                    # can still sign in there
    assert not shared.auth_provider.startswith(scim.DEACTIVATED)
    c = TestClient(app, base_url="https://testserver")
    assert c.post("/api/auth/login",
                  json={"email": shared.email, "password": "sharedpw123"}).status_code == 200


# ---------------------------------------------------------------- provisioning
def test_create_provisions_a_member_who_can_claim_the_account(db, tenant, sent):
    ctx, _, _ = tenant
    address = _email("new")
    user, role = scim.create(db, ctx, user_name=address.upper(), display_name="New Person")
    assert user.email == address.lower()                  # userName is normalised
    assert role == "member" and is_member(db, ctx.workspace_id, user.id).role == "member"
    # No password was set by the IdP, so "Forgot password" has to be a working first login.
    c = TestClient(app, base_url="https://testserver")
    sent.clear()
    assert c.post("/api/auth/forgot", json={"email": user.email}).status_code == 200
    assert [to for to, _, _ in sent] == [user.email]


def test_create_rejects_a_non_email_username(db, tenant):
    ctx, _, _ = tenant
    with pytest.raises(scim.ScimError) as exc:
        scim.create(db, ctx, user_name="not-an-email")
    assert exc.value.status_code == 400 and exc.value.scim_type == "invalidValue"


def test_create_for_an_existing_member_is_a_uniqueness_conflict(db, tenant):
    ctx, _, _ = tenant
    user = _member(db, ctx)
    with pytest.raises(scim.ScimError) as exc:
        scim.create(db, ctx, user_name=user.email)
    assert exc.value.status_code == 409 and exc.value.scim_type == "uniqueness"


def test_create_for_an_existing_account_joins_the_project(db, tenant):
    """People signed up before SCIM was switched on; rejecting them would make the connector
    unusable on any instance with history."""
    ctx, _, _ = tenant
    existing = User(email=_email("prior"), password_hash=auth.hash_password("priorpw123"))
    db.add(existing); db.commit(); db.refresh(existing)
    user, role = scim.create(db, ctx, user_name=existing.email)
    assert user.id == existing.id and role == "member"

    dormant = User(email=_email("dormant-prior"), password_hash=auth.hash_password("dormantpw1"))
    db.add(dormant); db.commit(); db.refresh(dormant)
    joined, role = scim.create(db, ctx, user_name=dormant.email, active=False)
    assert role == "" and is_member(db, ctx.workspace_id, joined.id) is None


def test_create_with_active_false_provisions_then_revokes(db, tenant):
    ctx, _, _ = tenant
    user, role = scim.create(db, ctx, user_name=_email("dormant"), active=False)
    assert role == "" and is_member(db, ctx.workspace_id, user.id) is None
    assert user.password_hash == ""


def test_reactivate_restores_access_and_a_way_back_in(db, tenant, sent):
    ctx, _, _ = tenant
    user = _member(db, ctx, password="returnpw123")
    scim.set_active(db, ctx, user, False)
    assert user.password_hash == ""

    role = scim.set_active(db, ctx, user, True)

    assert role == "member" and is_member(db, ctx.workspace_id, user.id).role == "member"
    assert user.auth_provider == "password"
    assert user.password_hash                              # unguessable, not empty
    c = TestClient(app, base_url="https://testserver")
    # The old password is genuinely gone — reactivation is not un-deleting a credential.
    assert c.post("/api/auth/login", json={"email": user.email, "password": "returnpw123"}).status_code == 401
    sent.clear()
    c.post("/api/auth/forgot", json={"email": user.email})
    assert [to for to, _, _ in sent] == [user.email]       # ...but recovery works again


def test_setting_active_true_on_an_active_member_keeps_their_role(db, tenant):
    ctx, _, _ = tenant
    user = _member(db, ctx, role="viewer")
    assert scim.set_active(db, ctx, user, True) == "viewer"


def test_reactivate_of_a_current_member_just_sets_the_role(db, tenant):
    ctx, _, _ = tenant
    user = _member(db, ctx, role="viewer")
    assert scim.reactivate(db, ctx, user, role="member") == "member"
    assert is_member(db, ctx.workspace_id, user.id).role == "member"
    # An unrecognised role is read as the least it could have meant, as routers/projects.py does.
    assert scim.reactivate(db, ctx, user, role="superuser") == "viewer"


# ---------------------------------------------------------------- reads
def test_filter_by_username_and_reject_anything_else(db, tenant):
    ctx, _, _ = tenant
    user = _member(db, ctx)
    rows = scim.visible(db, ctx.workspace_id)
    assert [u.id for u, _ in scim.apply_filter(rows, f'userName eq "{user.email.upper()}"')] == [user.id]
    assert scim.apply_filter(rows, 'userName eq "nobody@example.com"') == []
    assert scim.apply_filter(rows, "") == rows
    with pytest.raises(scim.ScimError) as exc:
        scim.apply_filter(rows, 'externalId eq "abc"')
    assert exc.value.status_code == 400 and exc.value.scim_type == "invalidFilter"
    with pytest.raises(scim.ScimError):
        scim.apply_filter(rows, "userName pr")


def test_paging_is_one_based(db, tenant):
    ctx, _, _ = tenant
    for _ in range(3):
        _member(db, ctx)
    rows = scim.visible(db, ctx.workspace_id)
    assert len(rows) == 4
    assert scim.page(rows, start_index=1, count=2) == rows[:2]
    assert scim.page(rows, start_index=3, count=2) == rows[2:4]
    assert scim.page(rows, start_index=0, count=1) == rows[:1]     # startIndex < 1 means 1
    assert len(scim.page(rows, start_index=1, count=10_000)) == 4  # count is capped, not honoured


def test_user_resource_shape(db, tenant):
    ctx, _, _ = tenant
    user = _member(db, ctx, role="viewer")
    res = scim.user_resource(user, workspace_id=ctx.workspace_id, role="viewer")
    assert res["schemas"] == [scim.USER_SCHEMA]
    assert res["id"] == str(user.id) and res["userName"] == user.email
    assert res["active"] is True
    assert res["emails"] == [{"value": user.email, "primary": True, "type": "work"}]
    assert res["groups"] == [{"value": f"{ctx.workspace_id}:viewer", "display": "viewer"}]
    assert res["meta"]["resourceType"] == "User"
    # No updated_at column exists, so lastModified can only repeat created. Asserted so the
    # limitation is visible here and not just in the docs.
    assert res["meta"]["lastModified"] == res["meta"]["created"]


def test_list_and_error_envelopes():
    body = scim.list_response([{"id": "1"}], total=7, start=3)
    assert body["schemas"] == [scim.LIST_SCHEMA]
    assert (body["totalResults"], body["startIndex"], body["itemsPerPage"]) == (7, 3, 1)
    err = scim.error_body(409, "nope", "uniqueness")
    assert err == {"schemas": [scim.ERROR_SCHEMA], "status": "409", "detail": "nope",
                   "scimType": "uniqueness"}
    assert "scimType" not in scim.error_body(404, "gone")


# ---------------------------------------------------------------- PATCH / PUT shapes
def test_patch_active_false_in_both_connector_shapes(db, tenant):
    ctx, _, _ = tenant
    okta = _member(db, ctx)
    assert scim.apply_patch(db, ctx, okta,
                            [{"op": "replace", "path": "active", "value": False}]) == ""
    entra = _member(db, ctx)
    assert scim.apply_patch(db, ctx, entra,
                            [{"op": "Replace", "value": {"active": "False"}}]) == ""
    assert is_member(db, ctx.workspace_id, okta.id) is None
    assert is_member(db, ctx.workspace_id, entra.id) is None


def test_patch_remove_active_deprovisions(db, tenant):
    ctx, _, _ = tenant
    user = _member(db, ctx)
    assert scim.apply_patch(db, ctx, user, [{"op": "remove", "path": "active"}]) == ""


def test_patch_updates_the_name_and_ignores_what_we_cannot_store(db, tenant):
    ctx, _, _ = tenant
    user = _member(db, ctx)
    role = scim.apply_patch(db, ctx, user, [
        {"op": "replace", "path": "displayName", "value": "Renamed Person"},
        {"op": "replace", "path": "name", "value": {"formatted": "Formatted Name"}},
        {"op": "add", "path": "externalId", "value": "idp-123"},   # no column; dropped, not 400
        {"op": "replace", "value": {"title": "Staff Engineer"}},
    ])
    assert role == "member" and user.name == "Formatted Name"


def test_patch_rejects_an_unknown_operation(db, tenant):
    ctx, _, _ = tenant
    user = _member(db, ctx)
    with pytest.raises(scim.ScimError) as exc:
        scim.apply_patch(db, ctx, user, [{"op": "delete", "path": "active"}])
    assert exc.value.status_code == 400


def test_username_change_and_collision(db, tenant):
    ctx, _, _ = tenant
    user = _member(db, ctx)
    other = _member(db, ctx)
    fresh = _email("renamed")
    scim.apply_patch(db, ctx, user, [{"op": "replace", "path": "userName", "value": fresh}])
    assert user.email == fresh
    with pytest.raises(scim.ScimError) as exc:
        scim.set_user_name(db, user, other.email)
    assert exc.value.status_code == 409 and exc.value.scim_type == "uniqueness"
    with pytest.raises(scim.ScimError) as exc:
        scim.set_user_name(db, user, "not-an-email")
    assert exc.value.status_code == 400 and exc.value.scim_type == "invalidValue"
    scim.set_user_name(db, user, user.email.upper())       # same address, different case: no-op
    assert user.email == fresh


def test_put_without_active_does_not_deprovision(db, tenant):
    """An omitted attribute must not read as "revoke this person"."""
    ctx, _, _ = tenant
    user = _member(db, ctx)
    role = scim.apply_replace(db, ctx, user, {"userName": user.email, "displayName": "Put Name"})
    assert role == "member" and user.name == "Put Name"
    assert scim.apply_replace(db, ctx, user, {"active": False}) == ""


# ---------------------------------------------------------------- Groups
def test_groups_are_the_three_project_roles(db, tenant):
    ctx, _, owner = tenant
    ids = {g["id"] for g in (scim.group_resource(db, ctx, r) for r in ("owner", "member", "viewer"))}
    assert ids == {f"{ctx.workspace_id}:{r}" for r in ("owner", "member", "viewer")}
    assert [m["value"] for m in scim.group_resource(db, ctx, "owner")["members"]] == [str(owner.id)]
    assert scim.parse_group_id(ctx, f"{ctx.workspace_id}:viewer") == "viewer"
    for bad in (f"{ctx.workspace_id}:admin", "999:owner", "owner"):
        with pytest.raises(scim.ScimError) as exc:
            scim.parse_group_id(ctx, bad)
        assert exc.value.status_code == 404


def test_group_add_moves_the_role_because_role_is_one_column(db, tenant):
    ctx, _, _ = tenant
    user = _member(db, ctx, role="viewer")
    scim.patch_group(db, ctx, "member", [{"op": "add", "path": "members",
                                          "value": [{"value": str(user.id)}]}])
    assert is_member(db, ctx.workspace_id, user.id).role == "member"
    assert [m["value"] for m in scim.group_resource(db, ctx, "viewer")["members"]] == []


def test_group_remove_drops_project_access_but_not_the_account(db, tenant):
    ctx, _, _ = tenant
    user = _member(db, ctx, password="stillherepw1")
    before = user.token_version
    scim.patch_group(db, ctx, "member",
                     [{"op": "remove", "path": f'members[value eq "{user.id}"]'}])
    assert is_member(db, ctx.workspace_id, user.id) is None
    # Removing a role is not a deactivation: the account keeps its credential and sessions.
    assert user.password_hash and user.token_version == before
    scim.patch_group(db, ctx, "viewer", [{"op": "remove", "path": "members",
                                          "value": [{"value": str(user.id)}]}])   # already out: no-op


def test_group_add_of_a_deactivated_user_restores_a_usable_account(db, tenant):
    ctx, _, _ = tenant
    user = _member(db, ctx)
    scim.set_active(db, ctx, user, False)
    scim.patch_group(db, ctx, "viewer", [{"op": "add", "value": [{"value": str(user.id)}]}])
    assert is_member(db, ctx.workspace_id, user.id).role == "viewer"
    assert user.password_hash and user.auth_provider == "password"


def test_group_replace_is_refused_rather_than_guessed(db, tenant):
    ctx, _, _ = tenant
    user = _member(db, ctx)
    with pytest.raises(scim.ScimError) as exc:
        scim.patch_group(db, ctx, "owner", [{"op": "replace", "path": "members",
                                             "value": [{"value": str(user.id)}]}])
    assert exc.value.status_code == 400


def test_group_patch_of_a_non_member_attribute_is_refused(db, tenant):
    ctx, _, _ = tenant
    with pytest.raises(scim.ScimError) as exc:
        scim.patch_group(db, ctx, "member", [{"op": "add", "path": "displayName", "value": "x"}])
    assert exc.value.status_code == 400 and exc.value.scim_type == "invalidPath"


def test_group_remove_protects_the_last_owner(db, tenant):
    ctx, _, owner = tenant
    with pytest.raises(scim.ScimError) as exc:
        scim.patch_group(db, ctx, "owner", [{"op": "remove", "path": "members",
                                             "value": [{"value": str(owner.id)}]}])
    assert exc.value.status_code == 400
    with pytest.raises(scim.ScimError):
        scim.patch_group(db, ctx, "viewer", [{"op": "add", "value": [{"value": str(owner.id)}]}])
    assert is_member(db, ctx.workspace_id, owner.id).role == "owner"


# ---------------------------------------------------------------- handlers (called directly)
#
# These prove the endpoint functions delegate correctly and shape their responses. They do not
# prove the endpoints are *reachable* — see the skipped HTTP tests below for that.
def test_handlers_list_get_and_filter(db, tenant):
    ctx, _, owner = tenant
    user = _member(db, ctx)
    listed = scim_router.list_users(filter=f'userName eq "{user.email}"', startIndex=1, count=50,
                                    ctx=ctx, db=db)
    assert listed["totalResults"] == 1
    assert listed["Resources"][0]["id"] == str(user.id)
    everyone = scim_router.list_users(filter="", startIndex=1, count=50, ctx=ctx, db=db)
    assert {r["id"] for r in everyone["Resources"]} == {str(owner.id), str(user.id)}
    assert scim_router.get_user(str(user.id), ctx=ctx, db=db)["userName"] == user.email


def test_handlers_create_patch_put_delete(db, tenant):
    ctx, _, _ = tenant
    created = scim_router.create_user(request=None, ctx=ctx, db=db,
                                      body={"userName": _email("handler"), "displayName": "H"})
    assert created.status_code == 201
    uid = json.loads(bytes(created.body))["id"]

    put = scim_router.replace_user(uid, request=None, ctx=ctx, db=db,
                                   body={"displayName": "Renamed"})
    assert put["displayName"] == "Renamed" and put["active"] is True

    patched = scim_router.patch_user(uid, request=None, ctx=ctx, db=db,
                                     body={"schemas": [scim.PATCH_SCHEMA],
                                           "Operations": [{"op": "replace", "path": "active",
                                                           "value": False}]})
    assert patched["active"] is False
    assert is_member(db, ctx.workspace_id, int(uid)) is None

    assert scim_router.delete_user(uid, request=None, ctx=ctx, db=db).status_code == 204
    with pytest.raises(scim.ScimError):
        scim_router.get_user(uid, ctx=ctx, db=db)


def test_handlers_groups_and_config(db, tenant):
    ctx, _, owner = tenant
    user = _member(db, ctx, role="viewer")
    listed = scim_router.list_groups(ctx=ctx, db=db)
    assert {g["displayName"] for g in listed["Resources"]} == {"owner", "member", "viewer"}
    gid = scim.group_id(ctx.workspace_id, "member")
    assert scim_router.get_group(gid, ctx=ctx, db=db)["members"] == []
    patched = scim_router.patch_group(gid, request=None, ctx=ctx, db=db,
                                      body={"Operations": [{"op": "add", "path": "members",
                                                            "value": [{"value": str(user.id)}]}]})
    assert [m["value"] for m in patched["members"]] == [str(user.id)]
    assert str(owner.id) not in [m["value"] for m in patched["members"]]
    cfg = scim_router.service_provider_config(ctx=ctx)
    assert cfg["patch"]["supported"] is True and cfg["bulk"]["supported"] is False
    assert cfg["authenticationSchemes"][0]["type"] == "oauthbearertoken"


def test_handler_auth_dependency_reads_the_bearer_header(db, tenant):
    ctx, token, _ = tenant
    ok = scim_router.require_scim(_FakeRequest(f"Bearer {token}"), db=db)
    assert ok.workspace_id == ctx.workspace_id
    with pytest.raises(scim.ScimError):
        scim_router.require_scim(_FakeRequest(""), db=db)


def test_rejections_are_scim_error_resources():
    """A connector shows its admin whatever comes back here, so it has to be a SCIM Error."""
    conflict = scim_router.error_response(scim.ScimError(409, "taken", "uniqueness"))
    assert conflict.status_code == 409 and conflict.media_type == scim.MEDIA_TYPE
    assert json.loads(bytes(conflict.body)) == {"schemas": [scim.ERROR_SCHEMA], "status": "409",
                                                "detail": "taken", "scimType": "uniqueness"}
    plain = scim_router.error_response(HTTPException(403, "nope"))
    assert plain.status_code == 403 and json.loads(bytes(plain.body))["detail"] == "nope"
    malformed = scim_router.error_response(RequestValidationError([]))
    assert malformed.status_code == 400
    assert json.loads(bytes(malformed.body))["scimType"] == "invalidSyntax"


# ---------------------------------------------------------------- HTTP surface
@requires_wiring
def test_http_requires_a_scim_token(tenant):
    c = TestClient(app, base_url="https://testserver")
    r = c.get(f"{scim.BASE_PATH}/Users")
    assert r.status_code == 401
    assert r.json()["schemas"] == [scim.ERROR_SCHEMA]


@requires_wiring
def test_http_deprovision_round_trip(db, tenant):
    ctx, token, _ = tenant
    user = _member(db, ctx)
    c = TestClient(app, base_url="https://testserver")
    hdr = {"Authorization": f"Bearer {token}"}

    listed = c.get(f"{scim.BASE_PATH}/Users", headers=hdr,
                   params={"filter": f'userName eq "{user.email}"'}).json()
    assert listed["totalResults"] == 1 and listed["Resources"][0]["active"] is True

    r = c.patch(f"{scim.BASE_PATH}/Users/{user.id}", headers=hdr,
                json={"schemas": [scim.PATCH_SCHEMA],
                      "Operations": [{"op": "replace", "path": "active", "value": False}]})
    assert r.status_code == 200 and r.json()["active"] is False
    assert c.get(f"{scim.BASE_PATH}/Users/{user.id}", headers=hdr).json()["active"] is False

    assert c.delete(f"{scim.BASE_PATH}/Users/{user.id}", headers=hdr).status_code == 204
    assert c.get(f"{scim.BASE_PATH}/Users/{user.id}", headers=hdr).status_code == 404


@requires_wiring
def test_http_create_and_groups(db, tenant):
    ctx, token, _ = tenant
    c = TestClient(app, base_url="https://testserver")
    hdr = {"Authorization": f"Bearer {token}"}
    created = c.post(f"{scim.BASE_PATH}/Users", headers=hdr,
                     json={"schemas": [scim.USER_SCHEMA], "userName": _email("http"),
                           "displayName": "HTTP Person", "active": True})
    assert created.status_code == 201
    uid = created.json()["id"]
    assert c.post(f"{scim.BASE_PATH}/Users", headers=hdr,
                  json={"userName": created.json()["userName"]}).status_code == 409

    groups = c.get(f"{scim.BASE_PATH}/Groups", headers=hdr).json()
    assert groups["totalResults"] == 3
    gid = f"{ctx.workspace_id}:viewer"
    patched = c.patch(f"{scim.BASE_PATH}/Groups/{gid}", headers=hdr,
                      json={"Operations": [{"op": "add", "path": "members",
                                            "value": [{"value": uid}]}]})
    assert patched.status_code == 200
    assert uid in [m["value"] for m in patched.json()["members"]]
    assert c.get(f"{scim.BASE_PATH}/ServiceProviderConfig",
                 headers=hdr).json()["bulk"]["supported"] is False
