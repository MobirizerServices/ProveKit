"""ProveKit tracing SDK — capture real agent runs, ship them to a ProveKit portal, then
turn a run into a regression test (the "trace → test" bridge).

    import provekit.trace as pk

    @pk.trace(name="support-agent")
    def run_agent(question: str) -> str:
        ...

Configuration is by environment (12-factor):
    PROVEKIT_API_KEY   the pk_ key minted in the portal (Settings → API keys)
    PROVEKIT_ENDPOINT  your ProveKit URL, e.g. https://provekit.your-co.com

Each decorated call becomes an OpenTelemetry span carrying the function's input and output
under the gen_ai conventions, so it lands as a run in the portal. Because it's real
OpenTelemetry, any LLM instrumentation you've installed (OpenAI/Anthropic) nests its own
gen_ai spans inside the same trace — no extra wiring.

Fail-open by construction: if PROVEKIT_API_KEY/ENDPOINT are unset, or the portal is
unreachable, your app runs completely unaffected — tracing degrades to a no-op.
"""
from __future__ import annotations

import functools
import json
import logging
import os
import threading

log = logging.getLogger("provekit.trace")

_lock = threading.Lock()
_tracer = None          # set once configured; None means tracing is a no-op
_configured = False


# ---- OTLP/JSON serialization (matches services.otel.ingest, which reads OTLP-JSON) ----
def _attr(value) -> dict:
    """One OTLP AnyValue for a Python scalar. Non-scalars are JSON-encoded to a string."""
    if isinstance(value, bool):
        return {"boolValue": value}
    if isinstance(value, int):
        return {"intValue": value}
    if isinstance(value, float):
        return {"doubleValue": value}
    if isinstance(value, str):
        return {"stringValue": value}
    try:
        return {"stringValue": json.dumps(value)}
    except (TypeError, ValueError):
        return {"stringValue": str(value)}


def _span_to_otlp(span) -> dict:
    attrs = [{"key": str(k), "value": _attr(v)} for k, v in (span.attributes or {}).items()]
    code = 2 if getattr(span.status, "status_code", None) and span.status.status_code.name == "ERROR" else 1
    out = {"name": span.name, "attributes": attrs,
           "startTimeUnixNano": str(span.start_time or 0),
           "endTimeUnixNano": str(span.end_time or 0),
           "status": {"code": code}}
    msg = getattr(span.status, "description", None)
    if code == 2 and msg:
        out["status"]["message"] = msg
    return out


class _ProveKitExporter:
    """A minimal OTel SpanExporter that ships spans to ProveKit's /v1/traces as OTLP-JSON.

    We emit JSON (not protobuf) because the ingest endpoint reads JSON; this keeps the
    server unchanged and the SDK's only heavy dependency the OTel SDK itself.
    """
    def __init__(self, url: str, api_key: str):
        self._url = url
        self._headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    def export(self, spans):
        from opentelemetry.sdk.trace.export import SpanExportResult
        try:
            import httpx
            body = {"resourceSpans": [{"scopeSpans": [{"spans": [_span_to_otlp(s) for s in spans]}]}]}
            httpx.post(self._url, json=body, headers=self._headers, timeout=5, follow_redirects=False)
            return SpanExportResult.SUCCESS
        except Exception as exc:  # never let a trace-export failure surface into the user's app
            log.debug("provekit trace export failed: %s", exc)
            return SpanExportResult.FAILURE

    def shutdown(self):
        pass

    def force_flush(self, timeout_millis: int = 30000):
        return True


def configure(api_key: str | None = None, endpoint: str | None = None,
              *, batch: bool = True) -> bool:
    """Wire up the tracer. Returns True if tracing is active, False if it's a no-op.

    Called automatically on first use; call it explicitly only to pass values in code
    instead of the environment. Idempotent."""
    global _tracer, _configured
    with _lock:
        if _configured:
            return _tracer is not None
        _configured = True
        api_key = api_key or os.environ.get("PROVEKIT_API_KEY")
        endpoint = endpoint or os.environ.get("PROVEKIT_ENDPOINT")
        if not api_key or not endpoint:
            log.debug("provekit tracing disabled: set PROVEKIT_API_KEY and PROVEKIT_ENDPOINT")
            return False
        try:
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor
            url = endpoint.rstrip("/") + "/v1/traces"
            provider = TracerProvider()
            exporter = _ProveKitExporter(url, api_key)
            proc = BatchSpanProcessor(exporter) if batch else SimpleSpanProcessor(exporter)
            provider.add_span_processor(proc)
            _tracer = provider.get_tracer("provekit")
            return True
        except Exception as exc:  # OTel missing or misconfigured → stay a no-op, never crash
            log.debug("provekit tracing could not start: %s", exc)
            _tracer = None
            return False


def _payload(args: tuple, kwargs: dict):
    """Best-effort JSON of a call's inputs — this is what the portal turns into a test's
    request. Positional args are indexed; keywords by name."""
    data = {**{f"arg{i}": a for i, a in enumerate(args)}, **kwargs}
    try:
        return json.dumps(data, default=str)
    except (TypeError, ValueError):
        return str(data)


def trace(name: str | None = None, *, operation: str = "invoke_agent"):
    """Decorate an agent entrypoint (or any function) so each call is captured as a run.

    @pk.trace(name="support-agent")
    def run_agent(q): ...
    """
    def deco(fn):
        span_name = name or getattr(fn, "__name__", "agent")

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            if not configure():           # tracing off → call straight through, zero overhead
                return fn(*args, **kwargs)
            from opentelemetry.trace import Status, StatusCode
            with _tracer.start_as_current_span(span_name) as span:
                span.set_attribute("gen_ai.operation.name", operation)
                span.set_attribute("gen_ai.input.messages", _payload(args, kwargs))
                try:
                    result = fn(*args, **kwargs)
                except Exception as exc:
                    span.set_status(Status(StatusCode.ERROR, str(exc)))
                    raise
                out = result if isinstance(result, str) else _payload((result,), {})
                span.set_attribute("gen_ai.output.messages", out)
                return result
        return wrapper
    return deco
