"""SCIM 2.0 provisioning — and, mostly, *de*provisioning (#78).

Removing a departed employee is manual today: an owner has to remember to open every project
and delete the membership. The thing that makes this worth building is not the create path,
it's the revoke path, so that is the path this module is built around.

## What "active: false" actually does

A deactivation that only marks a row has not deprovisioned anybody — the browser tab the
leaver still has open keeps working, because the session is a signed cookie, not a database
lookup. So `deactivate()` does three things, in this order:

1. **Deletes the `WorkspaceMember` row.** Every tenant-scoped route resolves access through
   `services/workspace.current_workspace` → `is_member()`, so with the row gone an
   `X-Project-Id` pointing at this project falls back to the caller's own default project.
2. **Bumps `User.token_version`.** This is the one that makes it immediate.
   `services/auth.get_current_user` compares the cookie's `v` claim against this column and
   refuses the cookie the moment the number moves — so every issued session, reset link and
   verify link dies at the same instant, without waiting for a 30-day cookie to expire.
3. **Clears `User.password_hash`, but only if the account has no membership left anywhere.**
   `routers/auth.login` 401s on an empty hash and `routers/auth.forgot` refuses to email a
   reset link for one, so the account cannot be re-entered or self-recovered. It is deliberately
   conditional: the SCIM token is scoped to *one* project, and locking a person out of a second
   tenant they still legitimately belong to is not this tenant's decision to make.

## Representing "deactivated" with no schema change

There is no `active` column and this wave adds no migration, so the state lives in
`User.auth_provider` (`String(32)`, today one of password | github | local):

| `auth_provider`   | meaning                                                              |
|-------------------|----------------------------------------------------------------------|
| `scim_off:<pid>`  | deprovisioned by project `<pid>`; still listed there as `active:false` |
| `scim_off`        | hard-deleted via `DELETE /Users/{id}`; invisible to every tenant       |

What that costs is written down in docs/SCIM.md; the short version is that the column no
longer records *how* the account used to authenticate, a reactivated account comes back as
`password`, and only one project id fits in it — see `deactivate()` for the multi-tenant case.
"""
from __future__ import annotations

import os
import re
import secrets
from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import User, Workspace, WorkspaceMember, iso_utc
from . import audit, roles
from .auth import hash_password
from .workspace import is_member

# ---- SCIM constants ----
USER_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:User"
GROUP_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:Group"
LIST_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:ListResponse"
ERROR_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:Error"
PATCH_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:PatchOp"
MEDIA_TYPE = "application/scim+json"
BASE_PATH = "/scim/v2"

#: `auth_provider` sentinel. Bare = deleted; `scim_off:<project id>` = deactivated by that project.
DEACTIVATED = "scim_off"

#: Audit actions. Literal strings rather than names in services/audit.py, which this wave does
#: not own — which also means they do not yet appear in the project activity feed (the feed
#: renders an allowlist, `audit.TENANT_VISIBLE`). Adding them there is a one-line change.
PROVISION = "scim.user.provision"
DEPROVISION = "scim.user.deprovision"
REACTIVATE = "scim.user.reactivate"
DELETE = "scim.user.delete"
ROLE_CHANGE = "scim.role.change"

MAX_COUNT = 200
DEFAULT_COUNT = 100


class ScimError(HTTPException):
    """An HTTPException that also carries a SCIM `scimType`. The router turns it into a
    `urn:...:2.0:Error` body; raising a plain HTTPException anywhere still produces one."""

    def __init__(self, status_code: int, detail: str, scim_type: str = "") -> None:
        super().__init__(status_code, detail)
        self.scim_type = scim_type


# ---- authentication: an IdP bearer token, which is NOT a project key ----
#
# Deliberately its own credential and its own resolution path. `services/workspace.
# workspace_from_key` accepts any `pk_` project key and the per-workspace ingest key — keys
# that exist so an exporter can ship traces, are handed to CI, and are minted by any member.
# Provisioning can delete people, so it must not be reachable by a credential that leaks at
# that blast radius. Nothing here calls apikey.resolve_workspace or workspace_from_key, and
# a project key presented to /scim/v2 is simply an unknown token.
#
# Configured out of band because this wave may not touch config.py: an environment variable
# holding `<project id>:<token>` pairs. One pair per tenant the IdP provisions, e.g.
# PROVEKIT_SCIM_TOKENS="7:9f3c…,12:be21…". Unset → SCIM is off and every request is a 401.
TOKENS_ENV = "PROVEKIT_SCIM_TOKENS"

