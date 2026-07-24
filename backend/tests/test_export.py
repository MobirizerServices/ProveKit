"""Bulk export (#93) — a project's spans streamed out as NDJSON for S3 or a warehouse.

Two things are load-bearing and get their own tests: the export must not build the project into
a list before sending it, and it must not write blob-store *pointers* into someone's warehouse
when a payload has been offloaded (#20).

The HTTP tests skip until `routers/export.py` is registered in `main.py` — see docs/EXPORT.md.
Self-registering the router here would make them pass against an app that does not exist.
"""
import json
from datetime import timedelta
from functools import lru_cache

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.engine import Engine

from conftest import ingest_workspace_id
from provekit.config import get_settings
from provekit.database import SessionLocal
from provekit.main import app
from provekit.models import AuditLog, Run, Workspace, _now
from provekit.services import export as export_svc
from provekit.services import payloads

# The routes exist as a router; whether they are reachable depends on wiring we do not own.
_WIRED = any(getattr(r, "path", "") == "/api/export/traces.ndjson" for r in app.routes)
needs_wiring = pytest.mark.skipif(
    not _WIRED, reason="export router is not registered in main.py yet (see docs/EXPORT.md)")


@lru_cache(maxsize=1)
def _owner_user_id() -> int:
    # ingest_workspace_id() drives a real request to find the workspace an ingest lands in;
    # once per module is plenty.
    db = SessionLocal()
    try:
        return db.get(Workspace, ingest_workspace_id()).owner_user_id
    finally:
        db.close()


@pytest.fixture
def project():
    """A workspace of our own, so assertions about *which* rows come out mean something.

    The suite shares one ingest workspace and other tests fill it with spans; counting rows in
    that one would assert nothing.
    """
    db = SessionLocal()
    try:
        ws = Workspace(name="export target", owner_user_id=_owner_user_id())
        db.add(ws)
        db.commit()
        return ws.id
    finally:
        db.close()


def _add(ws_id, label, *, request=None, result=None, minutes_ago=0, status="completed"):
    db = SessionLocal()
    try:
        row = Run(workspace_id=ws_id, type="llm", label=label, status=status,
                  request=request if request is not None else {"input": label},
                  result=result if result is not None else {"text": "ok"},
                  trace_id=f"{abs(hash(label)) % (16 ** 32):032x}", span_id="", duration_ms=5,
                  created_at=_now() - timedelta(minutes=minutes_ago))
        db.add(row)
        db.commit()
        return row.id
    finally:
        db.close()


def _read(ws_id, **kw):
    """Consume an export into (span records, sentinel-or-None)."""
    objs = [json.loads(line) for line in export_svc.iter_ndjson(ws_id, **kw)]
    tail = objs[-1] if objs and export_svc.SENTINEL_KEY in objs[-1] else None
    spans = [o for o in objs if export_svc.SENTINEL_KEY not in o]
    return spans, (tail or {}).get(export_svc.SENTINEL_KEY)


@pytest.fixture
def offloading(tmp_path):
    s = get_settings()
    prev = s.payload_offload_dir, s.payload_offload_min_bytes
    s.payload_offload_dir, s.payload_offload_min_bytes = str(tmp_path / "blobs"), 64
    yield tmp_path / "blobs"
    s.payload_offload_dir, s.payload_offload_min_bytes = prev


# ---------------------------------------------------------------- shape


def test_each_span_is_one_line_of_json(project):
    _add(project, "first")
    _add(project, "second")
    spans, tail = _read(project)
    assert [s["label"] for s in spans] == ["first", "second"]      # oldest first
    assert tail["status"] == "complete" and tail["rows"] == 2


def test_the_row_carries_the_scalars_a_warehouse_groups_by(project):
    """Lifted out of the JSON, not duplicated — the big text stays in request/result only."""
    _add(project, "priced", result={"text": "hi", "meta": {
        "model": "gpt-4o", "usage": {"input_tokens": 1000, "output_tokens": 500}}})
    spans, _ = _read(project)
    row = spans[0]
    assert row["model"] == "gpt-4o"
    assert (row["input_tokens"], row["output_tokens"]) == (1000, 500)
    assert row["cost_usd"] > 0
    assert row["created_at"].endswith("+00:00")                     # explicit UTC for the loader
    assert set(row) >= {"id", "trace_id", "span_id", "parent_span_id", "request", "result"}


def test_another_projects_spans_are_never_in_the_file(project):
    _add(project, "mine")
    _add(ingest_workspace_id(), "theirs")
    spans, _ = _read(project)
    assert [s["label"] for s in spans] == ["mine"]


# ---------------------------------------------------------------- streaming


def _count_run_queries():
    """Count SELECTs against `runs` while a block runs."""
    seen = []

    def hook(conn, cursor, statement, params, context, many):
        if "FROM runs" in statement:
            seen.append(statement)

    event.listen(Engine, "after_cursor_execute", hook)
    return seen, lambda: event.remove(Engine, "after_cursor_execute", hook)


