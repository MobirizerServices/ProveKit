"""Projects (workspaces) — a user can own/belong to several, each an isolated tenant with
its own keys, traces, datasets, experiments, and members. The active project is chosen by
the client via the `X-Project-Id` header (see services.workspace.current_workspace)."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import (Alert, ApiKey, Dataset, DatasetItem, Experiment, ExperimentResult,
                      Feedback, Run, User, Workspace, WorkspaceMember, iso_utc)
from ..services.auth import get_current_user
from ..services.workspace import get_or_create_default_workspace, is_member

router = APIRouter(prefix="/api/projects", tags=["projects"])


class _ProjectIn(BaseModel):
    name: str


class _MemberIn(BaseModel):
    email: str
    role: str = "member"


def _require_owner(db: Session, workspace_id: int, user: User) -> Workspace:
    ws = db.get(Workspace, workspace_id)
    if not ws:
        raise HTTPException(404, "Project not found")
    m = is_member(db, workspace_id, user.id)
    if not m:
        raise HTTPException(404, "Project not found")   # don't reveal projects you're not in
    if m.role != "owner":
        raise HTTPException(403, "Only an owner can do that")
    return ws


@router.get("")
def list_projects(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    default = get_or_create_default_workspace(db, user)
    rows = (db.query(Workspace, WorkspaceMember.role)
            .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
            .filter(WorkspaceMember.user_id == user.id)
            .order_by(Workspace.id).all())
    counts = dict(db.query(WorkspaceMember.workspace_id, func.count(WorkspaceMember.id))
                  .group_by(WorkspaceMember.workspace_id).all())
    return [{"id": w.id, "name": w.name, "role": role, "is_default": w.id == default.id,
             "member_count": counts.get(w.id, 1), "created_at": iso_utc(w.created_at)}
            for w, role in rows]


@router.post("")
def create_project(data: _ProjectIn, user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    ws = Workspace(name=(data.name or "New project")[:160], owner_user_id=user.id)
    db.add(ws)
    db.commit()
    db.refresh(ws)
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=user.id, role="owner"))
    db.commit()
    return {"id": ws.id, "name": ws.name, "role": "owner", "is_default": False,
            "member_count": 1, "created_at": iso_utc(ws.created_at)}


@router.patch("/{pid}")
def rename_project(pid: int, data: _ProjectIn, user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    ws = _require_owner(db, pid, user)
    ws.name = (data.name or ws.name)[:160]
    db.commit()
    return {"id": ws.id, "name": ws.name}


@router.delete("/{pid}")
def delete_project(pid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ws = _require_owner(db, pid, user)
    # Remove all tenant-scoped data before the project row (SQLite won't cascade for us).
    for model in (ExperimentResult, Experiment, DatasetItem, Dataset, Feedback, Alert, Run, ApiKey,
                  WorkspaceMember):
        db.query(model).filter(model.workspace_id == ws.id).delete(synchronize_session=False)
    db.delete(ws)
    db.commit()
    return {"ok": True}


# ---- members ----
@router.get("/{pid}/members")
def list_members(pid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not is_member(db, pid, user.id):
        raise HTTPException(404, "Project not found")
    rows = (db.query(WorkspaceMember, User)
            .join(User, User.id == WorkspaceMember.user_id)
            .filter(WorkspaceMember.workspace_id == pid)
            .order_by(WorkspaceMember.id).all())
    return [{"user_id": u.id, "email": u.email, "name": u.name, "role": m.role} for m, u in rows]


@router.post("/{pid}/members")
def add_member(pid: int, data: _MemberIn, user: User = Depends(get_current_user),
               db: Session = Depends(get_db)):
    _require_owner(db, pid, user)
    target = db.query(User).filter(func.lower(User.email) == data.email.strip().lower()).first()
    if not target:
        raise HTTPException(404, "No account with that email — they must sign up first")
    if is_member(db, pid, target.id):
        raise HTTPException(409, "Already a member")
    role = "owner" if data.role == "owner" else "member"
    db.add(WorkspaceMember(workspace_id=pid, user_id=target.id, role=role))
    db.commit()
    return {"user_id": target.id, "email": target.email, "name": target.name, "role": role}


@router.delete("/{pid}/members/{uid}")
def remove_member(pid: int, uid: int, user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    _require_owner(db, pid, user)
    m = is_member(db, pid, uid)
    if not m:
        raise HTTPException(404, "Not a member")
    owners = db.query(WorkspaceMember).filter(WorkspaceMember.workspace_id == pid,
                                              WorkspaceMember.role == "owner").count()
    if m.role == "owner" and owners <= 1:
        raise HTTPException(400, "Can't remove the last owner")
    db.delete(m)
    db.commit()
    return {"ok": True}
