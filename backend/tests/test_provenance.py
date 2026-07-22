"""Redaction provenance (#8) and the truncation policy (#6).

Both answer the same question: when what you're reading isn't what the agent produced, the
product has to say so. An observability tool that quietly alters a payload and renders it
like an untouched one has turned itself into a source of confident wrong answers.
"""
from fastapi.testclient import TestClient

from provekit.database import SessionLocal
from provekit.main import app
from provekit.models import Run, Workspace
from provekit.services import otel, redact

from conftest import ingest_workspace_id


def _span(i, prompt="", completion=""):
    attrs = [{"key": "gen_ai.request.model", "value": {"stringValue": "gpt-4o"}}]
    if prompt:
        attrs.append({"key": "gen_ai.prompt", "value": {"stringValue": prompt}})
    if completion:
        attrs.append({"key": "gen_ai.completion", "value": {"stringValue": completion}})
    return {"name": "chat", "traceId": f"{i:032x}", "spanId": f"{i:016x}",
            "startTimeUnixNano": "1000000000", "endTimeUnixNano": "1500000000",
            "status": {"code": 1}, "attributes": attrs}


def _otlp(*spans):
    return {"resourceSpans": [{"scopeSpans": [{"spans": list(spans)}]}]}


# -- #8 redaction provenance -----------------------------------------------------------------

def test_masked_span_records_what_was_masked():
    row = redact.scrub_run({
        "request": {"input": "mail alice@example.com or bob@example.com"},
        "result": {"text": "ok", "meta": {}}, "error": ""})
    prov = row["result"]["meta"]["redaction"]
    assert prov["fields"] == ["input"]
    assert prov["counts"]["input"]["EMAIL"] == 2


def test_untouched_span_carries_no_marker():
    """A badge on every span would be noise, and would stop meaning anything."""
    row = redact.scrub_run({"request": {"input": "nothing sensitive here"},
                            "result": {"text": "fine", "meta": {}}, "error": ""})
    assert "redaction" not in row["result"]["meta"]


def test_provenance_covers_output_and_error_too():
    row = redact.scrub_run({
        "request": {"input": "plain"},
        "result": {"text": "card 4111 1111 1111 1111", "meta": {}},
        "error": "failed for user@corp.io"})
    assert set(row["result"]["meta"]["redaction"]["fields"]) == {"output", "error"}


def test_a_false_positive_is_attributable():
    """The PHONE rule eats long digit runs. When it mangles a real output the result looks
    like a model producing nonsense — the marker is what makes it traceable to the masker."""
    row = redact.scrub_run({"request": {"input": "order 1234567890123 shipped"},
                            "result": {"text": "", "meta": {}}, "error": ""})
    assert "[REDACTED_" in row["request"]["input"]
    assert row["result"]["meta"]["redaction"]["counts"]["input"]      # and we said we did it


def test_provenance_survives_ingest():
    ws_id = ingest_workspace_id()
    db = SessionLocal()
    ws = db.query(Workspace).filter(Workspace.id == ws_id).first()
    prev = ws.redact_pii
    ws.redact_pii = True
    db.commit()
    db.close()
    try:
        with TestClient(app) as client:
            client.post("/v1/traces", json=_otlp(_span(0x7101, prompt="ping me at a@b.co")))
        db = SessionLocal()
        row = db.query(Run).filter(Run.trace_id == f"{0x7101:032x}").first()
        meta = (row.result or {}).get("meta") or {}
        db.close()
        assert meta.get("redaction", {}).get("fields") == ["input"]
    finally:
        db = SessionLocal()
        db.query(Workspace).filter(Workspace.id == ws_id).first().redact_pii = prev
        db.commit()
        db.close()


# -- #6 truncation policy --------------------------------------------------------------------

def test_oversized_payload_is_cut_at_the_documented_boundary_and_marked():
    big = "x" * (otel.MAX_PAYLOAD_CHARS + 500)
    rows = otel.ingest(_otlp(_span(0x7201, prompt=big)))
    row = rows[0]
    assert len(row["request"]["input"]) == otel.MAX_PAYLOAD_CHARS
    marker = row["result"]["meta"]["truncation"]["input"]
    assert marker["stored_chars"] == otel.MAX_PAYLOAD_CHARS
    assert marker["original_chars"] == otel.MAX_PAYLOAD_CHARS + 500


def test_output_truncation_is_marked_separately():
    big = "y" * (otel.MAX_PAYLOAD_CHARS + 1)
    rows = otel.ingest(_otlp(_span(0x7202, prompt="short", completion=big)))
    trunc = rows[0]["result"]["meta"]["truncation"]
    assert "output" in trunc and "input" not in trunc


def test_payload_within_the_boundary_is_untouched_and_unmarked():
    rows = otel.ingest(_otlp(_span(0x7203, prompt="a modest prompt", completion="a reply")))
    row = rows[0]
    assert row["request"]["input"] == "a modest prompt"
    assert "truncation" not in row["result"]["meta"]
