"""Runtime prompt fetch (#61) and live A/B by traffic split (#62).

Prompt versions could be saved and restored in the portal, but an application had no way to
*read* one — so changing a prompt still meant a deploy, and the portal's prompt history was a
record of what someone did in a playground rather than of what production is running.

Two mechanisms, and the second only makes sense because of the first:

**Labels.** An app fetches `get("checkout-agent", label="production")` and gets whatever
version currently carries that label. The label is a moving pointer; the version number stays
immutable. That is what lets a prompt change without a deploy.

**Traffic split.** Give two versions of one name a `traffic` weight and the fetch returns one
of them — deterministically, keyed on something stable the caller supplies (a session id, a
user id). Determinism is the whole feature: a user who gets variant B on turn one must get B
on turn four, or the conversation is incoherent and the experiment is measuring noise. Random
assignment per call would also make the live scores unattributable, which is the only reason
to run the split at all.

The chosen version is returned to the caller so it can be recorded on the trace. A split whose
outcome isn't attached to the run produces two populations you cannot tell apart afterwards.
"""
from __future__ import annotations

import hashlib

from sqlalchemy.orm import Session

from ..models import Prompt

#: Labels a prompt may carry. An allowlist so a typo doesn't create a label nothing fetches.
LABELS = ("production", "staging", "canary")


def _versions(db: Session, workspace_id: int, name: str) -> list[Prompt]:
    return (db.query(Prompt)
            .filter(Prompt.workspace_id == workspace_id, Prompt.name == name)
            .order_by(Prompt.version.desc()).all())


def serving(db: Session, workspace_id: int, name: str) -> list[Prompt]:
    """Versions currently taking traffic, if any."""
    return [p for p in _versions(db, workspace_id, name) if (p.traffic or 0) > 0]


def assign(candidates: list[Prompt], key: str) -> Prompt | None:
    """Pick a version for `key`, weighted by traffic and stable for that key.

    Hashed rather than random. A user who gets variant B on their first turn must get B on
    their fourth — otherwise the conversation is incoherent and the comparison is measuring
    assignment noise rather than the prompts. It also means a retried request lands on the same
    variant, so one interaction can't contribute scores to both arms.
    """
    live = [p for p in candidates if (p.traffic or 0) > 0]
    if not live:
        return None
    total = sum(p.traffic for p in live)
    if total <= 0:
        return None
    digest = hashlib.sha256(key.encode()).digest()
    point = int.from_bytes(digest[:8], "big") / float(1 << 64) * total
    upto = 0.0
    for p in sorted(live, key=lambda x: x.version):    # stable order, not insertion order
        upto += p.traffic
        if point < upto:
            return p
    return live[-1]


def resolve(db: Session, workspace_id: int, name: str, *, label: str = "",
            key: str = "") -> tuple[Prompt | None, str]:
    """(prompt, reason) for a runtime fetch.

    Resolution order is deliberate: an explicit label wins, then a traffic split, then the
    newest version. A split must not silently override a label — if someone pinned production
    to a version, an experiment started later should not quietly redirect them.
    """
    versions = _versions(db, workspace_id, name)
    if not versions:
        return None, "no prompt with that name"
    if label:
        for p in versions:
            if (p.label or "") == label:
                return p, f"label:{label}"
        return None, f"no version labelled {label!r}"
    live = [p for p in versions if (p.traffic or 0) > 0]
    if live:
        chosen = assign(live, key or name)
        return chosen, f"split:{chosen.version}" if chosen else "split:none"
    return versions[0], f"latest:{versions[0].version}"


def as_dict(p: Prompt, reason: str) -> dict:
    return {"name": p.name, "version": p.version, "label": p.label or "",
            "model": p.model, "messages": p.messages or [], "params": p.params or {},
            "traffic": p.traffic or 0.0,
            # Echoed so the caller can stamp it on the span. A split whose outcome isn't
            # attached to the run leaves two populations nobody can tell apart afterwards.
            "served_by": reason}


def validate_split(versions: list[Prompt]) -> None:
    """Refuse a split that can't be interpreted."""
    live = [p for p in versions if (p.traffic or 0) > 0]
    if not live:
        return
    if len(live) == 1:
        raise ValueError("a split needs at least two versions taking traffic — one version at "
                         "any weight is just the served prompt")
    if any(p.traffic < 0 for p in live):
        raise ValueError("traffic weights cannot be negative")
