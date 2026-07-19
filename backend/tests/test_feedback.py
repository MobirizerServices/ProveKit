"""Feedback/scoring on a trace (human annotation from the portal + programmatic via key),
and session grouping captured from a span's session.id attribute."""
from fastapi.testclient import TestClient

from provekit.main import app


def _span(span_id, parent, attrs, name, trace):
    return {"name": name, "traceId": trace, "spanId": span_id, "parentSpanId": parent,
            "startTimeUnixNano": "1000000000", "endTimeUnixNano": "1500000000",
            "status": {"code": 1},
            "attributes": [{"key": k, "value": {"stringValue": str(v)}} for k, v in attrs.items()]}


def _client():
    return TestClient(app, base_url="https://testserver")


def test_human_feedback_via_cookie_roundtrips():
    c = _client()
    c.post("/v1/traces", json={"resourceSpans": [{"scopeSpans": [{"spans": [
        _span("r", "", {"gen_ai.operation.name": "invoke_agent"}, "agent", "t-fb-1"),
    ]}]}]})
    created = c.post("/api/traces/t-fb-1/feedback",
                     json={"name": "thumbs", "value": "up", "comment": "great"}).json()
    assert created["source"] == "human" and created["value"] == "up"
    rows = c.get("/api/traces/t-fb-1/feedback").json()
    assert len(rows) == 1 and rows[0]["name"] == "thumbs"


def test_programmatic_feedback_via_key():
    c = _client()
    key = c.post("/api/api-keys", json={"name": "scorer"}).json()["key"]
    hdr = {"Authorization": f"Bearer {key}"}
    c.post("/v1/traces", headers=hdr, json={"resourceSpans": [{"scopeSpans": [{"spans": [
        _span("r", "", {"gen_ai.operation.name": "invoke_agent"}, "agent", "t-fb-2"),
    ]}]}]})
    c.post("/v1/traces/t-fb-2/feedback", headers=hdr,
           json={"name": "relevance", "score": 0.9, "source": "sdk"})
    rows = c.get("/v1/traces/t-fb-2/feedback", headers=hdr).json()
    assert rows[0]["score"] == 0.9 and rows[0]["source"] == "sdk"


def test_session_id_captured_and_surfaced():
    c = _client()
    c.post("/v1/traces", json={"resourceSpans": [{"scopeSpans": [{"spans": [
        _span("r", "", {"gen_ai.operation.name": "invoke_agent", "session.id": "sess-42"},
              "agent", "t-sess"),
    ]}]}]})
    row = next(t for t in c.get("/api/traces").json() if t["trace_id"] == "t-sess")
    assert row["session_id"] == "sess-42"
    span = c.get("/api/traces/t-sess").json()[0]
    assert span["session_id"] == "sess-42"


def test_invocation_params_and_finish_reason_captured():
    c = _client()
    c.post("/v1/traces", json={"resourceSpans": [{"scopeSpans": [{"spans": [
        _span("llm", "", {"gen_ai.request.model": "gpt-4o", "gen_ai.request.temperature": "0.7",
                          "gen_ai.response.finish_reasons": "stop"}, "chat", "t-params"),
    ]}]}]})
    span = c.get("/api/traces/t-params").json()[0]
    meta = span["result"]["meta"]
    assert meta["params"]["temperature"] == "0.7"
    assert meta["finish_reason"] == "stop"
