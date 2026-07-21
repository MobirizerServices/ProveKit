"""Platform superadmin — a global operator console across every user and project. Gated by
the superuser flag (or a bootstrap email in config.superuser_emails). This is separate from
per-project owner settings (see routers.projects)."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import (Dataset, Experiment, Run, User, Workspace, WorkspaceMember, iso_utc)
from ..services.auth import get_current_user, is_bootstrap, is_operator

router = APIRouter(prefix="/api/admin", tags=["admin"])


def require_superuser(user: User = Depends(get_current_user)) -> User:
    if is_operator(user):
        return user
    raise HTTPException(403, "Superuser only")


class _SuperIn(BaseModel):
    is_superuser: bool


@router.get("/stats")
def stats(_: User = Depends(require_superuser), db: Session = Depends(get_db)):
    def n(model, *filters):
        q = db.query(func.count(model.id))
        for f in filters:
            q = q.filter(f)
        return q.scalar() or 0
    return {
        "users": n(User),
        "projects": n(Workspace),
        "members": n(WorkspaceMember),
        "spans": n(Run),
        "traces": n(Run, Run.parent_span_id == ""),
        "datasets": n(Dataset),
        "experiments": n(Experiment),
    }


@router.get("/users")
def list_users(_: User = Depends(require_superuser), db: Session = Depends(get_db)):
    proj_counts = dict(db.query(WorkspaceMember.user_id, func.count(WorkspaceMember.id))
                       .group_by(WorkspaceMember.user_id).all())
    rows = db.query(User).order_by(User.id).all()
    # `is_superuser` is the *effective* answer; `is_bootstrap` says it comes from config, so the
    # UI can show that the grant isn't revocable here instead of offering a toggle that no-ops.
    return [{"id": u.id, "email": u.email, "name": u.name, "auth_provider": u.auth_provider,
             "is_superuser": u.is_superuser or is_bootstrap(u.email),
             "is_bootstrap": is_bootstrap(u.email),
             "project_count": proj_counts.get(u.id, 0), "created_at": iso_utc(u.created_at)}
            for u in rows]


@router.get("/projects")
def list_all_projects(_: User = Depends(require_superuser), db: Session = Depends(get_db)):
    owners = dict(db.query(Workspace.id, User.email)
                  .join(User, User.id == Workspace.owner_user_id).all())
    members = dict(db.query(WorkspaceMember.workspace_id, func.count(WorkspaceMember.id))
                   .group_by(WorkspaceMember.workspace_id).all())
    spans = dict(db.query(Run.workspace_id, func.count(Run.id))
                 .group_by(Run.workspace_id).all())
    rows = db.query(Workspace).order_by(Workspace.id).all()
    return [{"id": w.id, "name": w.name, "owner": owners.get(w.id, ""),
             "member_count": members.get(w.id, 0), "span_count": spans.get(w.id, 0),
             "retention": w.retention, "redact_pii": w.redact_pii,
             "created_at": iso_utc(w.created_at)} for w in rows]


@router.patch("/users/{uid}")
def set_superuser(uid: int, data: _SuperIn, me: User = Depends(require_superuser),
                  db: Session = Depends(get_db)):
    u = db.get(User, uid)
    if not u:
        raise HTTPException(404, "User not found")
    if u.id == me.id and not data.is_superuser:
        raise HTTPException(400, "You can't remove your own superuser access")
    if not data.is_superuser and is_bootstrap(u.email):
        # Clearing the flag would leave config still granting access — a revoke that looks like
        # it worked but didn't. Refuse loudly and say what actually revokes it.
        raise HTTPException(
            409,
            f"{u.email} is a superuser via the SUPERUSER_EMAILS config, which overrides this "
            "flag. Remove the address from SUPERUSER_EMAILS and restart the backend to revoke "
            "it — clearing the flag here would have no effect.",
        )
    u.is_superuser = data.is_superuser
    db.commit()
    return {"id": u.id, "is_superuser": u.is_superuser or is_bootstrap(u.email),
            "is_bootstrap": is_bootstrap(u.email)}
