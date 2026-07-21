"""Account quotas. Rate limits bound bursts; these bound totals — the difference between an
instance you can safely open to the public and one anyone can fill."""
from fastapi.testclient import TestClient

from provekit.config import get_settings
from provekit.main import app
from provekit.services import limits


def _client():
    return TestClient(app, base_url="https://testserver")


def _span(trace, sid="r"):
    return {"name": "agent", "traceId": trace, "spanId": sid, "parentSpanId": "",
            "startTimeUnixNano": "1000000000", "endTimeUnixNano": "1200000000",
            "status": {"code": 1}, "attributes": []}


def _otlp(*spans):
    return {"resourceSpans": [{"scopeSpans": [{"spans": list(spans)}]}]}


def test_quotas_are_off_by_default():
    """A self-hosted instance must never start refusing its owner's own data after an upgrade."""
    s = get_settings()
    assert s.monthly_span_quota == 0 and s.max_projects_per_account == 0
    c = _client()
    body = c.get("/api/projects/usage").json()
    assert body["spans"]["limit"] is None      # null, not 0 — the UI renders "unlimited"
    assert body["spans"]["pct"] is None
    assert body["projects"]["limit"] is None


def test_ingest_is_refused_once_the_span_quota_is_reached():
    s = get_settings()
    c = _client()
    uid = c.get("/api/auth/me").json()["id"]
    limits._window().add(limits._span_key(uid), -limits.spans_this_month(uid), 60)  # zero it
    s.monthly_span_quota = 3
    try:
        assert c.post("/v1/traces", json=_otlp(_span("q1", "a"), _span("q1", "b"))).status_code == 200
        used = c.get("/api/projects/usage").json()["spans"]
        assert used["used"] == 2 and used["limit"] == 3 and used["pct"] == 67

        c.post("/v1/traces", json=_otlp(_span("q2", "c"), _span("q2", "d")))   # crosses the line
        r = c.post("/v1/traces", json=_otlp(_span("q3", "e")))
        # 402, not 429: the condition clears at the start of next month, not in a moment, so
        # telling a client to retry shortly would be a lie.
        assert r.status_code == 402
        assert "quota" in r.json()["detail"].lower()
    finally:
        s.monthly_span_quota = 0


def test_a_retried_batch_is_not_charged_twice():
    """Ingest is deduped, so billing the retry would make the quota depend on network luck."""
    s = get_settings()
    c = _client()
    uid = c.get("/api/auth/me").json()["id"]
    limits._window().add(limits._span_key(uid), -limits.spans_this_month(uid), 60)
    s.monthly_span_quota = 1000
    try:
        batch = _otlp(_span("qdup", "z1"), _span("qdup", "z2"))
        c.post("/v1/traces", json=batch)
        first = c.get("/api/projects/usage").json()["spans"]["used"]
        for _ in range(3):
            c.post("/v1/traces", json=batch)       # exporter retries
        assert c.get("/api/projects/usage").json()["spans"]["used"] == first
    finally:
        s.monthly_span_quota = 0


def test_project_count_is_capped():
    """Without this a per-project quota is a formality — you just make another project."""
    s = get_settings()
    c = _client()
    owned = c.get("/api/projects/usage").json()["projects"]["used"]
    s.max_projects_per_account = owned + 1
    try:
        assert c.post("/api/projects", json={"name": "allowed"}).status_code == 200
        r = c.post("/api/projects", json={"name": "one too many"})
        assert r.status_code == 402 and "limited to" in r.json()["detail"]
    finally:
        s.max_projects_per_account = 0


def test_usage_declares_when_it_is_approximate():
    """Without Redis the counters are per-worker and reset on restart. Presenting a soft
    deterrent as a hard guarantee is how an operator gets a surprise bill."""
    body = _client().get("/api/projects/usage").json()
    assert body["approximate"] is (not get_settings().redis_url)
