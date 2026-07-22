"""OpenTelemetry GenAI ingest + emit.

Ingest: accept OTLP/HTTP-JSON trace exports and map gen_ai.* spans into ProveKit runs,
so a user SEES traces from an agent built in ANY framework (ADK, Strands, Pydantic AI,
CrewAI, Semantic Kernel, OpenAI Agents SDK…) without swapping in our SDK.

The gen_ai semantic conventions are still churning, so the mapping is deliberately thin
and accepts three dialects:
  - current  gen_ai.* v1.37+  (gen_ai.input.messages / gen_ai.output.messages,
             gen_ai.provider.name, gen_ai.request.model, gen_ai.usage.*)
  - legacy   gen_ai.prompt / gen_ai.completion / gen_ai.system
  - OpenInference  llm.* / input.value / output.value

Emit: optionally export ProveKit's own runs as gen_ai spans to an OTLP collector, the
dual-export escape hatch buyers now expect.
"""
from __future__ import annotations

import json
import logging
import re
import time

from . import pricing

log = logging.getLogger("provekit.otel")


def _attr_value(v: dict):
    if "stringValue" in v:
        return v["stringValue"]
    if "intValue" in v:
        return int(v["intValue"])
    if "doubleValue" in v:
        return v["doubleValue"]
    if "boolValue" in v:
        return v["boolValue"]
    if "arrayValue" in v:
        return [_attr_value(x) for x in v["arrayValue"].get("values", [])]
    if "kvlistValue" in v:
        return {kv["key"]: _attr_value(kv["value"]) for kv in v["kvlistValue"].get("values", [])}
    return None


def flatten_attrs(attributes: list) -> dict:
    return {a["key"]: _attr_value(a.get("value") or {}) for a in attributes or []}


_INDEXED_MSG_RE = re.compile(r"^llm\.(input|output)_messages\.(\d+)\.message\.(role|content|name)$")
_INDEXED_TEXT_RE = re.compile(
    r"^llm\.(input|output)_messages\.(\d+)\.message\.contents\.(\d+)\.message_content\.text$")


def _reconstruct_indexed_messages(attrs: dict, direction: str) -> list[dict] | None:
    """Rebuild a messages array from OpenInference's flattened per-message attributes
    (`llm.input_messages.{i}.message.role`/`.content`, and multimodal `.message.contents.{j}.
    message_content.text`), independently of whether `input.value`/`gen_ai.input.messages` is
    also present. These travel as SEPARATE attribute sets in real instrumented spans (governed
    by independent redaction config, and the OTel SDK's default 128-attribute-per-span cap can
    evict one while the other survives) — so a literal key lookup for "llm.input_messages"
    misses real production data whenever only the indexed form survives. Returns None if no
    indexed attributes for this direction exist, so the caller can fall back to other dialects."""
    by_index: dict[int, dict[str, str]] = {}
    text_parts: dict[int, dict[int, str]] = {}
    for key, value in attrs.items():
        if not isinstance(key, str) or value is None:
            continue
        m = _INDEXED_MSG_RE.match(key)
        if m and m.group(1) == direction:
            by_index.setdefault(int(m.group(2)), {})[m.group(3)] = str(value)
            continue
        m = _INDEXED_TEXT_RE.match(key)
        if m and m.group(1) == direction:
            text_parts.setdefault(int(m.group(2)), {})[int(m.group(3))] = str(value)
    if not by_index and not text_parts:
        return None
    indices = sorted(set(by_index) | set(text_parts))
    out = []
    for i in indices:
        fields = by_index.get(i, {})
        content = fields.get("content", "")
        if i in text_parts:  # multimodal: join the text blocks (non-text blocks carry no text key)
            joined = " ".join(text_parts[i][j] for j in sorted(text_parts[i]))
            content = content or joined
        out.append({"role": fields.get("role") or fields.get("name") or "user", "content": content})
    return out


def _first(attrs: dict, *keys):
    for k in keys:
        if k in attrs and attrs[k] not in (None, ""):
            return attrs[k]
    return None


def _as_text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    try:
        return json.dumps(v)
    except (TypeError, ValueError):
        return str(v)


#: Per-field storage ceiling for captured payloads, in characters.
#:
#: A documented boundary, not an incidental slice: anything longer is cut here, a marker is
#: written to `result.meta.truncation` recording the original length, and the tail is dropped.
#: It is never stored elsewhere — ProveKit does not keep a copy you cannot see. Raise it if
#: your payloads are bigger and your database can carry them (see roadmap #20 for the real
#: fix, moving large payloads to object storage).
MAX_PAYLOAD_CHARS = 8000


