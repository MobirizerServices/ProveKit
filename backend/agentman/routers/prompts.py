"""Prompt Registry — manage reusable prompts (generic version of Magari's registry)."""
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Prompt, iso_utc

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
def list_prompts(db: Session = Depends(get_db)):
    return [_p(p) for p in db.query(Prompt).order_by(Prompt.key).all()]


@router.post("")
def create_prompt(payload: PromptIn, db: Session = Depends(get_db)):
    key = payload.key or _slug(payload.name)
    if db.query(Prompt).filter(Prompt.key == key).first():
        base, n = key, 2
        while db.query(Prompt).filter(Prompt.key == key).first():
            key = f"{base}-{n}"; n += 1
    p = Prompt(key=key, name=payload.name, description=payload.description, content=payload.content)
    db.add(p); db.commit(); db.refresh(p)
    return _p(p)


@router.put("/{pid}")
def update_prompt(pid: int, payload: PromptIn, db: Session = Depends(get_db)):
    p = db.get(Prompt, pid)
    if not p:
        raise HTTPException(404, "Prompt not found")
    p.name, p.description, p.content = payload.name, payload.description, payload.content
    if payload.key:
        p.key = payload.key
    db.commit(); db.refresh(p)
    return _p(p)


@router.delete("/{pid}")
def delete_prompt(pid: int, db: Session = Depends(get_db)):
    p = db.get(Prompt, pid)
    if p:
        db.delete(p); db.commit()
    return {"deleted": True}
