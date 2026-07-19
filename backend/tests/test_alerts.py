"""Alerts: CRUD, threshold evaluation, cooldown, and validation."""
from fastapi.testclient import TestClient

from provekit.main import app


def _fail(trace):
    return {"name": "agent", "traceId": trace, "spanId": "r", "parentSpanId": "",
            "startTimeUnixNano": "1000000000", "endTimeUnixNano": "1500000000", "status": {"code": 2},
            "attributes": [{"key": "gen_ai.operation.name", "value": {"stringValue": "invoke_agent"}}]}


def _client():
    return TestClient(app, base_url="https://testserver")


def test_alert_fires_on_breach_then_cooled_down():
    c = _client()
    c.post("/v1/traces", json={"resourceSpans": [{"scopeSpans": [{"spans": [_fail("al-1")]}]}]})
    a = c.post("/api/alerts", json={"name": "errors", "metric": "error_rate",
                                    "comparator": "gt", "threshold": 0.0, "window_hours": 24}).json()
    fired = c.post("/api/alerts/check").json()["fired"]
    assert any(f["id"] == a["id"] for f in fired)          # breached → fired
    # last_triggered recorded; a second check within the window is cooled down
    again = c.post("/api/alerts/check").json()["fired"]
    assert not any(f["id"] == a["id"] for f in again)
    row = next(x for x in c.get("/api/alerts").json() if x["id"] == a["id"])
    assert row["last_triggered_at"] is not None


def test_alert_does_not_fire_when_not_breached():
    c = _client()
    a = c.post("/api/alerts", json={"metric": "trace_count", "comparator": "gt",
                                    "threshold": 1_000_000, "window_hours": 24}).json()
    fired = c.post("/api/alerts/check").json()["fired"]
    assert not any(f["id"] == a["id"] for f in fired)


def test_disabled_alert_is_skipped_and_toggle_works():
    c = _client()
    a = c.post("/api/alerts", json={"metric": "error_count", "comparator": "gt",
                                    "threshold": -1, "window_hours": 24, "enabled": False}).json()
    assert not c.post("/api/alerts/check").json()["fired"]
    c.patch(f"/api/alerts/{a['id']}", json={"enabled": True})
    # now enabled and threshold -1 (always breached) → fires
    assert any(f["id"] == a["id"] for f in c.post("/api/alerts/check").json()["fired"])


def test_validation_and_delete():
    c = _client()
    assert c.post("/api/alerts", json={"metric": "bogus"}).status_code == 422
    assert c.post("/api/alerts", json={"metric": "error_rate", "comparator": "x"}).status_code == 422
    a = c.post("/api/alerts", json={"metric": "error_rate"}).json()
    assert c.delete(f"/api/alerts/{a['id']}").json()["ok"] is True
    assert c.delete(f"/api/alerts/{a['id']}").status_code == 404
