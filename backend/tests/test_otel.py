"""OTel GenAI ingest: three dialects map to runs; the endpoint persists them."""
import pytest
from fastapi.testclient import TestClient

from provekit.main import app
from provekit.services import otel


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
    assert r["type"] == "llm" and r["status"] == "completed"
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


def test_non_genai_span_kept_as_a_step():
    # Every span is kept now (so the full flow survives), classified as a generic "step".
    span = _span({"foo": "bar"}, name="retrieve-docs")
    r = otel.ingest(_otlp(span))[0]
    assert r["type"] == "step" and r["label"] == "retrieve-docs"


def test_agent_operation_is_typed_agent():
    span = _span({"gen_ai.operation.name": "invoke_agent", "gen_ai.input.messages": "q"}, name="my-agent")
    r = otel.ingest(_otlp(span))[0]
    assert r["type"] == "agent"


def test_span_hierarchy_ids_are_carried():
    span = _span({"gen_ai.request.model": "m"})
    span.update(traceId="abc123", spanId="s1", parentSpanId="p0")
    r = otel.ingest(_otlp(span))[0]
    assert (r["trace_id"], r["span_id"], r["parent_span_id"]) == ("abc123", "s1", "p0")


def test_failed_span_status():
    span = _span({"gen_ai.request.model": "m"}, status_code=2)
    span["status"]["message"] = "boom"
    r = otel.ingest(_otlp(span))[0]
    assert r["status"] == "failed" and r["error"] == "boom"


def test_indexed_openinference_messages_reconstructed_without_input_value():
    """Real instrumented spans can carry ONLY the flattened llm.input_messages.{i}.message.role/
    content attributes with no input.value at all — e.g. hide_inputs redaction, or the OTel SDK's
    default 128-attribute-per-span cap evicting input.value from a long conversation while the
    indexed message attributes (added later) survive. A literal key lookup for the bare
    "llm.input_messages" string would previously miss this and store an empty prompt."""
    span = _span({
        "gen_ai.request.model": "gpt-4o",
        "llm.input_messages.0.message.role": "system",
        "llm.input_messages.0.message.content": "Be terse.",
        "llm.input_messages.1.message.role": "user",
        "llm.input_messages.1.message.content": "Hi there",
        "llm.output_messages.0.message.role": "assistant",
        "llm.output_messages.0.message.content": "Hello!",
    })
    r = otel.ingest(_otlp(span))[0]
    import json
    assert json.loads(r["request"]["input"]) == [
        {"role": "system", "content": "Be terse."}, {"role": "user", "content": "Hi there"}]
    assert r["result"]["text"] == json.dumps([{"role": "assistant", "content": "Hello!"}])


def test_indexed_messages_multimodal_text_blocks():
    span = _span({
        "gen_ai.request.model": "gpt-4o",
        "llm.input_messages.0.message.role": "user",
        "llm.input_messages.0.message.contents.0.message_content.text": "Describe this image",
    })
    r = otel.ingest(_otlp(span))[0]
    import json
    assert json.loads(r["request"]["input"]) == [{"role": "user", "content": "Describe this image"}]


def test_indexed_messages_absent_falls_back_to_input_value():
    """When there are no indexed attributes at all, the existing input.value/gen_ai.* dialects
    still work (no regression from adding the indexed-attribute priority path)."""
    span = _span({"gen_ai.request.model": "gpt-4o", "input.value": '{"messages":[{"role":"user","content":"hi"}]}'})
    r = otel.ingest(_otlp(span))[0]
    assert r["request"]["input"] == '{"messages":[{"role":"user","content":"hi"}]}'


def test_ingest_endpoint_persists_and_shows_in_history():
    with TestClient(app) as client:
        before = {r["id"] for r in client.get("/api/runs?limit=100").json()}
        span = _span({"gen_ai.provider.name": "openai", "gen_ai.request.model": "gpt-4o", "gen_ai.completion": "ok"})
        resp = client.post("/v1/traces", json=_otlp(span))
        assert resp.status_code == 200 and "partialSuccess" in resp.json()
        runs = client.get("/api/runs?limit=100").json()
        # Identity, not a count. `limit` saturates once the suite has written 100 runs, and a
        # `before + 1` assertion then compares 100 to 101 — it fails for whichever feature
        # happens to tip the shared workspace over the cap, not for the change that broke it.
        assert runs[0]["id"] not in before, "the ingested span sits at the top of history"
        assert runs[0]["type"] == "llm"


