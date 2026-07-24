"""Workspace (project) resolution. Each user gets a default project on first use;
current_workspace is the dependency every tenant-scoped router uses to isolate data."""
from __future__ import annotations

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Workspace, WorkspaceMember
from .auth import get_current_user


def get_or_create_default_workspace(db: Session, user) -> Workspace:
    w = (db.query(Workspace)
         .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
         .filter(WorkspaceMember.user_id == user.id)
         .order_by(Workspace.id).first())
    if w:
        return w
    w = Workspace(name="My project", owner_user_id=user.id)
    db.add(w); db.commit(); db.refresh(w)
    db.add(WorkspaceMember(workspace_id=w.id, user_id=user.id, role="owner")); db.commit()
    return w


def is_member(db: Session, workspace_id: int, user_id: int) -> WorkspaceMember | None:
    return (db.query(WorkspaceMember)
            .filter(WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.user_id == user_id)
            .first())


def current_workspace(request: Request, user=Depends(get_current_user),
                      db: Session = Depends(get_db)) -> Workspace:
    """The active project. A client selects one via the `X-Project-Id` header; we honor it
    only if the user is a member (so the header can't be used to reach another tenant's
    data). With no/invalid header, fall back to the user's default project."""
    pid = request.headers.get("X-Project-Id")
    if pid and pid.isdigit():
        member = is_member(db, int(pid), user.id)
        if member:
            ws = db.get(Workspace, int(pid))
            if ws:
                _guard_viewer(request, member.role)
                _guard_suspended(request, ws)
                return ws
    ws = get_or_create_default_workspace(db, user)
    member = is_member(db, ws.id, user.id)
    _guard_viewer(request, member.role if member else None)
    _guard_suspended(request, ws)
    return ws


def _guard_viewer(request: Request, role: str | None) -> None:
    """Refuse a write from a read-only viewer (#72).

    The check lives HERE, next to the resolution, and not in a middleware reading
    `X-Project-Id` — which is what I built first and got wrong. This function's whole job is
    that the header is only a *request*: an unknown or non-member project falls back to the
    caller's default. A middleware judging the header therefore evaluated a different project
    than the one the write landed in, and a viewer could bypass it by pointing the header at a
    project they weren't in at all. One resolution, one authorization decision.
    """
    from fastapi import HTTPException

    from .roles import can_write
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    if not can_write(role):
        raise HTTPException(403, "Your role in this project is viewer, which is read-only. "
                                 "Ask an owner for member access to make changes.")


def _guard_suspended(request: Request, ws: Workspace) -> None:
    """Refuse a write to a suspended project (#82).

    Here for the same reason as `_guard_viewer`: this is the one place a request's project is
    actually resolved, so it is the only place the decision can be made against the project the
    write would really land in.

    Reads are deliberately still served. Suspension exists to stop a project *accumulating*
    data, not to hold it hostage — an owner being wound down needs to export, and a state that
    hid the data would push them to hard-delete before they had a copy.

    Project-level routes (suspend, delete) resolve the workspace through `_require_owner`
    instead, so lifting a suspension and deleting a suspended project both still work.
    """
    from fastapi import HTTPException

    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    if ws is not None and ws.suspended_at:
        reason = f" ({ws.suspended_reason})" if ws.suspended_reason else ""
        raise HTTPException(403, f"This project is suspended{reason}, so it isn't accepting new "
                                 "data or changes. Its existing data is still readable and "
                                 "exportable. An owner can lift the suspension in Settings.")


def workspace_from_key(db: Session, request, authorization: str | None) -> Workspace:
    """Resolve the workspace from a Bearer project key (exporters, the SDK, the MCP server),
    falling back to the session cookie for interactive/local use. Shared by every key-authed
    route (ingest, reads, feedback, datasets)."""
    from fastapi import HTTPException

    from . import apikey, deploy
    if authorization and authorization.lower().startswith("bearer "):
        key = authorization[7:].strip()
        ws = apikey.resolve_workspace(db, key)
        if not ws:
            ws = (db.query(Workspace)
                  .filter(Workspace.ingest_key_hash == deploy.hash_key(key)).first())
        if ws:
            # A key is how data *arrives*, so a suspended project has to be refused here too —
            # otherwise suspension would stop the portal and not the firehose it exists to stop.
            _guard_suspended(request, ws)
            return ws
        raise HTTPException(403, "Invalid ingest key")
    ws = get_or_create_default_workspace(db, get_current_user(request, db))
    _guard_suspended(request, ws)
    return ws
