"""Append-only audit trail for privileged changes.

Records who did what, to what, and when — the question every compliance review asks and
ProveKit previously had no answer to. Grants, revocations, deletions and key lifecycle are
recorded; reads are not (see the note at the bottom).

Two rules shape the design:

1. **A record outlives its subject.** Actor email and target label are snapshotted, not
   joined, so deleting a user or project doesn't erase the evidence that it happened.
2. **Auditing must not break the action.** `record()` never raises. An audit trail that can
   500 a legitimate revoke would make operators avoid the safe path.
"""
from __future__ import annotations

import logging

from fastapi import Request
from sqlalchemy.orm import Session

from ..models import AuditLog, User

log = logging.getLogger(__name__)

# Actions. Kept as flat strings rather than an enum so a new call site can't be blocked by a
# schema change, but centralised here so the set stays greppable.
SUPERUSER_GRANT = "superuser.grant"
SUPERUSER_REVOKE = "superuser.revoke"
PROJECT_CREATE = "project.create"
PROJECT_DELETE = "project.delete"
PROJECT_UPDATE = "project.update"
MEMBER_ADD = "member.add"
MEMBER_REMOVE = "member.remove"
KEY_CREATE = "key.create"
KEY_REVOKE = "key.revoke"
INGEST_KEY_ROTATE = "ingest_key.rotate"


def client_ip(request: Request | None) -> str:
    """Best-effort caller IP. Trusts X-Forwarded-For's first hop, which is what the bundled
    Caddy config sets; behind a different proxy this is only as trustworthy as that proxy."""
    if request is None:
        return ""
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()[:45]
    return (getattr(request.client, "host", "") or "")[:45]


def record(db: Session, actor: User | None, action: str, *,
           workspace_id: int | None = None, target_type: str = "", target_id: str | int = "",
           target_label: str = "", detail: dict | None = None,
           request: Request | None = None) -> None:
    """Write one audit row. Commits, so the record survives a later rollback of the caller.

    Never raises: a failure to audit is logged loudly but must not turn a successful
    privileged action into a 500, which would push operators toward unaudited workarounds.
    """
    try:
        db.add(AuditLog(
            workspace_id=workspace_id,
            actor_user_id=getattr(actor, "id", None),
            actor_email=(getattr(actor, "email", "") or "")[:255],
            action=action[:64],
            target_type=target_type[:32],
            target_id=str(target_id)[:64],
            target_label=(target_label or "")[:255],
            detail=detail or {},
            ip=client_ip(request),
        ))
        db.commit()
    except Exception as exc:
        log.error("AUDIT WRITE FAILED action=%s actor=%s target=%s:%s — %s",
                  action, getattr(actor, "email", "?"), target_type, target_id, exc)
        try:
            db.rollback()
        except Exception:
            pass


# Read auditing (who *viewed* a trace) is deliberately out of scope for now: it would write a
# row on every page load, needs sampling and its own retention policy, and would bury the
# privileged-change events that make this table useful. Tracked as its own roadmap item.
