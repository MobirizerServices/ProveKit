"""Observable retention: pruning has to leave a record.

"My trace is missing" and "my trace never arrived" are a config question and an
instrumentation bug. Chased very differently, and until pruning was recorded there was
nothing in the product to tell them apart.
"""
import pytest
from fastapi.testclient import TestClient

from provekit.database import SessionLocal
from provekit.main import app
from provekit.models import RetentionEvent, Run, Workspace


def _span(i: int) -> dict:
    return {"name": "chat", "traceId": f"{i:032x}", "spanId": f"{i:016x}",
            "startTimeUnixNano": "1000000000", "endTimeUnixNano": "1500000000",
            "status": {"code": 1},
            "attributes": [{"key": "gen_ai.request.model", "value": {"stringValue": "gpt-4o"}}]}


def _otlp(*spans):
    return {"resourceSpans": [{"scopeSpans": [{"spans": list(spans)}]}]}


def _live_workspace() -> int:
    """The workspace ingest actually lands in.

    Not `Workspace.first()`: the local workspace is created lazily on first request, so
    standalone runs of this file would otherwise find no rows at all.
    """
    probe = 0xdead
    with TestClient(app) as client:
        client.post("/v1/traces", json=_otlp(_span(probe)))
    db = SessionLocal()
    try:
        # Read back where the probe landed. `Workspace.first()` is a different row once other
        # tests in the suite have created workspaces, and setting retention on the wrong one
        # silently makes every assertion here meaningless.
        return db.query(Run).filter(Run.trace_id == f"{probe:032x}").first().workspace_id
    finally:
        db.close()


@pytest.fixture
def tiny_retention():
    """Squeeze the cap so a handful of spans trips pruning."""
    ws_id = _live_workspace()
    db = SessionLocal()
    ws = db.query(Workspace).filter(Workspace.id == ws_id).first()
    prev = ws.retention
    ws.retention = 3
    db.commit()
    db.query(RetentionEvent).filter(RetentionEvent.workspace_id == ws_id).delete()
    db.commit()
    db.close()
    yield ws_id
    db = SessionLocal()
    ws = db.query(Workspace).filter(Workspace.id == ws_id).first()
    ws.retention = prev
    db.query(RetentionEvent).filter(RetentionEvent.workspace_id == ws_id).delete()
    db.commit()
    db.close()


def test_pruning_is_recorded(tiny_retention):
    with TestClient(app) as client:
        for i in range(900, 910):
            client.post("/v1/traces", json=_otlp(_span(i)))
        status = client.get("/api/workspace/retention").json()
    assert status["keep"] == 3
    assert status["stored_spans"] == 3
    assert status["pruned_total"] > 0            # ...and we can say so
    assert status["recent"] and status["recent"][0]["deleted"] > 0
    assert status["oldest_retained_at"]          # nothing older than this exists


def test_events_coalesce_into_one_row_per_hour(tiny_retention):
    """Pruning runs on almost every ingest; a row per prune would be its own write problem."""
    with TestClient(app) as client:
        for i in range(920, 940):
            client.post("/v1/traces", json=_otlp(_span(i)))
    db = SessionLocal()
    try:
        rows = db.query(RetentionEvent).filter(
            RetentionEvent.workspace_id == tiny_retention).all()
        assert len(rows) == 1                     # one bucket, many prunes
        assert rows[0].deleted >= 15
        assert rows[0].keep == 3
    finally:
        db.close()


def test_no_pruning_no_event():
    """A project inside its cap must not accumulate noise rows."""
    ws_id = _live_workspace()
    db = SessionLocal()
    ws = db.query(Workspace).filter(Workspace.id == ws_id).first()
    prev = ws.retention
    ws.retention = 100000
    db.commit()
    db.query(RetentionEvent).filter(RetentionEvent.workspace_id == ws_id).delete()
    db.commit()
    db.close()
    try:
        with TestClient(app) as client:
            client.post("/v1/traces", json=_otlp(_span(981)))
        db = SessionLocal()
        assert db.query(RetentionEvent).filter(
            RetentionEvent.workspace_id == ws_id).count() == 0
        db.close()
    finally:
        db = SessionLocal()
        db.query(Workspace).filter(Workspace.id == ws_id).first().retention = prev
        db.commit()
        db.close()


def test_status_reports_the_policy_even_with_no_history():
    with TestClient(app) as client:
        status = client.get("/api/workspace/retention").json()
    assert "keep" in status and "stored_spans" in status
    assert isinstance(status["recent"], list)


def test_pruned_spans_are_really_gone(tiny_retention):
    """The record has to describe something that actually happened."""
    with TestClient(app) as client:
        for i in range(950, 960):
            client.post("/v1/traces", json=_otlp(_span(i)))
    db = SessionLocal()
    try:
        assert db.query(Run).filter(Run.workspace_id == tiny_retention).count() == 3
    finally:
        db.close()
