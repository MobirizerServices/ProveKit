"""ProveKit tracing SDK — one decorator at your agent's entrypoint captures the whole
nested flow (LLM calls, tools, sub-steps) and ships it to your ProveKit portal to review.

    import provekit.trace as pk

    @pk.trace(name="support-agent")
    def run_agent(question: str) -> str:
        docs = retrieve(question)          # wrap sub-steps with pk.span() if you like
        return llm(question, docs)         # OpenAI/Anthropic calls are captured automatically

Configuration is by environment (12-factor):
    PROVEKIT_API_KEY   the pk_ project key from the portal
    PROVEKIT_ENDPOINT  your ProveKit URL, e.g. https://provekit.your-co.com

It's real OpenTelemetry underneath: the decorator opens a span and makes it the current
context, so any instrumented library beneath it (OpenAI, Anthropic, and anything emitting
OTel spans) nests as a child — you decorate the entrypoint ONCE and get the full tree, no
per-function wiring and no OpenTelemetry knowledge required.

Fail-open by construction: if the key/endpoint are unset, OTel isn't installed, or the
portal is unreachable, your app runs completely unaffected — tracing degrades to a no-op.
"""
from __future__ import annotations

import contextlib
import functools
import json
import logging
import os
import threading

log = logging.getLogger("provekit.trace")

_lock = threading.Lock()
_tracer = None          # set once configured; None means tracing is a no-op
_configured = False
_api_key = None         # kept so pk.score() can post feedback to the portal
_endpoint = None

# Best-effort auto-instrumentation: whichever of these are installed get enabled so their
# calls nest under the decorated entrypoint with no manual spans. All optional — a missing
# package (or a class that moved) is silently skipped. Install the matching openinference
# package (or use `provekit[trace-all]`) to light one up.
_INSTRUMENTORS = [
    # LLM providers
    ("openinference.instrumentation.openai", "OpenAIInstrumentor"),
    ("openinference.instrumentation.anthropic", "AnthropicInstrumentor"),
    ("openinference.instrumentation.bedrock", "BedrockInstrumentor"),
    ("openinference.instrumentation.mistralai", "MistralAIInstrumentor"),
    ("openinference.instrumentation.groq", "GroqInstrumentor"),
    ("openinference.instrumentation.google_genai", "GoogleGenAIInstrumentor"),
    ("openinference.instrumentation.vertexai", "VertexAIInstrumentor"),
    ("openinference.instrumentation.litellm", "LiteLLMInstrumentor"),
    # agent frameworks
    ("openinference.instrumentation.langchain", "LangChainInstrumentor"),
    ("openinference.instrumentation.llama_index", "LlamaIndexInstrumentor"),
    ("openinference.instrumentation.crewai", "CrewAIInstrumentor"),
    ("openinference.instrumentation.autogen", "AutogenInstrumentor"),
    ("openinference.instrumentation.openai_agents", "OpenAIAgentsInstrumentor"),
    ("openinference.instrumentation.smolagents", "SmolagentsInstrumentor"),
    ("openinference.instrumentation.dspy", "DSPyInstrumentor"),
    ("openinference.instrumentation.haystack", "HaystackInstrumentor"),
    ("openinference.instrumentation.guardrails", "GuardrailsInstrumentor"),
    ("openinference.instrumentation.instructor", "InstructorInstrumentor"),
    ("openinference.instrumentation.agno", "AgnoInstrumentor"),
    ("openinference.instrumentation.pydantic_ai", "OpenInferencePydanticAIInstrumentor"),
]

# Generic (non-LLM) instrumentors: every outbound HTTP call your agent makes — tool APIs,
# vector DBs, webhooks — becomes a child span too, so "capture everything" isn't just the
# model calls. Best-effort, same as above: install `provekit[http]` (or `[trace-all]`) to
# light these up. These come from opentelemetry-instrumentation-*, not openinference.
_HTTP_INSTRUMENTORS = [
    ("opentelemetry.instrumentation.httpx", "HTTPXClientInstrumentor"),
    ("opentelemetry.instrumentation.requests", "RequestsInstrumentor"),
    ("opentelemetry.instrumentation.aiohttp_client", "AioHttpClientInstrumentor"),
    ("opentelemetry.instrumentation.urllib", "URLLibInstrumentor"),
]


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
    ctx = span.context
    out = {"name": span.name, "attributes": attrs,
           # hex-encoded ids so the ingest can rebuild the parent/child tree
           "traceId": format(ctx.trace_id, "032x") if ctx else "",
           "spanId": format(ctx.span_id, "016x") if ctx else "",
           "parentSpanId": format(span.parent.span_id, "016x") if span.parent else "",
           "startTimeUnixNano": str(span.start_time or 0),
           "endTimeUnixNano": str(span.end_time or 0),
           "status": {"code": code}}
    msg = getattr(span.status, "description", None)
    if code == 2 and msg:
        out["status"]["message"] = msg
    events = span.events or []
    if events:
        out["events"] = [{
            "timeUnixNano": str(getattr(e, "timestamp", 0) or 0),
            "name": e.name,
            "attributes": [{"key": str(k), "value": _attr(v)} for k, v in (e.attributes or {}).items()],
        } for e in events]
    return out


