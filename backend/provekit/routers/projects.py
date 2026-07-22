"""Projects (workspaces) — a user can own/belong to several, each an isolated tenant with
its own keys, traces, datasets, experiments, and members. The active project is chosen by
the client via the `X-Project-Id` header (see services.workspace.current_workspace)."""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import (Alert, ApiKey, Dataset, DatasetItem, Experiment, ExperimentResult,
                      Feedback, Run, User, Workspace, WorkspaceMember, iso_utc)
from ..services import audit, errors, limits, roles
from ..services.auth import get_current_user
from ..services.workspace import get_or_create_default_workspace, is_member

router = APIRouter(prefix="/api/projects", tags=["projects"])


class _ProjectIn(BaseModel):
    name: str


class _ProjectPatch(BaseModel):
    name: str | None = None
    retention: int | None = None
    redact_pii: bool | None = None
    replay_url: str | None = None


class _MemberIn(BaseModel):
    email: str
    role: str = "member"


def _require_owner(db: Session, workspace_id: int, user: User) -> Workspace:
    ws = db.get(Workspace, workspace_id)
    if not ws:
        raise HTTPException(404, errors.PROJECT_NOT_FOUND)
    m = is_member(db, workspace_id, user.id)
    if not m:
        raise HTTPException(404, errors.PROJECT_NOT_FOUND)   # don't reveal projects you're not in
    if m.role != "owner":
        raise HTTPException(403, errors.OWNER_ONLY)
    return ws


@router.get("/usage")
def project_usage(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """What this account has used this month against its limits.

    A quota you can't see is indistinguishable from a bug: a throttled project just looks
    broken. Limits of 0 come back as null so a client renders "unlimited" rather than a meter
    pinned at 100% on a self-hosted instance with no quotas configured.
    """
    owned = db.query(Workspace).filter(Workspace.owner_user_id == user.id).count()
    return limits.usage_summary(user.id, owned)


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
             "member_count": counts.get(w.id, 1), "retention": w.retention,
             "redact_pii": w.redact_pii, "replay_url": w.replay_url, "created_at": iso_utc(w.created_at)}
            for w, role in rows]


@router.post("")
def create_project(data: _ProjectIn, user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    owned = db.query(Workspace).filter(Workspace.owner_user_id == user.id).count()
    limits.check_project_quota(owned)
    ws = Workspace(name=(data.name or "New project")[:160], owner_user_id=user.id)
    db.add(ws)
    db.commit()
    db.refresh(ws)
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=user.id, role="owner"))
    db.commit()
    return {"id": ws.id, "name": ws.name, "role": "owner", "is_default": False,
            "member_count": 1, "created_at": iso_utc(ws.created_at)}


@router.patch("/{pid}")
def update_project(pid: int, data: _ProjectPatch, request: Request,
                   user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Owner-facing per-project settings: name, span retention, and PII masking on ingest."""
    ws = _require_owner(db, pid, user)
    if data.name is not None:
        ws.name = data.name[:160] or ws.name
    if data.retention is not None:
        ws.retention = max(0, data.retention)
    if data.redact_pii is not None:
        ws.redact_pii = data.redact_pii
    if data.replay_url is not None:
        ws.replay_url = data.replay_url.strip()[:500]
    db.commit()
    # Retention and PII masking decide what is kept and what is stored in the clear, so a
    # change to either is exactly the kind of thing a review asks "who did that?" about.
    changed = {k: v for k, v in
               {"name": data.name, "retention": data.retention, "redact_pii": data.redact_pii,
                "replay_url": data.replay_url}.items() if v is not None}
    audit.record(db, user, audit.PROJECT_UPDATE, workspace_id=ws.id, target_type="project",
                 target_id=ws.id, target_label=ws.name, detail=changed, request=request)
    return {"id": ws.id, "name": ws.name, "retention": ws.retention, "redact_pii": ws.redact_pii,
            "replay_url": ws.replay_url}


@router.delete("/{pid}")
def delete_project(pid: int, request: Request, user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    ws = _require_owner(db, pid, user)
    name, span_count = ws.name, db.query(Run).filter(Run.workspace_id == ws.id).count()
    # Remove all tenant-scoped data before the project row (SQLite won't cascade for us).
    for model in (ExperimentResult, Experiment, DatasetItem, Dataset, Feedback, Alert, Run, ApiKey,
                  WorkspaceMember):
        db.query(model).filter(model.workspace_id == ws.id).delete(synchronize_session=False)
    db.delete(ws)
    db.commit()
    # workspace_id is left null: the project it pointed at no longer exists, and an FK to a
    # deleted row is exactly what would make this record disappear with its subject.
    audit.record(db, user, audit.PROJECT_DELETE, target_type="project", target_id=pid,
                 target_label=name, detail={"spans_deleted": span_count}, request=request)
    return {"ok": True}


# ---- members ----
@router.get("/{pid}/members")
def list_members(pid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not is_member(db, pid, user.id):
        raise HTTPException(404, errors.PROJECT_NOT_FOUND)
    rows = (db.query(WorkspaceMember, User)
            .join(User, User.id == WorkspaceMember.user_id)
            .filter(WorkspaceMember.workspace_id == pid)
            .order_by(WorkspaceMember.id).all())
    return [{"user_id": u.id, "email": u.email, "name": u.name, "role": m.role} for m, u in rows]


@router.post("/{pid}/members")
def add_member(pid: int, data: _MemberIn, request: Request,
               user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _require_owner(db, pid, user)
    target = db.query(User).filter(func.lower(User.email) == data.email.strip().lower()).first()
    if not target:
        raise HTTPException(404, errors.NO_SUCH_ACCOUNT)
    if is_member(db, pid, target.id):
        raise HTTPException(409, errors.ALREADY_MEMBER)
    # Anything unrecognised becomes viewer, not member. If a caller sends a role we don't
    # know, the safe reading is the least privilege it could have meant — defaulting the other
    # way turns a typo into write access.
    role = data.role if data.role in roles.ALL_ROLES else roles.VIEWER
    db.add(WorkspaceMember(workspace_id=pid, user_id=target.id, role=role))
    db.commit()
    audit.record(db, user, audit.MEMBER_ADD, workspace_id=pid, target_type="user",
                 target_id=target.id, target_label=target.email, detail={"role": role},
                 request=request)
    return {"user_id": target.id, "email": target.email, "name": target.name, "role": role}


@router.delete("/{pid}/members/{uid}")
def remove_member(pid: int, uid: int, request: Request,
                  user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _require_owner(db, pid, user)
    m = is_member(db, pid, uid)
    if not m:
        raise HTTPException(404, errors.NOT_A_MEMBER)
    owners = db.query(WorkspaceMember).filter(WorkspaceMember.workspace_id == pid,
                                              WorkspaceMember.role == "owner").count()
    if m.role == "owner" and owners <= 1:
        raise HTTPException(400, errors.LAST_OWNER)
    removed = db.get(User, uid)
    role = m.role
    db.delete(m)
    db.commit()
    audit.record(db, user, audit.MEMBER_REMOVE, workspace_id=pid, target_type="user",
                 target_id=uid, target_label=getattr(removed, "email", str(uid)),
                 detail={"role": role}, request=request)
    return {"ok": True}
