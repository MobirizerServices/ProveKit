"""Alerts — threshold rules over the dashboard metrics (error rate, latency, volume, tokens).
Evaluated on demand via POST /api/alerts/check (wire it to a cron); a breach outside the
rule's cooldown sends an email."""
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Alert, Workspace, _now, iso_utc
from ..services import email, errors, notify
from ..services.netguard import guard_url
from ..services.workspace import current_workspace
from .metrics import compute_metrics

router = APIRouter(prefix="/api/alerts", tags=["alerts"])

# Metrics an alert may watch. Volume and speed come from compute_metrics(); quality comes from
# _quality_metrics() below, which is computed only when a rule actually watches it.
_VOLUME_METRICS = {"error_rate", "latency_p50_ms", "latency_p95_ms", "trace_count",
                   "total_tokens", "error_count"}
# Quality (#49). Everything above answers "is it up and fast" — nothing answered "is it still
# any good", which is the question an eval stack exists to ask. `judge_kappa` is the one that
# matters: a judge drifting out of agreement with humans silently invalidates every online
# score downstream of it, and nothing else in the product would notice.
_QUALITY_METRICS = {"judge_kappa", "judge_agreement", "eval_mean_score", "human_mean_score"}
_METRICS = _VOLUME_METRICS | _QUALITY_METRICS
_COMPARATORS = {"gt", "lt"}


class _AlertIn(BaseModel):
    name: str = ""
    metric: str
    comparator: str = "gt"
    threshold: float = 0.0
    window_hours: int = 24
    email: str = ""
    webhook_url: str = ""
    enabled: bool = True


class _AlertPatch(BaseModel):
    enabled: bool


def _row(a: Alert) -> dict:
    return {"id": a.id, "name": a.name, "metric": a.metric, "comparator": a.comparator,
            "threshold": a.threshold, "window_hours": a.window_hours, "email": a.email,
            "webhook_url": a.webhook_url, "enabled": a.enabled,
            "last_triggered_at": iso_utc(a.last_triggered_at),
            "created_at": iso_utc(a.created_at)}


def _get(db: Session, ws: Workspace, aid: int) -> Alert:
    a = db.get(Alert, aid)
    if not a or a.workspace_id != ws.id:
        raise HTTPException(404, errors.not_in_project("alert", "GET /api/alerts"))
    return a


def _quality_metrics(db: Session, ws: Workspace, window_hours: int) -> dict[str, float | None]:
    """Quality signals an alert can watch. A value of None means *we don't know*.

    None is load-bearing here. `_fire` skips a metric it can't read, so a judge with too few
    paired labels never triggers an alert — calibration already refuses to publish a kappa below
    `MIN_LABELLED_N`, and an alerting path that quietly substituted 0.0 for "unmeasured" would
    page someone at 3am about a number the product declines to state on screen.
    """
    from ..models import Feedback
    from ..services import calibration

    rows = (db.query(Feedback)
            .filter(Feedback.workspace_id == ws.id,
                    Feedback.source.in_(sorted(calibration.HUMAN_SOURCES | calibration.JUDGE_SOURCES)))
            .order_by(Feedback.id.asc()).all())
    cal = calibration.calibrate(rows)

    def _mean(sources: frozenset[str]) -> float | None:
        cutoff = _now() - timedelta(hours=max(1, window_hours))
        vals = [float(f.score) for f in rows
                if f.source in sources and f.score is not None and _aware(f.created_at) >= cutoff]
        return sum(vals) / len(vals) if vals else None

    return {
        # Both None until calibration has enough paired labels to say anything.
        "judge_kappa": cal.get("kappa"),
        "judge_agreement": cal.get("agreement"),
        "eval_mean_score": _mean(calibration.JUDGE_SOURCES),
        "human_mean_score": _mean(calibration.HUMAN_SOURCES),
    }


def _aware(dt):
    from datetime import timezone
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


@router.post("")
def create_alert(data: _AlertIn, db: Session = Depends(get_db),
                 ws: Workspace = Depends(current_workspace)):
    if data.metric not in _METRICS:
        raise HTTPException(422, errors.bad_alert_metric(data.metric, _METRICS))
    if data.comparator not in _COMPARATORS:
        raise HTTPException(422, errors.bad_comparator(data.comparator))
    hook = data.webhook_url.strip()[:500]
    if hook:
        # Reject a bad or internal URL now, while someone is looking at the form. Discovering
        # it at 3am via a breach that notified nobody is the failure this feature exists to fix.
        try:
            guard_url(hook)
        except Exception as exc:
            raise HTTPException(422, errors.bad_webhook(str(exc)))
    a = Alert(workspace_id=ws.id, name=data.name[:160] or data.metric, metric=data.metric,
              comparator=data.comparator, threshold=data.threshold,
              window_hours=max(1, data.window_hours), email=data.email[:255],
              webhook_url=hook, enabled=data.enabled)
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


def _message(a: Alert, ws: Workspace, value) -> str:
    """One wording for every channel, so email and chat can't describe a breach differently."""
    return (f"{a.metric} is {value} ({a.comparator} {a.threshold}) over the last "
            f"{a.window_hours}h in project {ws.name}.")


def check_alerts(db: Session, ws: Workspace) -> list[dict]:
    """Evaluate every enabled alert; fire (record + notify) any breach outside its cooldown.
    Returns the list that fired this run."""
    fired = []
    now = _now()
    for a in db.query(Alert).filter(Alert.workspace_id == ws.id, Alert.enabled.is_(True)).all():
        if a.metric in _QUALITY_METRICS:
            value = _quality_metrics(db, ws, a.window_hours).get(a.metric)
        else:
            value = compute_metrics(db, ws, a.window_hours).get(a.metric)
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
        body = _message(a, ws, value)
        if a.email:
            email.send(a.email, f"[ProveKit] alert: {a.name}", body)
        delivered = notify.send_webhook(a.webhook_url, f"*[ProveKit] {a.name}* — {body}")
        fired.append({"id": a.id, "name": a.name, "metric": a.metric, "value": value,
                      "threshold": a.threshold,
                      # surfaced so a cron/CI caller can tell a silent delivery failure from a
                      # rule that simply has no webhook configured
                      "webhook_delivered": delivered if a.webhook_url else None})
    return fired


@router.post("/check")
def run_check(db: Session = Depends(get_db), ws: Workspace = Depends(current_workspace)):
    """Evaluate all enabled alerts now and return the ones that fired."""
    return {"fired": check_alerts(db, ws)}