def _identified(sid: str, tid: str = "a" * 32, **attrs):
    """A span carrying real OTel ids — what any actual exporter sends."""
    s = _span({"gen_ai.request.model": "gpt-4o", "gen_ai.completion": "ok", **attrs})
    s["spanId"], s["traceId"] = sid, tid
    return s


def test_retried_export_does_not_duplicate_spans():
    """OTLP exporters retry on 5xx by replaying the whole batch. The replay must be a no-op,
    not a second copy — duplicates silently inflate span counts, tokens and cost."""
    with TestClient(app) as client:
        batch = _otlp(_identified("1111111111111111"), _identified("2222222222222222"))
        assert client.post("/v1/traces", json=batch).status_code == 200
        after_first = len(client.get("/api/runs?limit=200").json())

        for _ in range(3):            # the exporter keeps retrying
            assert client.post("/v1/traces", json=batch).status_code == 200
        assert len(client.get("/api/runs?limit=200").json()) == after_first

        # A new span in an otherwise-replayed batch still lands.
        grown = _otlp(_identified("1111111111111111"), _identified("3333333333333333"))
        client.post("/v1/traces", json=grown)
        assert len(client.get("/api/runs?limit=200").json()) == after_first + 1


def test_same_span_repeated_within_one_batch_is_stored_once():
    with TestClient(app) as client:
        before = len(client.get("/api/runs?limit=200").json())
        dup = _identified("4444444444444444")
        client.post("/v1/traces", json=_otlp(dup, dup))
        assert len(client.get("/api/runs?limit=200").json()) == before + 1


def test_same_span_id_in_two_traces_is_kept():
    """OTel scopes span-id uniqueness to a *trace*. Two traces reusing an id is legal, and
    dropping the second would be worse data loss than the duplicate the dedupe prevents."""
    with TestClient(app) as client:
        before = len(client.get("/api/runs?limit=200").json())
        client.post("/v1/traces", json=_otlp(_identified("6666666666666666", tid="c" * 32)))
        client.post("/v1/traces", json=_otlp(_identified("6666666666666666", tid="d" * 32)))
        assert len(client.get("/api/runs?limit=200").json()) == before + 2


def test_same_span_id_in_two_projects_is_not_a_collision():
    """Span ids are only unique per project — two tenants can legitimately emit the same id."""
    from provekit.database import SessionLocal
    from provekit.models import Run, User, Workspace
    with TestClient(app) as client:
        client.post("/v1/traces", json=_otlp(_identified("5555555555555555")))
        db = SessionLocal()
        try:
            owner = db.query(User).first()
            other = Workspace(name="other-tenant", owner_user_id=owner.id)
            db.add(other)
            db.commit()
            db.add(Run(workspace_id=other.id, type="llm", span_id="5555555555555555",
                       trace_id="b" * 32))
            db.commit()                # must not raise
            assert db.query(Run).filter(Run.span_id == "5555555555555555").count() == 2
        finally:
            db.close()


def test_ingest_with_bearer_key():
    """Real OTLP exporters authenticate with a Bearer ingest key (no cookies)."""
    from provekit.config import get_settings
    with TestClient(app) as client:
        # mint a key for the (local) workspace
        key = client.post("/api/workspace/ingest-key").json()["ingest_key"]
        assert key.startswith("agm_")
        # a fresh client with NO cookie but the bearer key can push traces
        import httpx
        bare = TestClient(app)
        bare.cookies.clear()
        span = _span({"gen_ai.request.model": "gpt-4o", "gen_ai.completion": "hi"})
        r = bare.post("/v1/traces", json=_otlp(span), headers={"Authorization": f"Bearer {key}"})
        assert r.status_code == 200 and "partialSuccess" in r.json()
        # wrong key rejected
        bad = bare.post("/v1/traces", json=_otlp(span), headers={"Authorization": "Bearer agm_wrong"})
        assert bad.status_code == 403