def test_the_first_line_costs_one_bounded_query_not_a_full_scan(project, monkeypatch):
    """The point of streaming: a project with millions of spans must not be read, or built into
    a list, before the client gets its first byte."""
    monkeypatch.setattr(export_svc, "CHUNK", 2)
    for i in range(5):
        _add(project, f"span-{i}")
    seen, stop = _count_run_queries()
    try:
        gen = export_svc.iter_ndjson(project)
        first = json.loads(next(gen))
        assert first["label"] == "span-0"
        assert len(seen) == 1                     # one chunk read, not five rows fetched
        gen.close()
    finally:
        stop()


def test_it_pages_in_chunks_rather_than_fetching_everything(project, monkeypatch):
    monkeypatch.setattr(export_svc, "CHUNK", 2)
    for i in range(5):
        _add(project, f"span-{i}")
    seen, stop = _count_run_queries()
    try:
        spans, tail = _read(project)
    finally:
        stop()
    assert len(spans) == 5 and tail["rows"] == 5
    assert len(seen) == 3                          # 2 + 2 + 1, not one unbounded query


def test_no_more_than_one_chunk_of_rows_is_alive_at_a_time(project, monkeypatch):
    """Keyset paging is pointless if the ORM keeps every row it has seen.

    Checked mid-stream, not at the end: closing a session clears its identity map, so a check
    afterwards would pass whether or not chunks were released. Note the identity map holds
    clean rows weakly, so this bound would often hold by accident too — `expunge_all` is what
    makes it hold on purpose.
    """
    monkeypatch.setattr(export_svc, "CHUNK", 1)
    for i in range(4):
        _add(project, f"span-{i}")
    sessions = []
    real = export_svc.SessionLocal

    def spy():
        s = real()
        sessions.append(s)
        return s

    monkeypatch.setattr(export_svc, "SessionLocal", spy)
    gen = export_svc.iter_ndjson(project)
    for _ in range(3):
        next(gen)
    assert len(sessions) == 1                            # one session for the whole export
    assert len(sessions[0].identity_map.all_states()) <= export_svc.CHUNK
    gen.close()


# ---------------------------------------------------------------- window and cursor


def test_the_time_window_is_half_open(project):
    """Adjacent windows must not double-count the row on their shared boundary."""
    _add(project, "old", minutes_ago=180)
    _add(project, "wanted", minutes_ago=120)
    _add(project, "new", minutes_ago=60)
    edge = _now() - timedelta(minutes=150)
    mid = _now() - timedelta(minutes=90)
    early, _ = _read(project, until=edge)
    middle, _ = _read(project, since=edge, until=mid)
    late, _ = _read(project, since=mid)
    assert [s["label"] for s in early] == ["old"]
    assert [s["label"] for s in middle] == ["wanted"]
    assert [s["label"] for s in late] == ["new"]


def test_after_id_is_an_incremental_cursor(project):
    _add(project, "loaded")
    spans, tail = _read(project)
    _add(project, "landed later")
    fresh, _ = _read(project, after_id=tail["last_id"])
    assert [s["label"] for s in fresh] == ["landed later"]
    assert fresh[0]["id"] > spans[-1]["id"]


def test_a_malformed_timestamp_is_refused_not_ignored(project):
    """Degrading a mistyped `since` to 'no filter' would hand back the whole project."""
    with pytest.raises(ValueError):
        export_svc.parse_ts("last tuesday")
    assert export_svc.parse_ts("2026-07-01T00:00:00Z").tzinfo is not None
    assert export_svc.parse_ts("2026-07-01T00:00:00").tzinfo is not None   # bare = UTC
    assert export_svc.parse_ts("") is None


def test_limit_samples_the_shape_and_says_it_stopped_early(project):
    for i in range(3):
        _add(project, f"span-{i}")
    spans, tail = _read(project, limit=2)
    assert len(spans) == 2 and tail["status"] == "limit_reached"


def test_estimate_answers_how_big_this_would_be(project):
    _add(project, "a", minutes_ago=60)
    _add(project, "b")
    db = SessionLocal()
    try:
        out = export_svc.count(db, project)
        windowed = export_svc.count(db, project, _now() - timedelta(minutes=30), _now())
    finally:
        db.close()
    assert out["rows"] == 2 and out["oldest"] < out["newest"]
    assert windowed["rows"] == 1                  # the same window the export would apply


def test_a_quiet_window_is_a_valid_empty_file_not_an_error(project):
    """A scheduled hourly pull of a project that saw no traffic must produce a well-formed
    empty export, not a failure — otherwise 'quiet' and 'broken' look the same downstream."""
    spans, tail = _read(project)
    assert spans == []
    assert tail["status"] == "complete" and tail["rows"] == 0


def test_the_download_is_named_after_the_project_and_the_moment(project):
    name = export_svc.filename(project)
    assert name.startswith(f"provekit-project-{project}-") and name.endswith(".ndjson")


# ---------------------------------------------------------------- offloaded payloads


