"""Versioned price table (#9).

The property: a cost figure derived today must still be derivable next year. A single mutable
table meant that editing this file silently restated every historical cost — model prices have
moved 10x inside a year, so that is not a rounding difference.
"""
from fastapi.testclient import TestClient

from provekit.main import app
from provekit.services import otel, pricing


def test_longest_prefix_wins_not_list_order():
    """The old code took the first match, so correctness depended on literal table ordering —
    move "gpt-4o" above "gpt-4o-mini" on some future edit and mini silently prices at ~16x."""
    assert pricing.rates("gpt-4o-mini") == (0.15, 0.60)
    assert pricing.rates("gpt-4o") == (2.50, 10.00)
    assert pricing.rates("gpt-4o-mini-2024-07-18") == (0.15, 0.60)


def test_unknown_model_gets_the_documented_fallback_not_zero():
    """A silent 0.00 reads as "this was free" rather than "we don't know"."""
    assert pricing.rates("some-new-model-9") == (1.00, 3.00)
    assert pricing.estimate("some-new-model-9", 1_000_000, 0) == 1.00


def test_mock_and_empty_models_cost_nothing():
    assert pricing.estimate("mock", 10_000, 10_000) == 0.0
    assert pricing.estimate(None, 10_000, 10_000) == 0.0


def test_estimate_uses_the_requested_version():
    v = pricing.current_version()
    assert pricing.estimate("gpt-4o", 1_000_000, 0, version=v) == 2.50


def test_unknown_version_falls_back_rather_than_raising():
    """A span stamped by a newer deployment must not 500 an older one's dashboard."""
    assert pricing.estimate("gpt-4o", 1_000_000, 0, version="2099-01-01") == 2.50


def test_released_tables_are_never_mutated():
    """Editing a shipped version rewrites history. The 2025-01-01 rates are a fixed record."""
    t = dict((p, (i, o)) for p, i, o in pricing.table("2025-01-01"))
    assert t["gpt-4o"] == (2.50, 10.00)
    assert t["claude-3-opus"] == (15.00, 75.00)


def test_captured_spans_are_stamped_with_the_version():
    """Without the stamp, re-costing a span later applies whatever rates are current now."""
    span = {"name": "chat", "traceId": "aa" * 16, "spanId": "ab" * 8,
            "startTimeUnixNano": "1000000000", "endTimeUnixNano": "1500000000",
            "status": {"code": 1},
            "attributes": [{"key": "gen_ai.request.model", "value": {"stringValue": "gpt-4o"}}]}
    rows = otel.ingest({"resourceSpans": [{"scopeSpans": [{"spans": [span]}]}]})
    assert rows[0]["result"]["meta"]["price_version"] == pricing.current_version()


def test_a_span_with_no_model_is_not_stamped():
    """A tool or step span has no rate to record; stamping it would be noise."""
    span = {"name": "fetch", "traceId": "ac" * 16, "spanId": "ad" * 8,
            "startTimeUnixNano": "1000000000", "endTimeUnixNano": "1500000000",
            "status": {"code": 1},
            "attributes": [{"key": "gen_ai.tool.name", "value": {"stringValue": "fetch"}}]}
    rows = otel.ingest({"resourceSpans": [{"scopeSpans": [{"spans": [span]}]}]})
    assert "price_version" not in rows[0]["result"]["meta"]


def test_rate_card_endpoint_serves_the_table():
    """So the frontend can stop keeping its own copy of these numbers."""
    with TestClient(app) as client:
        body = client.get("/api/pricing").json()
    assert body["version"] == pricing.current_version()
    assert body["fallback"] == {"input": 1.00, "output": 3.00}
    assert any(m["prefix"] == "gpt-4o" and m["input"] == 2.50 for m in body["models"])


def test_rate_card_can_be_asked_for_a_historical_version():
    with TestClient(app) as client:
        body = client.get("/api/pricing", params={"version": "2025-01-01"}).json()
    assert body["version"] == "2025-01-01"
