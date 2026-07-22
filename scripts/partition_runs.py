#!/usr/bin/env python
"""Convert `runs` to a monthly time-partitioned table (PostgreSQL only).

Deliberately a script and not a boot migration: converting a populated table copies every row
and holds a lock, and doing that inside the migration that runs automatically on startup would
turn a deploy into an unbounded outage on exactly the instances large enough to want this.

    python scripts/partition_runs.py --plan       # what it would do; changes nothing
    python scripts/partition_runs.py --convert    # do it (maintenance window)

Afterwards, retention can drop whole partitions instead of deleting rows — a catalogue
operation rather than a delete storm competing with ingest for the same table.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))

from sqlalchemy import text                       # noqa: E402

from provekit.database import SessionLocal        # noqa: E402
from provekit.services import partitions          # noqa: E402


def convert(db) -> None:
    """Rebuild `runs` as a partitioned table and move the rows across.

    The partition key must be part of the primary key in Postgres, so `id` alone can no longer
    be it — the new key is (id, created_at). Sequence ownership moves with the column so ids
    keep advancing from where they were; resetting it would collide with existing rows.
    """
    if partitions.is_partitioned(db):
        print("runs is already partitioned — nothing to do.")
        return
    print("renaming runs -> runs_legacy …")
    db.execute(text("ALTER TABLE runs RENAME TO runs_legacy"))
    db.execute(text("""
        CREATE TABLE runs (LIKE runs_legacy INCLUDING DEFAULTS INCLUDING STORAGE)
        PARTITION BY RANGE (created_at)
    """))
    db.execute(text("ALTER TABLE runs ADD PRIMARY KEY (id, created_at)"))
    db.commit()

    row = db.execute(text("SELECT min(created_at), max(created_at) FROM runs_legacy")).first()
    if row and row[0]:
        cursor = partitions._month_start(row[0])
        while cursor <= row[1]:
            print("  partition", partitions.create_partition(db, cursor))
            cursor = partitions._next_month(cursor)
    partitions.ensure_ahead(db)
    db.commit()

    print("copying rows …")
    db.execute(text("INSERT INTO runs SELECT * FROM runs_legacy"))
    db.commit()
    moved = db.execute(text("SELECT count(*) FROM runs")).scalar()
    kept = db.execute(text("SELECT count(*) FROM runs_legacy")).scalar()
    if moved != kept:
        # Refuse to drop the original unless every row arrived. Losing spans to a performance
        # migration would be the worst possible trade.
        raise SystemExit(f"row count mismatch: {moved} in runs, {kept} in runs_legacy — "
                         "runs_legacy has been left in place, investigate before dropping it")
    print(f"moved {moved} rows; run 'DROP TABLE runs_legacy' once you are satisfied.")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--plan", action="store_true")
    g.add_argument("--convert", action="store_true")
    g.add_argument("--ensure-ahead", type=int, metavar="MONTHS")
    args = ap.parse_args()
    db = SessionLocal()
    try:
        if args.plan:
            print(json.dumps(partitions.plan(db), indent=2, default=str))
        elif args.convert:
            if not partitions.supported(db):
                raise SystemExit("partitioning requires PostgreSQL")
            convert(db)
        else:
            print("ensured:", partitions.ensure_ahead(db, args.ensure_ahead))
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
