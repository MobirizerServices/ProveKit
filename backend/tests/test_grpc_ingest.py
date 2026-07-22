"""OTLP protobuf ingest (#94): the decoder, and that the binary route reuses — rather than
reimplements — the JSON ingest pipeline (auth, rate limit, spool, dedupe).

GOLDEN_REQUEST below is a real ExportTraceServiceRequest serialised by the canonical
`opentelemetry-proto` encoder (v1.44.0 / protobuf 7.35.1), captured once and pasted here.
That is the point of it: the decoder in `provekit/grpc_ingest.py` is hand-written, so
testing it against bytes this repo produced itself would only prove it agrees with itself.
opentelemetry-proto is deliberately NOT a dependency — it is a build-time oracle, not a
runtime one. To regenerate, build the same message with `opentelemetry.proto.collector.
trace.v1.trace_service_pb2.ExportTraceServiceRequest` in a throwaway venv and base64 it.
"""
import base64

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from conftest import ingest_workspace_id
from provekit import grpc_ingest
from provekit.database import SessionLocal
from provekit.models import Run
from provekit.routers import traces
from provekit.services import otel

# One resource, one scope, two spans: an OK gen_ai LLM span carrying every AnyValue kind
# (string / int / negative int / double / bool / array / kvlist / bytes) plus a log event,
# and a failed tool span parented to it.
GOLDEN_REQUEST = base64.b64decode(
    "CosGCiEKHwoMc2VydmljZS5uYW1lEg8KDXN1cHBvcnQtYWdlbnQS5QUKKwokb3BlbnRlbGVtZXRyeS"
    "5pbnN0cnVtZW50YXRpb24ub3BlbmFpEgMwLjEStwQKEBoaGhoaGhoaGhoaGhoaGhoSCCsrKysrKysr"
    "KhBjaGF0IGdwdC00by1taW5pMAM5AAAqNv6clxdBAGX3U/6clxdKIAoUZ2VuX2FpLnByb3ZpZGVyLm"
    "5hbWUSCAoGb3BlbmFpSiUKFGdlbl9haS5yZXF1ZXN0Lm1vZGVsEg0KC2dwdC00by1taW5pSh8KFWdl"
    "bl9haS5vcGVyYXRpb24ubmFtZRIGCgRjaGF0SiYKFWdlbl9haS5pbnB1dC5tZXNzYWdlcxINCgtoZW"
    "xsbyDDqeS4lkokChZnZW5fYWkub3V0cHV0Lm1lc3NhZ2VzEgoKCGhpIHRoZXJlSh8KGWdlbl9haS51"
    "c2FnZS5pbnB1dF90b2tlbnMSAhgLSiAKGmdlbl9haS51c2FnZS5vdXRwdXRfdG9rZW5zEgIYB0onCh"
    "pnZW5fYWkucmVxdWVzdC50ZW1wZXJhdHVyZRIJIQAAAAAAANA/SigKGWdlbl9haS5yZXF1ZXN0Lm1h"
    "eF90b2tlbnMSCxj9//////////8BSg8KCXNvbWUuYm9vbBICEAFKGQoKc29tZS5hcnJheRILKgkKAw"
    "oBYQoCGAJKHAoIc29tZS5tYXASEDIOCgwKBWlubmVyEgMKAXZKEwoKc29tZS5ieXRlcxIFOgMAAf9a"
    "QgkAwhVC/pyXFxIIcmV0cnlpbmcaFgoJbG9nLmxldmVsEgkKB1dBUk5JTkcaFQoKbG9nLmxvZ2dlch"
    "IHCgVodHRweHoCGAESfAoQGhoaGhoaGhoaGhoaGhoaGhIIPDw8PDw8PDwiCCsrKysrKysrKgxsb29r"
    "dXBfb3JkZXI5AOEfPP6clxdBAKMLSP6clxdKIgoQZ2VuX2FpLnRvb2wubmFtZRIOCgxsb29rdXBfb3"
    "JkZXJ6EBIMdXBzdHJlYW0gNTAwGAI=")

TRACE_ID = "1a" * 16
LLM_SPAN_ID = "2b" * 8
TOOL_SPAN_ID = "3c" * 8

PROTOBUF = {"Content-Type": "application/x-protobuf"}


def _binary_first_app() -> FastAPI:
    """The registration main.py needs: the binary route BEFORE the JSON one, since
    Starlette dispatches to the first route whose path and method match."""
    app = FastAPI()
    app.include_router(grpc_ingest.router)
    app.include_router(traces.router)
    return app


