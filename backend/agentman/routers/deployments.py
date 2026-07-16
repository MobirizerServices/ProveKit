"""Deployments — publish a flow as a hosted, versioned endpoint. Workspace-scoped.
The public invocation route lives in routers/runtime.py."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..models import Deployment, Flow, Run, Workspace, iso_utc
from ..services import deploy
from ..services.workspace import current_workspace

router = APIRouter(prefix="/api/deployments", tags=["deployments"])


def _public(d: Deployment, url: str | None = None) -> dict:
    out = {"id": d.id, "slug": d.slug, "version": d.version, "name": d.name,
           "flow_id": d.flow_id, "active": d.active, "created_at": iso_utc(d.created_at)}
    if url:
        out["url"] = url
    return out


def _endpoint(slug: str) -> str:
    base = get_settings().public_base_url.rstrip("/")
    return f"{base}/v1/d/{slug}"


class DeployIn(BaseModel):
    flow_id: int


@router.post("")
def create_deployment(payload: DeployIn, db: Session = Depends(get_db), ws: Workspace = Depends(current_workspace)):
    """Publish a flow. First publish mints an API key (returned once); redeploys of the
    same flow bump the version, snapshot the current graph, and keep the key."""
    f = db.get(Flow, payload.flow_id)
    if not f or f.workspace_id != ws.id:
        raise HTTPException(404, "Flow not found")

    prior = (db.query(Deployment)
             .filter(Deployment.workspace_id == ws.id, Deployment.flow_id == f.id)
             .order_by(Deployment.version.desc()).first())
    snapshot = {"nodes": f.nodes, "edges": f.edges}
    plaintext = None
    if prior:
        key_hash, slug, version = prior.api_key_hash, prior.slug, prior.version + 1
        for d in db.query(Deployment).filter(Deployment.slug == slug, Deployment.active.is_(True)).all():
            d.active = False
    else:
        plaintext, key_hash = deploy.new_api_key()
        slug, version = _unique_slug(db, deploy.slugify(f.name)), 1

    d = Deployment(workspace_id=ws.id, flow_id=f.id, slug=slug, version=version,
                   name=f.name, snapshot=snapshot, api_key_hash=key_hash, active=True)
    db.add(d); db.commit(); db.refresh(d)
    resp = _public(d, _endpoint(slug))
    if plaintext:  # shown exactly once
        resp["api_key"] = plaintext
    return resp


def _unique_slug(db, base: str) -> str:
    slug, n = base, 2
    while db.query(Deployment).filter(Deployment.slug == slug).first():
        slug = f"{base}-{n}"; n += 1
    return slug


@router.get("")
def list_deployments(db: Session = Depends(get_db), ws: Workspace = Depends(current_workspace)):
    """One row per slug (the active/latest version), with version count."""
    rows = db.query(Deployment).filter(Deployment.workspace_id == ws.id).order_by(Deployment.id.desc()).all()
    by_slug: dict[str, dict] = {}
    for d in rows:
        cur = by_slug.get(d.slug)
        if not cur or d.version > cur["version"]:
            by_slug[d.slug] = {**_public(d, _endpoint(d.slug)), "versions": 0}
    for d in rows:
        by_slug[d.slug]["versions"] += 1
    return list(by_slug.values())


@router.get("/{slug}")
def get_deployment(slug: str, db: Session = Depends(get_db), ws: Workspace = Depends(current_workspace)):
    rows = (db.query(Deployment)
            .filter(Deployment.workspace_id == ws.id, Deployment.slug == slug)
            .order_by(Deployment.version.desc()).all())
    if not rows:
        raise HTTPException(404, "Deployment not found")
    active = next((r for r in rows if r.active), rows[0])
    return {**_public(active, _endpoint(slug)),
            "versions": [{"version": r.version, "active": r.active, "created_at": iso_utc(r.created_at)} for r in rows]}


@router.get("/{slug}/runs")
def deployment_runs(slug: str, limit: int = 50, db: Session = Depends(get_db), ws: Workspace = Depends(current_workspace)):
    """Recent invocations of this deployment (all versions)."""
    dep_ids = [d.id for d in db.query(Deployment.id).filter(Deployment.workspace_id == ws.id, Deployment.slug == slug).all()]
    if not dep_ids:
        raise HTTPException(404, "Deployment not found")
    rows = (db.query(Run).filter(Run.deployment_id.in_(dep_ids))
            .order_by(Run.id.desc()).limit(min(limit, 200)).all())
    return [{"id": r.id, "status": r.status, "duration_ms": r.duration_ms,
             "created_at": iso_utc(r.created_at)} for r in rows]


@router.get("/{slug}/stats")
def deployment_stats(slug: str, db: Session = Depends(get_db), ws: Workspace = Depends(current_workspace)):
    """Aggregate metrics: invocations, error rate, p50/p95 latency."""
    dep_ids = [d.id for d in db.query(Deployment.id).filter(Deployment.workspace_id == ws.id, Deployment.slug == slug).all()]
    if not dep_ids:
        raise HTTPException(404, "Deployment not found")
    rows = db.query(Run.status, Run.duration_ms).filter(Run.deployment_id.in_(dep_ids)).all()
    total = len(rows)
    failed = sum(1 for s, _ in rows if s == "failed")
    durs = sorted(d for _, d in rows if d is not None)

    def pct(p):
        if not durs:
            return 0
        return durs[min(len(durs) - 1, int(len(durs) * p))]
    return {"invocations": total, "failed": failed,
            "error_rate": round(failed / total, 4) if total else 0.0,
            "p50_ms": pct(0.50), "p95_ms": pct(0.95)}


@router.post("/{slug}/deactivate")
def deactivate(slug: str, db: Session = Depends(get_db), ws: Workspace = Depends(current_workspace)):
    rows = db.query(Deployment).filter(Deployment.workspace_id == ws.id, Deployment.slug == slug).all()
    if not rows:
        raise HTTPException(404, "Deployment not found")
    for r in rows:
        r.active = False
    db.commit()
    return {"ok": True}


class RollbackIn(BaseModel):
    version: int


@router.post("/{slug}/rollback")
def rollback(slug: str, payload: RollbackIn, db: Session = Depends(get_db), ws: Workspace = Depends(current_workspace)):
    rows = db.query(Deployment).filter(Deployment.workspace_id == ws.id, Deployment.slug == slug).all()
    target = next((r for r in rows if r.version == payload.version), None)
    if not target:
        raise HTTPException(404, "Version not found")
    for r in rows:
        r.active = (r.version == payload.version)
    db.commit()
    return _public(target, _endpoint(slug))
