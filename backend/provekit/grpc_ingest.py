"""OTLP *binary* trace ingest — accept `Content-Type: application/x-protobuf` on /v1/traces.

Roadmap #94 asks for gRPC. This ships the half of it that stops data loss today; see
"What is still missing" at the bottom for the half that isn't here.

Why this is the urgent half: `routers/traces.py` parses the body as JSON, and a body it
can't parse gets `200 {"partialSuccess": {"rejectedSpans": 0, "errorMessage": "invalid
JSON"}}`. Per the OTLP spec a 200 with `rejected_spans == 0` is *success* — the exporter
logs a warning at most, drops the batch from its queue and never retries. So every
protobuf exporter (Go's `otlptracehttp`, which has no JSON mode; Java/JS/.NET with the
default `http/protobuf`; an OpenTelemetry Collector's `otlphttp`, whose encoding defaults
to proto) reported a healthy pipeline while shipping into a hole.

Design: this module owns *decoding a transport*, not ingesting. The decoded payload is
handed to `traces.ingest_traces` unchanged, so the rate limit, the per-account span quota,
the spool (durability), the backpressure 503 and the (trace_id, span_id) dedupe all apply
exactly once and in one place. A second ingest path with its own copy of that sequence is
how those guarantees rot.

The protobuf is decoded by hand (~150 lines below) rather than by importing
`opentelemetry-proto`. That library pulls in `protobuf`, a C extension with per-platform
wheels, into a server whose whole dependency set is currently pure Python + psycopg. We
need to *read* one message family and never write it, which is the cheap direction of the
wire format. The tests check the decoder against golden bytes produced by the canonical
encoder, so "hand-rolled" doesn't mean "unverified".
"""
from __future__ import annotations

import base64
import json
import struct

from fastapi import APIRouter, Depends, Header, Request, Response
from sqlalchemy.orm import Session

from .database import get_db
from .routers import traces

# NOTE ON REGISTRATION: this router serves POST /v1/traces, the same path+method as the
# JSON handler, and Starlette dispatches to the FIRST route that matches. It must therefore
# be included BEFORE `traces.router` or it is dead code — and dead code here is the silent
# drop coming straight back. `test_grpc_ingest.py` pins that with a test that registers the
# two in the wrong order and asserts the protobuf body is dropped.
router = APIRouter(prefix="/v1", tags=["traces"])

#: What exporters actually send. `application/protobuf` is the RFC-registered spelling and
#: `application/x-protobuf` is what the OTel SDKs use; accept both, with or without params.
PROTOBUF_TYPES = ("application/x-protobuf", "application/protobuf")
_RESPONSE_MEDIA = "application/x-protobuf"


class ProtobufError(ValueError):
    """The body is not a decodable OTLP ExportTraceServiceRequest."""


# ---- protobuf wire format (read side) ----
_WIRE_VARINT, _WIRE_64BIT, _WIRE_LEN, _WIRE_32BIT = 0, 1, 2, 5

#: AnyValue nests through arrayValue/kvlistValue, so a hostile body can nest to arbitrary
#: depth and blow the Python stack. Real attribute values are flat or one level deep.
_MAX_VALUE_DEPTH = 8


def _varint(buf: bytes, i: int) -> tuple[int, int]:
    value = shift = 0
    while True:
        if i >= len(buf):
            raise ProtobufError("truncated varint")
        byte = buf[i]
        i += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, i
        shift += 7
        if shift > 63:
            raise ProtobufError("varint exceeds 64 bits")


def _fields(buf: bytes):
    """Yield (field_number, wire_type, raw) for one message, skipping nothing.

    Unknown fields come out too and every caller ignores the ones it doesn't know — which
    is the whole point of the format, and what lets a newer exporter talk to this decoder.
    """
    i, n = 0, len(buf)
    while i < n:
        key, i = _varint(buf, i)
        field, wire = key >> 3, key & 0x07
        if field == 0:
            raise ProtobufError("field number 0 is not valid")
        if wire == _WIRE_VARINT:
            raw, i = _varint(buf, i)
        elif wire in (_WIRE_64BIT, _WIRE_32BIT):
            width = 8 if wire == _WIRE_64BIT else 4
            if i + width > n:
                raise ProtobufError("truncated fixed-width field")
            raw, i = buf[i:i + width], i + width
        elif wire == _WIRE_LEN:
            length, i = _varint(buf, i)
            if i + length > n:
                raise ProtobufError("length-delimited field runs past the end of the message")
            raw, i = buf[i:i + length], i + length
        else:
            # Wire types 3/4 are the deprecated groups; 6/7 are unassigned. Neither appears
            # in OTLP, and guessing at a length for them would desynchronise the whole scan.
            raise ProtobufError(f"unsupported wire type {wire}")
        yield field, wire, raw


def _u64(raw: bytes) -> int:
    return int.from_bytes(raw, "little")


def _s64(value: int) -> int:
    """Varints carry int64 as unsigned two's complement; -3 arrives as 2**64 - 3."""
    return value - (1 << 64) if value >= (1 << 63) else value