def test_an_offloaded_payload_is_resolved_not_exported_as_a_pointer(project, offloading):
    """A `{"__ref__": …}` in a warehouse is a pointer to bytes that warehouse cannot read."""
    big = "a genuinely long prompt. " * 40
    ref = payloads.maybe_offload(big)
    assert payloads.is_ref(ref)
    _add(project, "offloaded", request={"input": ref})
    spans, _ = _read(project)
    assert spans[0]["request"]["input"] == big
    assert payloads.REF_KEY not in json.dumps(spans[0])


def test_resolve_false_keeps_the_reference_for_a_consumer_that_owns_the_store(project, offloading):
    big = "another long prompt. " * 40
    _add(project, "byref", request={"input": payloads.maybe_offload(big)})
    spans, tail = _read(project, resolve=False)
    assert spans[0]["request"]["input"][payloads.REF_KEY].startswith("sha256:")
    assert tail["resolved_payloads"] is False      # the file says which kind it is


def test_a_missing_blob_exports_the_marker_not_a_silent_excerpt(project, offloading):
    big = "content that will vanish " * 20
    _add(project, "gone", request={"input": payloads.maybe_offload(big)})
    for f in offloading.rglob("*"):
        if f.is_file():
            f.unlink()
    spans, _ = _read(project)
    assert "payload unavailable" in spans[0]["request"]["input"]
    assert big[:40] in spans[0]["request"]["input"]      # ...and you still get what survived


# ---------------------------------------------------------------- truncation


def test_a_failure_mid_stream_is_announced_in_the_file(project, monkeypatch):
    """The response is already 200 with a partial body — there is no status code left to
    change, and a short NDJSON file looks exactly like a complete one."""
    _add(project, "doomed")

    def boom(*a, **kw):
        raise RuntimeError("blob store is down")

    monkeypatch.setattr(export_svc.payloads, "resolve_row", boom)
    spans, tail = _read(project)
    assert spans == []
    assert tail["status"] == "error" and "blob store is down" in tail["error"]


def test_the_sentinel_can_be_suppressed_for_a_pure_span_file(project):
    _add(project, "only spans")
    objs = [json.loads(line) for line in export_svc.iter_ndjson(project, sentinel=False)]
    assert all(export_svc.SENTINEL_KEY not in o for o in objs)


def test_no_span_record_can_be_mistaken_for_the_sentinel(project):
    _add(project, "plain")
    spans, _ = _read(project)
    assert export_svc.SENTINEL_KEY not in spans[0]


# ---------------------------------------------------------------- HTTP (pending wiring)


def test_the_router_declares_the_paths_the_docs_promise():
    """Runs wired or not: an unregistered router still has to import cleanly and still has to
    expose exactly the paths docs/EXPORT.md tells people to call."""
    from provekit.routers import export as export_router
    paths = ({r.path for r in export_router.router.routes}
             | {r.path for r in export_router.key_router.routes})
    assert paths == {"/api/export/traces.ndjson", "/api/export/estimate",
                     "/api/export/schedules", "/api/export/schedules/{sid}",
                     "/api/export/schedules/{sid}/run",
                     "/v1/export/traces.ndjson", "/v1/export/estimate"}


@needs_wiring
def test_the_endpoint_streams_ndjson_for_ingested_traces():
    trace = "c1" * 16
    span = {"name": "chat", "traceId": trace, "spanId": "c2" * 8,
            "startTimeUnixNano": "1000000000", "endTimeUnixNano": "1500000000",
            "status": {"code": 1},
            "attributes": [{"key": "gen_ai.request.model", "value": {"stringValue": "gpt-4o"}},
                           {"key": "gen_ai.prompt", "value": {"stringValue": "exported"}}]}
    with TestClient(app) as client:
        assert client.post("/v1/traces",
                           json={"resourceSpans": [{"scopeSpans": [{"spans": [span]}]}]}
                           ).status_code == 200
        r = client.get("/api/export/traces.ndjson")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/x-ndjson")
        assert "attachment" in r.headers["content-disposition"]
        rows = [json.loads(x) for x in r.text.splitlines() if x]
        assert any(row.get("trace_id") == trace for row in rows)


@needs_wiring
def test_a_bad_window_is_a_422():
    with TestClient(app) as client:
        assert client.get("/api/export/traces.ndjson",
                          params={"since": "yesterday"}).status_code == 422


@needs_wiring
def test_the_key_authed_door_works_and_a_bad_key_does_not():
    with TestClient(app) as client:
        key = client.post("/api/workspace/ingest-key").json()["ingest_key"]
        ok = client.get("/v1/export/traces.ndjson", params={"limit": 1},
                        headers={"Authorization": f"Bearer {key}"})
        assert ok.status_code == 200
        bad = client.get("/v1/export/traces.ndjson",
                         headers={"Authorization": "Bearer nope"})
        assert bad.status_code == 403


@needs_wiring
def test_a_bulk_read_of_every_prompt_is_audited():
    with TestClient(app) as client:
        client.get("/api/export/traces.ndjson", params={"limit": 1})
    db = SessionLocal()
    try:
        row = (db.query(AuditLog).filter(AuditLog.action == export_svc.EXPORT_ACTION)
               .order_by(AuditLog.id.desc()).first())
        assert row is not None and row.detail.get("auth") == "session"
    finally:
        db.close()
