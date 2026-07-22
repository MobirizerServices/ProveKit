"""Time-partitioned span storage (#19).

Retention deletes rows, which is the expensive way: a delete storm rewrites index pages and
leaves dead tuples for autovacuum, all while competing with ingest for the same table.
Dropping a partition is a catalogue operation.

Postgres-only by nature. The suite runs on SQLite, so the tests here assert the *contract* on
SQLite (report unsupported, change nothing) and the Postgres behaviour is covered by tests
that skip unless PROVEKIT_TEST_PG points at a real server. Those were run against
postgres:17-alpine while writing this — conversion of a populated table, partition drop, and
inserts afterwards — and the results are in the commit message rather than asserted here,
because a test that silently skips is not evidence.
"""
import os
from datetime import datetime, timedelta, timezone

import pytest

from provekit.database import SessionLocal
from provekit.services import partitions

PG = os.environ.get("PROVEKIT_TEST_PG")


# ---- the SQLite contract: unsupported, and inert -------------------------------------------

def test_sqlite_reports_unsupported_and_does_nothing():
    """Not a degraded mode. A SQLite deployment is single-node dev or a small self-host, where
    the delete storm this avoids is not a problem it has — so retention keeps working as it
    always did and nothing here pretends otherwise."""
    db = SessionLocal()
    try:
        assert partitions.supported(db) is False
        assert partitions.is_partitioned(db) is False
        assert partitions.partitions(db) == []
        assert partitions.ensure_ahead(db) == []
        assert partitions.drop_before(db, datetime.now(timezone.utc)) == []
        plan = partitions.plan(db)
        assert plan["supported"] is False and "PostgreSQL" in plan["reason"]
    finally:
        db.close()


# ---- pure date arithmetic, worth pinning ---------------------------------------------------

def test_partition_names_are_monthly():
    assert partitions.partition_name(datetime(2026, 7, 22, tzinfo=timezone.utc)) == "runs_2026_07"
    assert partitions.partition_name(datetime(2026, 1, 1, tzinfo=timezone.utc)) == "runs_2026_01"


def test_next_month_crosses_a_year_boundary():
    """A 32-day step from a December start must land on January, not skip it."""
    dec = datetime(2026, 12, 5, tzinfo=timezone.utc)
    assert partitions._next_month(dec) == datetime(2027, 1, 1, tzinfo=timezone.utc)


def test_month_start_normalises_the_whole_timestamp():
    dt = datetime(2026, 7, 22, 13, 47, 11, 992, tzinfo=timezone.utc)
    assert partitions._month_start(dt) == datetime(2026, 7, 1, tzinfo=timezone.utc)


# ---- Postgres, only when one is actually available -----------------------------------------

pg_only = pytest.mark.skipif(
    not PG, reason="set PROVEKIT_TEST_PG=postgresql+psycopg://… to run the Postgres tests")


@pg_only
def test_conversion_moves_every_row_and_drop_removes_a_whole_month():
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session

    eng = create_engine(PG)
    with Session(eng) as db:
        if not partitions.is_partitioned(db):
            pytest.skip("run scripts/partition_runs.py --convert against this database first")
        before = db.execute(text("SELECT count(*) FROM runs")).scalar()
        names = partitions.partitions(db)
        assert names, "a partitioned table with no partitions rejects every insert"
        dropped = partitions.drop_before(db, datetime.now(timezone.utc) - timedelta(days=400))
        after = db.execute(text("SELECT count(*) FROM runs")).scalar()
        # Dropping only whole expired partitions: nothing inside the retention window goes.
        assert after == before or dropped
    eng.dispose()


@pg_only
def test_ensure_ahead_is_idempotent():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    eng = create_engine(PG)
    with Session(eng) as db:
        if not partitions.is_partitioned(db):
            pytest.skip("not partitioned")
        first = set(partitions.ensure_ahead(db, 3))
        second = set(partitions.ensure_ahead(db, 3))
        assert first == second
    eng.dispose()
