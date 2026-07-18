"""Workspace (project) resolution. Each user gets a default project on first use;
current_workspace is the dependency every tenant-scoped router uses to isolate data."""
from __future__ import annotations

from fastapi import Depends
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


def current_workspace(user=Depends(get_current_user), db: Session = Depends(get_db)) -> Workspace:
    return get_or_create_default_workspace(db, user)
