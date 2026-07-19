"""Key-authed read API (/v1/traces GET) — what the ProveKit MCP server calls with the
project key. Same data as the cookie-authed /api/traces, a different door."""
from fastapi.testclient import TestClient

from provekit.main import app


def _span(span_id, parent, attrs, name, trace, code=1):
    return {"name": name, "traceId": trace, "spanId": span_id, "parentSpanId": parent,
            "startTimeUnixNano": "1000000000", "endTimeUnixNano": "1500000000",
            "status": {"code": code},
            "attributes": [{"key": k, "value": {"stringValue": str(v)}} for k, v in attrs.items()]}


def _client():
    return TestClient(app, base_url="https://testserver")


def test_key_lists_and_reads_a_trace():
    c = _client()
    key = c.post("/api/api-keys", json={"name": "mcp"}).json()["key"]
    hdr = {"Authorization": f"Bearer {key}"}
    payload = {"resourceSpans": [{"scopeSpans": [{"spans": [
        _span("r", "", {"gen_ai.operation.name": "invoke_agent"}, "agent", "t-key-1"),
        _span("c1", "r", {"gen_ai.request.model": "gpt-4o"}, "chat", "t-key-1"),
    ]}]}]}
    assert c.post("/v1/traces", json=payload, headers=hdr).status_code == 200

    # list via the key
    traces = c.get("/v1/traces", headers=hdr).json()
    mine = next(t for t in traces if t["trace_id"] == "t-key-1")
    assert mine["span_count"] == 2

    # detail via the key
    spans = c.get("/v1/traces/t-key-1", headers=hdr).json()
    assert {s["span_id"] for s in spans} == {"r", "c1"}


def test_key_status_filter_surfaces_only_failures():
    c = _client()
    key = c.post("/api/api-keys", json={"name": "mcp2"}).json()["key"]
    hdr = {"Authorization": f"Bearer {key}"}
    c.post("/v1/traces", headers=hdr, json={"resourceSpans": [{"scopeSpans": [{"spans": [
        _span("ok", "", {"gen_ai.operation.name": "invoke_agent"}, "agent", "t-ok"),
    ]}]}]})
    c.post("/v1/traces", headers=hdr, json={"resourceSpans": [{"scopeSpans": [{"spans": [
        _span("bad", "", {"gen_ai.operation.name": "invoke_agent"}, "agent", "t-bad", code=2),
    ]}]}]})
    failed = c.get("/v1/traces", params={"status": "failed"}, headers=hdr).json()
    ids = {t["trace_id"] for t in failed}
    assert "t-bad" in ids and "t-ok" not in ids


def test_window_hours_excludes_old_traces():
    from datetime import timedelta

    from provekit.database import SessionLocal
    from provekit.models import Run, _now

    c = _client()
    key = c.post("/api/api-keys", json={"name": "win"}).json()["key"]
    hdr = {"Authorization": f"Bearer {key}"}
    c.post("/v1/traces", headers=hdr, json={"resourceSpans": [{"scopeSpans": [{"spans": [
        _span("rec", "", {"gen_ai.operation.name": "invoke_agent"}, "agent", "t-recent"),
    ]}]}]})
    with SessionLocal() as db:
        wsid = db.query(Run).filter(Run.trace_id == "t-recent").first().workspace_id
        db.add(Run(workspace_id=wsid, type="agent", label="old", trace_id="t-old",
                   span_id="o", parent_span_id="", created_at=_now() - timedelta(hours=48)))
        db.commit()
    got = c.get("/v1/traces", params={"window_hours": 24}, headers=hdr).json()
    ids = {t["trace_id"] for t in got}
    assert "t-recent" in ids and "t-old" not in ids


def test_key_read_rejects_bad_key_and_unknown_trace():
    c = _client()
    bad = {"Authorization": "Bearer pk_nope"}
    assert c.get("/v1/traces", headers=bad).status_code == 403
    key = c.post("/api/api-keys", json={"name": "mcp3"}).json()["key"]
    assert c.get("/v1/traces/missing", headers={"Authorization": f"Bearer {key}"}).status_code == 404
