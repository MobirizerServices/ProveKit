"""Named, revocable `pk_` API keys — the portal-issued bearer keys a user drops in their
`.env` so the tracing decorator (and CI/CLI) can reach the workspace without a cookie.

Only the SHA-256 hash is ever stored (via deploy.hash_key); the plaintext is returned once,
at creation. A key resolves to its workspace on every ingest request, which also stamps
last_used_at so stale keys are visible in the portal.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..models import ApiKey, Workspace
from . import deploy

PREFIX = "pk_"


def mint() -> tuple[str, str, str]:
    """Return (plaintext, key_hash, display_prefix). Plaintext is shown to the user once."""
    key = PREFIX + secrets.token_urlsafe(32)
    return key, deploy.hash_key(key), key[:11]


def resolve_workspace(db: Session, key: str) -> Workspace | None:
    """Look up the workspace for a live `pk_` key and stamp last_used_at. Revoked or
    unknown keys return None (the caller turns that into a 403)."""
    if not key.startswith(PREFIX):
        return None
    row = (db.query(ApiKey)
           .filter(ApiKey.key_hash == deploy.hash_key(key), ApiKey.revoked.is_(False))
           .first())
    if not row:
        return None
    row.last_used_at = datetime.now(timezone.utc)
    return db.get(Workspace, row.workspace_id)
