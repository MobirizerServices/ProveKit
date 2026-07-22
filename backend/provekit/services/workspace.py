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
                return ws
    ws = get_or_create_default_workspace(db, user)
    member = is_member(db, ws.id, user.id)
    _guard_viewer(request, member.role if member else None)
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


def workspace_from_key(db: Session, request, authorization: str | None) -> Workspace:
    """Resolve the workspace from a Bearer project key (exporters, the SDK, the MCP server),
    falling back to the session cookie for interactive/local use. Shared by every key-authed
    route (ingest, reads, feedback, datasets)."""
    from fastapi import HTTPException

    from . import apikey, deploy
    if authorization and authorization.lower().startswith("bearer "):
        key = authorization[7:].strip()
        ws = apikey.resolve_workspace(db, key)
        if ws:
            return ws
        ws = db.query(Workspace).filter(Workspace.ingest_key_hash == deploy.hash_key(key)).first()
        if ws:
            return ws
        raise HTTPException(403, "Invalid ingest key")
    return get_or_create_default_workspace(db, get_current_user(request, db))
