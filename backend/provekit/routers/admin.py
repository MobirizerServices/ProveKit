"""Platform superadmin — a global operator console across every user and project. Gated by
the superuser flag (or a bootstrap email in config.superuser_emails). This is separate from
per-project owner settings (see routers.projects)."""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import (AuditLog, Dataset, Experiment, Run, User, Workspace,
                      WorkspaceMember, iso_utc)
from ..services import audit, fleet, impersonation
from ..services.auth import get_current_user, is_bootstrap, is_operator
# The impersonated views deliberately reuse the tenant's own read path instead of
# re-implementing it: "what the tenant sees" is only true if it is literally the same query.
from .traces import _get_trace, _list_traces

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _operator(user: User = Depends(get_current_user)) -> User:
    """Effective superuser, re-checked per request — revoking the grant ends any in-flight
    impersonation session on its next call, without waiting for the cookie to expire."""
    if is_operator(user):
        return user
    raise HTTPException(403, "Superuser only")


def require_superuser(request: Request, user: User = Depends(_operator)) -> User:
    """Operator access to the console proper. An impersonating session is refused here even
    though it belongs to an operator: support mode must not be a way to run operator actions
    (grants, revokes) while wearing a tenant's view."""
    if impersonation.claim(request) is not None:
        raise HTTPException(403, "This session is impersonating a tenant. Stop impersonation "
                                 "(DELETE /api/admin/impersonate) before using operator tools.")
    return user


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


def _page(limit: int, offset: int) -> tuple[int, int]:
    return max(1, min(limit, 200)), max(0, offset)


@router.get("/users")
def list_users(limit: int = 50, offset: int = 0, q: str = "",
               _: User = Depends(require_superuser), db: Session = Depends(get_db)):
    """One page of users, newest-registered last. `q` matches email or name."""
    limit, offset = _page(limit, offset)
    query = db.query(User)
    if q.strip():
        term = f"%{q.strip()}%"
        query = query.filter(or_(User.email.ilike(term), User.name.ilike(term)))
    total = query.order_by(None).count()
    rows = query.order_by(User.id).limit(limit).offset(offset).all()
    # Count memberships only for the users on this page — grouping over the whole table would
    # scan every membership row on every request and give pagination nothing to save.
    ids = [u.id for u in rows]
    proj_counts = dict(db.query(WorkspaceMember.user_id, func.count(WorkspaceMember.id))
                       .filter(WorkspaceMember.user_id.in_(ids))
                       .group_by(WorkspaceMember.user_id).all()) if ids else {}
    # `is_superuser` is the *effective* answer; `is_bootstrap` says it comes from config, so the
    # UI can show that the grant isn't revocable here instead of offering a toggle that no-ops.
    return {"total": total, "limit": limit, "offset": offset, "users": [
        {"id": u.id, "email": u.email, "name": u.name, "auth_provider": u.auth_provider,
         "is_superuser": u.is_superuser or is_bootstrap(u.email),
         "is_bootstrap": is_bootstrap(u.email),
         "project_count": proj_counts.get(u.id, 0), "created_at": iso_utc(u.created_at)}
        for u in rows]}


@router.get("/projects")
def list_all_projects(limit: int = 50, offset: int = 0, q: str = "",
                      _: User = Depends(require_superuser), db: Session = Depends(get_db)):
    """One page of projects. `q` matches the project name or its owner's email."""
    limit, offset = _page(limit, offset)
    query = db.query(Workspace)
    if q.strip():
        term = f"%{q.strip()}%"
        query = (query.outerjoin(User, User.id == Workspace.owner_user_id)
                 .filter(or_(Workspace.name.ilike(term), User.email.ilike(term))))
    total = query.order_by(None).count()
    rows = query.order_by(Workspace.id).limit(limit).offset(offset).all()
    ids = [w.id for w in rows]
    owners = dict(db.query(Workspace.id, User.email)
                  .join(User, User.id == Workspace.owner_user_id)
                  .filter(Workspace.id.in_(ids)).all()) if ids else {}
    members = dict(db.query(WorkspaceMember.workspace_id, func.count(WorkspaceMember.id))
                   .filter(WorkspaceMember.workspace_id.in_(ids))
                   .group_by(WorkspaceMember.workspace_id).all()) if ids else {}
    spans = dict(db.query(Run.workspace_id, func.count(Run.id))
                 .filter(Run.workspace_id.in_(ids))
                 .group_by(Run.workspace_id).all()) if ids else {}
    return {"total": total, "limit": limit, "offset": offset, "projects": [
        {"id": w.id, "name": w.name, "owner": owners.get(w.id, ""),
         "member_count": members.get(w.id, 0), "span_count": spans.get(w.id, 0),
         "retention": w.retention, "redact_pii": w.redact_pii,
         "created_at": iso_utc(w.created_at)} for w in rows]}


