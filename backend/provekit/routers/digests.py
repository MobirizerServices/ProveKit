"""Manage recurring project digests (services/digests.py)."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Digest, Workspace, iso_utc
from ..services import digests, netguard
from ..services.workspace import current_workspace

router = APIRouter(prefix="/api/digests", tags=["digests"])


class _DigestIn(BaseModel):
    cadence: str = "weekly"
    webhook_url: str = ""
    email: str = ""
    enabled: bool = True


def _row(d: Digest) -> dict:
    return {"id": d.id, "cadence": d.cadence, "webhook_url": d.webhook_url, "email": d.email,
            "enabled": d.enabled, "last_sent_at": iso_utc(d.last_sent_at),
            "last_status": d.last_status, "created_at": iso_utc(d.created_at)}


@router.get("")
def list_digests(db: Session = Depends(get_db), ws: Workspace = Depends(current_workspace)):
    rows = db.query(Digest).filter(Digest.workspace_id == ws.id).order_by(Digest.id.asc()).all()
    return [_row(d) for d in rows]


@router.post("")
def create_digest(data: _DigestIn, db: Session = Depends(get_db),
                  ws: Workspace = Depends(current_workspace)):
    if data.cadence not in digests.CADENCES:
        raise HTTPException(422, f"cadence must be one of {sorted(digests.CADENCES)}")
    if not data.webhook_url.strip() and not data.email.strip():
        # A digest with nowhere to go would sit there looking configured and deliver nothing.
        raise HTTPException(422, "set a webhook_url or an email to deliver to")
    if data.webhook_url.strip():
        try:
            netguard.guard_url(data.webhook_url.strip())
        except Exception as exc:
            raise HTTPException(422, f"webhook_url rejected: {exc}") from None
    d = Digest(workspace_id=ws.id, cadence=data.cadence,
               webhook_url=data.webhook_url.strip()[:500], email=data.email.strip()[:255],
               enabled=data.enabled)
    db.add(d)
    db.commit()
    db.refresh(d)
    return _row(d)


@router.post("/{digest_id}/preview")
def preview(digest_id: int, db: Session = Depends(get_db),
            ws: Workspace = Depends(current_workspace)):
    """What this digest would say right now, without sending or rescheduling it.

    Configuring a weekly digest and finding out in a week whether it is useful is a bad loop.
    """
    d = db.get(Digest, digest_id)
    if not d or d.workspace_id != ws.id:
        raise HTTPException(404, "Digest not found")
    summary = digests.build(db, ws, d.cadence)
    return {"summary": summary, "text": digests.render(summary)}


@router.delete("/{digest_id}")
def delete_digest(digest_id: int, db: Session = Depends(get_db),
                  ws: Workspace = Depends(current_workspace)):
    d = db.get(Digest, digest_id)
    if not d or d.workspace_id != ws.id:
        raise HTTPException(404, "Digest not found")
    db.delete(d)
    db.commit()
    return {"ok": True}
