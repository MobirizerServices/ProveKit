"""ProveKit tracing SDK: fail-open when unconfigured, and a decorated call round-trips
through the OTLP-JSON exporter into a run via services.otel.ingest (the trace→test raw
material). Requires the [trace] extra (opentelemetry-sdk)."""
import httpx
import pytest

pytest.importorskip("opentelemetry.sdk.trace")  # the [trace] extra; skip if not installed

import provekit.trace as pk  # noqa: E402
from provekit.services import otel  # noqa: E402


def _reset():
    # configure() is idempotent via module globals; reset them per test.
    pk._configured = False
    pk._tracer = None


def test_trace_is_a_no_op_when_unconfigured(monkeypatch):
    _reset()
    monkeypatch.delenv("PROVEKIT_API_KEY", raising=False)
    monkeypatch.delenv("PROVEKIT_ENDPOINT", raising=False)

    @pk.trace(name="agent")
    def run(q):
        return f"answer to {q}"

    assert run("hi") == "answer to hi"     # runs unaffected with no key/endpoint
    assert pk.configure() is False


def test_init_is_an_alias_for_configure(monkeypatch):
    _reset()
    monkeypatch.delenv("PROVEKIT_API_KEY", raising=False)
    monkeypatch.delenv("PROVEKIT_ENDPOINT", raising=False)
    assert pk.init() is False                 # no env → no-op, same as configure()
    _reset()
    monkeypatch.setattr(httpx, "post", lambda *a, **k: None)
    assert pk.init(api_key="pk_x", endpoint="http://p.test", batch=False) is True


def test_auto_module_imports_and_is_a_no_op_without_env(monkeypatch):
    _reset()
    monkeypatch.delenv("PROVEKIT_API_KEY", raising=False)
    monkeypatch.delenv("PROVEKIT_ENDPOINT", raising=False)
    import importlib

    import provekit.auto
    importlib.reload(provekit.auto)           # re-runs init() at import; must not raise


def test_decorated_call_ships_a_run_with_input_and_output(monkeypatch):
    _reset()
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None, follow_redirects=None):
        captured.update(url=url, body=json, auth=(headers or {}).get("Authorization"))

    monkeypatch.setattr(httpx, "post", fake_post)
    assert pk.configure(api_key="pk_test", endpoint="http://portal.test", batch=False) is True

    @pk.trace(name="support-agent")
    def run_agent(question):
        return "the capital is Paris"

    assert run_agent("capital of France?") == "the capital is Paris"  # transparent

    assert captured["url"] == "http://portal.test/v1/traces"
    assert captured["auth"] == "Bearer pk_test"

    runs = otel.ingest(captured["body"])
    assert len(runs) == 1
    assert "capital of France?" in runs[0]["request"]["input"]
    assert runs[0]["result"]["text"] == "the capital is Paris"
    assert runs[0]["status"] == "completed"


def test_exception_in_traced_fn_marks_the_run_failed(monkeypatch):
    _reset()
    captured = {}
    monkeypatch.setattr(httpx, "post",
                        lambda url, json=None, headers=None, timeout=None, follow_redirects=None:
                        captured.update(body=json))
    pk.configure(api_key="pk_x", endpoint="http://p.test", batch=False)

    @pk.trace(name="boom")
    def run():
        raise ValueError("kaboom")

    with pytest.raises(ValueError):
        run()

    runs = otel.ingest(captured["body"])
    assert runs and runs[0]["status"] == "failed"


def test_export_failure_never_breaks_the_app(monkeypatch):
    _reset()

    def boom_post(*a, **k):
        raise httpx.ConnectError("portal down")

    monkeypatch.setattr(httpx, "post", boom_post)
    pk.configure(api_key="pk_x", endpoint="http://down.test", batch=False)

    @pk.trace(name="resilient")
    def run():
        return 42

    assert run() == 42     # exporter swallows the transport error; the app is unaffected