def _rows(trace_id: str) -> list[Run]:
    db = SessionLocal()
    try:
        return db.query(Run).filter(Run.trace_id == trace_id).order_by(Run.id.asc()).all()
    finally:
        db.close()


def _retag(body: bytes, trace_id: str) -> bytes:
    """Point a copy of the golden batch at a different trace id, so each test owns its own
    rows (dedupe is on (trace_id, span_id), and it is global to the workspace)."""
    return body.replace(bytes.fromhex(TRACE_ID), bytes.fromhex(trace_id))


# ---- the decoder, against bytes from the canonical encoder ----
def test_decode_shapes_match_the_json_mapping():
    payload = grpc_ingest.decode_export_trace_request(GOLDEN_REQUEST)
    spans = payload["resourceSpans"][0]["scopeSpans"][0]["spans"]
    assert len(spans) == 2
    llm, tool = spans

    # Ids are hex, exactly as the OTLP/JSON mapping (and Run.trace_id) spell them.
    assert llm["traceId"] == TRACE_ID and llm["spanId"] == LLM_SPAN_ID
    assert llm["parentSpanId"] == ""          # unset bytes field, not a missing key
    assert llm["name"] == "chat gpt-4o-mini"
    # Nanosecond timestamps stay strings: 1.7e18 does not survive a float.
    assert llm["startTimeUnixNano"] == "1700000000000000000"
    assert llm["endTimeUnixNano"] == "1700000000500000000"
    assert llm["status"] == {"code": 1}

    assert tool["parentSpanId"] == LLM_SPAN_ID
    assert tool["status"] == {"code": 2, "message": "upstream 500"}

    # Resource attributes survive the decode even though ingest ignores them today.
    assert payload["resourceSpans"][0]["resource"]["attributes"] == [
        {"key": "service.name", "value": {"stringValue": "support-agent"}}]


