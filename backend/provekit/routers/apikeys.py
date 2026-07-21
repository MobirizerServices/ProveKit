"""API keys: named, revocable `pk_` bearer keys for machine access (trace ingest, CI, CLI).

The plaintext key is returned exactly once, from POST — the portal shows it, the user drops
it in their `.env`, and it's never retrievable again (only the SHA-256 hash is stored).
Listing shows the display prefix + last-used so stale keys are obvious.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import ApiKey, User, Workspace, iso_utc
from ..services import apikey, audit
from ..services.auth import get_current_user
from ..services.workspace import current_workspace

router = APIRouter(prefix="/api/api-keys", tags=["api-keys"])


def _public(k: ApiKey) -> dict:
    return {"id": k.id, "name": k.name, "prefix": k.prefix, "revoked": k.revoked,
            "last_used_at": iso_utc(k.last_used_at), "created_at": iso_utc(k.created_at)}


class KeyIn(BaseModel):
    name: str = ""


@router.get("")
def list_keys(db: Session = Depends(get_db), ws: Workspace = Depends(current_workspace)):
    keys = (db.query(ApiKey).filter(ApiKey.workspace_id == ws.id)
            .order_by(ApiKey.created_at.desc()).all())
    return [_public(k) for k in keys]


@router.post("")
def create_key(body: KeyIn, request: Request, db: Session = Depends(get_db),
               user: User = Depends(get_current_user),
               ws: Workspace = Depends(current_workspace)):
    """Mint a key. The plaintext `key` in the response is shown once and never again."""
    plaintext, key_hash, prefix = apikey.mint()
    row = ApiKey(workspace_id=ws.id, name=(body.name or "").strip(),
                 key_hash=key_hash, prefix=prefix)
    db.add(row)
    db.commit()
    db.refresh(row)
    # The prefix, never the key: an audit trail that records secrets is a new place to leak
    # them, and the prefix is enough to match a row against a key seen elsewhere.
    audit.record(db, user, audit.KEY_CREATE, workspace_id=ws.id, target_type="key",
                 target_id=row.id, target_label=row.name or row.prefix,
                 detail={"prefix": row.prefix}, request=request)
    return {**_public(row), "key": plaintext}


@router.delete("/{key_id}")
def revoke_key(key_id: int, request: Request, db: Session = Depends(get_db),
               user: User = Depends(get_current_user),
               ws: Workspace = Depends(current_workspace)):
    """Revoke a key (soft — the row stays so last_used history survives). 404 across workspaces."""
    row = db.get(ApiKey, key_id)
    if not row or row.workspace_id != ws.id:
        raise HTTPException(404, "API key not found")
    row.revoked = True
    db.commit()
    audit.record(db, user, audit.KEY_REVOKE, workspace_id=ws.id, target_type="key",
                 target_id=row.id, target_label=row.name or row.prefix,
                 detail={"prefix": row.prefix}, request=request)
    return {"ok": True}
