"""Durable usage metering (#80).

Quotas were enforced from TTL'd counters, which is right for gating and wrong for billing: an
in-memory count dies with the process and the TTL drops the history. Tokens and cost weren't
metered at all. The guarantee that matters most here is that a *retried* export doesn't bill
twice — ingest is retried by every real OTLP exporter.
"""
import time
import uuid

from fastapi.testclient import TestClient

from provekit.database import SessionLocal
from provekit.main import app
from provekit.models import UsageRecord
from provekit.services import usage


def _client():
    return TestClient(app, base_url="https://testserver")


def _account(c) -> str:
    email = f"u{uuid.uuid4().hex[:10]}@ex.com"
    assert c.post("/api/auth/register", json={"email": email, "password": "pw12345678"}).status_code == 200
    return email


def _span(trace: str, sid: str, *, model="gpt-4o", inp=100, out=50):
    now = int(time.time() * 1e9)
    attrs = [{"key": "gen_ai.request.model", "value": {"stringValue": model}}]
    if inp is not None:
        attrs.append({"key": "gen_ai.usage.input_tokens", "value": {"intValue": str(inp)}})
    if out is not None:
        attrs.append({"key": "gen_ai.usage.output_tokens", "value": {"intValue": str(out)}})
    return {"name": "chat", "traceId": trace, "spanId": sid, "parentSpanId": "",
            "startTimeUnixNano": str(now - 10**9), "endTimeUnixNano": str(now),
            "status": {"code": 1}, "attributes": attrs}


def _otlp(*spans):
    return {"resourceSpans": [{"scopeSpans": [{"spans": list(spans)}]}]}


def test_ingest_meters_tokens_and_cost():
    c = _client()
    _account(c)
    key = c.post("/api/workspace/ingest-key").json()["ingest_key"]
    kh = {"Authorization": f"Bearer {key}"}
    t = uuid.uuid4().hex[:32]
    assert c.post("/v1/traces", json=_otlp(_span(t, "aa" * 8)), headers=kh).status_code == 200

    metered = c.get("/api/projects/usage").json()["metered"]
    assert metered["spans"] >= 1
    assert metered["input_tokens"] == 100 and metered["output_tokens"] == 50
    assert metered["cost_usd"] > 0, "a priced model call must cost something"
    assert metered["priced_calls"] == 1 and metered["unpriced_calls"] == 0
    assert metered["usage_coverage"] == 1.0


def test_a_retried_export_is_not_billed_twice():
    """The guarantee that matters: every real exporter retries, and dedupe happens before
    metering, so the ledger prices what was stored rather than what was sent."""
    c = _client()
    _account(c)
    key = c.post("/api/workspace/ingest-key").json()["ingest_key"]
    kh = {"Authorization": f"Bearer {key}"}
    t = uuid.uuid4().hex[:32]
    batch = _otlp(_span(t, "bb" * 8))

    for _ in range(3):                       # the exporter keeps retrying
        assert c.post("/v1/traces", json=batch, headers=kh).status_code == 200

    metered = c.get("/api/projects/usage").json()["metered"]
    assert metered["spans"] == 1, f"a replayed batch was billed more than once: {metered}"
    assert metered["input_tokens"] == 100 and metered["output_tokens"] == 50


def test_a_call_reporting_no_usage_is_counted_but_not_priced():
    """"Cheap" and "nobody reported tokens" are different answers, and an invoice must not
    conflate them."""
    c = _client()
    _account(c)
    key = c.post("/api/workspace/ingest-key").json()["ingest_key"]
    kh = {"Authorization": f"Bearer {key}"}
    t = uuid.uuid4().hex[:32]
    c.post("/v1/traces", json=_otlp(_span(t, "cc" * 8, inp=None, out=None)), headers=kh)

    metered = c.get("/api/projects/usage").json()["metered"]
    assert metered["unpriced_calls"] == 1 and metered["priced_calls"] == 0
    assert metered["cost_usd"] == 0.0
    assert metered["usage_coverage"] == 0.0


def test_the_ledger_survives_a_counter_reset():
    """The whole point of a durable record: quotas are gated from a TTL'd counter, but the bill
    is read from rows that outlive it."""
    c = _client()
    _account(c)
    key = c.post("/api/workspace/ingest-key").json()["ingest_key"]
    kh = {"Authorization": f"Bearer {key}"}
    t = uuid.uuid4().hex[:32]
    c.post("/v1/traces", json=_otlp(_span(t, "dd" * 8)), headers=kh)

    from provekit.services import limits
    limits._window.cache_clear()             # as a restart would

    metered = c.get("/api/projects/usage").json()["metered"]
    assert metered["spans"] >= 1 and metered["cost_usd"] > 0


def test_history_is_per_month_and_newest_first():
    c = _client()
    _account(c)
    key = c.post("/api/workspace/ingest-key").json()["ingest_key"]
    kh = {"Authorization": f"Bearer {key}"}
    t = uuid.uuid4().hex[:32]
    c.post("/v1/traces", json=_otlp(_span(t, "ee" * 8)), headers=kh)

    uid = None
    db = SessionLocal()
    try:
        row = db.query(UsageRecord).order_by(UsageRecord.id.desc()).first()
        uid = row.user_id
        # A second period, so ordering is actually exercised.
        db.add(UsageRecord(user_id=uid, workspace_id=row.workspace_id, period="2000-01",
                           spans=5, input_tokens=1, output_tokens=2, cost_usd=0.5))
        db.commit()
    finally:
        db.close()

    months = c.get("/api/projects/usage/history").json()["months"]
    periods = [m["period"] for m in months]
    assert periods == sorted(periods, reverse=True)
    assert "2000-01" in periods
    old = next(m for m in months if m["period"] == "2000-01")
    assert old["spans"] == 5 and old["tokens"] == 3


def test_measure_prices_only_model_calls():
    rows = [
        {"result": {"meta": {"model": "gpt-4o", "usage": {"input_tokens": 10, "output_tokens": 5}}}},
        {"result": {"meta": {"model": "gpt-4o"}}},                    # no usage reported
        {"result": {"meta": {}}, "request": {}},                      # not a model call at all
    ]
    t = usage.measure(rows)
    assert t["spans"] == 3
    assert t["priced_calls"] == 1 and t["unpriced_calls"] == 1
    assert t["input_tokens"] == 10 and t["output_tokens"] == 5 and t["cost_usd"] > 0


def test_metering_failure_never_breaks_ingest(monkeypatch):
    """An under-counted meter costs one batch of billing; a raised exception costs the
    customer's spans."""
    def boom(*a, **k):
        raise RuntimeError("ledger down")
    monkeypatch.setattr(usage, "measure", boom)
    c = _client()
    _account(c)
    key = c.post("/api/workspace/ingest-key").json()["ingest_key"]
    kh = {"Authorization": f"Bearer {key}"}
    t = uuid.uuid4().hex[:32]
    r = c.post("/v1/traces", json=_otlp(_span(t, "ff" * 8)), headers=kh)
    assert r.status_code == 200, r.text
    assert c.get("/api/traces").status_code == 200
