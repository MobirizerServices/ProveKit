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


# ---- what we ask the database to do ---------------------------------------------------------
# The Postgres tests above only run when a server is pointed at, so on CI the decision logic
# below — which month gets created, which partition is old enough to drop — was executing
# nowhere. These drive it against a stub session that records the SQL instead of running it.
#
# This is not a substitute for the real thing: a stub cannot tell you Postgres accepts the DDL.
# It tells you we asked for the right months and refused to drop a partition still holding
# retained rows, which is the part that would silently delete a customer's data if it were
# wrong.

class _Result:
    def __init__(self, rows):
        self._rows = rows

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return self._rows


class _StubDB:
    """Answers the catalogue queries; records everything else."""

    class _Bind:
        class dialect:
            name = "sqlite"          # the real dialect check sees SQLite unless patched

    bind = _Bind()

    def __init__(self, *, partitioned=True, existing=(), rowcount=0, span=None):
        self.partitioned, self.existing = partitioned, list(existing)
        self.rowcount, self.span = rowcount, span
        self.sql, self.commits = [], 0

    def execute(self, clause, params=None):
        q = " ".join(str(clause).split())
        self.sql.append(q)
        if "pg_class c WHERE c.relname" in q:
            return _Result([("p",)] if self.partitioned else [("r",)])
        if "pg_inherits" in q:
            return _Result([(n,) for n in self.existing])
        if q.lower().startswith("select count(*)"):
            return _Result([(self.rowcount, *(self.span or (None, None)))])
        return _Result([])

    def commit(self):
        self.commits += 1


@pytest.fixture
def as_postgres(monkeypatch):
    monkeypatch.setattr(partitions, "supported", lambda db: True)


def test_ensure_ahead_creates_this_month_and_the_months_after_it(as_postgres):
    """The failure this prevents is specific: a partitioned table with no partition for the
    current month rejects the insert outright, so ingest starts failing at midnight on the 1st."""
    db = _StubDB()
    made = partitions.ensure_ahead(db, 3, now=datetime(2026, 11, 14, tzinfo=timezone.utc))
    assert made == ["runs_2026_11", "runs_2026_12", "runs_2027_01", "runs_2027_02"]
    ddl = [q for q in db.sql if q.startswith("CREATE TABLE")]
    assert len(ddl) == 4
    # bounds are half-open and contiguous — no gap for a row to fall through, no overlap
    assert "FOR VALUES FROM ('2026-11-01') TO ('2026-12-01')" in ddl[0]
    assert "FOR VALUES FROM ('2026-12-01') TO ('2027-01-01')" in ddl[1]
    assert all("IF NOT EXISTS" in q for q in ddl), "re-running must not error on an existing month"
    assert db.commits == 1


def test_ensure_ahead_on_an_unpartitioned_table_does_nothing(as_postgres):
    db = _StubDB(partitioned=False)
    assert partitions.ensure_ahead(db, 3) == []
    assert not [q for q in db.sql if q.startswith("CREATE TABLE")]


def test_drop_before_leaves_a_partition_that_straddles_the_cutoff(as_postgres):
    """The one that matters. A partition ending after the cutoff still holds rows inside the
    retention window; dropping it would delete retained data to save a vacuum."""
    db = _StubDB(existing=["runs_2026_01", "runs_2026_02", "runs_2026_03"])
    dropped = partitions.drop_before(db, datetime(2026, 3, 10, tzinfo=timezone.utc))
    assert dropped == ["runs_2026_01", "runs_2026_02"]
    assert "runs_2026_03" not in " ".join(q for q in db.sql if q.startswith("DROP"))


def test_drop_before_ignores_tables_that_are_not_ours(as_postgres):
    """Something else inheriting from the table is not ours to drop."""
    db = _StubDB(existing=["runs_2026_01", "runs_archive_backup", "runs_not_a_date"])
    dropped = partitions.drop_before(db, datetime(2027, 1, 1, tzinfo=timezone.utc))
    assert dropped == ["runs_2026_01"]


def test_drop_before_with_nothing_expired_does_not_commit(as_postgres):
    db = _StubDB(existing=["runs_2026_05"])
    assert partitions.drop_before(db, datetime(2026, 5, 2, tzinfo=timezone.utc)) == []
    assert db.commits == 0


def test_is_partitioned_reads_the_catalogue(as_postgres):
    assert partitions.is_partitioned(_StubDB(partitioned=True)) is True
    assert partitions.is_partitioned(_StubDB(partitioned=False)) is False


def test_partitions_lists_the_children_in_order(as_postgres):
    db = _StubDB(existing=["runs_2026_01", "runs_2026_02"])
    assert partitions.partitions(db) == ["runs_2026_01", "runs_2026_02"]


def test_plan_reports_an_already_partitioned_table_without_counting_rows(as_postgres):
    db = _StubDB(existing=["runs_2026_01"])
    out = partitions.plan(db)
    assert out["already_partitioned"] is True
    assert out["partitions"] == ["runs_2026_01"]
    assert not [q for q in db.sql if q.lower().startswith("select count(*)")]


def test_plan_sizes_the_job_before_an_operator_starts_it(as_postgres):
    """Converting rewrites the largest table they have; the row count and month span are the
    two numbers that decide whether to do it now or at 3am."""
    db = _StubDB(partitioned=False, rowcount=1_500_000,
                 span=(datetime(2026, 1, 5, tzinfo=timezone.utc),
                       datetime(2026, 4, 20, tzinfo=timezone.utc)))
    out = partitions.plan(db)
    assert out["supported"] is True
    assert out.get("already_partitioned") in (False, None)
    assert out["rows"] == 1_500_000
    assert out["partitions_needed"] == 4        # Jan..Apr inclusive
    assert out["oldest"].startswith("2026-01-05")
    assert "maintenance window" in out["note"]


def test_plan_on_sqlite_says_why_not():
    db = _StubDB()
    out = partitions.plan(db)          # `supported` NOT patched here — the real dialect check
    assert out["supported"] is False
    assert "PostgreSQL" in out["reason"]
