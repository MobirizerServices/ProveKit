"""Webhook delivery: the per-host body shape, the on-call credential scheme, and dedup keys."""
from unittest import mock

import httpx
import pytest

from provekit.services import notify

_PD = "https://events.pagerduty.com/v2/enqueue?routing_key=R0EXAMPLE"
_OG = "https://api.opsgenie.com/v2/alerts?apikey=secret-genie-key"
_TEXT = "*[ProveKit] errors* — error_rate is 0.42 (gt 0.1) over the last 24h in project acme."


def _capture():
    """Record the one outbound POST instead of making it."""
    sent = {}

    def _post(url, json=None, headers=None, **kw):
        sent["url"], sent["json"], sent["headers"] = url, json, headers
        return httpx.Response(200)

    return sent, _post


# --- host routing ---------------------------------------------------------------------

def test_kind_is_chosen_by_host():
    assert notify.kind_for(_PD) == "pagerduty"
    assert notify.kind_for("https://events.eu.pagerduty.com/v2/enqueue") == "pagerduty"
    assert notify.kind_for(_OG) == "opsgenie"
    assert notify.kind_for("https://api.eu.opsgenie.com/v2/alerts") == "opsgenie"
    assert notify.kind_for("https://discord.com/api/webhooks/1/x") == "discord"
    assert notify.kind_for("https://hooks.slack.com/services/T/B/x") == "slack"
    assert notify.kind_for("https://example.com/hook") == "slack"      # generic fallback


def test_chat_shapes_are_unchanged():
    """#66's behaviour must survive: Discord rejects a body with neither content nor embeds."""
    assert notify.payload_for("https://discord.com/api/webhooks/1/x", "hi") == {"content": "hi"}
    assert notify.payload_for("https://hooks.slack.com/services/T/B/x", "hi") == {"text": "hi"}
    url, _, headers = notify.request_for("https://example.com/hook?foo=1", "hi")
    assert url == "https://example.com/hook?foo=1"   # a generic URL is posted verbatim
    assert headers == {}


# --- PagerDuty ------------------------------------------------------------------------

def test_pagerduty_body_and_stripped_routing_key():
    url, body, headers = notify.request_for(_PD, _TEXT)
    assert url == "https://events.pagerduty.com/v2/enqueue"   # the key never rides on the wire URL
    assert body["routing_key"] == "R0EXAMPLE"
    assert body["event_action"] == "trigger"
    assert body["payload"] == {"summary": _TEXT, "severity": "error", "source": "provekit"}
    assert body["dedup_key"]
    assert headers == {}


def test_pagerduty_severity_is_optional_and_validated():
    _, body, _ = notify.request_for(_PD + "&severity=critical", _TEXT)
    assert body["payload"]["severity"] == "critical"
    with pytest.raises(ValueError, match="severity"):
        notify.request_for(_PD + "&severity=catastrophic", _TEXT)


def test_pagerduty_without_a_routing_key_says_exactly_what_is_missing():
    """The one field a rule has is the URL, so a wrong URL is the whole failure mode: the
    error has to name the parameter and show the shape, not just fail the POST."""
    with pytest.raises(ValueError) as exc:
        notify.request_for("https://events.pagerduty.com/v2/enqueue", _TEXT)
    assert "routing_key" in str(exc.value)
    assert "events.pagerduty.com" in str(exc.value)


def test_pagerduty_summary_is_truncated_to_the_api_limit():
    _, body, _ = notify.request_for(_PD, "x" * 2000)
    assert len(body["payload"]["summary"]) == 1024


# --- Opsgenie -------------------------------------------------------------------------

def test_opsgenie_body_alias_and_auth_header():
    url, body, headers = notify.request_for(_OG, _TEXT)
    assert url == "https://api.opsgenie.com/v2/alerts"
    assert headers == {"Authorization": "GenieKey secret-genie-key"}
    assert body["message"] == _TEXT             # short enough to pass through whole
    assert body["description"] == _TEXT
    assert body["alias"]
    assert "priority" not in body               # omitted unless asked for


def test_opsgenie_long_message_is_capped_but_description_keeps_everything():
    long = "y" * 400
    _, body, _ = notify.request_for(_OG, long)
    assert len(body["message"]) == 130          # Opsgenie rejects anything longer
    assert body["description"] == long


def test_opsgenie_priority_is_optional_and_validated():
    _, body, _ = notify.request_for(_OG + "&priority=p1", _TEXT)
    assert body["priority"] == "P1"
    with pytest.raises(ValueError, match="priority"):
        notify.request_for(_OG + "&priority=P9", _TEXT)


