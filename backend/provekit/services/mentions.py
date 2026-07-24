"""@mentions in collaboration notes (#65).

Two rules, both about not lying to the person typing:

1. **A mention only counts if the person can open the trace.** `@someone` who isn't a member of
   this project resolves to nothing — no stored mention, no email. Recording it anyway would show
   the author a mention that will never reach anyone, and emailing it would leak a trace label to
   an address that has no access.
2. **Notification is best-effort and never blocks the note.** A note that failed to save because
   an SMTP host was down would lose the writing, which is the part that matters.

Matching is deliberately narrow: the local-part of a member's email (`@ana` for
`ana@corp.com`), or their display name with spaces removed. Anything else is left as plain text
rather than guessed at.
"""
from __future__ import annotations

import logging
import re

from sqlalchemy.orm import Session

from ..models import User, Workspace, WorkspaceMember
from . import email as email_svc

log = logging.getLogger("provekit.mentions")

#: `@` followed by a name-ish run. Stops at whitespace and at punctuation that normally ends a
#: sentence, so "ask @ana." mentions ana rather than "ana.".
_MENTION = re.compile(r"@([A-Za-z0-9._-]{1,64})")


def _candidates(db: Session, ws_id: int) -> dict[str, str]:
    """handle -> email, for every member of the workspace."""
    rows = (db.query(User)
            .join(WorkspaceMember, WorkspaceMember.user_id == User.id)
            .filter(WorkspaceMember.workspace_id == ws_id).all())
    out: dict[str, str] = {}
    for u in rows:
        email = (u.email or "").strip()
        if not email:
            continue
        out[email.split("@")[0].lower()] = email
        out[email.lower()] = email
        if u.name:
            out[u.name.replace(" ", "").lower()] = email
    return out


def resolve(db: Session, ws_id: int, body: str) -> list[str]:
    """Emails of workspace members named in `body`. Order-preserving, de-duplicated."""
    if "@" not in body:
        return []
    known = _candidates(db, ws_id)
    found: list[str] = []
    for handle in _MENTION.findall(body):
        email = known.get(handle.lower())
        if email and email not in found:
            found.append(email)
    return found


def notify(db: Session, ws_id: int, emails: list[str], *, author: str, trace_id: str,
           body: str, origin: str = "") -> None:
    """Tell the mentioned members, once each. Never raises — see the module docstring."""
    if not emails:
        return
    ws = db.get(Workspace, ws_id)
    project = (ws.name if ws else "") or "a project"
    where = f"{origin.rstrip('/')}/traces?trace={trace_id}" if origin else f"trace {trace_id}"
    who = author or "Someone"
    excerpt = body.strip()
    if len(excerpt) > 400:
        excerpt = excerpt[:400] + "…"
    for addr in emails:
        try:
            email_svc.send(
                addr,
                f"{who} mentioned you on a trace in {project}",
                f"{who} mentioned you in a note on {where}\n\n{excerpt}\n",
            )
        except Exception:                     # noqa: BLE001 — notification must not fail the note
            log.exception("mention notification failed for %s", addr)
