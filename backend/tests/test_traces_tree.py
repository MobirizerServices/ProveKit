"""Nested traces: a decorated entrypoint + its child spans ingest as one trace, list as a
single root, and come back as a tree the portal can render."""
import uuid

from fastapi.testclient import TestClient

from provekit.main import app


def _span(span_id, parent, attrs, name, trace="t-tree-1"):
    return {"name": name, "traceId": trace, "spanId": span_id, "parentSpanId": parent,
            "startTimeUnixNano": "1000000000", "endTimeUnixNano": "1500000000",
            "status": {"code": 1},
            "attributes": [{"key": k, "value": {"stringValue": str(v)}} for k, v in attrs.items()]}


def test_span_notes():
    with TestClient(app) as c:
        n = c.post("/api/traces/t-notes/notes", json={"span_id": "s1", "body": "check this step"}).json()
        assert n["body"] == "check this step" and n["span_id"] == "s1"
        assert any(x["id"] == n["id"] for x in c.get("/api/traces/t-notes/notes").json())
        assert c.delete(f"/api/notes/{n['id']}").json()["ok"] is True
        assert c.get("/api/traces/t-notes/notes").json() == []
        assert c.post("/api/traces/t-notes/notes", json={"body": ""}).status_code == 422


def test_trace_content_search():
    with TestClient(app) as c:
        c.post("/v1/traces", json={"resourceSpans": [{"scopeSpans": [{"spans": [
            _span("sr1", "", {"gen_ai.operation.name": "invoke_agent",
                              "gen_ai.output.messages": "the mitochondria is the powerhouse"},
                  "agent", trace="t-search-a")]}]}]})
        c.post("/v1/traces", json={"resourceSpans": [{"scopeSpans": [{"spans": [
            _span("sr2", "", {"gen_ai.operation.name": "invoke_agent",
                              "gen_ai.output.messages": "quarterly revenue projections"},
                  "agent", trace="t-search-b")]}]}]})
        # search matches on span content, not just the label
        tids = {t["trace_id"] for t in c.get("/api/traces", params={"q": "mitochondria"}).json()}
        assert "t-search-a" in tids and "t-search-b" not in tids
        # no match → empty list
        assert c.get("/api/traces", params={"q": "zzz-no-such-content"}).json() == []


def test_agent_trace_lists_as_one_root_and_returns_a_tree():
    with TestClient(app) as c:
        payload = {"resourceSpans": [{"scopeSpans": [{"spans": [
            _span("root", "", {"gen_ai.operation.name": "invoke_agent", "gen_ai.input.messages": "hi"}, "agent"),
            _span("llm1", "root", {"gen_ai.request.model": "gpt-4o", "gen_ai.output.messages": "hello"}, "chat"),
            _span("tool1", "root", {"gen_ai.tool.name": "search"}, "search"),
        ]}]}]}
        assert c.post("/v1/traces", json=payload).status_code == 200

        # the list shows ONE row for the trace (its root), with the span count
        traces = c.get("/api/traces").json()
        mine = next(t for t in traces if t["trace_id"] == "t-tree-1")
        assert mine["type"] == "agent" and mine["span_count"] == 3

        # the detail returns all three spans, wired parent→child
        spans = c.get("/api/traces/t-tree-1").json()
        by_id = {s["span_id"]: s for s in spans}
        assert len(spans) == 3
        assert by_id["root"]["parent_span_id"] == ""
        assert by_id["llm1"]["parent_span_id"] == "root" and by_id["llm1"]["type"] == "llm"
        assert by_id["tool1"]["parent_span_id"] == "root" and by_id["tool1"]["type"] == "tool"


def test_unknown_trace_is_404():
    with TestClient(app) as c:
        assert c.get("/api/traces/does-not-exist").status_code == 404


def test_trace_list_pages_by_cursor():
    """Without a cursor the list stopped at `limit` (max 200) and older traces were simply
    unreachable — the failure mode arrives exactly when someone is succeeding with the tool."""
    c = TestClient(app)
    tag = uuid.uuid4().hex[:8]
    for i in range(5):
        c.post("/v1/traces", json={"resourceSpans": [{"scopeSpans": [{"spans": [
            _span("r", "", {}, f"root-{tag}-{i}", trace=f"cur-{tag}-{i}")]}]}]})

    page1 = c.get("/api/traces?limit=2").json()
    assert len(page1) == 2
    page2 = c.get(f"/api/traces?limit=2&cursor={page1[-1]['id']}").json()
    assert len(page2) == 2
    assert {t["id"] for t in page1}.isdisjoint({t["id"] for t in page2})
    # strictly descending across the page boundary
    assert page1[-1]["id"] > page2[0]["id"]

    # walking to the end terminates rather than looping
    seen, cursor = [], None
    for _ in range(20):
        url = "/api/traces?limit=2" + (f"&cursor={cursor}" if cursor else "")
        batch = c.get(url).json()
        if not batch:
            break
        seen += batch
        cursor = batch[-1]["id"]
    assert len({t["id"] for t in seen}) == len(seen)      # no repeats
    assert sum(1 for t in seen if tag in (t["label"] or "")) == 5


def test_cursor_is_honoured_on_the_key_authed_api():
    c = TestClient(app)
    key = c.post("/api/workspace/ingest-key").json()["ingest_key"]
    tag = uuid.uuid4().hex[:8]
    for i in range(3):
        c.post("/v1/traces", json={"resourceSpans": [{"scopeSpans": [{"spans": [
            _span("r", "", {}, f"kroot-{tag}-{i}", trace=f"k-{tag}-{i}")]}]}]})
    bare = TestClient(app)
    bare.cookies.clear()
    h = {"Authorization": f"Bearer {key}"}
    first = bare.get("/v1/traces?limit=1", headers=h).json()
    assert isinstance(first, list) and len(first) == 1      # still a bare list, not an envelope
    nxt = bare.get(f"/v1/traces?limit=1&cursor={first[0]['id']}", headers=h).json()
    assert nxt[0]["id"] < first[0]["id"]


