"""PII redaction: the pure scrubber, and the config-gated masking on ingest."""
from fastapi.testclient import TestClient

from provekit.config import get_settings
from provekit.main import app
from provekit.services import redact


def test_redact_text_masks_common_pii():
    assert redact.redact_text("mail me at joe@acme.com") == "mail me at [REDACTED_EMAIL]"
    assert "[REDACTED_CARD]" in redact.redact_text("card 4111 1111 1111 1111 ok")
    assert "[REDACTED_SSN]" in redact.redact_text("ssn 123-45-6789")
    assert "[REDACTED_KEY]" in redact.redact_text("key sk-ABCDEFGHIJKLMNOP123456")
    assert redact.redact_text(None) is None
    assert redact.redact_text("") == ""


def test_scrub_run_mutates_free_text_fields():
    kw = {"request": {"input": "email a@b.com"}, "result": {"text": "call 123-45-6789"},
          "error": "token sk-ABCDEFGHIJKLMNOP99999"}
    redact.scrub_run(kw)
    assert kw["request"]["input"] == "email [REDACTED_EMAIL]"
    assert "[REDACTED_SSN]" in kw["result"]["text"]
    assert "[REDACTED_KEY]" in kw["error"]


def _span(attrs, trace):
    return {"name": "agent", "traceId": trace, "spanId": "r", "parentSpanId": "",
            "startTimeUnixNano": "1000000000", "endTimeUnixNano": "1500000000", "status": {"code": 1},
            "attributes": [{"key": k, "value": {"stringValue": str(v)}} for k, v in attrs.items()]}


def test_ingest_redacts_when_enabled():
    s = get_settings()
    s.redact_pii = True   # mutate the cached singleton for this test
    try:
        with TestClient(app, base_url="https://testserver") as c:
            c.post("/v1/traces", json={"resourceSpans": [{"scopeSpans": [{"spans": [
                _span({"gen_ai.operation.name": "invoke_agent",
                       "gen_ai.input.messages": "contact joe@acme.com",
                       "gen_ai.output.messages": "ok"}, "t-redact"),
            ]}]}]})
            span = c.get("/api/traces/t-redact").json()[0]
            assert span["request"]["input"] == "contact [REDACTED_EMAIL]"
    finally:
        s.redact_pii = False


def test_ingest_keeps_raw_when_disabled():
    with TestClient(app, base_url="https://testserver") as c:
        c.post("/v1/traces", json={"resourceSpans": [{"scopeSpans": [{"spans": [
            _span({"gen_ai.operation.name": "invoke_agent",
                   "gen_ai.input.messages": "contact joe@acme.com"}, "t-raw"),
        ]}]}]})
        span = c.get("/api/traces/t-raw").json()[0]
        assert "joe@acme.com" in span["request"]["input"]
