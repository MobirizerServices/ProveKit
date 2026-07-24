"""Human review queue (#40) — which traces are worth a person's attention, in order.

Feedback *capture* already existed (👍/👎 + comment on a trace). What was missing is the queue:
without one, labelling is something you do when you happen to open a trace, which is why judge
calibration (services/calibration.py) sits starved below its `MIN_LABELLED_N` threshold and
reports nothing.

So the ordering is not "newest first" — it is "what would teach us the most":

1. **Judge-scored but unlabelled.** Each of these becomes a calibration *pair* the moment a human
   labels it, which is the only thing that moves kappa off nothing.
2. **Failed and unlabelled.** A failure nobody has judged is the case most likely to be worth
   turning into a dataset item.
3. **Everything else unlabelled**, newest first.

Already-labelled traces are excluded rather than re-queued: a second opinion is a different
feature (and a different statistic) from a first one.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Feedback, Run, Workspace, iso_utc
from ..services import calibration
from ..services.workspace import current_workspace

router = APIRouter(prefix="/api/review", tags=["review"])

#: How many recent root spans the queue considers. The queue is a work list, not an archive —
#: someone working through it never reaches the bottom, and an unbounded scan on a busy project
#: would cost far more than the answer is worth. Reported back so the number isn't silently a
#: sample.
SCAN_LIMIT = 500


def _judge_scores(db: Session, ws_id: int) -> dict[str, dict]:
    """trace_id -> the most recent judge/eval score on it."""
    rows = (db.query(Feedback)
            .filter(Feedback.workspace_id == ws_id,
                    Feedback.source.in_(sorted(calibration.JUDGE_SOURCES)))
            .order_by(Feedback.id.asc()).all())
    out: dict[str, dict] = {}
    for r in rows:
        if r.score is None:
            continue
        out[r.trace_id] = {"name": r.name or "judge", "score": float(r.score),
                           "verdict": "pass" if float(r.score) >= calibration.PASS_AT else "fail"}
    return out


def _human_labelled(db: Session, ws_id: int) -> set[str]:
    rows = (db.query(Feedback.trace_id)
            .filter(Feedback.workspace_id == ws_id,
                    Feedback.source.in_(sorted(calibration.HUMAN_SOURCES))).all())
    return {t for (t,) in rows}


@router.get("/queue")
def review_queue(limit: int = 50, db: Session = Depends(get_db),
                 ws: Workspace = Depends(current_workspace)):
    limit = max(1, min(int(limit or 50), 200))
    judged = _judge_scores(db, ws.id)
    labelled = _human_labelled(db, ws.id)

    roots = (db.query(Run)
             .filter(Run.workspace_id == ws.id, Run.parent_span_id == "")
             .order_by(Run.id.desc()).limit(SCAN_LIMIT).all())

    items = []
    for r in roots:
        if not r.trace_id or r.trace_id in labelled:
            continue
        judge = judged.get(r.trace_id)
        # Lower sorts first: judge-scored, then failed, then the rest.
        rank = 0 if judge else (1 if r.status == "failed" else 2)
        items.append((rank, -r.id, {
            "trace_id": r.trace_id,
            "label": r.label or "",
            "status": r.status,
            "model": (r.result or {}).get("meta", {}).get("model") or "",
            "duration_ms": r.duration_ms,
            "created_at": iso_utc(r.created_at),
            "judge": judge,
            "reason": ("judge scored it, nobody has" if judge
                       else "failed run, unreviewed" if r.status == "failed"
                       else "not reviewed yet"),
        }))
    items.sort(key=lambda x: (x[0], x[1]))

    paired = len(set(judged) & labelled)
    return {
        "summary": {
            "awaiting": len(items),
            "human_labelled": len(labelled),
            "judge_scored": len(judged),
            "paired": paired,
            "min_pairs": calibration.MIN_LABELLED_N,
            # What calibration is still waiting for, stated as a number rather than implied.
            "pairs_needed": max(0, calibration.MIN_LABELLED_N - paired),
            "scanned": len(roots),
            "scan_limit": SCAN_LIMIT,
        },
        "items": [it for _, _, it in items[:limit]],
    }