_UNCONFIGURED = (
    "SCIM is not enabled on this instance. Set PROVEKIT_SCIM_TOKENS to `<project id>:<token>` "
    "pairs (comma-separated) and restart. See docs/SCIM.md")
_NO_HEADER = (
    "SCIM requires `Authorization: Bearer <token>` using the tenant SCIM token, not a project "
    "API key. See docs/SCIM.md")
_BAD_TOKEN = (
    "That SCIM token is not configured on this instance. Check PROVEKIT_SCIM_TOKENS, and note "
    "that a `pk_` project key is not a SCIM token. See docs/SCIM.md")


@dataclass(frozen=True)
class ScimContext:
    """Everything a SCIM request is allowed to touch: exactly one project."""
    workspace: Workspace

    @property
    def workspace_id(self) -> int:
        return self.workspace.id


def configured_pairs() -> list[tuple[int, str]]:
    """Parsed `PROVEKIT_SCIM_TOKENS`. Read per request, not cached at import: an operator who
    rotates the token and restarts a worker should not be served by a stale copy, and it keeps
    the setting testable without reaching into an lru_cache."""
    pairs: list[tuple[int, str]] = []
    for part in os.environ.get(TOKENS_ENV, "").split(","):
        pid, _, token = part.strip().partition(":")
        if pid.strip().isdigit() and token.strip():
            pairs.append((int(pid), token.strip()))
    return pairs


def authenticate(db: Session, authorization: str | None) -> ScimContext:
    """Resolve the bearer token to the one project it provisions, or raise."""
    pairs = configured_pairs()
    if not pairs:
        raise ScimError(401, _UNCONFIGURED)
    if not (authorization or "").lower().startswith("bearer "):
        raise ScimError(401, _NO_HEADER)
    presented = authorization[7:].strip()
    matched: int | None = None
    for pid, token in pairs:
        # compare_digest on every pair, and no early break: the time this loop takes must not
        # depend on which token matched or how far down the list it sits.
        if secrets.compare_digest(presented, token):
            matched = pid
    if matched is None:
        raise ScimError(401, _BAD_TOKEN)
    ws = db.get(Workspace, matched)
    if ws is None:
        raise ScimError(401, f"The SCIM token is configured for project {matched}, which no longer "
                             f"exists. Update PROVEKIT_SCIM_TOKENS. See docs/SCIM.md")
    return ScimContext(workspace=ws)


# ---- state, expressed in the columns that already exist ----
def marker(workspace_id: int) -> str:
    return f"{DEACTIVATED}:{workspace_id}"


def is_deactivated_for(user: User, workspace_id: int) -> bool:
    return user.auth_provider == marker(workspace_id)


def _lookup(db: Session, email: str) -> User | None:
    return db.query(User).filter(func.lower(User.email) == email.strip().lower()).first()


def visible(db: Session, workspace_id: int) -> list[tuple[User, str]]:
    """`(user, role)` for everyone this tenant's IdP may see; role `""` means deactivated.

    Two sources, because deprovisioning deletes the membership row: current members, plus the
    accounts still carrying this project's `scim_off:` marker. Without the second half a
    freshly-deactivated user would 404 on the IdP's read-back instead of reporting
    `active: false`, and most connectors report that as a sync failure.
    """
    members = (db.query(User, WorkspaceMember.role)
               .join(WorkspaceMember, WorkspaceMember.user_id == User.id)
               .filter(WorkspaceMember.workspace_id == workspace_id).all())
    gone = db.query(User).filter(User.auth_provider == marker(workspace_id)).all()
    rows = [(u, r) for u, r in members] + [(u, "") for u in gone]
    return sorted(rows, key=lambda row: row[0].id)


def find(db: Session, ctx: ScimContext, user_id: str) -> tuple[User, str]:
    """One visible user, or a SCIM 404. Users outside this project are 404, not 403 — a
    provisioning token must not become a way to probe which addresses hold an account."""
    for user, role in visible(db, ctx.workspace_id):
        if str(user.id) == str(user_id).strip():
            return user, role
    raise ScimError(404, f"No user {user_id} in project {ctx.workspace_id}.")


