"""Automation rules — route production traces into datasets and online scoring."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AutomationRule, Dataset, Workspace, iso_utc
from ..services import automation
from ..services.workspace import current_workspace

router = APIRouter(prefix="/api/automation", tags=["automation"])


class _RuleIn(BaseModel):
    name: str = ""
    match: dict = {}
    action: str = "promote"
    target_dataset_id: int | None = None
    scorers: list[str] = []
    sample: float = 1.0
    enabled: bool = True


def _row(r: AutomationRule) -> dict:
    return {"id": r.id, "name": r.name, "match": r.match or {}, "action": r.action,
            "target_dataset_id": r.target_dataset_id, "scorers": r.scorers or [],
            "sample": r.sample, "enabled": r.enabled, "matched": r.matched, "acted": r.acted,
            "last_run_id": r.last_run_id, "last_status": r.last_status,
            "created_at": iso_utc(r.created_at)}


@router.get("")
def list_rules(db: Session = Depends(get_db), ws: Workspace = Depends(current_workspace)):
    rows = (db.query(AutomationRule).filter(AutomationRule.workspace_id == ws.id)
            .order_by(AutomationRule.id.asc()).all())
    return [_row(r) for r in rows]


@router.post("")
def create_rule(data: _RuleIn, db: Session = Depends(get_db),
                ws: Workspace = Depends(current_workspace)):
    try:
        automation.validate(data.match, data.action, target_dataset_id=data.target_dataset_id,
                            scorers=data.scorers, sample=data.sample)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    if data.target_dataset_id:
        ds = db.get(Dataset, data.target_dataset_id)
        if not ds or ds.workspace_id != ws.id:
            raise HTTPException(404, "Target dataset not found in this project")
    # Start the watermark at the newest existing trace: a new rule acts on new traffic, not on
    # a project's whole history. Sweeping backwards would be a surprise, and for a `score` rule
    # a judge call against every trace ever captured.
    from sqlalchemy import func

    from ..models import Run
    newest = (db.query(func.max(Run.id))
              .filter(Run.workspace_id == ws.id).scalar()) or 0
    r = AutomationRule(workspace_id=ws.id, name=(data.name or "rule")[:160],
                       match={k: v for k, v in data.match.items() if k in automation.MATCH_KEYS},
                       action=data.action, target_dataset_id=data.target_dataset_id,
                       scorers=data.scorers, sample=data.sample, enabled=data.enabled,
                       last_run_id=newest)
    db.add(r)
    db.commit()
    db.refresh(r)
    return _row(r)


@router.post("/{rule_id}/run")
def run_now(rule_id: int, db: Session = Depends(get_db),
            ws: Workspace = Depends(current_workspace)):
    """Advance one rule immediately — so you can see what it does without waiting for a pass."""
    r = db.get(AutomationRule, rule_id)
    if not r or r.workspace_id != ws.id:
        raise HTTPException(404, "Rule not found")
    out = automation.run_rule(db, r)
    db.commit()
    return {**out, "rule": _row(r)}


@router.delete("/{rule_id}")
def delete_rule(rule_id: int, db: Session = Depends(get_db),
                ws: Workspace = Depends(current_workspace)):
    r = db.get(AutomationRule, rule_id)
    if not r or r.workspace_id != ws.id:
        raise HTTPException(404, "Rule not found")
    db.delete(r)
    db.commit()
    return {"ok": True}