def _child(tid, sid, parent, name):
    return _span(sid, parent, {"gen_ai.request.model": "gpt-4o"}, name, trace=tid)


def test_a_trace_whose_root_never_arrived_is_still_listed():
    """A root span is only exported when it *ends*, so a process that dies mid-run never sends
    one. The trace used to vanish from the list entirely — the run that crashed being exactly
    the one you most need to see."""
    c = TestClient(app)
    tid = f"orphan-{uuid.uuid4().hex[:8]}"
    c.post("/v1/traces", json={"resourceSpans": [{"scopeSpans": [{"spans": [
        _child(tid, "c1", "neverarrived", "retrieve"),
        _child(tid, "c2", "neverarrived", "chat")]}]}]})

    rows = c.get("/api/traces?limit=200").json()
    row = next((t for t in rows if t["trace_id"] == tid), None)
    assert row is not None, "a trace with no root span must still be listed"
    assert row["incomplete"] is True
    assert row["span_count"] == 2
    # and its spans are still reachable
    assert len(c.get(f"/api/traces/{tid}").json()) == 2


def test_a_complete_trace_is_not_marked_incomplete():
    c = TestClient(app)
    tid = f"whole-{uuid.uuid4().hex[:8]}"
    c.post("/v1/traces", json={"resourceSpans": [{"scopeSpans": [{"spans": [
        _span("r", "", {}, "agent", trace=tid), _child(tid, "c1", "r", "chat")]}]}]})
    row = next(t for t in c.get("/api/traces?limit=200").json() if t["trace_id"] == tid)
    assert row["incomplete"] is False


def test_trace_stream_announces_new_traces(monkeypatch):
    """Drive the watcher directly: TestClient runs the app on one event loop, so issuing a
    request from inside a streaming read is not a faithful stand-in for a second client."""
    import asyncio

    from provekit.database import SessionLocal
    from provekit.models import Run, Workspace
    from provekit.routers import traces as tr

    monkeypatch.setattr(tr, "_STREAM_POLL_SECONDS", 0.01)

    db = SessionLocal()
    try:
        ws = db.query(Workspace).first()
        assert ws is not None
        ws_id = ws.id
    finally:
        db.close()

    class _Connected:
        async def is_disconnected(self):
            return False

    async def drive():
        gen = tr._watch_traces(ws_id, _Connected())
        first = await gen.__anext__()                 # baseline, not an announcement
        assert '"type": "ready"' in first

        # A new root span lands while the stream is open.
        db = SessionLocal()
        try:
            db.add(Run(workspace_id=ws_id, type="agent", label="streamed",
                       trace_id=f"sse-{uuid.uuid4().hex[:8]}", span_id="",
                       parent_span_id="", status="completed"))
            db.commit()
        finally:
            db.close()

        for _ in range(50):                           # keepalives may precede the announcement
            frame = await gen.__anext__()
            if '"type": "traces"' in frame:
                await gen.aclose()
                return True
        await gen.aclose()
        return False

    assert asyncio.run(drive()), "a trace landing mid-stream should be announced"


def test_stream_does_not_replay_history_on_connect(monkeypatch):
    """Announcing the backlog would make every page load look like fresh activity."""
    import asyncio

    from provekit.database import SessionLocal
    from provekit.models import Workspace
    from provekit.routers import traces as tr

    monkeypatch.setattr(tr, "_STREAM_POLL_SECONDS", 0.01)
    db = SessionLocal()
    try:
        ws_id = db.query(Workspace).first().id
    finally:
        db.close()

    class _Connected:
        async def is_disconnected(self):
            return False

    async def drive():
        gen = tr._watch_traces(ws_id, _Connected())
        await gen.__anext__()                         # ready
        frames = [await gen.__anext__() for _ in range(5)]
        await gen.aclose()
        return frames

    assert all('"type": "traces"' not in f for f in asyncio.run(drive()))


def test_stream_stops_when_the_client_goes_away(monkeypatch):
    """Otherwise a closed tab leaves a generator polling the database forever."""
    import asyncio

    from provekit.routers import traces as tr

    monkeypatch.setattr(tr, "_STREAM_POLL_SECONDS", 0.01)

    class _Gone:
        async def is_disconnected(self):
            return True

    async def drive():
        return [f async for f in tr._watch_traces(1, _Gone())]

    assert asyncio.run(drive()) == []


def test_stream_response_contract(monkeypatch):
    from provekit.routers import traces as tr
    # Without bounding both, the server-side generator keeps polling for the full lifetime
    # after the client detaches — TestClient never reports the disconnect.
    monkeypatch.setattr(tr, "_STREAM_POLL_SECONDS", 0.01)
    monkeypatch.setattr(tr, "_STREAM_MAX_SECONDS", 1.0)
    c = TestClient(app)
    with c.stream("GET", "/api/traces/stream") as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        # nginx and friends buffer by default, which turns a stream into one delayed blob.
        assert resp.headers.get("x-accel-buffering") == "no"
        assert resp.headers.get("cache-control") == "no-cache"
        for line in resp.iter_lines():
            if line.startswith("data:"):
                assert '"type": "ready"' in line
                break


def test_stream_route_is_not_shadowed_by_the_trace_id_route():
    """/traces/{trace_id} would happily match 'stream' if declared first."""
    routes = [r.path for r in app.routes if getattr(r, "path", "").startswith("/api/traces")]
    assert routes.index("/api/traces/stream") < routes.index("/api/traces/{trace_id}")