class _ProveKitExporter:
    """A minimal OTel SpanExporter that ships spans to ProveKit's /v1/traces as OTLP-JSON.

    We emit JSON (not protobuf) because the ingest endpoint reads JSON; this keeps the
    server unchanged and the SDK's only heavy dependency the OTel SDK itself.
    """
    def __init__(self, url: str, api_key: str, buffer=None):
        self._url = url
        self._headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        self._buffer = buffer

    def _send(self, body: dict) -> bool:
        """POST one OTLP body. False on anything that isn't an accepted write.

        The status code matters: the server sheds load with 503 when its ingest backlog is
        full, and a key can be revoked mid-run. Treating those as success — which this did,
        by never looking — silently drops exactly the spans the retry path exists for.
        """
        import httpx
        r = httpx.post(self._url, json=body, headers=self._headers, timeout=5,
                       follow_redirects=False)
        if r.status_code >= 400:
            log.debug("provekit trace export rejected: HTTP %s", r.status_code)
            return False
        return True

    def export(self, spans):
        from opentelemetry.sdk.trace.export import SpanExportResult
        body = {"resourceSpans": [{"scopeSpans": [{"spans": [_span_to_otlp(s) for s in spans]}]}]}
        try:
            # Retry what an earlier outage left buffered first, so traces land in the order
            # they happened rather than newest-first after a reconnect.
            if self._buffer is not None and self._buffer.depth():
                self._buffer.drain(self._send)
            if self._send(body):
                return SpanExportResult.SUCCESS
            self._stash(body)
            return SpanExportResult.FAILURE
        except Exception as exc:  # never let a trace-export failure surface into the user's app
            log.debug("provekit trace export failed: %s", exc)
            self._stash(body)
            return SpanExportResult.FAILURE

    def _stash(self, body: dict) -> None:
        if self._buffer is not None:
            self._buffer.put(body)

    def shutdown(self):
        pass

    def force_flush(self, timeout_millis: int = 30000):
        """A flush is the app's last chance to get its spans out — drain the buffer too."""
        try:
            if self._buffer is not None and self._buffer.depth():
                self._buffer.drain(self._send)
        except Exception:
            pass
        return True


def _auto_instrument(provider) -> None:
    """Enable whichever LLM and HTTP instrumentors are installed, routed to our provider so
    their spans nest under the decorated entrypoint. Best-effort; never raises."""
    # An instrumentor whose target library is absent (e.g. no `openai` installed in a
    # mock-LLM demo) logs an ERROR-level "DependencyConflict" and skips itself. That's
    # expected for us — we enable whatever's present — but it looks alarming to a first-time
    # user, so quiet that logger while probing, then restore it.
    inst_log = logging.getLogger("opentelemetry.instrumentation.instrumentor")
    prev_level = inst_log.level
    inst_log.setLevel(logging.CRITICAL)
    try:
        for module, cls in (*_INSTRUMENTORS, *_HTTP_INSTRUMENTORS):
            try:
                mod = __import__(module, fromlist=[cls])
                getattr(mod, cls)().instrument(tracer_provider=provider)
                log.debug("provekit: auto-instrumented %s", module)
            except Exception:  # not installed / already instrumented / incompatible → skip
                pass
    finally:
        inst_log.setLevel(prev_level)


class _SpanLogHandler(logging.Handler):
    """Attach `logging` records to the active span as events, so your app's own logs show up
    inline in the trace. Only records emitted while a ProveKit span is recording are captured
    (logs outside a traced flow are ignored)."""
    def emit(self, record):
        try:
            from opentelemetry import trace as _otel
            span = _otel.get_current_span()
            if span is None or not span.is_recording():
                return
            span.add_event(record.getMessage()[:1000],
                           {"log.level": record.levelname, "log.logger": record.name})
        except Exception:
            pass


_log_handler = None


# Transport/plumbing loggers whose records are noise in an agent trace (and our own).
_NOISY_LOGGERS = ("provekit", "httpx", "httpcore", "urllib3", "openai._base_client",
                  "anthropic._base_client", "opentelemetry")