def test_opsgenie_accepts_either_spelling_of_the_key_param():
    _, _, headers = notify.request_for("https://api.eu.opsgenie.com/v2/alerts?api_key=k", _TEXT)
    assert headers["Authorization"] == "GenieKey k"


def test_opsgenie_without_a_key_says_exactly_what_is_missing():
    with pytest.raises(ValueError) as exc:
        notify.request_for("https://api.opsgenie.com/v2/alerts", _TEXT)
    assert "apikey" in str(exc.value)


# --- URL handling ---------------------------------------------------------------------

def test_unrelated_query_params_survive_the_strip():
    url, _, _ = notify.request_for(_PD + "&team=payments", _TEXT)
    assert url == "https://events.pagerduty.com/v2/enqueue?team=payments"


def test_credentials_never_appear_in_an_error_message():
    """Errors reach logs; a routing key or GenieKey in one is a leaked secret."""
    with pytest.raises(ValueError) as exc:
        notify.request_for(_PD + "&severity=bogus", _TEXT)
    assert "R0EXAMPLE" not in str(exc.value)
    with pytest.raises(ValueError) as exc:
        notify.request_for(_OG + "&priority=P9", _TEXT)
    assert "secret-genie-key" not in str(exc.value)


# --- deduplication --------------------------------------------------------------------

def test_dedup_key_is_stable_across_breaches_of_one_rule():
    """Twenty breaches of the same rule must fold into one incident, not twenty pages."""
    first = notify.dedup_key_for("*[ProveKit] errors* — error_rate is 0.42 (gt 0.1) over 24h in acme.")
    later = notify.dedup_key_for("*[ProveKit] errors* — error_rate is 0.91 (gt 0.1) over 24h in acme.")
    assert first == later


def test_dedup_key_differs_between_rules_and_projects():
    base = "*[ProveKit] {n}* — error_rate is 0.42 (gt 0.1) over 24h in project {p}."
    assert notify.dedup_key_for(base.format(n="errors", p="acme")) != \
        notify.dedup_key_for(base.format(n="latency", p="acme"))
    assert notify.dedup_key_for(base.format(n="errors", p="acme")) != \
        notify.dedup_key_for(base.format(n="errors", p="beta"))


def test_an_explicit_dedup_key_wins():
    _, pd, _ = notify.request_for(_PD, _TEXT, dedup_key="alert-7")
    _, og, _ = notify.request_for(_OG, _TEXT, dedup_key="alert-7")
    assert pd["dedup_key"] == og["alias"] == "alert-7"


# --- send_webhook ---------------------------------------------------------------------

def test_send_webhook_posts_the_pagerduty_shape():
    sent, post = _capture()
    with mock.patch("provekit.services.notify.httpx.post", post):
        assert notify.send_webhook(_PD, _TEXT) is True
    assert sent["url"] == "https://events.pagerduty.com/v2/enqueue"
    assert sent["json"]["routing_key"] == "R0EXAMPLE"
    assert sent["headers"] is None


def test_send_webhook_posts_the_opsgenie_shape():
    sent, post = _capture()
    with mock.patch("provekit.services.notify.httpx.post", post):
        assert notify.send_webhook(_OG, _TEXT) is True
    assert sent["headers"]["Authorization"] == "GenieKey secret-genie-key"
    assert sent["json"]["message"]


def test_a_misconfigured_on_call_url_fails_delivery_without_raising():
    """A rule that pages nobody must still report as undelivered, not blow up the alert run."""
    calls = []
    with mock.patch("provekit.services.notify.httpx.post", lambda *a, **k: calls.append(a)):
        assert notify.send_webhook("https://events.pagerduty.com/v2/enqueue", _TEXT) is False
    assert calls == []                          # nothing was sent at all


def test_send_webhook_still_ssrf_guards_the_destination():
    """An alert destination is user-supplied; the metadata endpoint is blocked everywhere."""
    calls = []
    with mock.patch("provekit.services.notify.httpx.post", lambda *a, **k: calls.append(a)):
        assert notify.send_webhook("http://169.254.169.254/v2/enqueue?routing_key=k", _TEXT) is False
        assert notify.send_webhook("", _TEXT) is False
    assert calls == []


def test_a_rejecting_receiver_is_reported_as_undelivered():
    with mock.patch("provekit.services.notify.httpx.post",
                    lambda *a, **k: httpx.Response(402, text="bad routing key")):
        assert notify.send_webhook(_PD, _TEXT) is False
