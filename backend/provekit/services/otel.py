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


def map_span(span: dict) -> dict:
    """Map one OTLP span to Run kwargs. Every span is kept (so the full nested flow
    survives, not just the LLM calls) and classified: agent | llm | tool | step. The
    trace/span/parent ids are carried so the portal can rebuild the tree."""
    attrs = flatten_attrs(span.get("attributes"))
    model = _first(attrs, "gen_ai.request.model", "gen_ai.response.model", "llm.model_name", "gen_ai.model")
    provider = _first(attrs, "gen_ai.provider.name", "gen_ai.system", "llm.provider")
    operation = _first(attrs, "gen_ai.operation.name")
    tool = _first(attrs, "gen_ai.tool.name")

    prompt = _first(attrs, "gen_ai.input.messages", "gen_ai.prompt", "input.value",
                    "llm.input_messages", "input")
    completion = _first(attrs, "gen_ai.output.messages", "gen_ai.completion", "output.value",
                        "llm.output_messages", "output")
    usage = {}
    it = _first(attrs, "gen_ai.usage.input_tokens", "gen_ai.usage.prompt_tokens", "llm.token_count.prompt")
    ot = _first(attrs, "gen_ai.usage.output_tokens", "gen_ai.usage.completion_tokens", "llm.token_count.completion")
    if it is not None:
        usage["input_tokens"] = it
    if ot is not None:
        usage["output_tokens"] = ot

    start = int(span.get("startTimeUnixNano") or 0)
    end = int(span.get("endTimeUnixNano") or 0)
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
    if tool:
        meta["tool"] = tool
    return {
        "type": rtype,
        "label": label[:200],
        "request": {"type": rtype, "provider": provider, "model": model,
                    "operation": op, "input": _as_text(prompt)[:8000]},
        "result": {"text": _as_text(completion) or None, "output": None, "meta": meta},
        "status": status,
        "duration_ms": dur_ms,
        "error": (span.get("status") or {}).get("message", "") if status == "failed" else "",
        "trace_id": span.get("traceId") or "",
        "span_id": span.get("spanId") or "",
        "parent_span_id": span.get("parentSpanId") or "",
    }


def ingest(payload: dict) -> list[dict]:
    """Turn an OTLP ExportTraceServiceRequest into a list of Run kwargs (one per span)."""
    runs = []
    for rs in payload.get("resourceSpans", []):
        for ss in rs.get("scopeSpans", []) + rs.get("instrumentationLibrarySpans", []):
            for span in ss.get("spans", []):
                runs.append(map_span(span))
    return runs


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