# ---- resource serialization ----
def user_resource(user: User, *, workspace_id: int, role: str) -> dict:
    """A SCIM User. `role` empty → deactivated.

    `meta.lastModified` repeats `created`: there is no `updated_at` column and this wave adds
    no migration. Connectors use it for delta imports, so a delta-only sync will not notice
    changes made here — documented in docs/SCIM.md, and the reason the full import is correct.
    """
    return {
        "schemas": [USER_SCHEMA],
        "id": str(user.id),
        "userName": user.email,
        "displayName": user.name or user.email,
        "name": {"formatted": user.name or user.email},
        "emails": [{"value": user.email, "primary": True, "type": "work"}],
        "active": bool(role),
        "groups": [{"value": f"{workspace_id}:{role}", "display": role}] if role else [],
        "meta": {"resourceType": "User", "created": iso_utc(user.created_at),
                 "lastModified": iso_utc(user.created_at),
                 "location": f"{BASE_PATH}/Users/{user.id}"},
    }


def list_response(resources: list[dict], *, total: int, start: int) -> dict:
    return {"schemas": [LIST_SCHEMA], "totalResults": total, "startIndex": start,
            "itemsPerPage": len(resources), "Resources": resources}


def error_body(status: int, detail: str, scim_type: str = "") -> dict:
    body = {"schemas": [ERROR_SCHEMA], "status": str(status), "detail": detail}
    if scim_type:
        body["scimType"] = scim_type
    return body


# ---- filtering / paging ----
_EQ = re.compile(r'^\s*(?P<attr>[\w.]+)\s+eq\s+"(?P<value>[^"]*)"\s*$', re.IGNORECASE)


def apply_filter(rows: list[tuple[User, str]], expr: str) -> list[tuple[User, str]]:
    """Only `userName eq "…"` — the existence probe every connector runs before a create.

    Anything else is rejected rather than silently ignored. A filter that quietly matches
    everything reads to the IdP as "that user does not exist here", and the next thing it does
    is create a duplicate.
    """
    expr = (expr or "").strip()
    if not expr:
        return rows
    m = _EQ.match(expr)
    attr = m.group("attr").lower() if m else ""
    if attr not in ("username", "emails.value", "emails"):
        raise ScimError(400, 'Unsupported filter. This endpoint supports `userName eq "value"` '
                             '(externalId is not stored — see docs/SCIM.md).',
                        scim_type="invalidFilter")
    want = m.group("value").strip().lower()
    return [(u, r) for u, r in rows if u.email.lower() == want]


def page(rows: list, *, start_index: int, count: int) -> list:
    """SCIM paging is 1-based, and `startIndex` below 1 means 1 (RFC 7644 §3.4.2.4)."""
    start = max(1, int(start_index or 1))
    size = max(0, min(int(count if count is not None else DEFAULT_COUNT), MAX_COUNT))
    return rows[start - 1:start - 1 + size]


# ---- mutations ----
def _guard_last_owner(db: Session, workspace_id: int, member: WorkspaceMember) -> None:
    """Refuse to strip the project's only owner — the same rule routers/projects.py enforces.

    Deprovisioning is the point of this module, so refusing one is a real cost; leaving a
    project with no owner is worse, because nobody can then manage its members or keys and
    there is no in-app way back. The IdP admin transfers ownership first.
    """
    if member.role != roles.OWNER:
        return
    owners = db.query(WorkspaceMember).filter(WorkspaceMember.workspace_id == workspace_id,
                                              WorkspaceMember.role == roles.OWNER).count()
    if owners <= 1:
        raise ScimError(400, "This is the project's only owner, so deprovisioning them would leave "
                             "nobody able to manage it. Make someone else an owner first, then retry.",
                        scim_type="mutability")


