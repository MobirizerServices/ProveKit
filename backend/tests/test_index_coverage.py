"""Query plans for the hot read paths.

An index audit written as prose is out of date the day someone adds a filter. These assert the
plan itself, so a query that regresses to a scan fails here instead of on someone's production
dashboard.

SQLite plans, since that's the dev/test database. The shapes are the same ones Postgres plans —
a composite led by the filtered column, carrying the ordering/range column — so a regression
that shows up here is a regression there too. It is not a substitute for EXPLAIN on real
Postgres data, but it catches the change that causes it.
"""
import pytest
from sqlalchemy import text

from provekit.database import SessionLocal, engine
from provekit.models import Run


def _plan(sql: str, params: dict | None = None) -> str:
    with engine.connect() as conn:
        rows = conn.execute(text("EXPLAIN QUERY PLAN " + sql), params or {}).fetchall()
    return " | ".join(str(r[-1]) for r in rows)


@pytest.fixture(scope="module", autouse=True)
def _rows():
    """SQLite will happily scan a tiny table whatever indexes exist, so give the planner enough
    rows that choosing an index is the cheaper plan and the assertion means something."""
    db = SessionLocal()
    try:
        existing = db.query(Run).filter(Run.workspace_id == 424242).count()
        if existing < 400:
            for i in range(400):
                db.add(Run(workspace_id=424242, type="llm", label=f"seed-{i}",
                           status="failed" if i % 7 == 0 else "completed",
                           trace_id=f"{i:032x}", span_id=f"{i:016x}",
                           parent_span_id="" if i % 5 == 0 else f"{i - 1:016x}",
                           session_id=f"s{i % 13}", duration_ms=i, request={}, result={}))
            db.commit()
        yield
    finally:
        db.close()


def test_trace_list_walks_an_index_not_the_table():
    """"Newest N traces in this project" is the most-loaded query in the product."""
    plan = _plan("SELECT * FROM runs WHERE workspace_id = :ws AND parent_span_id = '' "
                 "ORDER BY id DESC LIMIT 50", {"ws": 424242})
    assert "ix_runs_ws_root" in plan, plan
    assert "SCAN runs" not in plan, plan


def test_metrics_window_uses_the_created_at_composite():
    """The widest scan we have: every span in a project inside a time window."""
    plan = _plan("SELECT result, request, created_at FROM runs "
                 "WHERE workspace_id = :ws AND created_at >= :cut", {"ws": 424242, "cut": "2000-01-01"})
    assert "ix_runs_ws_created" in plan, plan
    assert "SCAN runs" not in plan, plan


def test_failures_panel_uses_the_status_composite():
    plan = _plan("SELECT type, count(id) FROM runs WHERE workspace_id = :ws "
                 "AND status = 'failed' AND created_at >= :cut GROUP BY type",
                 {"ws": 424242, "cut": "2000-01-01"})
    assert "ix_runs_ws_status_created" in plan, plan
    assert "SCAN runs" not in plan, plan


def test_session_grouping_uses_an_index():
    plan = _plan("SELECT * FROM runs WHERE workspace_id = :ws AND session_id = 's3'",
                 {"ws": 424242})
    assert "SCAN runs" not in plan, plan


def test_span_dedupe_lookup_uses_the_unique_index():
    """The ingest hot path — checked on every batch, so a scan here costs on every write."""
    plan = _plan("SELECT trace_id, span_id FROM runs WHERE workspace_id = :ws "
                 "AND trace_id IN ('abc') AND span_id != ''", {"ws": 424242})
    assert "uq_run_span" in plan or "ix_runs_trace_id" in plan, plan
    assert "SCAN runs" not in plan, plan
