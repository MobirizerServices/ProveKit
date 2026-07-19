"""Shareable trace links: mint a signed token (authed), read it publicly (no login),
reject a tampered or bogus token, and enforce expiry."""
from fastapi.testclient import TestClient

from provekit.main import app
from provekit.services import share


def _span(trace):
    return {"name": "agent", "traceId": trace, "spanId": "r", "parentSpanId": "",
            "startTimeUnixNano": "1000000000", "endTimeUnixNano": "1500000000",
            "status": {"code": 1},
            "attributes": [{"key": "gen_ai.operation.name", "value": {"stringValue": "invoke_agent"}}]}


def _client():
    return TestClient(app, base_url="https://testserver")


def test_share_mint_then_public_read():
    c = _client()
    c.post("/v1/traces", json={"resourceSpans": [{"scopeSpans": [{"spans": [_span("t-share-1")]}]}]})
    token = c.post("/api/traces/t-share-1/share").json()["token"]

    # a fresh client with NO session cookie can still read it
    pub = TestClient(app, base_url="https://testserver")
    spans = pub.get(f"/v1/share/{token}").json()
    assert len(spans) == 1 and spans[0]["span_id"] == "r"


def test_share_unknown_trace_is_404():
    c = _client()
    assert c.post("/api/traces/nope/share").status_code == 404


def test_tampered_or_bogus_token_is_404():
    c = _client()
    c.post("/v1/traces", json={"resourceSpans": [{"scopeSpans": [{"spans": [_span("t-share-2")]}]}]})
    token = c.post("/api/traces/t-share-2/share").json()["token"]
    assert c.get(f"/v1/share/{token}x").status_code == 404      # tampered signature
    assert c.get("/v1/share/not.a.token").status_code == 404    # garbage
    assert c.get("/v1/share/nodothere").status_code == 404      # no separator → parse error


def test_token_expiry(monkeypatch):
    import time as _t

    good = share.make_share_token(1, "t-ok", ttl_days=30)
    assert share.verify_share_token(good) == (1, "t-ok")

    # jump 31 days into the future → the 30-day token is now expired
    now = _t.time()
    monkeypatch.setattr(share.time, "time", lambda: now + 31 * 86400)
    assert share.verify_share_token(good) is None

    # a perpetual token (ttl_days=0) survives the time jump
    perpetual = share.make_share_token(2, "t-forever", ttl_days=0)
    assert share.verify_share_token(perpetual) == (2, "t-forever")