def deactivate(db: Session, ctx: ScimContext, user: User, *, forget: bool = False,
               request=None) -> None:
    """End this person's access now. See the module docstring for why each step is here.

    `forget=True` is `DELETE /Users/{id}`: identical revocation, but the account stops being
    visible to this tenant's SCIM at all, which is what a connector expects after a delete.

    Multi-tenant caveat, stated plainly: `token_version` and `password_hash` are account-level
    columns, not per-project ones. Bumping the version signs the person out of *every* project
    they belong to (they sign back in and simply no longer see this one); the password is only
    cleared once no membership remains anywhere. There is no per-project session revocation
    without a schema change.
    """
    member = is_member(db, ctx.workspace_id, user.id)
    if member:
        _guard_last_owner(db, ctx.workspace_id, member)
        db.delete(member)
        db.flush()
    user.token_version += 1
    remaining = db.query(WorkspaceMember).filter(WorkspaceMember.user_id == user.id).count()
    if remaining == 0:
        user.password_hash = ""
        user.auth_provider = DEACTIVATED if forget else marker(ctx.workspace_id)
    db.commit()
    audit.record(db, None, DELETE if forget else DEPROVISION, workspace_id=ctx.workspace_id,
                 target_type="user", target_id=user.id, target_label=user.email,
                 detail={"via": "scim", "sessions_revoked": True,
                         "login_disabled": remaining == 0,
                         "memberships_remaining": remaining},
                 request=request)


def reactivate(db: Session, ctx: ScimContext, user: User, *, role: str = roles.MEMBER,
               request=None) -> str:
    """Put a deactivated account back, at `role` (default member, matching the product default
    in routers/projects.py).

    The old password hash is gone — that is the point of clearing it — so a random unguessable
    one is installed instead of leaving the column empty. An empty hash makes `forgot` refuse
    to send a reset link, which would leave a reactivated person permanently locked out. With
    a hash nobody knows, the existing "Forgot password" flow is their way back in. SCIM sends
    no mail of its own.
    """
    role = role if role in roles.ALL_ROLES else roles.VIEWER
    member = is_member(db, ctx.workspace_id, user.id)
    if member:
        member.role = role
    else:
        db.add(WorkspaceMember(workspace_id=ctx.workspace_id, user_id=user.id, role=role))
    if user.auth_provider.startswith(DEACTIVATED):
        user.auth_provider = "password"
    if not user.password_hash:
        user.password_hash = hash_password(secrets.token_urlsafe(32))
    user.token_version += 1
    db.commit()
    audit.record(db, None, REACTIVATE, workspace_id=ctx.workspace_id, target_type="user",
                 target_id=user.id, target_label=user.email,
                 detail={"via": "scim", "role": role}, request=request)
    return role


def create(db: Session, ctx: ScimContext, *, user_name: str, display_name: str = "",
           active: bool = True, request=None) -> tuple[User, str]:
    """Provision a person into this project. Returns `(user, role)`.

    An address that already has an account joins the project rather than being rejected — the
    same thing `POST /api/projects/{id}/members` does, and the only behaviour that works on an
    instance where people signed up before SCIM was switched on. Already a member → 409
    `uniqueness`, which is what a connector expects and what stops it retrying forever.
    """
    email = (user_name or "").strip().lower()
    if "@" not in email or len(email) > 255:
        raise ScimError(400, "userName must be the person's email address.", scim_type="invalidValue")
    existing = _lookup(db, email)
    if existing is not None:
        if is_member(db, ctx.workspace_id, existing.id):
            raise ScimError(409, "That account is already a member of this project. Change their "
                                 "access with PATCH /scim/v2/Users/{id} instead.",
                            scim_type="uniqueness")
        role = reactivate(db, ctx, existing, request=request)
        if not active:
            deactivate(db, ctx, existing, request=request)
            role = ""
        return existing, role

    user = User(email=email, name=(display_name or email.split("@")[0])[:160],
                auth_provider="password",
                # Unguessable rather than empty, so "Forgot password" is a working first login.
                password_hash=hash_password(secrets.token_urlsafe(32)))
    db.add(user)
    db.commit()
    db.refresh(user)
    db.add(WorkspaceMember(workspace_id=ctx.workspace_id, user_id=user.id, role=roles.MEMBER))
    db.commit()
    audit.record(db, None, PROVISION, workspace_id=ctx.workspace_id, target_type="user",
                 target_id=user.id, target_label=user.email,
                 detail={"via": "scim", "role": roles.MEMBER}, request=request)
    role = roles.MEMBER
    if not active:
        deactivate(db, ctx, user, request=request)
        role = ""
    return user, role


