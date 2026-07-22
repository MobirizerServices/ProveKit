"""Manage outbound webhook subscriptions (services/webhooks.py)."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Workspace, WebhookSubscription, iso_utc
from ..services import netguard, webhooks
from ..services.workspace import current_workspace

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


class _SubIn(BaseModel):
    url: str
    events: list[str] = []
    enabled: bool = True


def _row(s: WebhookSubscription, *, secret: str | None = None) -> dict:
    # The secret is returned exactly once, at creation, like an API key. Serving it on every
    # read would put it in logs, screenshots and browser history for no benefit.
    out = {"id": s.id, "url": s.url, "events": s.events or [], "enabled": s.enabled,
           "failures": s.failures, "last_status": s.last_status,
           "last_attempt_at": iso_utc(s.last_attempt_at), "created_at": iso_utc(s.created_at)}
    if secret is not None:
        out["secret"] = secret
    return out


@router.get("")
def list_subs(db: Session = Depends(get_db), ws: Workspace = Depends(current_workspace)):
    rows = (db.query(WebhookSubscription)
            .filter(WebhookSubscription.workspace_id == ws.id)
            .order_by(WebhookSubscription.id.asc()).all())
    return [_row(s) for s in rows]


@router.post("")
def create_sub(data: _SubIn, db: Session = Depends(get_db),
               ws: Workspace = Depends(current_workspace)):
    unknown = [e for e in data.events if e not in webhooks.EVENTS]
    if unknown:
        # Rejected at save time: a typo'd event would otherwise create a subscription that
        # silently never fires, which is the hardest kind of integration bug to notice.
        raise HTTPException(422, f"unknown event(s) {unknown}; valid: {list(webhooks.EVENTS)}")
    if not data.events:
        raise HTTPException(422, "subscribe to at least one event")
    try:
        netguard.guard_url(data.url)
    except Exception as exc:
        raise HTTPException(422, f"url rejected: {exc}") from None
    secret = webhooks.new_secret()
    sub = WebhookSubscription(workspace_id=ws.id, url=data.url.strip()[:500],
                              events=data.events, secret=secret, enabled=data.enabled)
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return _row(sub, secret=secret)


@router.delete("/{sub_id}")
def delete_sub(sub_id: int, db: Session = Depends(get_db),
               ws: Workspace = Depends(current_workspace)):
    sub = db.get(WebhookSubscription, sub_id)
    if not sub or sub.workspace_id != ws.id:
        raise HTTPException(404, "Subscription not found")
    db.delete(sub)
    db.commit()
    return {"ok": True}


@router.post("/{sub_id}/enable")
def reenable(sub_id: int, db: Session = Depends(get_db),
             ws: Workspace = Depends(current_workspace)):
    """Re-enable a subscription that backed off to disabled, and clear its failure count."""
    sub = db.get(WebhookSubscription, sub_id)
    if not sub or sub.workspace_id != ws.id:
        raise HTTPException(404, "Subscription not found")
    sub.enabled, sub.failures, sub.last_status = True, 0, ""
    db.commit()
    return _row(sub)
