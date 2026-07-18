"""The wedge, as a regression test: one @pk.trace + auto-instrumentation captures a real
OpenAI SDK call as a nested span, with no tracing code on the call. A local mock serves the
completion, so no API key or network is needed. Skips if the optional deps aren't installed."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

pytest.importorskip("openai")
pytest.importorskip("openinference.instrumentation.openai")

import provekit.trace as pk  # noqa: E402
from opentelemetry.sdk.trace.export import SpanExportResult  # noqa: E402


class _MockOpenAI(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.dumps({
            "id": "chatcmpl-mock", "object": "chat.completion", "created": 0, "model": "gpt-4o-mini",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "Paris."}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 7, "total_tokens": 19},
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def test_openai_call_auto_nests_under_the_decorator(monkeypatch):
    pk._configured = False
    pk._tracer = None
    captured = []
    monkeypatch.setattr(pk._ProveKitExporter, "export",
                        lambda self, spans: (captured.extend(spans), SpanExportResult.SUCCESS)[1])

    srv = HTTPServer(("127.0.0.1", 0), _MockOpenAI)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        assert pk.configure(api_key="pk_x", endpoint="http://portal.test", batch=False)
        from openai import OpenAI
        client = OpenAI(api_key="sk-fake", base_url=f"http://127.0.0.1:{port}/v1")

        @pk.trace(name="qa-agent")
        def run(q):
            # no tracing code here — the OpenAI call instruments itself
            return client.chat.completions.create(
                model="gpt-4o-mini", messages=[{"role": "user", "content": q}]).choices[0].message.content

        assert run("capital of France?") == "Paris."
    finally:
        srv.shutdown()

    by_name = {s.name: s for s in captured}
    agent = by_name.get("qa-agent")
    llm = next((s for s in captured if s is not agent and s.parent), None)
    assert agent is not None and llm is not None, f"expected agent + a child span, got {list(by_name)}"
    # the auto-instrumented OpenAI span nests under the decorated entrypoint
    assert llm.parent.span_id == agent.context.span_id
