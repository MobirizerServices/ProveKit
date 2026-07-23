"""The evaluator catalog — the scorers an experiment or automation can run.

Read-only: it surfaces the built-in registry (services scorers.SCORERS) so the portal can show
what's available and describe it, rather than the user having to know the names by heart. The
one-line description is the scorer's own docstring, so this can't drift from what the scorer
actually does.
"""
from fastapi import APIRouter, Depends

from ..database import get_db
from ..models import Workspace
from ..scorers import SCORERS
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
