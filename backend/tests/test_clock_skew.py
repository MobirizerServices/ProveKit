"""Clock-skew defence (#5).

The waterfall positions every bar from client-supplied start times. A machine whose clock is
wrong therefore produces a chart that is confidently, invisibly wrong — children starting
before their parents, spans overlapping that never overlapped — and nothing about it looks
different from a correct one. Detection is what lets the chart say so.
"""
import time

from provekit.services import otel


def _span(end_ns, start_ns=None, sid="aa"):
    start_ns = start_ns if start_ns is not None else end_ns - 500_000_000
    return {"name": "chat", "traceId": "5a" * 16, "spanId": sid * 8,
            "startTimeUnixNano": str(start_ns), "endTimeUnixNano": str(end_ns),
            "status": {"code": 1},
            "attributes": [{"key": "gen_ai.request.model", "value": {"stringValue": "gpt-4o"}}]}


def _otlp(*spans):
    return {"resourceSpans": [{"scopeSpans": [{"spans": list(spans)}]}]}


def test_a_clock_running_ahead_is_flagged():
    now = time.time_ns()
    future = now + 10 * 60 * 1_000_000_000            # ten minutes ahead
    rows = otel.ingest(_otlp(_span(future)), received_ns=now)
    skew = rows[0]["result"]["meta"]["clock_skew_ms"]
    assert 590_000 < skew < 610_000


def test_a_normal_span_is_not_flagged():
    now = time.time_ns()
    rows = otel.ingest(_otlp(_span(now - 1_000_000_000)), received_ns=now)
    assert "clock_skew_ms" not in rows[0]["result"]["meta"]


def test_batching_delay_is_not_mistaken_for_skew():
    """Exporters batch and networks are slow, so a timestamp well in the past is ordinary.
    Flagging it would mark every healthy deployment as broken."""
    now = time.time_ns()
    an_hour_ago = now - 3600 * 1_000_000_000
    rows = otel.ingest(_otlp(_span(an_hour_ago)), received_ns=now)
    assert "clock_skew_ms" not in rows[0]["result"]["meta"]


def test_tolerance_absorbs_small_drift():
    """Just inside the tolerance must stay quiet — a flag has to mean the clock is wrong,
    not that the export was slightly early."""
    now = time.time_ns()
    just_inside = now + (otel.CLOCK_SKEW_TOLERANCE_MS - 5_000) * 1_000_000
    rows = otel.ingest(_otlp(_span(just_inside)), received_ns=now)
    assert "clock_skew_ms" not in rows[0]["result"]["meta"]


def test_malformed_timestamps_do_not_raise():
    span = _span(0)
    span["endTimeUnixNano"] = "not-a-number"
    rows = otel.ingest(_otlp(span), received_ns=time.time_ns())
    assert "clock_skew_ms" not in rows[0]["result"]["meta"]


def test_receipt_time_defaults_to_now():
    """Callers that don't pass one still get detection rather than silently skipping it."""
    future = time.time_ns() + 10 * 60 * 1_000_000_000
    rows = otel.ingest(_otlp(_span(future)))
    assert rows[0]["result"]["meta"]["clock_skew_ms"] > 0
