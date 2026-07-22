"""Project activity feed (#74) — who changed what, in this project.

A thin read over `audit_logs`. It deliberately writes nothing: the audit trail (#75) already
records privileged changes with actor, target and IP, and a second log of the same events
would drift from it within a release. So this router filters and phrases; `services/audit.py`
owns the visibility rules, because the module that writes a row should be the one that decides
who may read it.

Any member can read it, viewers included — it is a GET, so `current_workspace` admits them.
Knowing who changed the retention policy is not a privileged question inside your own project.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Workspace
from ..services import audit
from ..services.workspace import current_workspace

router = APIRouter(prefix="/api/activity", tags=["activity"])


@router.get("")
def list_activity(limit: int = audit.FEED_LIMIT, cursor: int | None = None, action: str = "",
                  db: Session = Depends(get_db),
                  ws: Workspace = Depends(current_workspace)):
    """This project's recent changes, newest first.

    `next_cursor` is null when the feed is exhausted. `not_yet_recorded` names the actions the
    feed can render but nothing emits yet — shipped as part of the response rather than left
    to a changelog, because a reader who can't tell "nothing happened" from "that isn't
    captured" will trust the feed for a guarantee it doesn't make.
    """
    entries, next_cursor = audit.feed(db, ws.id, limit=limit, cursor=cursor, action=action)
    return {"entries": entries, "next_cursor": next_cursor,
            "not_yet_recorded": audit.coverage_gaps()}
