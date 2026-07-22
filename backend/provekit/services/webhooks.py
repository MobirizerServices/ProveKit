"""Outbound webhooks — push events to customer systems.

Alerts could already POST to a webhook (#66), but only when an alert rule breached. Everything
else a customer might want to react to — a trace failed, an experiment finished — was only
observable by polling, so an integration either polled too often or found out too late.

Three properties this has to get right, because a webhook sender is a small piece of code with
a large blast radius:

- **Signed.** The receiver has no other way to know a POST is genuinely from ProveKit. An
  unsigned endpoint is a way for anyone who learns the URL to inject fabricated events into a
  customer's system, and "a trace failed" is exactly the sort of event that triggers something.
  HMAC-SHA256 over the raw body, in `X-ProveKit-Signature`, with the timestamp signed too so a
  captured delivery can't be replayed indefinitely.

- **Backed off, and eventually stopped.** A dead endpoint retried forever is an outbound DoS
  the customer is paying for, and it is *our* egress. Consecutive failures disable the
  subscription, and the reason is recorded so they can see why it stopped rather than
  discovering silence.

- **Guarded.** The URL is user-supplied and we fetch it, which is SSRF by construction — so it
  goes through `netguard`, exactly like alert webhooks and replay callbacks.

Delivery is best-effort and never blocks the thing that produced the event. An ingest that
fails because a customer's webhook is slow would make this feature strictly worse than polling.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
import time
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..models import WebhookSubscription

log = logging.getLogger("provekit.webhooks")

#: Events a subscription may ask for. An allowlist so a typo is rejected at save time rather
#: than producing a subscription that silently never fires.
EVENTS = ("trace.completed", "trace.failed", "experiment.finished", "alert.fired")

#: Consecutive failures before a subscription is disabled.
MAX_FAILURES = 10

SIGNATURE_HEADER = "X-ProveKit-Signature"
TIMESTAMP_HEADER = "X-ProveKit-Timestamp"


def new_secret() -> str:
    return secrets.token_hex(24)


def sign(secret: str, timestamp: str, body: bytes) -> str:
    """`v1=<hex>` over "timestamp.body".

    The timestamp is inside the signed material so a receiver can reject an old delivery; if
    only the body were signed, a captured POST would stay valid forever.
    """
    mac = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256)
    return "v1=" + mac.hexdigest()


def verify(secret: str, timestamp: str, body: bytes, signature: str, *,
           tolerance_seconds: int = 300) -> bool:
    """Receiver-side check, shipped so integrators don't have to guess at it.

    Compared with `compare_digest`: a naive `==` leaks the correct prefix through timing, which
    is enough to forge a signature given patience.
    """
    try:
        if abs(time.time() - float(timestamp)) > tolerance_seconds:
            return False
    except (TypeError, ValueError):
        return False
    return hmac.compare_digest(sign(secret, timestamp, body), signature or "")


def subscriptions_for(db: Session, workspace_id: int, event: str) -> list[WebhookSubscription]:
    rows = (db.query(WebhookSubscription)
            .filter(WebhookSubscription.workspace_id == workspace_id,
                    WebhookSubscription.enabled.is_(True)).all())
    return [r for r in rows if event in (r.events or [])]


def deliver(db: Session, sub: WebhookSubscription, event: str, payload: dict) -> bool:
    """POST one event. Returns whether the receiver accepted it.

    Never raises: this runs off the back of something the user actually asked for (an ingest,
    an experiment), and a customer's broken endpoint must not fail that.
    """
    import httpx

    from . import netguard
    body = json.dumps({"event": event, "workspace_id": sub.workspace_id,
                       "sent_at": time.time(), "data": payload},
                      sort_keys=True).encode()
    ts = f"{time.time():.0f}"
    ok, status = False, ""
    try:
        netguard.guard_url(sub.url)          # user-supplied destination; SSRF guard
        r = httpx.post(sub.url, content=body, timeout=5, follow_redirects=False,
                       headers={"Content-Type": "application/json",
                                TIMESTAMP_HEADER: ts,
                                SIGNATURE_HEADER: sign(sub.secret, ts, body)})
        ok = r.status_code < 400
        status = f"HTTP {r.status_code}"
    except Exception as exc:                 # network, DNS, SSRF refusal — all the same here
        status = f"{type(exc).__name__}: {exc}"[:120]

    sub.last_status = status[:120]
    sub.last_attempt_at = datetime.now(timezone.utc)
    if ok:
        sub.failures = 0
    else:
        sub.failures = (sub.failures or 0) + 1
        if sub.failures >= MAX_FAILURES:
            # Stop rather than retry forever. Recorded, so the reason is visible instead of the
            # subscription just going quiet.
            sub.enabled = False
            sub.last_status = f"disabled after {sub.failures} failures — {status}"[:120]
            log.warning("webhook %s disabled after %d failures", sub.id, sub.failures)
    return ok


def emit(db: Session, workspace_id: int, event: str, payload: dict) -> int:
    """Fan an event out to every matching subscription. Returns how many were accepted.

    Best-effort by contract — the caller is a request path that has already done the work the
    user cared about.
    """
    if event not in EVENTS:
        return 0
    delivered = 0
    try:
        subs = subscriptions_for(db, workspace_id, event)
        for sub in subs:
            delivered += 1 if deliver(db, sub, event, payload) else 0
        if subs:
            db.commit()
    except Exception:
        log.exception("webhook fan-out failed for %s", event)
        db.rollback()
    return delivered
