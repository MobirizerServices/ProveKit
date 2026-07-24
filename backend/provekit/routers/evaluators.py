"""The evaluator catalog, and the project-defined scorers beside it.

The catalog is read-only: it surfaces the built-in registry (scorers.SCORERS) so the portal can
show what's available and describe it, rather than the user having to know the names by heart.
The one-line description is the scorer's own docstring, so this can't drift from what the scorer
actually does.

`/custom` is the writable half (#48): rules a project defines, stored server-side so online eval
can use them. Declarative rather than uploaded code — see services/custom_scorers.py for why.
"""
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import CustomScorer, Workspace
from ..scorers import SCORERS
from ..services import custom_scorers, errors
from ..services.workspace import current_workspace

router = APIRouter(prefix="/api/evaluators", tags=["evaluators"])

#: Grouping for display. A scorer not listed here falls under "Other" — new scorers still show
#: up, just ungrouped, so the catalog can't silently omit one.
_CATEGORY = {
    "exact_match": "Correctness", "contains": "Correctness", "regex_match": "Correctness",
    "json_valid": "Correctness",
    "expected_tools_used": "Trajectory", "tool_order": "Trajectory", "no_repeat": "Trajectory",
    "step_budget": "Trajectory",
    "faithfulness": "RAG", "context_relevance": "RAG", "answer_relevance": "RAG",
    "cost_budget": "Budgets", "latency_budget": "Budgets", "token_budget": "Budgets",
    "session_complete": "Multi-turn", "session_no_repeat": "Multi-turn",
    "session_expected_covered": "Multi-turn",
}


def _doc(fn) -> str:
    return " ".join((fn.__doc__ or "").strip().split("\n")[0].split())[:160]


@router.get("")
def list_evaluators(db=Depends(get_db), ws: Workspace = Depends(current_workspace)):
    """Every built-in scorer, with its category and one-line description."""
    return [
        {"name": name, "category": _CATEGORY.get(name, "Other"), "description": _doc(fn)}
        for name, fn in SCORERS.items()
    ]


# ---- project-defined scorers (#48) ----
class _ScorerIn(BaseModel):
    name: str
    kind: str = "contains"
    config: dict = {}
    description: str = ""
    enabled: bool = True


def _clean_name(raw: str) -> str:
    name = (raw or "").strip()
    if not re.fullmatch(r"[a-z0-9_]{2,80}", name):
        raise HTTPException(422, "name must be 2-80 characters of lowercase letters, digits or "
                                 "underscores — it is referenced the same way a built-in scorer "
                                 "is, so it has to be a plain identifier.")
    if name in SCORERS:
        raise HTTPException(409, f"'{name}' is a built-in scorer. Pick another name — a rule that "
                                 "shadowed a built-in would make the same name mean different "
                                 "things in different projects.")
    return name


@router.get("/custom")
def list_custom(db: Session = Depends(get_db), ws: Workspace = Depends(current_workspace)):
    rows = (db.query(CustomScorer).filter(CustomScorer.workspace_id == ws.id)
            .order_by(CustomScorer.id.desc()).all())
    return [custom_scorers.row(r) for r in rows]


@router.post("/custom")
def create_custom(data: _ScorerIn, db: Session = Depends(get_db),
                  ws: Workspace = Depends(current_workspace)):
    name = _clean_name(data.name)
    try:
        cfg = custom_scorers.validate(data.kind, data.config)
    except custom_scorers.ScorerError as exc:
        raise HTTPException(422, str(exc)) from None
    if (db.query(CustomScorer)
            .filter(CustomScorer.workspace_id == ws.id, CustomScorer.name == name).first()):
        raise HTTPException(409, f"this project already has a scorer called '{name}'.")
    r = CustomScorer(workspace_id=ws.id, name=name, kind=data.kind, config=cfg,
                     description=(data.description or "")[:300], enabled=data.enabled)
    db.add(r); db.commit(); db.refresh(r)
    return custom_scorers.row(r)


@router.post("/custom/{sid}/try")
def try_custom(sid: int, body: dict, db: Session = Depends(get_db),
               ws: Workspace = Depends(current_workspace)):
    """Score one sample output against a stored rule.

    A scoring rule you cannot try is one you find out about from a month of wrong numbers.
    """
    r = db.get(CustomScorer, sid)
    if not r or r.workspace_id != ws.id:
        raise HTTPException(404, errors.not_in_project("scorer", "GET /api/evaluators/custom"))
    score = custom_scorers.evaluate(r.kind, r.config or {}, str(body.get("output") or ""))
    return {"score": score, "applies": score is not None}


@router.delete("/custom/{sid}")
def delete_custom(sid: int, db: Session = Depends(get_db),
                  ws: Workspace = Depends(current_workspace)):
    r = db.get(CustomScorer, sid)
    if not r or r.workspace_id != ws.id:
        raise HTTPException(404, errors.not_in_project("scorer", "GET /api/evaluators/custom"))
    db.delete(r); db.commit()
    return {"ok": True}
