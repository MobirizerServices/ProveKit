"""Per-workspace token usage aggregation — the foundation for quotas/billing later.
Normalizes the different providers' usage shapes (OpenAI prompt/completion, Anthropic
and Responses input/output) into one in/out count."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Run, Workspace
from ..services.workspace import current_workspace

router = APIRouter(prefix="/api/usage", tags=["usage"])


def _tokens(usage: dict) -> tuple[int, int]:
    if not isinstance(usage, dict):
        return 0, 0
    tin = usage.get("input_tokens") or usage.get("prompt_tokens") or 0
    tout = usage.get("output_tokens") or usage.get("completion_tokens") or 0
    return int(tin or 0), int(tout or 0)


@router.get("")
def usage(days: int = 30, db: Session = Depends(get_db), ws: Workspace = Depends(current_workspace)):
    """Totals + per-model breakdown of runs and tokens over the last `days`."""
    since = datetime.now(timezone.utc) - timedelta(days=max(1, days))
    rows = (db.query(Run).filter(Run.workspace_id == ws.id, Run.created_at >= since.replace(tzinfo=None)).all())
    total_in = total_out = 0
    by_model: dict[str, dict] = {}
    for r in rows:
        meta = (r.result or {}).get("meta") or {}
        model = meta.get("model") or "—"
        tin, tout = _tokens(meta.get("usage"))
        total_in += tin; total_out += tout
        m = by_model.setdefault(model, {"runs": 0, "tokens_in": 0, "tokens_out": 0})
        m["runs"] += 1; m["tokens_in"] += tin; m["tokens_out"] += tout
    return {
        "window_days": days, "runs": len(rows),
        "tokens_in": total_in, "tokens_out": total_out, "tokens_total": total_in + total_out,
        "by_model": [{"model": k, **v} for k, v in sorted(by_model.items(), key=lambda kv: -kv[1]["tokens_in"] - kv[1]["tokens_out"])],
    }