def test_attr_encodes_each_scalar_type():
    assert pk._attr(True) == {"boolValue": True}
    assert pk._attr(3) == {"intValue": 3}
    assert pk._attr(1.5) == {"doubleValue": 1.5}
    assert pk._attr("x") == {"stringValue": "x"}
    assert pk._attr({"a": 1}) == {"stringValue": '{"a": 1}'}
    assert "object" in pk._attr(object())["stringValue"]     # non-JSON → str fallback


def test_exporter_shutdown_and_flush_are_safe():
    exp = pk._ProveKitExporter("http://x/v1/traces", "pk_x")
    exp.shutdown()
    assert exp.force_flush() is True


def test_non_string_return_is_json_encoded(monkeypatch):
    _reset()
    captured = {}
    monkeypatch.setattr(httpx, "post",
                        lambda url, json=None, headers=None, timeout=None, follow_redirects=None:
                        captured.update(body=json))
    pk.configure(api_key="pk_x", endpoint="http://p.test", batch=False)

    @pk.trace(name="dict-out")
    def run():
        return {"answer": "Paris"}

    run()
    assert "Paris" in otel.ingest(captured["body"])[0]["result"]["text"]


def test_payload_falls_back_on_unserializable_input(monkeypatch):
    _reset()
    captured = {}
    monkeypatch.setattr(httpx, "post",
                        lambda url, json=None, headers=None, timeout=None, follow_redirects=None:
                        captured.update(body=json))
    pk.configure(api_key="pk_x", endpoint="http://p.test", batch=False)

    circular = {}
    circular["self"] = circular          # json.dumps raises even with default=str → str() fallback

    @pk.trace(name="weird-input")
    def run(_data):
        return "ok"

    run(circular)
    assert otel.ingest(captured["body"])[0]["result"]["text"] == "ok"


def test_nested_spans_form_a_parent_child_tree(monkeypatch):
    _reset()
    bodies = []
    monkeypatch.setattr(httpx, "post",
                        lambda url, json=None, headers=None, timeout=None, follow_redirects=None:
                        bodies.append(json))
    pk.configure(api_key="pk_x", endpoint="http://p.test", batch=False)

    @pk.trace(name="agent")
    def run():
        with pk.span("retrieve"):
            pass
        return "done"

    run()
    spans = [s for b in bodies for rs in b["resourceSpans"] for ss in rs["scopeSpans"] for s in ss["spans"]]
    by_name = {s["name"]: s for s in spans}
    assert "agent" in by_name and "retrieve" in by_name          # one decorator captured both
    assert by_name["retrieve"]["traceId"] == by_name["agent"]["traceId"]      # same trace
    assert by_name["retrieve"]["parentSpanId"] == by_name["agent"]["spanId"]  # nested under it


def test_app_logs_become_span_events(monkeypatch):
    import logging
    _reset()
    bodies = []
    monkeypatch.setattr(httpx, "post",
                        lambda url, json=None, headers=None, timeout=None, follow_redirects=None:
                        bodies.append(json))
    logging.getLogger("myapp").setLevel(logging.INFO)
    pk.configure(api_key="pk_x", endpoint="http://p.test", batch=False, capture_logs=True)

    @pk.trace(name="agent")
    def run():
        logging.getLogger("myapp").info("retrieved 5 docs")
        return "ok"

    run()
    runs = [r for b in bodies for r in otel.ingest(b)]
    agent = next(r for r in runs if r["type"] == "agent")
    events = agent["result"]["meta"].get("events", [])
    assert any("retrieved 5 docs" in e["name"] and e["level"] == "INFO" for e in events)


def test_configure_stays_no_op_if_otel_missing(monkeypatch):
    _reset()
    import builtins
    real_import = builtins.__import__

    def blocked(name, *a, **k):
        if name.startswith("opentelemetry"):
            raise ImportError("no opentelemetry")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", blocked)
    assert pk.configure(api_key="pk_x", endpoint="http://p.test") is False   # degrades, never crashes