def _text(raw: bytes) -> str:
    # "replace", not "strict": one span with a bad byte must not reject a 500-span batch.
    return raw.decode("utf-8", "replace")


# ---- OTLP messages -> the OTLP/JSON shape services/otel.py already reads ----
# Field numbers are from opentelemetry-proto v1 (trace.proto / common.proto), which is
# frozen: OTLP guarantees wire compatibility, so these cannot be renumbered.
def _any_value(buf: bytes, depth: int = 0) -> dict:
    """One AnyValue -> its JSON-mapping form. It's a oneof, so the first set field wins."""
    for field, wire, raw in _fields(buf):
        if field == 1 and wire == _WIRE_LEN:
            return {"stringValue": _text(raw)}
        if field == 2 and wire == _WIRE_VARINT:
            return {"boolValue": bool(raw)}
        if field == 3 and wire == _WIRE_VARINT:
            # int64 travels as a JSON string in the canonical mapping (>2**53 loses
            # precision as a float), and services/otel.py int()s it back.
            return {"intValue": str(_s64(raw))}
        if field == 4 and wire == _WIRE_64BIT:
            return {"doubleValue": struct.unpack("<d", raw)[0]}
        if field == 5 and wire == _WIRE_LEN and depth < _MAX_VALUE_DEPTH:
            values = [_any_value(v, depth + 1) for f, w, v in _fields(raw)
                      if f == 1 and w == _WIRE_LEN]
            return {"arrayValue": {"values": values}}
        if field == 6 and wire == _WIRE_LEN and depth < _MAX_VALUE_DEPTH:
            return {"kvlistValue": {"values": _key_values(raw, depth + 1)}}
        if field == 7 and wire == _WIRE_LEN:
            return {"bytesValue": base64.b64encode(raw).decode()}
    return {}


def _key_value(buf: bytes, depth: int = 0) -> dict:
    key, value = "", {}
    for field, wire, raw in _fields(buf):
        if field == 1 and wire == _WIRE_LEN:
            key = _text(raw)
        elif field == 2 and wire == _WIRE_LEN:
            value = _any_value(raw, depth)
    return {"key": key, "value": value}


def _key_values(buf: bytes, depth: int = 0) -> list[dict]:
    return [_key_value(raw, depth) for f, w, raw in _fields(buf) if f == 1 and w == _WIRE_LEN]


def _status(buf: bytes) -> dict:
    out: dict = {}
    for field, wire, raw in _fields(buf):
        if field == 2 and wire == _WIRE_LEN:
            out["message"] = _text(raw)
        elif field == 3 and wire == _WIRE_VARINT:
            out["code"] = raw
    return out


def _event(buf: bytes) -> dict:
    out: dict = {"attributes": []}
    for field, wire, raw in _fields(buf):
        if field == 1 and wire == _WIRE_64BIT:
            out["timeUnixNano"] = str(_u64(raw))
        elif field == 2 and wire == _WIRE_LEN:
            out["name"] = _text(raw)
        elif field == 3 and wire == _WIRE_LEN:
            out["attributes"].append(_key_value(raw))
    return out


def _span(buf: bytes) -> dict:
    # Ids are bytes on the wire and lowercase hex in the JSON mapping — which is also what
    # Run.trace_id/span_id store, so the tree, the dedupe index and share links all key off
    # the same string whichever transport a span arrived on.
    out: dict = {"traceId": "", "spanId": "", "parentSpanId": "", "name": "",
                 "attributes": [], "events": []}
    for field, wire, raw in _fields(buf):
        if wire == _WIRE_LEN and field == 1:
            out["traceId"] = raw.hex()
        elif wire == _WIRE_LEN and field == 2:
            out["spanId"] = raw.hex()
        elif wire == _WIRE_LEN and field == 4:
            out["parentSpanId"] = raw.hex()
        elif wire == _WIRE_LEN and field == 5:
            out["name"] = _text(raw)
        elif wire == _WIRE_64BIT and field == 7:
            out["startTimeUnixNano"] = str(_u64(raw))
        elif wire == _WIRE_64BIT and field == 8:
            out["endTimeUnixNano"] = str(_u64(raw))
        elif wire == _WIRE_LEN and field == 9:
            out["attributes"].append(_key_value(raw))
        elif wire == _WIRE_LEN and field == 11:
            out["events"].append(_event(raw))
        elif wire == _WIRE_LEN and field == 15:
            out["status"] = _status(raw)
    return out


def _scope_spans(buf: bytes) -> dict:
    return {"spans": [_span(raw) for f, w, raw in _fields(buf)
                      if f == 2 and w == _WIRE_LEN]}


