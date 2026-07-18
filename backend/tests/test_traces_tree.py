"""Nested traces: a decorated entrypoint + its child spans ingest as one trace, list as a
single root, and come back as a tree the portal can render."""
from fastapi.testclient import TestClient

from provekit.main import app


def _span(span_id, parent, attrs, name, trace="t-tree-1"):
    return {"name": name, "traceId": trace, "spanId": span_id, "parentSpanId": parent,
            "startTimeUnixNano": "1000000000", "endTimeUnixNano": "1500000000",
            "status": {"code": 1},
            "attributes": [{"key": k, "value": {"stringValue": str(v)}} for k, v in attrs.items()]}


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
