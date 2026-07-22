"""Time-partitioned span storage (Postgres).

`runs` grows without bound and dominates the schema, and retention is enforced by deleting
rows — which is the expensive way to do it. A delete storm rewrites index pages, leaves dead
tuples for autovacuum to chase, and does all of that while ingest is competing for the same
table. Dropping a partition is a catalogue operation: constant time, no dead tuples, no
vacuum debt.

**This is opt-in and Postgres-only, and it is deliberately not part of the boot migration.**
Converting a populated `runs` table means moving every row, and doing that inside the
migration that runs automatically on startup would turn a deploy into an unbounded outage on
exactly the instances big enough to want partitioning. `plan()` tells you what it would do,
`convert()` does it when an operator chooses to, and `ensure_ahead()` keeps future partitions
created so ingest never arrives at a month with nowhere to go.

SQLite has no declarative partitioning and never will; on SQLite everything here reports
"unsupported" and retention keeps working exactly as before. That is not a degraded mode —
a SQLite deployment is a single-node dev or small self-host, where the delete storm this
avoids is not a problem it has.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

log = logging.getLogger("provekit.partitions")

PARTITIONED_TABLE = "runs"
#: Monthly. Daily would make a year 365 partitions and Postgres plans slowly past a few
#: hundred; yearly makes retention useless, since you can only drop a whole year at once.
_FMT = "%Y_%m"


def supported(db: Session) -> bool:
    return db.bind.dialect.name == "postgresql"


def _month_start(dt: datetime) -> datetime:
    return dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _next_month(dt: datetime) -> datetime:
    return _month_start(_month_start(dt) + timedelta(days=32))


def partition_name(dt: datetime) -> str:
    return f"{PARTITIONED_TABLE}_{_month_start(dt).strftime(_FMT)}"


def is_partitioned(db: Session) -> bool:
    """Whether `runs` is already a partitioned table."""
    if not supported(db):
        return False
    row = db.execute(text(
        "SELECT c.relkind FROM pg_class c WHERE c.relname = :t"), {"t": PARTITIONED_TABLE}).first()
    return bool(row and row[0] == "p")


def partitions(db: Session) -> list[str]:
    if not supported(db):
        return []
    rows = db.execute(text(
        "SELECT c.relname FROM pg_inherits i "
        "JOIN pg_class c ON c.oid = i.inhrelid "
        "JOIN pg_class p ON p.oid = i.inhparent "
        "WHERE p.relname = :t ORDER BY c.relname"), {"t": PARTITIONED_TABLE}).all()
    return [r[0] for r in rows]


def create_partition(db: Session, when: datetime) -> str:
    """Create the monthly partition covering `when`, if absent. Returns its name."""
    start = _month_start(when)
    end = _next_month(start)
    name = partition_name(start)
    db.execute(text(
        f'CREATE TABLE IF NOT EXISTS "{name}" PARTITION OF "{PARTITIONED_TABLE}" '
        f"FOR VALUES FROM ('{start:%Y-%m-%d}') TO ('{end:%Y-%m-%d}')"))
    return name


def ensure_ahead(db: Session, months: int = 3, *, now: datetime | None = None) -> list[str]:
    """Make sure the next `months` partitions exist.

    Run on a schedule. A partitioned table with no partition for the current month rejects
    the insert outright — so ingest would start failing at midnight on the 1st, which is the
    single worst way to discover this feature exists.
    """
    if not is_partitioned(db):
        return []
    now = now or datetime.now(timezone.utc)
    made = []
    cursor = _month_start(now)
    for _ in range(max(1, months) + 1):
        made.append(create_partition(db, cursor))
        cursor = _next_month(cursor)
    db.commit()
    return made


def drop_before(db: Session, cutoff: datetime) -> list[str]:
    """Drop whole partitions that end at or before `cutoff`. Returns what was dropped.

    The point of the exercise: retention becomes a catalogue operation instead of a delete
    storm. Only drops partitions entirely older than the cutoff — a partition that straddles
    it still holds rows you are keeping, and dropping it would delete retained data to save
    a vacuum.
    """
    if not is_partitioned(db):
        return []
    dropped = []
    for name in partitions(db):
        try:
            stamp = datetime.strptime(name[len(PARTITIONED_TABLE) + 1:], _FMT)
        except ValueError:
            continue                      # not one of ours; leave it alone
        stamp = stamp.replace(tzinfo=timezone.utc)
        if _next_month(stamp) <= _month_start(cutoff):
            db.execute(text(f'DROP TABLE IF EXISTS "{name}"'))
            dropped.append(name)
    if dropped:
        db.commit()
        log.info("dropped %d expired span partition(s): %s", len(dropped), ", ".join(dropped))
    return dropped


def plan(db: Session) -> dict:
    """What conversion would involve, without doing any of it.

    An operator should be able to see the row count and the month span before starting a
    migration that rewrites the largest table they have.
    """
    if not supported(db):
        return {"supported": False, "reason": "partitioning requires PostgreSQL"}
    if is_partitioned(db):
        return {"supported": True, "already_partitioned": True,
                "partitions": partitions(db)}
    row = db.execute(text(
        f"SELECT count(*), min(created_at), max(created_at) FROM {PARTITIONED_TABLE}")).first()
    count, oldest, newest = row[0] or 0, row[1], row[2]
    months = 0
    if oldest and newest:
        months = (newest.year - oldest.year) * 12 + (newest.month - oldest.month) + 1
    return {"supported": True, "already_partitioned": False, "rows": count,
            "oldest": oldest.isoformat() if oldest else None,
            "newest": newest.isoformat() if newest else None,
            "partitions_needed": months,
            "note": ("Conversion copies every row and holds a lock on runs. Run it in a "
                     "maintenance window, not during ingest.")}
