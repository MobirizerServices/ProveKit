"""Outbound alert delivery to a webhook — chat (Slack, Discord) or on-call (PagerDuty, Opsgenie).

Email alone doesn't reach anyone who is on call. This posts the same breach message to an
incoming-webhook URL the project configures.

Receivers disagree on the body key — Slack reads `text`, Discord reads `content` and rejects a
body that has neither — so the shape is chosen by host. Anything unrecognised gets Slack's
shape, which is what most Slack-compatible receivers expect.

## On-call destinations

An alert rule carries exactly one field, `webhook_url`. PagerDuty and Opsgenie both need a
credential that isn't part of their endpoint path, so it rides in the URL's query string and is
stripped back out before the request is sent (it goes in the body or an auth header instead):

    PagerDuty   https://events.pagerduty.com/v2/enqueue?routing_key=R0XXXXXXXXXXXXXXXXXXXXXXXXX
                (also events.eu.pagerduty.com; optional &severity=critical|error|warning|info)

    Opsgenie    https://api.opsgenie.com/v2/alerts?apikey=<GenieKey>
                (also api.eu.opsgenie.com; optional &priority=P1..P5)

Any other query parameter is left on the request untouched. Getting the scheme wrong is the
failure that pages nobody, so a missing credential raises with the full example above rather
than posting a body the vendor will silently 400.

The credential is stored with the same sensitivity as the URL it arrived in — a Slack webhook
URL is already a bearer secret, so this adds no new class of stored secret and no new column.

## Deduplication

PagerDuty (`dedup_key`) and Opsgenie (`alias`) fold repeat events into one open incident. The
key has to be stable for a rule across breaches but differ between rules, and the only input
here is the message — whose one varying part is the measured value. So the key hashes the
message with every number masked: same rule, same key; twentieth breach, still one incident.
Two rules that differ *only* by a numeric threshold (same name, same metric) share a key —
name them apart, or pass `dedup_key` explicitly once the caller has the rule id.
"""
from __future__ import annotations

import hashlib
import logging
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from .netguard import guard_url

log = logging.getLogger(__name__)

_TIMEOUT = 5
_DISCORD_HOSTS = ("discord.com", "discordapp.com")
_PAGERDUTY_HOSTS = ("events.pagerduty.com", "events.eu.pagerduty.com")
_OPSGENIE_HOSTS = ("api.opsgenie.com", "api.eu.opsgenie.com")

# Query params ProveKit consumes as configuration. Only stripped for the hosts that define
# them, so a chat webhook whose URL happens to carry one still arrives intact.
_CONFIG_KEYS = {"routing_key", "apikey", "api_key", "severity", "priority"}

_PD_SEVERITIES = ("critical", "error", "warning", "info")
_OG_PRIORITIES = ("P1", "P2", "P3", "P4", "P5")
# PagerDuty's payload.source is required and identifies the emitting system, not the rule.
_SOURCE = "provekit"
_PD_SUMMARY_MAX = 1024
_OG_MESSAGE_MAX = 130   # Opsgenie rejects a longer message outright

_PD_HELP = ("PagerDuty webhook URL must carry the Events API v2 integration routing key as a "
            "query parameter, e.g. https://events.pagerduty.com/v2/enqueue?routing_key=R0XXXXXXXX")
_OG_HELP = ("Opsgenie webhook URL must carry the API key as a query parameter, e.g. "
            "https://api.opsgenie.com/v2/alerts?apikey=00000000-0000-0000-0000-000000000000")

_NUMBERS = re.compile(r"\d[\d.,]*")


def _matches(host: str, hosts: tuple[str, ...]) -> bool:
    return any(host == h or host.endswith("." + h) for h in hosts)


def kind_for(url: str) -> str:
    """Which receiver dialect a URL speaks. 'slack' is the fallback for anything unrecognised."""
    host = (urlsplit(url).hostname or "").lower()
    if _matches(host, _PAGERDUTY_HOSTS):
        return "pagerduty"
    if _matches(host, _OPSGENIE_HOSTS):
        return "opsgenie"
    if _matches(host, _DISCORD_HOSTS):
        return "discord"
    return "slack"


def _split_config(url: str) -> tuple[str, dict[str, str]]:
    """Peel ProveKit's config params off the query, returning (url to POST, config)."""
    parts = urlsplit(url)
    kept: list[tuple[str, str]] = []
    cfg: dict[str, str] = {}
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key.lower() in _CONFIG_KEYS:
            cfg[key.lower()] = value.strip()
        else:
            kept.append((key, value))
    return urlunsplit(parts._replace(query=urlencode(kept))), cfg


def dedup_key_for(text: str) -> str:
    """A key that is stable across breaches of one rule — see the module docstring."""
    return "provekit-" + hashlib.sha256(_NUMBERS.sub("#", text).encode()).hexdigest()[:16]


def request_for(url: str, text: str, dedup_key: str = "") -> tuple[str, dict, dict]:
    """Build (url to POST, JSON body, extra headers) for whichever receiver `url` points at.

    Raises ValueError when an on-call destination is missing or misusing its credential —
    the caller decides whether that surfaces as a form error or a failed delivery.
    """
    kind = kind_for(url)
    key = dedup_key or dedup_key_for(text)

    if kind == "pagerduty":
        post_url, cfg = _split_config(url)
        routing_key = cfg.get("routing_key", "")
        if not routing_key:
            raise ValueError(_PD_HELP)
        severity = cfg.get("severity") or "error"
        if severity not in _PD_SEVERITIES:
            raise ValueError(f"PagerDuty severity must be one of {list(_PD_SEVERITIES)}, got '{severity}'")
        return post_url, {
            "routing_key": routing_key,
            "event_action": "trigger",
            "dedup_key": key,
            "payload": {"summary": text[:_PD_SUMMARY_MAX], "severity": severity, "source": _SOURCE},
        }, {}

    if kind == "opsgenie":
        post_url, cfg = _split_config(url)
        api_key = cfg.get("apikey") or cfg.get("api_key") or ""
        if not api_key:
            raise ValueError(_OG_HELP)
        body = {"message": text[:_OG_MESSAGE_MAX], "description": text, "alias": key}
        priority = cfg.get("priority", "").upper()
        if priority:
            if priority not in _OG_PRIORITIES:
                raise ValueError(f"Opsgenie priority must be one of {list(_OG_PRIORITIES)}, got '{priority}'")
            body["priority"] = priority
        return post_url, body, {"Authorization": f"GenieKey {api_key}"}

    if kind == "discord":
        return url, {"content": text}, {}
    return url, {"text": text}, {}


def payload_for(url: str, text: str) -> dict:
    """Just the JSON body — the request shape without the routing details."""
    return request_for(url, text)[1]


def send_webhook(url: str, text: str, dedup_key: str = "") -> bool:
    """POST a breach message to an alert webhook. Returns whether it was delivered.

    Never raises. A misconfigured or dead webhook must not abort the alert run that found a
    real breach — the other rules still need to fire, and the breach is already recorded.
    """
    if not url:
        return False
    try:
        guard_url(url)          # the URL is user-supplied and fetched server-side
        post_url, body, headers = request_for(url, text, dedup_key)
        resp = httpx.post(post_url, json=body, headers=headers or None, timeout=_TIMEOUT,
                          follow_redirects=False)
    except Exception as exc:
        log.warning("alert webhook failed: %s", exc)
        return False
    if resp.status_code >= 400:
        log.warning("alert webhook rejected with %s: %s", resp.status_code, resp.text[:200])
        return False
    return True