def rename(db: Session, user: User, display_name: str | None) -> None:
    if display_name is not None and display_name.strip():
        user.name = display_name.strip()[:160]
        db.commit()


def set_user_name(db: Session, user: User, user_name: str | None) -> None:
    """Rename the account. Email is the unique key, so a collision is a SCIM `uniqueness` 409
    rather than an IntegrityError surfacing as a 500 mid-sync."""
    email = (user_name or "").strip().lower()
    if not email or email == user.email.lower():
        return
    if "@" not in email or len(email) > 255:
        raise ScimError(400, "userName must be the person's email address.", scim_type="invalidValue")
    if _lookup(db, email) is not None:
        raise ScimError(409, "Another ProveKit account already uses that email address.",
                        scim_type="uniqueness")
    user.email = email
    db.commit()


def set_active(db: Session, ctx: ScimContext, user: User, active: bool, *, request=None) -> str:
    """The one operation this feature exists for. Returns the resulting role (`""` = inactive)."""
    if active:
        current = is_member(db, ctx.workspace_id, user.id)
        return current.role if current else reactivate(db, ctx, user, request=request)
    deactivate(db, ctx, user, request=request)
    return ""


def _truthy(value) -> bool:
    return value if isinstance(value, bool) else str(value).strip().lower() in ("true", "1", "yes")


#: Attributes this product can actually store. Everything else in a SCIM payload (externalId,
#: title, department, addresses, phoneNumbers, …) is accepted and dropped: there is no column
#: for it, and rejecting the request instead would stall the connector's whole sync over a
#: field nobody asked us to keep. docs/SCIM.md lists what survives.
_NAME_KEYS = ("displayname", "name.formatted", "name.givenname", "nickname")


def apply_patch(db: Session, ctx: ScimContext, user: User, operations: list[dict], *,
                request=None) -> str:
    """Apply a PatchOp and return the resulting role (`""` = deactivated).

    Handles both shapes connectors send for the deactivation that matters: an explicit
    `{"op":"replace","path":"active","value":false}` and the path-less
    `{"op":"replace","value":{"active":false}}` that Entra ID sends.
    """
    member = is_member(db, ctx.workspace_id, user.id)
    role = member.role if member else ""
    for op in operations or []:
        verb = str(op.get("op", "")).lower()
        path = str(op.get("path") or "").strip()
        if verb == "remove" and path.lower() == "active":
            role = set_active(db, ctx, user, False, request=request)
            continue
        if verb not in ("replace", "add"):
            raise ScimError(400, 'Supported user patch operations are `replace`, `add`, and '
                                 '`remove` of `active`.', scim_type="invalidValue")
        value = op.get("value")
        fields = value if (not path and isinstance(value, dict)) else {path: value}
        for key, val in fields.items():
            # Strip any urn: prefix an IdP glued onto the attribute name.
            attr = str(key).split(":")[-1].lower()
            if attr == "active":
                role = set_active(db, ctx, user, _truthy(val), request=request)
            elif attr == "username":
                set_user_name(db, user, str(val or ""))
            elif attr == "name" and isinstance(val, dict):
                rename(db, user, val.get("formatted") or val.get("givenName"))
            elif attr in _NAME_KEYS:
                rename(db, user, None if val is None else str(val))
    return role


def apply_replace(db: Session, ctx: ScimContext, user: User, body: dict, *, request=None) -> str:
    """`PUT /Users/{id}` — the whole resource. Absent `active` means active: RFC 7644 says an
    omitted attribute is cleared, but reading "not mentioned" as "deprovision" would turn a
    partial connector payload into an outage."""
    set_user_name(db, user, body.get("userName"))
    rename(db, user, body.get("displayName") or (body.get("name") or {}).get("formatted"))
    return set_active(db, ctx, user, _truthy(body.get("active", True)), request=request)


# ---- Groups: the three project roles ----
#
# Roles live in a single `WorkspaceMember.role` column, so the three groups are mutually
# exclusive by construction: adding someone to `member` is what removes them from `viewer`.
# Removing someone from their group removes their membership of the project — but it does NOT
# deactivate the account (that is `active:false`, which also kills their sessions).
def group_id(workspace_id: int, role: str) -> str:
    return f"{workspace_id}:{role}"


