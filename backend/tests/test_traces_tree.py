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