def _resource_spans(buf: bytes) -> dict:
    out: dict = {"scopeSpans": [], "instrumentationLibrarySpans": []}
    for field, wire, raw in _fields(buf):
        if wire != _WIRE_LEN:
            continue
        if field == 1:
            out["resource"] = {"attributes": _key_values(raw)}
        elif field == 2:
            out["scopeSpans"].append(_scope_spans(raw))
        elif field == 1000:
            # The pre-1.0 name for the same message. Old collectors and pinned SDKs still
            # emit it, and services/otel.py already reads both spellings.
            out["instrumentationLibrarySpans"].append(_scope_spans(raw))
    return out


def decode_export_trace_request(body: bytes) -> dict:
    """OTLP ExportTraceServiceRequest (protobuf) -> the same dict `services/otel.ingest`
    gets from a JSON body.

    This is the seam a gRPC servicer would reuse verbatim: gRPC carries byte-identical
    `ExportTraceServiceRequest` messages, only the framing differs.
    """
    return {"resourceSpans": [_resource_spans(raw) for f, w, raw in _fields(body)
                              if f == 1 and w == _WIRE_LEN]}


# ---- ExportTraceServiceResponse (write side; the only message we ever encode) ----
def _encode_varint(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        out.append(byte | (0x80 if value else 0))
        if not value:
            return bytes(out)


def encode_response(rejected_spans: int = 0, error_message: str = "") -> bytes:
    """An ExportTraceServiceResponse. Full success is the empty message (zero bytes) —
    that is not a stub, it is what the protobuf encoding of "no fields set" is.

    A protobuf request must get a protobuf response: recent OTel exporters parse the body
    to read partial-success counts, and handing them JSON turns a delivered batch into a
    parse error in the exporter's own logs.
    """
    if not rejected_spans and not error_message:
        return b""
    inner = b""
    if rejected_spans:
        inner += b"\x08" + _encode_varint(rejected_spans)
    if error_message:
        encoded = error_message.encode("utf-8")
        inner += b"\x12" + _encode_varint(len(encoded)) + encoded
    return b"\x0a" + _encode_varint(len(inner)) + inner


# ---- the route ----
def is_protobuf(content_type: str | None) -> bool:
    return (content_type or "").split(";")[0].strip().lower() in PROTOBUF_TYPES


def _as_json_request(request: Request, payload: dict) -> Request:
    """The same request with a JSON body, so `traces.ingest_traces` can run untouched.

    Re-serialising costs a pass over the batch. The alternative is a second copy of the
    quota/spool/dedupe sequence in this module, and that copy is guaranteed to drift from
    the original the first time either is changed. Headers (hence the bearer key and the
    session cookie) and the client address are carried over unchanged.
    """
    body = json.dumps(payload).encode()
    headers = [(k, v) for k, v in request.scope.get("headers", [])
               if k not in (b"content-type", b"content-length")]
    headers += [(b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode())]

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(dict(request.scope, headers=headers), receive)


@router.post("/traces", include_in_schema=False)
async def ingest_traces_binary(request: Request, db: Session = Depends(get_db),
                               authorization: str | None = Header(default=None),
                               content_type: str | None = Header(default=None)):
    """POST /v1/traces for exporters that send protobuf; JSON falls straight through.

    Hidden from the schema deliberately: it is the same path and method as the documented
    JSON route, so publishing it would overwrite that operation in the OpenAPI document
    with a body type half the clients don't send. One endpoint, two encodings.
    """
    if not is_protobuf(content_type):
        return await traces.ingest_traces(request, db, authorization)
    try:
        payload = decode_export_trace_request(await request.body())
    except ProtobufError as exc:
        # 400, not a 200 with a note in it. The body is malformed, so a retry sends the
        # same bytes; the exporter should surface this and stop, which is exactly the
        # behaviour the JSON path's "invalid JSON" success response denied it.
        return Response(content=encode_response(0, f"malformed OTLP protobuf: {exc}"),
                        media_type=_RESPONSE_MEDIA, status_code=400)
    result = await traces.ingest_traces(_as_json_request(request, payload), db, authorization)
    partial = (result or {}).get("partialSuccess") or {}
    return Response(content=encode_response(int(partial.get("rejectedSpans") or 0),
                                            str(partial.get("errorMessage") or "")),
                    media_type=_RESPONSE_MEDIA)


# ---- What is still missing (the gRPC half of #94) ----
# gRPC needs an HTTP/2 server on :4317 speaking the `opentelemetry.proto.collector.trace
# .v1.TraceService/Export` method. That is not something the ASGI app can host: uvicorn
# serves HTTP/1.1, so it means grpcio (a C extension, per-platform wheels) plus a second
# listener started and stopped in main.py's lifespan and a second port in the Dockerfile
# and compose files. What it does NOT need is any of the code above being rewritten: a
# servicer's `Export(request, context)` receives the identical message, so it would call
# `decode_export_trace_request(request.SerializeToString())` — or skip straight to the
# dict — and hand it to the same `traces.ingest_traces`, with `context.invocation_metadata()`
# supplying the `authorization` header. The remaining work is transport and deployment.
# Until then, a gRPC exporter reaches ProveKit through a collector: receive OTLP/gRPC,
# export `otlphttp` to /v1/traces. That path is now lossless, which it was not before.
