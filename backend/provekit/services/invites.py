"""Pending project invites (#73).

Membership requires a `users` row, so inviting a colleague who hadn't signed up yet was a 404.
The owner was told "no such account" and left with nothing on screen — no record that the person
had been asked, no way to cancel it, and no way to tell a typo'd address from one that simply
hadn't registered.

An invite is that missing state. Three rules:

* **It expires.** An invitation that grants access forever is a standing key handed to whoever
  eventually controls that mailbox.
* **It is visible and revocable.** The owner can see who is outstanding and withdraw it.
* **It is consumed, not matched forever.** Accepting sets `accepted_at`, so a re-registration
  after an account is deleted doesn't silently re-grant access on the strength of an old row.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import ProjectInvite, User, Workspace, WorkspaceMember, _now
from . import email as email_svc
from . import roles

log = logging.getLogger("provekit.invites")

#: How long an invitation stays good. Long enough to survive a holiday, short enough that a
#: forgotten one stops being an open door.
TTL_DAYS = 14


def _norm(email: str) -> str:
    return (email or "").strip().lower()


def is_expired(inv: ProjectInvite) -> bool:
    if inv.expires_at is None:
        return False
    expires = inv.expires_at
    if expires.tzinfo is None:                      # SQLite hands timestamps back naive
        from datetime import timezone
        expires = expires.replace(tzinfo=timezone.utc)
    return expires < _now()


def status_of(inv: ProjectInvite) -> str:
    if inv.accepted_at:
        return "accepted"
    return "expired" if is_expired(inv) else "pending"


def create(db: Session, ws: Workspace, email: str, role: str, *, invited_by: str = "",
           origin: str = "") -> ProjectInvite:
    """Invite an address that has no account yet. Re-inviting refreshes the existing row."""
    addr = _norm(email)
    role = role if role in roles.ALL_ROLES else roles.VIEWER
    inv = (db.query(ProjectInvite)
           .filter(ProjectInvite.workspace_id == ws.id,
                   func.lower(ProjectInvite.email) == addr,
                   ProjectInvite.accepted_at.is_(None)).first())
    if inv is None:
        inv = ProjectInvite(workspace_id=ws.id, email=addr)
        db.add(inv)
    inv.role = role
    inv.invited_by_email = (invited_by or "")[:255]
    inv.expires_at = _now() + timedelta(days=TTL_DAYS)
    db.commit(); db.refresh(inv)
    _notify(inv, ws, origin)
    return inv


def _notify(inv: ProjectInvite, ws: Workspace, origin: str) -> None:
    """Best-effort: an invite that was recorded must not be lost because email failed."""
    try:
        where = f"{origin.rstrip('/')}/signup" if origin else "the ProveKit sign-up page"
        who = inv.invited_by_email or "A teammate"
        email_svc.send(
            inv.email,
            f"{who} invited you to {ws.name} on ProveKit",
            f"{who} invited you to the project \"{ws.name}\" as {inv.role}.\n\n"
            f"Sign up with this address at {where} and you'll join automatically.\n"
            f"This invitation expires in {TTL_DAYS} days.\n",
        )
    except Exception:                              # noqa: BLE001 — see docstring
        log.exception("invite email failed for %s", inv.email)


def pending_for(db: Session, workspace_id: int) -> list[ProjectInvite]:
    return (db.query(ProjectInvite)
            .filter(ProjectInvite.workspace_id == workspace_id,
                    ProjectInvite.accepted_at.is_(None))
            .order_by(ProjectInvite.id.desc()).all())


def consume_for(db: Session, user: User) -> list[int]:
    """Join a freshly-registered account to every project that invited it.

    Returns the workspace ids joined. Expired invitations are skipped but left on the row so an
    owner can still see that the person was asked and that it lapsed.
    """
    addr = _norm(user.email)
    if not addr:
        return []
    joined: list[int] = []
    rows = (db.query(ProjectInvite)
            .filter(func.lower(ProjectInvite.email) == addr,
                    ProjectInvite.accepted_at.is_(None)).all())
    for inv in rows:
        if is_expired(inv):
            continue
        ws = db.get(Workspace, inv.workspace_id)
        if ws is None:                             # the project was deleted meanwhile
            continue
        already = (db.query(WorkspaceMember)
                   .filter(WorkspaceMember.workspace_id == inv.workspace_id,
                           WorkspaceMember.user_id == user.id).first())
        if not already:
            db.add(WorkspaceMember(workspace_id=inv.workspace_id, user_id=user.id,
                                   role=inv.role if inv.role in roles.ALL_ROLES else roles.VIEWER))
        inv.accepted_at = _now()
        joined.append(inv.workspace_id)
    if joined:
        db.commit()
    return joined
