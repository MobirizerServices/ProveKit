"""Scheduled bulk export (#93).

`services/export.iter_ndjson` already pages on `after_id`, which is exactly the incremental
cursor a schedule needs. What was missing is somewhere to keep that cursor between runs — and
that is the whole difficulty, because the obvious shortcuts are the ones that fail quietly:

* **Re-sending everything each run** grows without bound and eventually times out.
* **Keeping the cursor in memory** forgets on restart, so a warehouse silently goes stale while
  the schedule reports itself as running.
* **Advancing the cursor before delivery is accepted** turns one failed POST into a permanent
  hole in the customer's data — the worst outcome here, because nothing surfaces it.

So the cursor is persisted, and advanced *only* after the destination accepts the batch. A
failed run re-sends the same window next time and records why on the row, where an operator can
see it, rather than being swallowed by a background loop nobody watches.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..models import ExportSchedule, _now
from . import export as export_svc
from . import netguard

log = logging.getLogger("provekit.export_schedule")

#: Cadence → how often a schedule is due.
CADENCES = {"hourly": 1, "daily": 24, "weekly": 24 * 7}

#: Rows per delivery. A schedule that fell far behind catches up over several runs instead of
#: building one request too large for the destination to accept.
MAX_ROWS = 5000

_TIMEOUT = 60.0


def interval_hours(cadence: str) -> int:
    return CADENCES.get(cadence, CADENCES["daily"])


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def due(db: Session, *, now: datetime | None = None) -> list[ExportSchedule]:
    """Schedules ready to run.

    One that has never run is due immediately — otherwise creating a schedule would appear to do
    nothing until a full cadence had elapsed, and the natural reading of that is "it's broken".
    """
    now = now or _now()
    out = []
    for s in db.query(ExportSchedule).filter(ExportSchedule.enabled.is_(True)).all():
        last = _aware(s.last_run_at)
        if last is None or now - last >= timedelta(hours=interval_hours(s.cadence)):
            out.append(s)
    return out


def _deliver(url: str, body: str) -> None:
    """POST one NDJSON batch. Raises on anything that isn't an accepted response."""
    netguard.guard_url(url)          # same SSRF guard every other outbound URL goes through
    r = httpx.post(url, content=body.encode("utf-8"), timeout=_TIMEOUT,
                   headers={"Content-Type": "application/x-ndjson"})
    if r.status_code >= 300:
        raise RuntimeError(f"destination returned {r.status_code}")


def run(db: Session, s: ExportSchedule) -> dict:
    """Run one schedule. Never raises — a failing destination must not stop the others.

    Returns a small report; the same facts are written to the row so the portal and an operator
    see exactly what the loop saw.
    """
    started = _now()
    try:
        lines, last_id = [], s.cursor or 0
        for line in export_svc.iter_ndjson(s.workspace_id, after_id=s.cursor or 0,
                                           limit=MAX_ROWS, sentinel=False):
            lines.append(line)
        # The sentinel is off, so every line is a record; recover the high-water mark from the
        # last one rather than trusting a count.
        if lines:
            import json
            try:
                last_id = int(json.loads(lines[-1]).get("id") or last_id)
            except (ValueError, TypeError):
                last_id = s.cursor or 0

        if not lines:
            s.last_run_at, s.last_status, s.last_error, s.last_rows = started, "ok", "", 0
            db.commit()
            return {"rows": 0, "status": "ok", "cursor": s.cursor or 0}

        _deliver(s.destination_url, "".join(lines))
        # Only now: the batch is somewhere the customer controls.
        s.cursor = last_id
        s.last_run_at, s.last_status, s.last_error, s.last_rows = started, "ok", "", len(lines)
        db.commit()
        return {"rows": len(lines), "status": "ok", "cursor": s.cursor}
    except Exception as exc:                       # noqa: BLE001 — see docstring
        db.rollback()
        s.last_run_at, s.last_status = started, "failed"
        s.last_error = str(exc)[:300]
        s.last_rows = 0
        try:
            db.commit()
        except Exception:                          # noqa: BLE001
            db.rollback()
        log.warning("export schedule %s failed: %s", s.id, exc)
        return {"rows": 0, "status": "failed", "error": str(exc)[:300],
                "cursor": s.cursor or 0}


#: How long a worker's claim on a schedule is good for. Long enough to cover a slow delivery,
#: short enough that a worker killed mid-run doesn't strand the schedule for an hour.
LEASE_SECONDS = 600


def claim(db: Session, s: ExportSchedule, *, now: datetime | None = None) -> bool:
    """Take an exclusive lease on a schedule. True if this worker won it.

    A conditional UPDATE rather than a Redis lock: Redis is optional in this deployment and this
    must not be the feature that makes it mandatory. The database is already the thing both
    workers agree on.
    """
    now = now or _now()
    deadline = now + timedelta(seconds=LEASE_SECONDS)
    updated = (db.query(ExportSchedule)
               .filter(ExportSchedule.id == s.id,
                       or_(ExportSchedule.claimed_until.is_(None),
                           ExportSchedule.claimed_until < now))
               .update({ExportSchedule.claimed_until: deadline},
                       synchronize_session=False))
    db.commit()
    return bool(updated)


def release(db: Session, s: ExportSchedule) -> None:
    s.claimed_until = None
    try:
        db.commit()
    except Exception:                              # noqa: BLE001
        db.rollback()


def run_due(db: Session) -> int:
    """Run every due schedule this worker can claim. Returns how many ran."""
    ran = 0
    for s in due(db):
        if not claim(db, s):
            continue                               # another worker has it
        try:
            run(db, s)
            ran += 1
        finally:
            release(db, s)
    return ran


def row(s: ExportSchedule) -> dict:
    from ..models import iso_utc
    return {"id": s.id, "name": s.name, "cadence": s.cadence,
            "destination_url": s.destination_url, "cursor": s.cursor or 0,
            "enabled": s.enabled, "last_run_at": iso_utc(s.last_run_at),
            "last_status": s.last_status or "", "last_error": s.last_error or "",
            "last_rows": s.last_rows or 0, "created_at": iso_utc(s.created_at)}
