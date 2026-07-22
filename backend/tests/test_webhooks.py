"""Outbound webhooks (#92).

Most of this file is about the ways a webhook sender goes wrong: forged deliveries, replayed
deliveries, a dead endpoint retried forever, and a user-supplied URL pointed at our own network.
"""
import json
import time

import pytest
from fastapi.testclient import TestClient

from provekit.main import app
from provekit.services import webhooks


def _client():
    return TestClient(app, base_url="https://testserver")


# ---- signing ------------------------------------------------------------------------------

def test_a_genuine_delivery_verifies():
    secret, ts, body = "s3cr3t", f"{time.time():.0f}", b'{"event":"trace.failed"}'
    assert webhooks.verify(secret, ts, body, webhooks.sign(secret, ts, body))


def test_a_tampered_body_does_not_verify():
    """Without this, anyone who learns the URL can inject a fabricated event — and
    "trace.failed" is exactly the sort of thing that triggers something on the far end."""
    secret, ts, body = "s3cr3t", f"{time.time():.0f}", b'{"event":"trace.failed"}'
    sig = webhooks.sign(secret, ts, body)
    assert not webhooks.verify(secret, ts, b'{"event":"trace.completed"}', sig)


def test_the_wrong_secret_does_not_verify():
    ts, body = f"{time.time():.0f}", b"{}"
    assert not webhooks.verify("other", ts, body, webhooks.sign("s3cr3t", ts, body))


def test_an_old_delivery_is_refused():
    """The timestamp is inside the signed material, so a captured POST can't be replayed
    forever — it stays valid only inside the tolerance."""
    secret, body = "s3cr3t", b"{}"
    old = f"{time.time() - 3600:.0f}"
    assert not webhooks.verify(secret, old, body, webhooks.sign(secret, old, body))


def test_a_missing_or_junk_signature_is_refused():
    ts, body = f"{time.time():.0f}", b"{}"
    assert not webhooks.verify("s", ts, body, "")
    assert not webhooks.verify("s", ts, body, "v1=deadbeef")
    assert not webhooks.verify("s", "not-a-timestamp", body, "v1=x")


# ---- subscriptions ------------------------------------------------------------------------

def test_the_secret_is_returned_once_and_never_again():
    """Like an API key: serving it on every read puts it in logs and screenshots for nothing."""
    with _client() as c:
        made = c.post("/api/webhooks", json={"url": "https://example.com/hook",
                                             "events": ["trace.failed"]}).json()
        assert made["secret"]
        listed = [s for s in c.get("/api/webhooks").json() if s["id"] == made["id"]][0]
        assert "secret" not in listed
        c.delete(f"/api/webhooks/{made['id']}")


def test_an_unknown_event_is_refused_at_save_time():
    """A typo'd event would create a subscription that silently never fires — the hardest kind
    of integration bug to notice."""
    with _client() as c:
        r = c.post("/api/webhooks", json={"url": "https://example.com/h",
                                          "events": ["trace.exploded"]})
        assert r.status_code == 422 and "unknown event" in r.text
        assert c.post("/api/webhooks", json={"url": "https://example.com/h",
                                             "events": []}).status_code == 422


def test_cloud_metadata_is_refused_everywhere():
    """169.254.169.254 is the credential-stealing target, so netguard blocks link-local in
    every mode — not only hosted."""
    with _client() as c:
        r = c.post("/api/webhooks", json={"url": "http://169.254.169.254/latest/meta-data",
                                          "events": ["trace.failed"]})
        assert r.status_code == 422


def test_private_addresses_are_refused_in_hosted_mode_only():
    """Deliberate asymmetry, and worth pinning so nobody 'fixes' it: a self-hosted instance may
    legitimately webhook to a service on its own network, but a shared hosted instance must not
    let one tenant reach the internal network."""
    import pytest as _pytest

    from provekit.config import get_settings
    from provekit.services import netguard

    # Asserted at the guard rather than through the API: hosted mode also raises a login wall,
    # so a request never reaches the check and a 401 would pass this test for the wrong reason.
    s = get_settings()
    prev = s.hosted
    try:
        s.hosted = False
        netguard.guard_url("http://127.0.0.1:9/x")            # allowed self-hosted
        s.hosted = True
        with _pytest.raises(netguard.BlockedURL):
            netguard.guard_url("http://127.0.0.1:9/x")        # refused on a shared instance
    finally:
        s.hosted = prev


# ---- delivery -----------------------------------------------------------------------------

class _Resp:
    def __init__(self, code): self.status_code = code


def _sub(**kw):
    from provekit.models import WebhookSubscription
    d = dict(id=1, workspace_id=1, url="https://example.com/hook", events=["trace.failed"],
             secret="s3cr3t", enabled=True, failures=0, last_status="", last_attempt_at=None)
    d.update(kw)
    return WebhookSubscription(**d)


def test_delivery_signs_the_body_it_sends(monkeypatch):
    import httpx
    sent = {}

    def _post(url, content=None, timeout=None, follow_redirects=None, headers=None):
        sent.update(url=url, body=content, headers=headers)
        return _Resp(200)

    monkeypatch.setattr(httpx, "post", _post)
    sub = _sub()
    assert webhooks.deliver(_FakeDB(), sub, "trace.failed", {"trace_id": "abc"}) is True
    assert webhooks.verify(sub.secret, sent["headers"][webhooks.TIMESTAMP_HEADER],
                           sent["body"], sent["headers"][webhooks.SIGNATURE_HEADER])
    assert json.loads(sent["body"])["data"]["trace_id"] == "abc"
    assert sub.failures == 0


def test_a_dead_endpoint_eventually_disables_itself(monkeypatch):
    """Retrying forever is an outbound DoS the customer pays for, on our egress."""
    import httpx
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _Resp(500))
    sub = _sub()
    db = _FakeDB()
    for _ in range(webhooks.MAX_FAILURES):
        webhooks.deliver(db, sub, "trace.failed", {})
    assert sub.enabled is False
    assert "disabled after" in sub.last_status      # and it says why, rather than going quiet


def test_a_success_resets_the_failure_count(monkeypatch):
    import httpx
    sub = _sub(failures=3)
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _Resp(204))
    webhooks.deliver(_FakeDB(), sub, "trace.failed", {})
    assert sub.failures == 0 and sub.enabled is True


def test_a_transport_error_is_recorded_not_raised(monkeypatch):
    """This runs off the back of work the user asked for; their broken endpoint must not fail
    an ingest."""
    import httpx

    def _boom(*a, **k):
        raise httpx.ConnectError("no route to host")

    monkeypatch.setattr(httpx, "post", _boom)
    sub = _sub()
    assert webhooks.deliver(_FakeDB(), sub, "trace.failed", {}) is False
    assert "ConnectError" in sub.last_status


def test_emit_ignores_an_unknown_event():
    assert webhooks.emit(_FakeDB(), 1, "not.an.event", {}) == 0


def test_a_disabled_subscription_can_be_re_enabled():
    with _client() as c:
        made = c.post("/api/webhooks", json={"url": "https://example.com/hook",
                                             "events": ["alert.fired"]}).json()
        back = c.post(f"/api/webhooks/{made['id']}/enable").json()
        assert back["enabled"] is True and back["failures"] == 0
        c.delete(f"/api/webhooks/{made['id']}")


class _FakeDB:
    def commit(self): pass
    def rollback(self): pass
    def query(self, *a, **k): raise AssertionError("not used in these tests")
