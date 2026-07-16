"""OTLP/HTTP trace ingest — point any OpenTelemetry GenAI exporter at /v1/traces and
its LLM/agent spans show up in AgentMan's history, no SDK swap required."""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Run
from ..services import otel

router = APIRouter(prefix="/v1", tags=["traces"])


@router.post("/traces")
async def ingest_traces(request: Request, db: Session = Depends(get_db)):
    """Accept an OTLP ExportTraceServiceRequest (JSON) and persist gen_ai spans as runs.
    Returns the OTLP success shape so standard exporters are satisfied."""
    try:
        payload = await request.json()
    except Exception:
        return {"partialSuccess": {"rejectedSpans": 0, "errorMessage": "invalid JSON"}}
    rows = otel.ingest(payload)
    for kw in rows:
        db.add(Run(**kw))
    if rows:
        db.commit()
    return {"partialSuccess": {}}
