"""Durable accept: a batch the server took must survive the database losing it.

The property under test is the one an observability tool cannot get wrong — if ingest returns
success, the spans exist somewhere; if ingest fails, they are still staged for retry. Nothing
in between.
"""
import pytest
from fastapi.testclient import TestClient

from provekit.main import app
from provekit.routers import traces as traces_router
from provekit.services import spool


def _span(name="chat", trace_id=None, span_id=None):
    s = {"name": name, "startTimeUnixNano": "1000000000", "endTimeUnixNano": "1500000000",
         "status": {"code": 1},
         "attributes": [{"key": "gen_ai.request.model", "value": {"stringValue": "gpt-4o"}},
                        {"key": "gen_ai.completion", "value": {"stringValue": "hi"}}]}
    if trace_id:
        s["traceId"] = trace_id
    if span_id:
        s["spanId"] = span_id
    return s


def _otlp(*spans):
    return {"resourceSpans": [{"scopeSpans": [{"spans": list(spans)}]}]}


def _ingesting_workspace(client) -> int:
    """The workspace this client's ingest actually lands in.

    Don't assume `Workspace.first()` — the suite includes tenant-deletion tests, so whichever
    row that returns depends on execution order. Push a span and read back where it went.
    """
    probe = "9f" * 16
    client.post("/v1/traces", json=_otlp(_span(trace_id=probe, span_id="9e" * 8)))
    from provekit.database import SessionLocal
    from provekit.models import Run
    db = SessionLocal()
    try:
        return db.query(Run).filter(Run.trace_id == probe).first().workspace_id
    finally:
        db.close()


def _rows_with_trace(trace_id: str, workspace_id: int | None = None) -> int:
    """Count landed spans by trace id — `/api/runs` is page-capped and shared with every other
    test's data, so it can't answer 'did exactly this batch land'.

    Scope to a workspace when the test knows it: span-id uniqueness is per (workspace, trace),
    so the same id legitimately exists in two tenants and a global count would conflate them.
    """
    from provekit.database import SessionLocal
    from provekit.models import Run
    db = SessionLocal()
    try:
        q = db.query(Run).filter(Run.trace_id == trace_id)
        if workspace_id is not None:
            q = q.filter(Run.workspace_id == workspace_id)
        return q.count()
    finally:
        db.close()


@pytest.fixture(autouse=True)
def _clean_spool():
    """Each test owns the backlog; a leftover entry would change every depth assertion."""
    for p in spool.spool_dir().glob("*") if spool.spool_dir().exists() else []:
        p.unlink()
    spool.invalidate_depth_cache()   # files removed behind the cache's back
    yield
    for p in spool.spool_dir().glob("*") if spool.spool_dir().exists() else []:
        p.unlink()
    spool.invalidate_depth_cache()


def test_successful_ingest_leaves_no_backlog():
    """The happy path stages and then releases — a spool that only grows is a leak."""
    with TestClient(app) as client:
        r = client.post("/v1/traces", json=_otlp(_span()))
        assert r.status_code == 200
    assert spool.depth() == 0


def test_failed_persist_retains_the_batch_and_reports_failure(monkeypatch):
    """A DB blip must not be reported as success, and must not consume the data.

    This is the whole point: before the spool, this scenario returned 200 (or a 5xx after the
    rows were already gone) and the spans existed nowhere.
    """
    def _boom(*a, **kw):
        raise RuntimeError("database is gone")

    monkeypatch.setattr(traces_router, "_persist_spans", _boom)
    with TestClient(app) as client:
        r = client.post("/v1/traces", json=_otlp(_span("doomed")))
    assert r.status_code == 503                 # the exporter will retry, and #184 dedupes it
    assert spool.depth() == 1                   # ...but the batch is already safe on disk


def test_drain_replays_a_staged_batch(monkeypatch):
    """What the drainer exists for: the rows land once the database is back."""
    def _boom(*a, **kw):
        raise RuntimeError("database is gone")

    tid = "a1" * 16
    with TestClient(app) as client:
        monkeypatch.setattr(traces_router, "_persist_spans", _boom)
        client.post("/v1/traces", json=_otlp(_span(trace_id=tid, span_id="b1" * 8)))
        assert spool.depth() == 1
        assert _rows_with_trace(tid) == 0        # genuinely not in the database yet
        monkeypatch.undo()                       # database recovers
        assert traces_router.drain_spool() == 1
        assert spool.depth() == 0
    assert _rows_with_trace(tid) == 1            # the span the write had lost


def test_drain_is_idempotent(monkeypatch):
    """Draining a batch that actually did land must not duplicate it — the drainer and the
    request path can both believe they own the same rows after a partial failure."""
    tid = "5b" * 16                                       # distinct from every other test's ids
    rows = [{"type": "llm", "label": "once", "trace_id": tid, "span_id": "d" * 16,
             "parent_span_id": "", "duration_ms": 500, "status": "ok",
             "request": {}, "result": {}}]
    with TestClient(app) as client:
        ws_id = _ingesting_workspace(client)
        # Stage the same batch twice, as a crash between commit and release would leave it.
        spool.stage(ws_id, rows)
        assert traces_router.drain_spool() == 1
        spool.stage(ws_id, rows)
        assert traces_router.drain_spool() == 1           # entry cleared again...
        landed = _rows_with_trace(tid, ws_id)
    assert landed == 1                                    # ...but the span landed exactly once


def test_backpressure_sheds_load_when_the_backlog_is_full(monkeypatch):
    """A spike must become a retriable 503, not unbounded disk and database pressure."""
    with TestClient(app) as client:
        # Stage *after* startup: the drainer makes a pass as soon as it starts, and would
        # otherwise clear the backlog this test is about to assert on.
        ws_id = _ingesting_workspace(client)
        monkeypatch.setattr(traces_router.get_settings(), "spool_max_depth", 1, raising=False)
        spool.stage(ws_id, [{"type": "llm", "label": "backlog", "trace_id": "e" * 32,
                             "span_id": "f" * 16, "parent_span_id": "", "duration_ms": 1,
                             "status": "ok", "request": {}, "result": {}}])
        r = client.post("/v1/traces", json=_otlp(_span()))
    assert r.status_code == 503
    assert r.headers.get("Retry-After") == "5"


def test_health_reports_ingest_backlog():
    """ProveKit should be the first tool to say ProveKit is unhealthy (#14)."""
    with TestClient(app) as client:
        body = client.get("/healthz").json()
    assert body["ingest"]["spool"] is True
    assert body["ingest"]["queue_depth"] == 0
    assert body["ingest"]["lag_seconds"] == 0.0
    # The two ways a batch fails to become rows are reported, not just logged.
    assert "shed" in body["ingest"] and "quarantined" in body["ingest"]


def test_corrupt_entry_is_quarantined_not_retried_forever():
    """An unparseable entry must not wedge the queue behind it."""
    d = spool.spool_dir()
    d.mkdir(parents=True, exist_ok=True)
    bad = d / "0000000000001-1-000001.json"
    bad.write_text("{not json")
    assert spool.load(bad) is None
    assert not bad.exists()
    assert bad.with_suffix(".corrupt").exists()
    bad.with_suffix(".corrupt").unlink()
