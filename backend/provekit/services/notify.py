"""Outbound alert delivery to a chat webhook (Slack, Discord, or anything Slack-shaped).

Email alone doesn't reach anyone who is on call. This posts the same breach message to an
incoming-webhook URL the project configures.

Slack and Discord disagree on the body key — Slack reads `text`, Discord reads `content` and
rejects a body that has neither — so the shape is chosen by host. Anything unrecognised gets
Slack's shape, which is what most Slack-compatible receivers expect.
"""
from __future__ import annotations

import logging
from urllib.parse import urlparse

import httpx

from .netguard import guard_url

log = logging.getLogger(__name__)

_TIMEOUT = 5
_DISCORD_HOSTS = ("discord.com", "discordapp.com")


def payload_for(url: str, text: str) -> dict:
    host = (urlparse(url).hostname or "").lower()
    if any(host == h or host.endswith("." + h) for h in _DISCORD_HOSTS):
        return {"content": text}
    return {"text": text}


def send_webhook(url: str, text: str) -> bool:
    """POST a breach message to a chat webhook. Returns whether it was delivered.

    Never raises. A misconfigured or dead webhook must not abort the alert run that found a
    real breach — the other rules still need to fire, and the breach is already recorded.
    """
    if not url:
        return False
    try:
        guard_url(url)          # the URL is user-supplied and fetched server-side
        resp = httpx.post(url, json=payload_for(url, text), timeout=_TIMEOUT,
                          follow_redirects=False)
    except Exception as exc:
        log.warning("alert webhook failed: %s", exc)
        return False
    if resp.status_code >= 400:
        log.warning("alert webhook rejected with %s: %s", resp.status_code, resp.text[:200])
        return False
    return True
