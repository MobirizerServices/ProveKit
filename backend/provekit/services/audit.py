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

from ..models import AuditLog, User, iso_utc

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

# Actions the project activity feed (#74) can render but which NOTHING emits yet. They are
# named here rather than left implicit so the gap is a value the product can show: the feed
# publishes them as `not_yet_recorded` and says so in the UI. A feed that silently covers half
# of what a reader assumes it covers is worse than one that names its blind spots.
# Wiring one up is two lines at its source — add the `record()` call, move the name out of
# UNWIRED. `test_activity.py` fails if a call site appears while the name is still listed here.
PROMPT_SAVE = "prompt.save"                     # POST /api/prompts (a new prompt version)
PROMPT_DELETE = "prompt.delete"
DATASET_CREATE = "dataset.create"
DATASET_DELETE = "dataset.delete"
DATASET_ITEM_PROMOTE = "dataset.item.promote"   # a captured trace promoted into a dataset row
DATASET_ITEM_DELETE = "dataset.item.delete"
ALERT_CREATE = "alert.create"
ALERT_UPDATE = "alert.update"                   # enable/disable — "resolved" as alerts exist today
ALERT_DELETE = "alert.delete"
CONNECTION_CREATE = "connection.create"         # a sealed provider credential was added
CONNECTION_DELETE = "connection.delete"

#: Defined above but not yet written by any call site. Kept as data so the feed can be honest.
UNWIRED = frozenset({
    PROJECT_CREATE, INGEST_KEY_ROTATE,
    PROMPT_SAVE, PROMPT_DELETE,
    DATASET_CREATE, DATASET_DELETE, DATASET_ITEM_PROMOTE, DATASET_ITEM_DELETE,
    ALERT_CREATE, ALERT_UPDATE, ALERT_DELETE,
    CONNECTION_CREATE, CONNECTION_DELETE,
})

#: What a member sees in a project's activity feed. An ALLOWLIST, deliberately, and not a
#: denylist of platform actions: a denylist leaks by omission, so the next platform-level
#: action someone adds (a support tool, a billing override) would appear in every tenant's feed
#: until noticed. Adding a row here is a conscious "a tenant may read this".
#:
#: Excluded on purpose:
#:   superuser.grant/revoke — platform-level, and carry no workspace_id anyway.
#:   impersonation.start/stop — these DO carry the tenant's workspace_id, so the workspace
#:     filter alone would surface them. Telling a tenant an operator entered their project is a
#:     real feature, but it is a support/disclosure decision with its own phrasing and its own
#:     question of whether the operator's identity is disclosed. Not smuggled in via this feed.
#:   project.delete — recorded with a null workspace_id (see routers/projects.py); the project
#:     it describes no longer exists, so there is no feed left to read it in.
TENANT_VISIBLE = frozenset({PROJECT_UPDATE, MEMBER_ADD, MEMBER_REMOVE, KEY_CREATE, KEY_REVOKE}
                           | UNWIRED)

#: Human phrasing, `{actor} <label> {target}`. Lives beside the constants because the two
#: change together; a new action with no label would otherwise render as a raw dotted string.
LABELS = {
    PROJECT_CREATE: "created project",
    PROJECT_UPDATE: "changed project settings",
    PROJECT_DELETE: "deleted project",
    MEMBER_ADD: "added member",
    MEMBER_REMOVE: "removed member",
    KEY_CREATE: "created API key",
    KEY_REVOKE: "revoked API key",
    INGEST_KEY_ROTATE: "rotated the ingest key",
    PROMPT_SAVE: "saved prompt",
    PROMPT_DELETE: "deleted prompt",
    DATASET_CREATE: "created dataset",
    DATASET_DELETE: "deleted dataset",
    DATASET_ITEM_PROMOTE: "promoted a trace into dataset",
    DATASET_ITEM_DELETE: "removed a row from dataset",
    ALERT_CREATE: "created alert",
    ALERT_UPDATE: "changed alert",
    ALERT_DELETE: "deleted alert",
    CONNECTION_CREATE: "connected a model provider",
    CONNECTION_DELETE: "disconnected a model provider",
}


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


# ---- reading it back as a project activity feed (#74) ----
#
# The feed is a *view* of this table, not a second log. Two records of the same event drift,
# and the one that must stay authoritative is the audit trail — so the feed adds no writes and
# no storage, it only filters and phrases what record() already wrote.

FEED_LIMIT = 50
FEED_MAX = 200


def entry(row: AuditLog) -> dict:
    """One feed row. Note what is *not* here: `ip`. The platform audit view keeps it because
    an incident investigation needs it; a project feed readable by every member does not, and
    a teammate's home IP address is not something you hand out to answer "who renamed this".
    """
    return {"id": row.id, "action": row.action,
            "label": LABELS.get(row.action, row.action.replace(".", " ")),
            "actor_email": row.actor_email, "actor_user_id": row.actor_user_id,
            "target_type": row.target_type, "target_id": row.target_id,
            "target_label": row.target_label, "detail": row.detail or {},
            "created_at": iso_utc(row.created_at)}


def feed(db: Session, workspace_id: int, *, limit: int = FEED_LIMIT,
         cursor: int | None = None, action: str = "") -> tuple[list[dict], int | None]:
    """This project's activity, newest first, plus the cursor to continue from.

    Two filters, and both are load-bearing. `workspace_id` keeps other tenants out;
    `TENANT_VISIBLE` keeps *platform* rows out even when they carry this workspace's id —
    which impersonation rows do. Scoping alone would have leaked those.

    Keyset paging on the id rather than an offset: rows are appended at the head, so an offset
    window shifts under a reader and repeats or skips a row every time someone acts mid-scroll.
    """
    limit = max(1, min(int(limit or FEED_LIMIT), FEED_MAX))
    q = db.query(AuditLog).filter(AuditLog.workspace_id == workspace_id,
                                  AuditLog.action.in_(TENANT_VISIBLE))
    if action.strip():
        # Still intersected with the allowlist above, so naming a platform action here returns
        # nothing rather than becoming a way to ask for one.
        q = q.filter(AuditLog.action == action.strip())
    if cursor:
        q = q.filter(AuditLog.id < int(cursor))
    rows = q.order_by(AuditLog.id.desc()).limit(limit + 1).all()
    more = len(rows) > limit
    rows = rows[:limit]
    return [entry(r) for r in rows], (rows[-1].id if more and rows else None)


def coverage_gaps() -> list[dict]:
    """The actions the feed would render but nothing records yet — served alongside the feed
    so a reader can tell "nothing happened" apart from "that isn't captured". Sorted so the
    response is stable enough to assert on."""
    return [{"action": a, "label": LABELS.get(a, a)} for a in sorted(UNWIRED)]


# Read auditing (who *viewed* a trace) is deliberately out of scope for now: it would write a
# row on every page load, needs sampling and its own retention policy, and would bury the
# privileged-change events that make this table useful. Tracked as its own roadmap item.
