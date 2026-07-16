"""Prompt Registry — manage reusable prompts, scoped per workspace."""
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Prompt, Workspace, iso_utc
from ..services.workspace import current_workspace

router = APIRouter(prefix="/api/prompts", tags=["prompts"])


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9.]+", "-", s.lower()).strip("-") or "prompt"


def _p(p: Prompt) -> dict:
    return {"id": p.id, "key": p.key, "name": p.name, "description": p.description,
            "content": p.content, "updated_at": iso_utc(p.updated_at)}


class PromptIn(BaseModel):
    key: str | None = None
    name: str
    description: str = ""
    content: str = ""


@router.get("")
def list_prompts(db: Session = Depends(get_db), ws: Workspace = Depends(current_workspace)):
    return [_p(p) for p in db.query(Prompt).filter(Prompt.workspace_id == ws.id).order_by(Prompt.key).all()]


@router.post("")
def create_prompt(payload: PromptIn, db: Session = Depends(get_db), ws: Workspace = Depends(current_workspace)):
    def taken(k: str) -> bool:
        return db.query(Prompt).filter(Prompt.workspace_id == ws.id, Prompt.key == k).first() is not None
    key = payload.key or _slug(payload.name)
    if taken(key):
        base, n = key, 2
        while taken(key):
            key = f"{base}-{n}"; n += 1
    p = Prompt(workspace_id=ws.id, key=key, name=payload.name, description=payload.description, content=payload.content)
    db.add(p); db.commit(); db.refresh(p)
    return _p(p)


@router.put("/{pid}")
def update_prompt(pid: int, payload: PromptIn, db: Session = Depends(get_db), ws: Workspace = Depends(current_workspace)):
    p = db.get(Prompt, pid)
    if not p or p.workspace_id != ws.id:
        raise HTTPException(404, "Prompt not found")
    p.name, p.description, p.content = payload.name, payload.description, payload.content
    if payload.key:
        p.key = payload.key
    db.commit(); db.refresh(p)
    return _p(p)


@router.delete("/{pid}")
def delete_prompt(pid: int, db: Session = Depends(get_db), ws: Workspace = Depends(current_workspace)):
    p = db.get(Prompt, pid)
    if p and p.workspace_id == ws.id:
        db.delete(p); db.commit()
    return {"deleted": True}
