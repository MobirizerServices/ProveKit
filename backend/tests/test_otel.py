"""OTel GenAI ingest: three dialects map to runs; the endpoint persists them."""
import pytest
from fastapi.testclient import TestClient

from agentman.main import app
from agentman.services import otel


def _span(attrs: dict, name="chat", start=1_000_000_000, end=1_500_000_000, status_code=1):
    return {
        "name": name,
        "startTimeUnixNano": str(start),
        "endTimeUnixNano": str(end),
        "status": {"code": status_code},
        "attributes": [{"key": k, "value": _val(v)} for k, v in attrs.items()],
    }


def _val(v):
    if isinstance(v, bool):
        return {"boolValue": v}
    if isinstance(v, int):
        return {"intValue": str(v)}
    if isinstance(v, str):
        return {"stringValue": v}
    return {"stringValue": str(v)}


def _otlp(*spans):
    return {"resourceSpans": [{"scopeSpans": [{"spans": list(spans)}]}]}


def test_current_genai_dialect():
    span = _span({
        "gen_ai.provider.name": "openai",
        "gen_ai.request.model": "gpt-4o-mini",
        "gen_ai.operation.name": "chat",
        "gen_ai.input.messages": "hello",
        "gen_ai.output.messages": "hi there",
        "gen_ai.usage.input_tokens": 5,
        "gen_ai.usage.output_tokens": 2,
    })
    rows = otel.ingest(_otlp(span))
    assert len(rows) == 1
    r = rows[0]
    assert r["type"] == "trace" and r["status"] == "completed"
    assert r["result"]["meta"]["model"] == "gpt-4o-mini"
    assert r["result"]["meta"]["usage"] == {"input_tokens": 5, "output_tokens": 2}
    assert r["result"]["text"] == "hi there"
    assert r["duration_ms"] == 500  # (1.5e9 - 1.0e9) ns = 500 ms


def test_legacy_dialect():
    span = _span({"gen_ai.system": "anthropic", "gen_ai.request.model": "claude",
                  "gen_ai.prompt": "q", "gen_ai.completion": "a"})
    r = otel.ingest(_otlp(span))[0]
    assert r["result"]["meta"]["provider"] == "anthropic"
    assert r["result"]["text"] == "a"


def test_openinference_dialect():
    span = _span({"llm.model_name": "gpt-4o", "llm.provider": "openai",
                  "input.value": "hey", "output.value": "yo"}, name="llm")
    r = otel.ingest(_otlp(span))[0]
    assert r["result"]["meta"]["model"] == "gpt-4o"
    assert r["result"]["text"] == "yo"


def test_tool_span_maps_operation_and_tool():
    span = _span({"gen_ai.operation.name": "execute_tool", "gen_ai.tool.name": "search"}, name="tool")
    r = otel.ingest(_otlp(span))[0]
    assert r["result"]["meta"]["tool"] == "search"
    assert r["request"]["operation"] == "execute_tool"


def test_non_genai_span_ignored():
    span = _span({"http.method": "GET", "http.url": "http://x"}, name="GET /x")
    assert otel.ingest(_otlp(span)) == []


def test_failed_span_status():
    span = _span({"gen_ai.request.model": "m"}, status_code=2)
    span["status"]["message"] = "boom"
    r = otel.ingest(_otlp(span))[0]
    assert r["status"] == "failed" and r["error"] == "boom"


def test_ingest_endpoint_persists_and_shows_in_history():
    with TestClient(app) as client:
        before = len(client.get("/api/runs?limit=100").json())
        span = _span({"gen_ai.provider.name": "openai", "gen_ai.request.model": "gpt-4o", "gen_ai.completion": "ok"})
        resp = client.post("/v1/traces", json=_otlp(span))
        assert resp.status_code == 200 and "partialSuccess" in resp.json()
        runs = client.get("/api/runs?limit=100").json()
        assert len(runs) == before + 1
        assert runs[0]["type"] == "trace"