def group_resource(db: Session, ctx: ScimContext, role: str) -> dict:
    members = [{"value": str(u.id), "display": u.email}
               for u, r in visible(db, ctx.workspace_id) if r == role]
    return {"schemas": [GROUP_SCHEMA], "id": group_id(ctx.workspace_id, role),
            "displayName": role, "members": members,
            "meta": {"resourceType": "Group",
                     "location": f"{BASE_PATH}/Groups/{group_id(ctx.workspace_id, role)}"}}


def parse_group_id(ctx: ScimContext, raw: str) -> str:
    prefix, _, role = str(raw).partition(":")
    if prefix != str(ctx.workspace_id) or role not in roles.ALL_ROLES:
        raise ScimError(404, f"No group {raw}. This project has three: "
                             f"{', '.join(group_id(ctx.workspace_id, r) for r in sorted(roles.ALL_ROLES))}.")
    return role


_MEMBER_PATH = re.compile(r'^\s*members(\[\s*value\s+eq\s+"(?P<id>[^"]*)"\s*\])?\s*$', re.IGNORECASE)


def _op_member_ids(op: dict) -> list[str]:
    """User ids named by one PatchOp, in either shape connectors send: a `value` list of
    `{"value": id}` objects, or the id folded into the path as `members[value eq "id"]`."""
    m = _MEMBER_PATH.match(str(op.get("path") or "members"))
    if not m:
        raise ScimError(400, 'Only the `members` attribute can be patched on a group.',
                        scim_type="invalidPath")
    if m.group("id"):
        return [m.group("id")]
    value = op.get("value")
    items = value if isinstance(value, list) else [value]
    return [str(i.get("value")) if isinstance(i, dict) else str(i) for i in items if i not in (None, "")]


def patch_group(db: Session, ctx: ScimContext, role: str, operations: list[dict],
                request=None) -> None:
    """`add` sets the role, `remove` removes the project membership.

    `replace` on `members` is rejected on purpose: with one role column it cannot express the
    difference between "these are now the owners" and "everyone else loses the project", and
    guessing wrong either leaves privilege behind or removes people the IdP never touched.
    """
    for op in operations or []:
        verb = str(op.get("op", "")).lower()
        if verb not in ("add", "remove"):
            raise ScimError(400, "Group membership supports `add` and `remove`. `replace` is not "
                                 "supported — see docs/SCIM.md for why.", scim_type="invalidValue")
        for uid in _op_member_ids(op):
            changed = (_group_add if verb == "add" else _group_remove)(db, ctx, role, uid, request)
            if changed is not None:
                user, detail = changed
                audit.record(db, None, ROLE_CHANGE, workspace_id=ctx.workspace_id,
                             target_type="user", target_id=user.id, target_label=user.email,
                             detail=detail, request=request)


def _group_add(db: Session, ctx: ScimContext, role: str, uid: str, request) -> tuple[User, dict]:
    user, current = find(db, ctx, uid)
    member = is_member(db, ctx.workspace_id, user.id)
    if member is None:
        # Deactivated, or never in this project: go through reactivate() so the account also
        # regains a usable login instead of a membership row it can never sign in to use.
        reactivate(db, ctx, user, role=role, request=request)
    else:
        if member.role == roles.OWNER and role != roles.OWNER:
            _guard_last_owner(db, ctx.workspace_id, member)
        member.role = role
        db.commit()
    return user, {"via": "scim", "role": role, "was": current or "inactive"}


def _group_remove(db: Session, ctx: ScimContext, role: str, uid: str,
                  request) -> tuple[User, dict] | None:
    """None when there was nothing to do.

    Lenient about unknown ids rather than 404: a connector re-sending a removal it already made
    would otherwise stall its whole sync, and someone who is not in this project is already
    removed. Note this removes project access only — it is not a deactivation, so the account
    keeps its credential and its sessions. `active: false` is the one that revokes those.
    """
    user = db.get(User, int(uid)) if str(uid).strip().isdigit() else None
    member = is_member(db, ctx.workspace_id, user.id) if user else None
    if member is None or member.role != role:
        return None
    _guard_last_owner(db, ctx.workspace_id, member)
    db.delete(member)
    db.commit()
    return user, {"via": "scim", "role": "", "was": role}