def _install_log_handler(level: int) -> None:
    global _log_handler
    if _log_handler is not None:
        return
    _log_handler = _SpanLogHandler(level=level)
    _log_handler.addFilter(lambda r: not r.name.startswith(_NOISY_LOGGERS))
    logging.getLogger().addHandler(_log_handler)


def _make_buffer(max_batches: int | None, directory: str | None):
    """Build the on-disk retry buffer, or None if it's disabled/unusable.

    Never raises: a buffer we can't construct means the SDK behaves exactly as it did before
    it existed, which is a degraded safety net and not a broken app.
    """
    try:
        from .buffer import SpanBuffer
        if max_batches is None:
            max_batches = int(os.environ.get("PROVEKIT_BUFFER_BATCHES", "500"))
        if max_batches <= 0:
            return None
        return SpanBuffer(directory or os.environ.get("PROVEKIT_BUFFER_DIR") or None,
                          max_batches=max_batches)
    except Exception as exc:
        log.debug("provekit: span buffer disabled (%s)", exc)
        return None


def configure(api_key: str | None = None, endpoint: str | None = None,
              *, batch: bool = True, capture_logs: bool = True, log_level: int = logging.INFO,
              buffer_batches: int | None = None, buffer_dir: str | None = None) -> bool:
    """Wire up the tracer. Returns True if tracing is active, False if it's a no-op.

    Called automatically on first use; call it explicitly only to pass values in code
    instead of the environment. Idempotent. `capture_logs` attaches a handler that records
    your `logging` calls (at `log_level`+) as events on the active span.

    A failed export is buffered on disk and retried on the next one, so a deploy or a brief
    network blip doesn't lose traces. `buffer_batches=0` turns that off and restores the old
    drop-on-failure behaviour; `PROVEKIT_BUFFER_BATCHES` / `PROVEKIT_BUFFER_DIR` do the same
    from the environment."""
    global _tracer, _configured, _api_key, _endpoint
    with _lock:
        if _configured:
            return _tracer is not None
        _configured = True
        api_key = api_key or os.environ.get("PROVEKIT_API_KEY")
        endpoint = endpoint or os.environ.get("PROVEKIT_ENDPOINT")
        if not api_key or not endpoint:
            log.debug("provekit tracing disabled: set PROVEKIT_API_KEY and PROVEKIT_ENDPOINT")
            return False
        _api_key, _endpoint = api_key, endpoint.rstrip("/")
        try:
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor
            url = endpoint.rstrip("/") + "/v1/traces"
            provider = TracerProvider()
            exporter = _ProveKitExporter(url, api_key, buffer=_make_buffer(buffer_batches,
                                                                          buffer_dir))
            proc = BatchSpanProcessor(exporter) if batch else SimpleSpanProcessor(exporter)
            provider.add_span_processor(proc)
            _tracer = provider.get_tracer("provekit")
            _auto_instrument(provider)   # LLM calls beneath the entrypoint capture themselves
            if capture_logs:
                _install_log_handler(log_level)   # your logging.* calls become trace events
            return True
        except Exception as exc:  # OTel missing or misconfigured → stay a no-op, never crash
            log.debug("provekit tracing could not start: %s", exc)
            _tracer = None
            return False


def _payload(args: tuple, kwargs: dict):
    """Best-effort JSON of a call's inputs. Positional args are indexed; keywords by name."""
    data = {**{f"arg{i}": a for i, a in enumerate(args)}, **kwargs}
    try:
        return json.dumps(data, default=str)
    except (TypeError, ValueError):
        return str(data)


def _as_attr(v):
    return v if isinstance(v, (str, int, float, bool)) else _payload((v,), {})


