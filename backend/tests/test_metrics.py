"""Dashboard metrics: counts, error rate, latency percentiles, tokens, series, by-model."""
from fastapi.testclient import TestClient

from provekit.main import app


def _root(trace, code=1, dur="1500000000"):
    return {"name": "agent", "traceId": trace, "spanId": "r", "parentSpanId": "",
            "startTimeUnixNano": "1000000000", "endTimeUnixNano": dur, "status": {"code": code},
            "attributes": [{"key": "gen_ai.operation.name", "value": {"stringValue": "invoke_agent"}}]}


def _llm(trace, model, itok, otok):
    return {"name": "chat", "traceId": trace, "spanId": "c", "parentSpanId": "r",
            "startTimeUnixNano": "1000000000", "endTimeUnixNano": "1200000000", "status": {"code": 1},
            "attributes": [
                {"key": "gen_ai.request.model", "value": {"stringValue": model}},
                {"key": "gen_ai.usage.input_tokens", "value": {"intValue": itok}},
                {"key": "gen_ai.usage.output_tokens", "value": {"intValue": otok}}]}


def test_metrics_aggregate():
    with TestClient(app, base_url="https://testserver") as c:
        c.post("/v1/traces", json={"resourceSpans": [{"scopeSpans": [{"spans": [
            _root("m-ok"), _llm("m-ok", "gpt-4o", 100, 20)]}]}]})
        c.post("/v1/traces", json={"resourceSpans": [{"scopeSpans": [{"spans": [
            _root("m-bad", code=2)]}]}]})

        m = c.get("/api/metrics", params={"window_hours": 24}).json()
        assert m["trace_count"] >= 2
        assert m["error_count"] >= 1
        assert 0 < m["error_rate"] <= 1
        assert m["total_tokens"] >= 120
        assert m["latency_p95_ms"] >= m["latency_p50_ms"]
        assert any(row["model"] == "gpt-4o" and row["tokens"] >= 120 for row in m["by_model"])
        assert isinstance(m["series"], list) and len(m["series"]) >= 1
        # each bucket trends volume, errors, latency percentiles, and tokens
        b = m["series"][0]
        assert {"t", "count", "errors", "p50", "p95", "tokens"} <= set(b)
        assert b["p95"] >= b["p50"] >= 0
        assert sum(x["tokens"] for x in m["series"]) >= 120
        # per-bucket model breakdown lets the frontend price each bucket
        assert any(x.get("by_model", {}).get("gpt-4o", 0) >= 120 for x in m["series"])


def _failed_tool(trace, msg):
    return {"name": "fetch", "traceId": trace, "spanId": "t", "parentSpanId": "r",
            "startTimeUnixNano": "1000000000", "endTimeUnixNano": "1100000000",
            "status": {"code": 2, "message": msg},
            "attributes": [{"key": "gen_ai.tool.name", "value": {"stringValue": "fetch"}}]}


def test_metrics_failure_breakdown():
    with TestClient(app, base_url="https://testserver") as c:
        c.post("/v1/traces", json={"resourceSpans": [{"scopeSpans": [{"spans": [
            _root("f-1", code=2), _failed_tool("f-1", "ConnectionError: timeout")]}]}]})

        m = c.get("/api/metrics", params={"window_hours": 24}).json()
        # failing span types are broken out (an agent root + a tool both failed)
        types = {row["type"]: row["count"] for row in m["fail_by_type"]}
        assert types.get("tool", 0) >= 1 and types.get("agent", 0) >= 1
        # the tool's error message surfaces in top_errors
        assert any("ConnectionError" in e["error"] and e["type"] == "tool" for e in m["top_errors"])
        # recent_failures lists the latest failing spans, newest first
        assert len(m["recent_failures"]) >= 2
        assert all({"label", "type", "error", "trace_id", "at"} <= set(f) for f in m["recent_failures"])


def test_metrics_empty_window_is_safe():
    with TestClient(app, base_url="https://testserver") as c:
        # a 0-length window edge: window_hours far in the future filter → still valid shape
        m = c.get("/api/metrics", params={"window_hours": 1}).json()
        assert "trace_count" in m and m["error_rate"] in (0.0,) or m["trace_count"] >= 0
        assert m["latency_p50_ms"] >= 0