@router.get("/fleet")
def fleet_health(window_hours: int = fleet.DEFAULT_WINDOW_HOURS, limit: int = fleet.DEFAULT_LIMIT,
                 _: User = Depends(require_superuser), db: Session = Depends(get_db)):
    """Per-tenant ingest volume, trend, error rate, size and freshness — worst tenant first.

    `/projects` answers "how big is each project"; this answers "who is responsible for what
    the instance dashboard is showing me right now", which is the question actually being asked
    during an incident. Ordered by share of the instance's own traces and failures, so the top
    row is the tenant to look at. See services/fleet.py for why nothing here scans raw spans.
    """
    return fleet.snapshot(db, window_hours=window_hours, limit=limit)


@router.get("/audit")
def list_audit(limit: int = 50, offset: int = 0, action: str = "", q: str = "",
               _: User = Depends(require_superuser), db: Session = Depends(get_db)):
    """The audit trail, newest first. `action` filters exactly (e.g. `superuser.grant`);
    `q` matches the actor's email or the target's label."""
    limit, offset = _page(limit, offset)
    query = db.query(AuditLog)
    if action.strip():
        query = query.filter(AuditLog.action == action.strip())
    if q.strip():
        term = f"%{q.strip()}%"
        query = query.filter(or_(AuditLog.actor_email.ilike(term),
                                 AuditLog.target_label.ilike(term)))
    total = query.order_by(None).count()
    rows = query.order_by(AuditLog.id.desc()).limit(limit).offset(offset).all()
    return {"total": total, "limit": limit, "offset": offset, "entries": [
        {"id": r.id, "action": r.action, "actor_email": r.actor_email,
         "actor_user_id": r.actor_user_id, "workspace_id": r.workspace_id,
         "target_type": r.target_type, "target_id": r.target_id,
         "target_label": r.target_label, "detail": r.detail or {}, "ip": r.ip,
         "created_at": iso_utc(r.created_at)} for r in rows]}


@router.patch("/users/{uid}")
def set_superuser(uid: int, data: _SuperIn, request: Request,
                  me: User = Depends(require_superuser), db: Session = Depends(get_db)):
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
    # Operator access is the highest-privilege change in the product; if only one thing is
    # ever audited, it is this.
    audit.record(db, me, audit.SUPERUSER_GRANT if data.is_superuser else audit.SUPERUSER_REVOKE,
                 target_type="user", target_id=u.id, target_label=u.email, request=request)
    return {"id": u.id, "is_superuser": u.is_superuser or is_bootstrap(u.email),
            "is_bootstrap": is_bootstrap(u.email)}


# ---- impersonation: read-only "view as tenant" (services/impersonation.py) ----
class _ImpersonateIn(BaseModel):
    workspace_id: int
    # Required, and recorded in the audit row. A support tool whose trail says *who* looked but
    # not *why* answers half the question a customer will ask afterwards.
    reason: str = Field(min_length=3, max_length=200)
    minutes: int = Field(default=impersonation.DEFAULT_MINUTES, ge=1, le=impersonation.MAX_MINUTES)


