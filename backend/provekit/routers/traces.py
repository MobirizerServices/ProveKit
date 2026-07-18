"""OTLP/HTTP trace ingest — point any OpenTelemetry GenAI exporter at /v1/traces and
its LLM/agent spans show up in ProveKit's history, no SDK swap required.

Auth: a workspace ingest key via `Authorization: Bearer <key>` (what real exporters can
send), or a session cookie for interactive/local use. Mint the key from
POST /api/workspace/ingest-key."""
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..models import Run, Workspace
from ..services import deploy, otel
from ..services.workspace import current_workspace

router = APIRouter(prefix="/v1", tags=["traces"])
ws_router = APIRouter(prefix="/api/workspace", tags=["workspace"])


def _resolve_ingest_ws(db: Session, request: Request, authorization: str | None) -> Workspace:
    """Bearer ingest key first (exporters), else fall back to the session cookie."""
    if authorization and authorization.lower().startswith("bearer "):
        key = authorization[7:].strip()
        h = deploy.hash_key(key)
        ws = db.query(Workspace).filter(Workspace.ingest_key_hash == h).first()
        if ws:
            return ws
        raise HTTPException(403, "Invalid ingest key")
    # No bearer key: only allowed via a logged-in session (or local mode's default user).
    from ..services.auth import get_current_user
    from ..services.workspace import get_or_create_default_workspace
    user = get_current_user(request, db)
    return get_or_create_default_workspace(db, user)


@router.post("/traces")
async def ingest_traces(request: Request, db: Session = Depends(get_db),
                        authorization: str | None = Header(default=None)):
    """Accept an OTLP ExportTraceServiceRequest (JSON) and persist gen_ai spans as runs.
    Returns the OTLP success shape so standard exporters are satisfied."""
    ws = _resolve_ingest_ws(db, request, authorization)
    try:
        payload = await request.json()
    except Exception:
        return {"partialSuccess": {"rejectedSpans": 0, "errorMessage": "invalid JSON"}}
    rows = otel.ingest(payload)
    for kw in rows:
        db.add(Run(workspace_id=ws.id, **kw))
    if rows:
        db.commit()
    return {"partialSuccess": {}}


class _KeyOut(BaseModel):
    ingest_key: str


@ws_router.post("/ingest-key", response_model=_KeyOut)
def rotate_ingest_key(db: Session = Depends(get_db), ws: Workspace = Depends(current_workspace)):
    """Mint/rotate this workspace's OTLP ingest key (shown once; stored hashed)."""
    plaintext, key_hash = deploy.new_api_key()
    ws.ingest_key_hash = key_hash
    db.commit()
    return {"ingest_key": plaintext}