def _truncate(value, limit: int):
    """(stored, marker) — marker is None when nothing was dropped."""
    if not isinstance(value, str) or len(value) <= limit:
        return value, None
    return value[:limit], {"stored_chars": limit, "original_chars": len(value)}


def map_span(span: dict) -> dict:
    """Map one OTLP span to Run kwargs. Every span is kept (so the full nested flow
    survives, not just the LLM calls) and classified: agent | llm | tool | step. The
    trace/span/parent ids are carried so the portal can rebuild the tree."""
    attrs = flatten_attrs(span.get("attributes"))
    model = _first(attrs, "gen_ai.request.model", "gen_ai.response.model", "llm.model_name", "gen_ai.model")
    provider = _first(attrs, "gen_ai.provider.name", "gen_ai.system", "llm.provider")
    operation = _first(attrs, "gen_ai.operation.name")
    tool = _first(attrs, "gen_ai.tool.name")
    session = _first(attrs, "session.id", "gen_ai.conversation.id", "thread.id", "session_id")

    # Reconstructed indexed OpenInference attributes take priority: they can be present when
    # input.value/gen_ai.input.messages are absent (see _reconstruct_indexed_messages).
    prompt = (_reconstruct_indexed_messages(attrs, "input")
             or _first(attrs, "gen_ai.input.messages", "gen_ai.prompt", "input.value",
                       "llm.input_messages", "input"))
    completion = (_reconstruct_indexed_messages(attrs, "output")
                 or _first(attrs, "gen_ai.output.messages", "gen_ai.completion", "output.value",
                           "llm.output_messages", "output"))
    usage = {}
    it = _first(attrs, "gen_ai.usage.input_tokens", "gen_ai.usage.prompt_tokens", "llm.token_count.prompt")
    ot = _first(attrs, "gen_ai.usage.output_tokens", "gen_ai.usage.completion_tokens", "llm.token_count.completion")
    if it is not None:
        usage["input_tokens"] = it
    if ot is not None:
        usage["output_tokens"] = ot

    # Parsed defensively: a non-numeric timestamp from a buggy exporter used to raise out of
    # here, and since ingest now retains a batch it failed to persist, one malformed span
    # would be retried out of the spool forever. A bad timestamp costs its own span's
    # duration, not the batch.
    start = _int(span.get("startTimeUnixNano"))
    end = _int(span.get("endTimeUnixNano"))
    dur_ms = round((end - start) / 1e6) if end > start else 0
    status = "failed" if (span.get("status") or {}).get("code") == 2 else "completed"

    if tool:
        rtype, op = "tool", "execute_tool"
    elif operation == "invoke_agent":
        rtype, op = "agent", "invoke_agent"
    elif model or provider:   # a real model call, not just any span that carries gen_ai.* io
        rtype, op = "llm", operation or "chat"
    else:
        rtype, op = "step", operation or (span.get("name") or "step")

    label = f"{op} {model}" if model else (span.get("name") or op)
    # start_ns as a STRING: epoch-nanoseconds overflow JS's 53-bit floats, but the client
    # only needs per-span *offsets* within a trace (a small delta) — computed via BigInt.
    meta = {"provider": provider, "model": model, "usage": usage, "source": "otel",
            "start_ns": str(start)}
    if model:
        # Stamp the rate table in force at capture time. Without it, re-costing this span
        # later applies whatever prices happen to be current, so a vendor repricing silently
        # rewrites what last quarter cost (services/pricing.py).
        meta["price_version"] = pricing.current_version()
    if session:
        meta["session_id"] = session
    if tool:
        meta["tool"] = tool
    # Deep span metadata the portal surfaces on an LLM span: invocation params + finish reason.
    params = {}
    for src, dst in (("gen_ai.request.temperature", "temperature"),
                     ("gen_ai.request.top_p", "top_p"),
                     ("gen_ai.request.max_tokens", "max_tokens")):
        v = _first(attrs, src)
        if v is not None:
            params[dst] = v
    if params:
        meta["params"] = params
    finish = _first(attrs, "gen_ai.response.finish_reasons", "gen_ai.response.finish_reason",
                    "llm.response.finish_reason")
    if finish is not None:
        meta["finish_reason"] = finish
    events = []
    for ev in span.get("events") or []:
        ea = flatten_attrs(ev.get("attributes"))
        events.append({"name": (ev.get("name") or "")[:500],
                       "level": ea.get("log.level", "INFO"), "logger": ea.get("log.logger", "")})
    if events:
        meta["events"] = events
    stored_input, in_trunc = _truncate(_as_text(prompt), MAX_PAYLOAD_CHARS)
    stored_output, out_trunc = _truncate(_as_text(completion), MAX_PAYLOAD_CHARS)
    if in_trunc or out_trunc:
        # What was kept vs. what arrived. Silently dropping the tail of a payload and
        # rendering it like a complete one means a truncated answer reads as the model's
        # answer — the reader has no way to tell the tool did it.
        meta["truncation"] = {k: v for k, v in
                              (("input", in_trunc), ("output", out_trunc)) if v}
    return {
        "type": rtype,
        "label": label[:200],
        "request": {"type": rtype, "provider": provider, "model": model,
                    "operation": op, "input": stored_input},
        "result": {"text": stored_output or None, "output": None, "meta": meta},
        "status": status,
        "duration_ms": dur_ms,
        "error": (span.get("status") or {}).get("message", "") if status == "failed" else "",
        "trace_id": span.get("traceId") or "",
        "span_id": span.get("spanId") or "",
        "parent_span_id": span.get("parentSpanId") or "",
        "session_id": session or "",
    }


