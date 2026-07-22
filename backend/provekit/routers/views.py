"""Saved views — a named trace filter a team can share by URL.

A filter used to exist only as whatever someone had typed into the toolbar, so "our failing
checkout traces" could be described in chat but never handed over. Saving it makes the thing
a team actually refers to into an object with a name.

The stored `params` are the same key/values `/api/traces` already accepts, so a view is
replayed through the normal read path. That is deliberate: inventing a second query
representation would let the saved query and the live one drift apart, and a view that no
longer means what it meant when it was saved is worse than no view.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import SavedView, Workspace, iso_utc
from ..services.auth import get_current_user
from ..services.workspace import current_workspace

router = APIRouter(prefix="/api/views", tags=["views"])

#: Only the trace-list parameters are storable. An allowlist rather than "whatever was sent"
#: because these values are replayed into a query later — accepting arbitrary keys would make
#: a saved view a way to smuggle parameters into a future request.
_ALLOWED = {"status", "window_hours", "q", "limit"}


class _ViewIn(BaseModel):
    name: str
    params: dict = {}


def _row(v: SavedView) -> dict:
    return {"id": v.id, "name": v.name, "params": v.params or {},
            "created_by": v.created_by, "created_at": iso_utc(v.created_at)}


def _clean(params: dict) -> dict:
    return {k: v for k, v in (params or {}).items() if k in _ALLOWED and v not in (None, "")}


@router.get("")
def list_views(db: Session = Depends(get_db), ws: Workspace = Depends(current_workspace)):
    views = (db.query(SavedView).filter(SavedView.workspace_id == ws.id)
             .order_by(SavedView.name.asc()).all())
    return [_row(v) for v in views]


@router.post("")
def create_view(data: _ViewIn, db: Session = Depends(get_db),
                ws: Workspace = Depends(current_workspace), user=Depends(get_current_user)):
    name = (data.name or "").strip()[:160]
    if not name:
        raise HTTPException(422, "name is required")
    view = SavedView(workspace_id=ws.id, name=name, params=_clean(data.params),
                     created_by=getattr(user, "email", "") or "")
    db.add(view)
    try:
        db.commit()
    except IntegrityError:
        # Names are unique per project so a shared link means one thing to everyone; silently
        # creating a second "failing checkout" would make the name useless as a reference.
        db.rollback()
        raise HTTPException(409, f"a view named {name!r} already exists") from None
    db.refresh(view)
    return _row(view)


@router.put("/{view_id}")
def update_view(view_id: int, data: _ViewIn, db: Session = Depends(get_db),
                ws: Workspace = Depends(current_workspace)):
    view = db.get(SavedView, view_id)
    if not view or view.workspace_id != ws.id:
        raise HTTPException(404, "View not found")
    name = (data.name or "").strip()[:160]
    if not name:
        raise HTTPException(422, "name is required")
    view.name, view.params = name, _clean(data.params)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, f"a view named {name!r} already exists") from None
    return _row(view)


@router.delete("/{view_id}")
def delete_view(view_id: int, db: Session = Depends(get_db),
                ws: Workspace = Depends(current_workspace)):
    view = db.get(SavedView, view_id)
    if not view or view.workspace_id != ws.id:
        raise HTTPException(404, "View not found")
    db.delete(view)
    db.commit()
    return {"ok": True}
