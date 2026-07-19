"""Alerts — threshold rules over the dashboard metrics (error rate, latency, volume, tokens).
Evaluated on demand via POST /api/alerts/check (wire it to a cron); a breach outside the
rule's cooldown sends an email."""
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Alert, Workspace, _now, iso_utc
from ..services import email
from ..services.workspace import current_workspace
from .metrics import compute_metrics

router = APIRouter(prefix="/api/alerts", tags=["alerts"])

# Metrics an alert may watch (must be numeric keys of compute_metrics()).
_METRICS = {"error_rate", "latency_p50_ms", "latency_p95_ms", "trace_count", "total_tokens", "error_count"}
_COMPARATORS = {"gt", "lt"}


class _AlertIn(BaseModel):
    name: str = ""
    metric: str
    comparator: str = "gt"
    threshold: float = 0.0
    window_hours: int = 24
    email: str = ""
    enabled: bool = True


class _AlertPatch(BaseModel):
    enabled: bool


def _row(a: Alert) -> dict:
    return {"id": a.id, "name": a.name, "metric": a.metric, "comparator": a.comparator,
            "threshold": a.threshold, "window_hours": a.window_hours, "email": a.email,
            "enabled": a.enabled, "last_triggered_at": iso_utc(a.last_triggered_at),
            "created_at": iso_utc(a.created_at)}


def _get(db: Session, ws: Workspace, aid: int) -> Alert:
    a = db.get(Alert, aid)
    if not a or a.workspace_id != ws.id:
        raise HTTPException(404, "Alert not found")
    return a


@router.post("")
def create_alert(data: _AlertIn, db: Session = Depends(get_db),
                 ws: Workspace = Depends(current_workspace)):
    if data.metric not in _METRICS:
        raise HTTPException(422, f"metric must be one of {sorted(_METRICS)}")
    if data.comparator not in _COMPARATORS:
        raise HTTPException(422, "comparator must be 'gt' or 'lt'")
    a = Alert(workspace_id=ws.id, name=data.name[:160] or data.metric, metric=data.metric,
              comparator=data.comparator, threshold=data.threshold,
              window_hours=max(1, data.window_hours), email=data.email[:255], enabled=data.enabled)
    db.add(a)
    db.commit()
    return _row(a)


@router.get("")
def list_alerts(db: Session = Depends(get_db), ws: Workspace = Depends(current_workspace)):
    rows = db.query(Alert).filter(Alert.workspace_id == ws.id).order_by(Alert.id.desc()).all()
    return [_row(a) for a in rows]


@router.patch("/{aid}")
def toggle_alert(aid: int, data: _AlertPatch, db: Session = Depends(get_db),
                 ws: Workspace = Depends(current_workspace)):
    a = _get(db, ws, aid)
    a.enabled = data.enabled
    db.commit()
    return _row(a)


@router.delete("/{aid}")
def delete_alert(aid: int, db: Session = Depends(get_db),
                 ws: Workspace = Depends(current_workspace)):
    db.delete(_get(db, ws, aid))
    db.commit()
    return {"ok": True}


def _breached(value: float, comparator: str, threshold: float) -> bool:
    return value > threshold if comparator == "gt" else value < threshold


def check_alerts(db: Session, ws: Workspace) -> list[dict]:
    """Evaluate every enabled alert; fire (record + email) any breach outside its cooldown.
    Returns the list that fired this run."""
    fired = []
    now = _now()
    for a in db.query(Alert).filter(Alert.workspace_id == ws.id, Alert.enabled.is_(True)).all():
        m = compute_metrics(db, ws, a.window_hours)
        value = m.get(a.metric)
        if value is None or not _breached(float(value), a.comparator, a.threshold):
            continue
        # cooldown: don't re-fire within the rule's own window
        last = a.last_triggered_at
        if last is not None:
            if last.tzinfo is None:
                last = last.replace(tzinfo=now.tzinfo)
            if now - last < timedelta(hours=a.window_hours):
                continue
        a.last_triggered_at = now
        db.commit()
        if a.email:
            email.send(a.email, f"[ProveKit] alert: {a.name}",
                       f"{a.metric} is {value} ({a.comparator} {a.threshold}) over the last "
                       f"{a.window_hours}h in project {ws.name}.")
        fired.append({"id": a.id, "name": a.name, "metric": a.metric, "value": value,
                      "threshold": a.threshold})
    return fired


@router.post("/check")
def run_check(db: Session = Depends(get_db), ws: Workspace = Depends(current_workspace)):
    """Evaluate all enabled alerts now and return the ones that fired."""
    return {"fired": check_alerts(db, ws)}