#: How far a client's clock may run ahead of ours before we stop trusting its timestamps.
#: Generous on purpose — it has to absorb network delay, exporter batching and ordinary NTP
#: drift, so that a flag means "this clock is wrong", not "this export was slow".
CLOCK_SKEW_TOLERANCE_MS = 60_000


def ingest(payload: dict, *, received_ns: int | None = None) -> list[dict]:
    """Turn an OTLP ExportTraceServiceRequest into a list of Run kwargs (one per span).

    `received_ns` is server receipt time, used to detect client clock skew. The waterfall
    positions every bar from client-supplied start offsets, so a machine whose clock is wrong
    draws a chart that is confidently, invisibly nonsense — spans overlapping that never did,
    or a child starting before its parent. Detecting it is the only way the chart can say so.
    """
    received_ns = received_ns if received_ns is not None else time.time_ns()
    runs = []
    for rs in payload.get("resourceSpans", []):
        for ss in rs.get("scopeSpans", []) + rs.get("instrumentationLibrarySpans", []):
            for span in ss.get("spans", []):
                runs.append(_with_skew(map_span(span), span, received_ns))
    return runs


def _with_skew(row: dict, span: dict, received_ns: int) -> dict:
    """Flag a span whose clock disagrees with ours by more than the tolerance.

    Only a span that ended in the *future* is evidence of skew. A timestamp in the past is
    perfectly normal — exporters batch, networks are slow, a process can sit on a span for
    seconds — so treating "old" as skew would flag every healthy deployment.
    """
    end = _int(span.get("endTimeUnixNano"))
    if not end:
        return row
    ahead_ms = (end - received_ns) / 1_000_000
    if ahead_ms > CLOCK_SKEW_TOLERANCE_MS:
        meta = row.setdefault("result", {}).setdefault("meta", {})
        meta["clock_skew_ms"] = round(ahead_ms)
    return row


def _int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


# ---- emit (best-effort) ----
def emit_run(run_row) -> None:
    """Export one ProveKit run as a gen_ai span to an OTLP collector, if configured."""
    from ..config import get_settings
    url = get_settings().otel_export_url
    if not url:
        return
    import httpx

    from .netguard import guard_url
    meta = (run_row.result or {}).get("meta") or {}
    attrs = [{"key": "gen_ai.operation.name", "value": {"stringValue": run_row.type}}]
    if meta.get("provider"):
        attrs.append({"key": "gen_ai.provider.name", "value": {"stringValue": str(meta["provider"])}})
    if meta.get("model"):
        attrs.append({"key": "gen_ai.request.model", "value": {"stringValue": str(meta["model"])}})
    usage = meta.get("usage") or {}
    for src, dst in (("input_tokens", "gen_ai.usage.input_tokens"), ("output_tokens", "gen_ai.usage.output_tokens")):
        if usage.get(src) is not None:
            attrs.append({"key": dst, "value": {"intValue": int(usage[src])}})
    body = {"resourceSpans": [{"scopeSpans": [{"spans": [{
        "name": run_row.label or run_row.type, "attributes": attrs,
        "status": {"code": 2 if run_row.status == "failed" else 1}}]}]}]}
    try:
        guard_url(url)
        httpx.post(url, json=body, timeout=5, follow_redirects=False)
    except Exception as exc:  # best-effort; never break a run on export failure
        log.debug("otel emit failed: %s", exc)
