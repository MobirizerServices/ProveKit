"""The trace list carries an estimated per-trace cost, priced from reported usage."""
from fastapi.testclient import TestClient

from provekit.main import app


def _otlp(model: str, itok: int, otok: int, tid: str):
    return {"resourceSpans": [{"scopeSpans": [{"spans": [{
        "name": "chat", "traceId": tid, "spanId": "c0c0c0c0c0c0c0c0",
        "startTimeUnixNano": "1000000000", "endTimeUnixNano": "1500000000", "status": {"code": 1},
        "attributes": [
            {"key": "gen_ai.request.model", "value": {"stringValue": model}},
            {"key": "gen_ai.usage.input_tokens", "value": {"intValue": itok}},
            {"key": "gen_ai.usage.output_tokens", "value": {"intValue": otok}},
            {"key": "gen_ai.completion", "value": {"stringValue": "ok"}},
        ],
    }]}]}]}


def test_a_trace_with_usage_gets_a_priced_cost():
    c = TestClient(app, base_url="https://testserver")
    tid = "c0" * 16
    c.post("/v1/traces", json=_otlp("gpt-4o", 1000, 500, tid))
    row = next(t for t in c.get("/api/traces?limit=100").json() if t["trace_id"] == tid)
    assert row["cost"] is not None and row["cost"] > 0, "priced from the reported input/output split"


def test_a_trace_without_usage_reports_no_cost_rather_than_zero():
    """A $0 would read like a measured free call; None lets the UI show '—' honestly."""
    c = TestClient(app, base_url="https://testserver")
    tid = "d0" * 16
    span = {"name": "step", "traceId": tid, "spanId": "d0d0d0d0d0d0d0d0",
            "startTimeUnixNano": "1000000000", "endTimeUnixNano": "1100000000", "status": {"code": 1},
            "attributes": [{"key": "gen_ai.operation.name", "value": {"stringValue": "invoke_agent"}}]}
    c.post("/v1/traces", json={"resourceSpans": [{"scopeSpans": [{"spans": [span]}]}]})
    row = next(t for t in c.get("/api/traces?limit=100").json() if t["trace_id"] == tid)
    assert row["cost"] is None