def current_impersonation(request: Request, me: User = Depends(_operator),
                          db: Session = Depends(get_db)) -> tuple[User, Workspace, impersonation.Claim]:
    """The active support session, or 403. Every impersonated read goes through here."""
    claim = impersonation.claim(request)
    if claim is None:
        raise HTTPException(403, "No active impersonation session")
    ws = db.get(Workspace, claim.workspace_id)
    if ws is None:
        raise HTTPException(404, "That project no longer exists")
    return me, ws, claim


def _status(db: Session, ws: Workspace, claim: impersonation.Claim) -> dict:
    owner = db.query(User.email).filter(User.id == ws.owner_user_id).scalar() or ""
    return {"active": True, "read_only": True, "workspace_id": ws.id, "workspace": ws.name,
            "owner": owner, "expires_at": claim.expires_at,
            "seconds_remaining": claim.seconds_remaining,
            "span_count": db.query(func.count(Run.id)).filter(Run.workspace_id == ws.id).scalar() or 0}


@router.post("/impersonate")
def start_impersonation(data: _ImpersonateIn, request: Request, response: Response,
                        me: User = Depends(require_superuser), db: Session = Depends(get_db)):
    """Begin a time-boxed, read-only view of one project. Replaces the caller's session cookie
    with one that carries the impersonation claim — so it expires on its own, and every write
    in the deployment is refused until it is stopped."""
    ws = db.get(Workspace, data.workspace_id)
    if not ws:
        raise HTTPException(404, "Project not found")
    seconds = data.minutes * 60
    token = impersonation.issue(me, ws.id, seconds)
    # Read the claim back out of the token we just signed rather than recomputing the deadline:
    # the response then reports exactly what the cookie will be judged by.
    claim = impersonation.claim_from_token(token)
    impersonation.set_impersonation_cookie(response, token, seconds)
    audit.record(db, me, impersonation.START, workspace_id=ws.id, target_type="project",
                 target_id=ws.id, target_label=ws.name, request=request,
                 detail={"reason": data.reason, "minutes": data.minutes, "read_only": True})
    return _status(db, ws, claim)


@router.get("/impersonate")
def impersonation_status(request: Request, me: User = Depends(_operator),
                         db: Session = Depends(get_db)):
    """Whether this session is impersonating, and for how much longer — the banner the console
    keeps on screen. Answers `{"active": false}` rather than 403 so it can be polled always."""
    claim = impersonation.claim(request)
    if claim is None:
        return {"active": False}
    ws = db.get(Workspace, claim.workspace_id)
    if ws is None:
        return {"active": False}
    return _status(db, ws, claim)


@router.delete("/impersonate")
def stop_impersonation(request: Request, response: Response,
                       session: tuple = Depends(current_impersonation),
                       db: Session = Depends(get_db)):
    """End support mode and hand the operator back their own session. The one write allowed
    while impersonating (see impersonation.STOP_ROUTE) — the exit must never be blocked."""
    me, ws, claim = session
    impersonation.restore_session_cookie(response, me)
    audit.record(db, me, impersonation.STOP, workspace_id=ws.id, target_type="project",
                 target_id=ws.id, target_label=ws.name, request=request,
                 detail={"seconds_remaining": claim.seconds_remaining})
    return {"active": False, "workspace_id": ws.id, "workspace": ws.name}


@router.get("/impersonate/traces")
def impersonated_traces(limit: int = 50, status: str | None = None, window_hours: int | None = None,
                        q: str | None = None, cursor: int | None = None,
                        session: tuple = Depends(current_impersonation),
                        db: Session = Depends(get_db)):
    """The tenant's trace list, exactly as `/api/traces` renders it for them."""
    _, ws, _claim = session
    return _list_traces(db, ws, limit, status, window_hours, search=q, cursor=cursor)


@router.get("/impersonate/traces/{trace_id}")
def impersonated_trace(trace_id: str, session: tuple = Depends(current_impersonation),
                       db: Session = Depends(get_db)):
    """All spans of one of the tenant's traces — the same payload `/api/traces/{id}` returns."""
    _, ws, _claim = session
    return _get_trace(db, ws, trace_id)
