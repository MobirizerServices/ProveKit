"""Alerts: CRUD, threshold evaluation, cooldown, and validation."""
from unittest import mock

import httpx
from fastapi.testclient import TestClient

from provekit.main import app
from provekit.services import notify


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


def test_webhook_url_is_ssrf_guarded_at_creation():
    """The URL is user-supplied and fetched server-side. Rejecting it at creation also means
    the operator learns it's wrong while looking at the form, not via a silent 3am breach.

    Local mode deliberately permits localhost (it's a dev tool), so only the always-blocked
    cases apply here; the private-range policy is asserted in hosted mode below."""
    c = _client()
    for bad in ("http://169.254.169.254/latest/meta-data", "file:///etc/passwd"):
        r = c.post("/api/alerts", json={"metric": "error_rate", "webhook_url": bad})
        assert r.status_code == 422, f"{bad} should be rejected"


    # The hosted-mode private-range policy itself is asserted in test_netguard.py; the cases
    # above are enough to prove alert creation actually routes through the guard.


def test_breach_posts_to_the_webhook():
    c = _client()
    c.post("/v1/traces", json={"resourceSpans": [{"scopeSpans": [{"spans": [_fail("al-hook")]}]}]})
    sent = {}

    def _fake_post(url, json=None, **kw):
        sent["url"], sent["json"] = url, json
        return httpx.Response(200)

    with mock.patch("provekit.services.notify.httpx.post", _fake_post):
        a = c.post("/api/alerts", json={"name": "errs", "metric": "error_rate", "comparator": "gt",
                                        "threshold": 0.0,
                                        "webhook_url": "https://hooks.slack.com/services/T/B/x"}).json()
        fired = c.post("/api/alerts/check").json()["fired"]
    hit = next(f for f in fired if f["id"] == a["id"])
    assert hit["webhook_delivered"] is True
    assert sent["url"].startswith("https://hooks.slack.com/")
    assert "error_rate" in sent["json"]["text"]          # Slack shape


def test_discord_gets_content_not_text():
    """Discord rejects a body with neither `content` nor `embeds`, so the shape is per-host."""
    assert "content" in notify.payload_for("https://discord.com/api/webhooks/1/x", "hi")
    assert "content" in notify.payload_for("https://ptb.discord.com/api/webhooks/1/x", "hi")
    assert "text" in notify.payload_for("https://hooks.slack.com/services/T/B/x", "hi")


def test_a_dead_webhook_does_not_abort_the_alert_run():
    """A breach is already recorded when delivery is attempted; a broken webhook must not
    swallow the fired-list or stop later rules from evaluating."""
    c = _client()
    c.post("/v1/traces", json={"resourceSpans": [{"scopeSpans": [{"spans": [_fail("al-dead")]}]}]})

    def _boom(url, json=None, **kw):
        raise httpx.ConnectError("no route to host")

    with mock.patch("provekit.services.notify.httpx.post", _boom):
        a = c.post("/api/alerts", json={"metric": "error_rate", "comparator": "gt", "threshold": 0.0,
                                        "webhook_url": "https://hooks.slack.com/services/T/B/y"}).json()
        fired = c.post("/api/alerts/check").json()["fired"]
    hit = next(f for f in fired if f["id"] == a["id"])
    assert hit["webhook_delivered"] is False            # reported, not raised
