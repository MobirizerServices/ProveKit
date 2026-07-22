"""Runtime prompt fetch and A/B configuration (services/prompts.py)."""
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Prompt, Workspace
from ..services import prompts as prompt_svc
from ..services.workspace import current_workspace, workspace_from_key

router = APIRouter(prefix="/api/prompts", tags=["prompts"])
key_router = APIRouter(prefix="/v1/prompts", tags=["prompts"])


@key_router.get("/{name}")
def fetch_prompt(name: str, request: Request, label: str = "", key: str = "",
                 db: Session = Depends(get_db),
                 authorization: str | None = Header(default=None)):
    """Fetch a prompt at runtime, by label or through an active traffic split.

    Key-authed because this is called by the customer's application, not their browser — that
    is the whole point of #61: changing a prompt should not need a deploy.
    """
    ws = workspace_from_key(db, request, authorization)
    p, reason = prompt_svc.resolve(db, ws.id, name, label=label, key=key)
    if p is None:
        raise HTTPException(404, reason)
    return prompt_svc.as_dict(p, reason)


class _LabelIn(BaseModel):
    label: str = ""


class _SplitIn(BaseModel):
    weights: dict[int, float] = {}      # version -> traffic weight


@router.post("/{name}/label")
def set_label(name: str, version: int, data: _LabelIn, db: Session = Depends(get_db),
              ws: Workspace = Depends(current_workspace)):
    """Move a label onto a version. Labels are unique per name, so this moves rather than adds —
    two versions both labelled "production" would make the fetch ambiguous."""
    if data.label and data.label not in prompt_svc.LABELS:
        raise HTTPException(422, f"label must be one of {list(prompt_svc.LABELS)}")
    rows = (db.query(Prompt)
            .filter(Prompt.workspace_id == ws.id, Prompt.name == name).all())
    target = next((p for p in rows if p.version == version), None)
    if target is None:
        raise HTTPException(404, "No such prompt version")
    for p in rows:
        if p.label == data.label:
            p.label = ""
    target.label = data.label
    db.commit()
    return {"name": name, "version": version, "label": target.label}


@router.post("/{name}/split")
def set_split(name: str, data: _SplitIn, db: Session = Depends(get_db),
              ws: Workspace = Depends(current_workspace)):
    """Set the live traffic split across versions of one prompt."""
    rows = (db.query(Prompt)
            .filter(Prompt.workspace_id == ws.id, Prompt.name == name).all())
    if not rows:
        raise HTTPException(404, "No prompt with that name")
    known = {p.version for p in rows}
    unknown = [v for v in data.weights if v not in known]
    if unknown:
        raise HTTPException(422, f"unknown version(s) {unknown}")
    for p in rows:
        p.traffic = float(data.weights.get(p.version, 0) or 0)
    try:
        prompt_svc.validate_split(rows)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(422, str(exc)) from None
    db.commit()
    return {"name": name, "weights": {p.version: p.traffic for p in rows if p.traffic > 0}}