def test_decode_every_anyvalue_kind():
    payload = grpc_ingest.decode_export_trace_request(GOLDEN_REQUEST)
    span = payload["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
    attrs = otel.flatten_attrs(span["attributes"])
    assert attrs["gen_ai.request.model"] == "gpt-4o-mini"
    assert attrs["gen_ai.input.messages"] == "hello é世"       # multi-byte utf-8
    assert attrs["gen_ai.usage.input_tokens"] == 11
    assert attrs["gen_ai.request.temperature"] == 0.25
    assert attrs["gen_ai.request.max_tokens"] == -3            # two's-complement varint
    assert attrs["some.bool"] is True
    assert attrs["some.array"] == ["a", 2]
    assert attrs["some.map"] == {"inner": "v"}

    events = span["events"]
    assert len(events) == 1 and events[0]["name"] == "retrying"
    assert otel.flatten_attrs(events[0]["attributes"])["log.level"] == "WARNING"


def test_decoded_payload_maps_to_the_same_runs_as_json():
    rows = otel.ingest(grpc_ingest.decode_export_trace_request(GOLDEN_REQUEST))
    assert [r["type"] for r in rows] == ["llm", "tool"]
    llm, tool = rows
    assert llm["result"]["meta"]["model"] == "gpt-4o-mini"
    assert llm["result"]["meta"]["usage"] == {"input_tokens": 11, "output_tokens": 7}
    assert llm["result"]["meta"]["params"] == {"temperature": 0.25, "max_tokens": -3}
    assert llm["result"]["text"] == "hi there"
    assert llm["duration_ms"] == 500
    assert tool["status"] == "failed" and tool["error"] == "upstream 500"
    assert tool["parent_span_id"] == LLM_SPAN_ID


def test_unknown_fields_are_skipped_not_fatal():
    """A newer exporter adding a field must not break an older server — that is the whole
    reason the wire format is length-prefixed."""
    # field 9, wire type 2 (length-delimited), 3 bytes — no such field in this message.
    extra = b"\x4a\x03abc"
    payload = grpc_ingest.decode_export_trace_request(extra + GOLDEN_REQUEST)
    assert len(payload["resourceSpans"][0]["scopeSpans"][0]["spans"]) == 2


@pytest.mark.parametrize("body, reason", [
    (b"\x08", "truncated varint"),
    (b"\x0a\xff\x7f", "length-delimited field runs past"),
    (b"\x0d\x01", "truncated fixed-width field"),
    (b"\x0b\x01", "unsupported wire type"),
    (b"\x00\x01", "field number 0"),
    (b"\x08" + b"\xff" * 11, "varint exceeds 64 bits"),
])
def test_malformed_bodies_raise_rather_than_decode_to_nothing(body, reason):
    """The failure mode being fixed is "looks fine, stored nothing", so a body we cannot
    read must raise — never return an empty-but-plausible payload."""
    with pytest.raises(grpc_ingest.ProtobufError) as exc:
        grpc_ingest.decode_export_trace_request(body)
    assert reason in str(exc.value)


def test_nested_values_are_depth_bounded():
    """arrayValue nests into itself, so an adversarial body could recurse until the stack
    goes. Deep nesting is truncated; it does not crash the worker."""
    value = b"\x0a\x01x"                                    # AnyValue{string_value: "x"}
    for _ in range(20):                                     # stays under a 1-byte length
        inner = b"\x0a" + bytes([len(value)]) + value       # ArrayValue{values: [prev]}
        value = b"\x2a" + bytes([len(inner)]) + inner       # AnyValue{array_value: ...}
    kv = b"\x0a\x01k\x12" + bytes([len(value)]) + value
    decoded = grpc_ingest._key_value(kv)
    assert decoded["key"] == "k"
    depth = 0
    node = decoded["value"]
    while "arrayValue" in node:
        depth += 1
        node = node["arrayValue"]["values"][0]
    assert depth <= grpc_ingest._MAX_VALUE_DEPTH


def test_legacy_instrumentation_library_spans_are_read():
    """Field 1000 is the pre-1.0 spelling of scope_spans; pinned collectors still emit it."""
    scope = b"\x12\x02\x2a\x00"                             # ScopeSpans{spans: [Span{name:""}]}
    stray = b"\x18\x01"                                     # a scalar field we don't read
    rs = stray + b"\xc2\x3e" + bytes([len(scope)]) + scope  # field 1000, wire type 2
    body = b"\x0a" + bytes([len(rs)]) + rs
    payload = grpc_ingest.decode_export_trace_request(body)
    assert payload["resourceSpans"][0]["instrumentationLibrarySpans"][0]["spans"]


# ---- the response message ----
@pytest.mark.parametrize("args, expected", [
    ((), ""),                                    # full success is the empty message
    ((3, "nope"), "CggIAxIEbm9wZQ=="),
    ((0, "warned"), "CggSBndhcm5lZA=="),
])
def test_encode_response_matches_the_canonical_encoder(args, expected):
    assert base64.b64encode(grpc_ingest.encode_response(*args)).decode() == expected


@pytest.mark.parametrize("header, expected", [
    ("application/x-protobuf", True),
    ("application/protobuf", True),
    ("Application/X-Protobuf; charset=utf-8", True),
    ("application/json", False),
    (None, False),
])
def test_content_type_negotiation(header, expected):
    assert grpc_ingest.is_protobuf(header) is expected


# ---- the route, end to end ----
def test_protobuf_body_is_stored_and_answered_in_protobuf():
    trace_id = "a1" * 16
    with TestClient(_binary_first_app()) as client:
        resp = client.post("/v1/traces", content=_retag(GOLDEN_REQUEST, trace_id),
                           headers=PROTOBUF)
    assert resp.status_code == 200
    # Empty ExportTraceServiceResponse = full success, and in the encoding that was asked for.
    assert resp.content == b""
    assert resp.headers["content-type"].startswith("application/x-protobuf")
    stored = _rows(trace_id)
    assert [r.type for r in stored] == ["llm", "tool"]
    assert stored[0].workspace_id == ingest_workspace_id()
    assert stored[0].span_id == LLM_SPAN_ID
    assert stored[0].result["meta"]["model"] == "gpt-4o-mini"
    assert stored[1].span_id == TOOL_SPAN_ID and stored[1].status == "failed"


def test_retried_batch_is_deduped_by_the_shared_pipeline():
    """The exporter replaying a batch must not double the rows — proof the binary path goes
    through `_persist_spans` rather than writing its own."""
    trace_id = "a2" * 16
    body = _retag(GOLDEN_REQUEST, trace_id)
    with TestClient(_binary_first_app()) as client:
        assert client.post("/v1/traces", content=body, headers=PROTOBUF).status_code == 200
        assert client.post("/v1/traces", content=body, headers=PROTOBUF).status_code == 200
    assert len(_rows(trace_id)) == 2


def test_json_bodies_fall_through_untouched():
    """Registering this router in front of the JSON one must be invisible to JSON clients."""
    trace_id = "a3" * 16
    span = {"name": "chat", "traceId": trace_id, "spanId": "b1" * 8,
            "startTimeUnixNano": "1000000000", "endTimeUnixNano": "1200000000",
            "status": {"code": 1},
            "attributes": [{"key": "gen_ai.request.model", "value": {"stringValue": "m"}}]}
    with TestClient(_binary_first_app()) as client:
        resp = client.post("/v1/traces",
                           json={"resourceSpans": [{"scopeSpans": [{"spans": [span]}]}]})
    assert resp.status_code == 200 and resp.json() == {"partialSuccess": {}}
    assert len(_rows(trace_id)) == 1


def test_a_bad_ingest_key_is_still_rejected():
    """Auth is `workspace_from_key`, same as the JSON route — a new transport must not be a
    new way in."""
    with TestClient(_binary_first_app()) as client:
        resp = client.post("/v1/traces", content=GOLDEN_REQUEST,
                           headers={**PROTOBUF, "Authorization": "Bearer not-a-real-key"})
    assert resp.status_code == 403


def test_rate_limit_and_quota_still_apply(monkeypatch):
    """429 comes out of the shared `limits` check, not from anything in this module."""
    from fastapi import HTTPException

    def _throttled(ws_id):
        raise HTTPException(429, "Ingest rate limit exceeded for this project.")

    monkeypatch.setattr(traces.limits, "check_ingest_rate", _throttled)
    trace_id = "a4" * 16
    with TestClient(_binary_first_app()) as client:
        resp = client.post("/v1/traces", content=_retag(GOLDEN_REQUEST, trace_id),
                           headers=PROTOBUF)
    assert resp.status_code == 429
    assert _rows(trace_id) == []


def test_persist_failure_keeps_the_batch_spooled(monkeypatch):
    """Durability is the spool's, and the binary path inherits it: a failed write answers
    503 (which exporters retry) and leaves the batch staged for the drainer."""
    from provekit.services import spool

    def _boom(db, ws, rows):
        raise RuntimeError("database is gone")

    monkeypatch.setattr(traces, "_persist_spans", _boom)
    before = set(spool.pending())
    with TestClient(_binary_first_app()) as client:
        resp = client.post("/v1/traces", content=_retag(GOLDEN_REQUEST, "a5" * 16),
                           headers=PROTOBUF)
    assert resp.status_code == 503
    staged = set(spool.pending()) - before
    assert len(staged) == 1
    # Hand it back: a batch left staged counts toward the backpressure depth every later
    # test shares, and this one only needed to prove it got there.
    for path in staged:
        spool.release(path)


def test_malformed_body_is_a_loud_400_not_a_quiet_200():
    """The bug this closes: a body the server cannot read used to come back 200 with
    `rejectedSpans: 0`, which OTLP defines as success. Now it is a 400 carrying a real
    ExportTraceServiceResponse the exporter can print."""
    with TestClient(_binary_first_app()) as client:
        resp = client.post("/v1/traces", content=b"\x08\xff\xff", headers=PROTOBUF)
    assert resp.status_code == 400
    assert resp.headers["content-type"].startswith("application/x-protobuf")
    assert b"malformed OTLP protobuf" in resp.content


def test_partial_success_from_the_pipeline_is_re_encoded(monkeypatch):
    """Whatever the shared handler reports has to reach the exporter in protobuf, not JSON."""
    async def _partial(request, db, authorization):
        return {"partialSuccess": {"rejectedSpans": 3, "errorMessage": "nope"}}

    monkeypatch.setattr(traces, "ingest_traces", _partial)
    with TestClient(_binary_first_app()) as client:
        resp = client.post("/v1/traces", content=GOLDEN_REQUEST, headers=PROTOBUF)
    assert resp.status_code == 200
    assert resp.content == base64.b64decode("CggIAxIEbm9wZQ==")


def test_registering_after_the_json_router_reinstates_the_silent_drop():
    """Pins the ordering requirement in main.py. Included second, the binary route never
    matches, and a protobuf batch goes back to being acknowledged and thrown away — which
    is the exact failure #94 exists to fix, so it is worth a test rather than a comment."""
    app = FastAPI()
    app.include_router(traces.router)          # deliberately the wrong way round
    app.include_router(grpc_ingest.router)
    trace_id = "a6" * 16
    with TestClient(app) as client:
        resp = client.post("/v1/traces", content=_retag(GOLDEN_REQUEST, trace_id),
                           headers=PROTOBUF)
    assert resp.status_code == 200
    assert resp.json()["partialSuccess"]["errorMessage"] == "invalid JSON"
    assert _rows(trace_id) == []