def trace(name: str | None = None, *, operation: str = "invoke_agent", session_id: str | None = None):
    """Decorate an agent entrypoint (or any function) so each call is captured. Everything
    that runs inside — instrumented LLM calls, pk.span() blocks — nests beneath it.

    @pk.trace(name="support-agent")
    def run_agent(q): ...

    Pass `session_id` to group multi-turn runs (a conversation/thread) in the portal.
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
                if session_id:
                    span.set_attribute("session.id", str(session_id))
                span.set_attribute("gen_ai.input.messages", _payload(args, kwargs))
                try:
                    result = fn(*args, **kwargs)
                except Exception as exc:
                    span.set_status(Status(StatusCode.ERROR, str(exc)))
                    raise
                span.set_attribute("gen_ai.output.messages", _as_attr(result))
                return result
        return wrapper
    return deco


def init(api_key: str | None = None, endpoint: str | None = None, **kwargs) -> bool:
    """One-line, zero-decorator setup — the whole client integration.

        import provekit.trace as pk
        pk.init()                       # reads PROVEKIT_API_KEY / PROVEKIT_ENDPOINT

    After this every instrumented library beneath your code — LLM providers, agent
    frameworks, and outbound HTTP (with `provekit[http]`) — is captured on its own, no
    decorator and no per-call wiring. Add `@pk.trace` only when you want a run grouped
    under one named root. Even shorter: `import provekit.auto` calls this for you.

    Returns True if tracing is active, False if it's a no-op (keys unset / OTel missing).
    """
    return configure(api_key, endpoint, **kwargs)


@contextlib.contextmanager
def span(name: str, **attributes):
    """Capture a sub-step (a retrieval, a tool call, a branch) as a child span:

        with pk.span("retrieve", query=q) as s:
            docs = search(q)
            s and s.set_attribute("gen_ai.output.messages", str(docs))
    """
    if not configure():
        yield None
        return
    from opentelemetry.trace import Status, StatusCode
    with _tracer.start_as_current_span(name) as sp:
        for k, v in attributes.items():
            sp.set_attribute(k, _as_attr(v))
        try:
            yield sp
        except Exception as exc:
            sp.set_status(Status(StatusCode.ERROR, str(exc)))
            raise


def get_prompt(name: str, *, label: str = "", key: str = "", default=None) -> dict | None:
    """Fetch a prompt from the portal at runtime (#61), honouring any live A/B split (#62).

        p = pk.get_prompt("checkout-agent", label="production", key=session_id)
        reply = client.chat.completions.create(model=p["model"], messages=p["messages"])

    `key` is what the split is keyed on — pass a session or user id. Assignment is stable for
    that key, so a user stays on one variant across their whole conversation; without it the
    variants interleave mid-conversation and the comparison measures assignment noise.

    Returns `default` if the portal is unreachable, unconfigured, or has no such prompt. A
    prompt fetch that raises would take down the app on a network blip — the same fail-open
    contract the rest of this SDK follows — so a caller who needs a guarantee passes a default
    and gets it.

    The served version is recorded on the current span as `prompt.version` / `prompt.served_by`
    so live scores can be attributed back to the variant that produced them. A split whose
    outcome isn't attached to the run leaves two populations nobody can tell apart.
    """
    import os

    configure()
    api_key = _api_key or os.environ.get("PROVEKIT_API_KEY")
    endpoint = (_endpoint or os.environ.get("PROVEKIT_ENDPOINT") or "").rstrip("/")
    if not api_key or not endpoint:
        return default
    try:
        import httpx
        r = httpx.get(f"{endpoint}/v1/prompts/{name}",
                      params={"label": label, "key": key},
                      headers={"Authorization": f"Bearer {api_key}"}, timeout=5)
        if r.status_code >= 400:
            log.debug("provekit: prompt %r fetch returned %s", name, r.status_code)
            return default
        body = r.json()
    except Exception as exc:
        log.debug("provekit: prompt %r fetch failed: %s", name, exc)
        return default
    try:
        from opentelemetry import trace as _otel
        span = _otel.get_current_span()
        if span is not None:
            span.set_attribute("prompt.name", name)
            span.set_attribute("prompt.version", int(body.get("version") or 0))
            span.set_attribute("prompt.served_by", str(body.get("served_by") or ""))
    except Exception:
        pass          # attribution is a nicety; never let it cost the caller their prompt
    return body


def score(name: str, *, score: float | None = None, value: str | None = None,
          comment: str | None = None, trace_id: str | None = None) -> bool:
    """Attach a feedback score to a trace from code — a scorer, a guardrail, a heuristic.

        pk.score("relevance", score=0.9)          # from inside a traced run
        pk.score("thumbs", value="up", comment="great answer")

    Uses the current trace's id when `trace_id` is omitted. Fail-open: returns True if it
    was sent, False if tracing is off or there's no active trace to attach to."""
    if not configure():
        return False
    if trace_id is None:
        try:
            from opentelemetry import trace as _otel
            ctx = _otel.get_current_span().get_span_context()
            trace_id = format(ctx.trace_id, "032x") if ctx and ctx.trace_id else None
        except Exception:
            trace_id = None
    if not trace_id:
        log.debug("provekit score: no trace_id (call inside a traced run or pass trace_id=)")
        return False
    body = {"name": name, "score": score, "value": value, "comment": comment, "source": "sdk"}
    try:
        import httpx
        httpx.post(f"{_endpoint}/v1/traces/{trace_id}/feedback", json=body,
                   headers={"Authorization": f"Bearer {_api_key}"}, timeout=5, follow_redirects=False)
        return True
    except Exception as exc:  # never let a feedback post surface into the user's app
        log.debug("provekit score post failed: %s", exc)
        return False
