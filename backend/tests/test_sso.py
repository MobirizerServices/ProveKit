"""OIDC SSO (#77) — mostly a test of the *refusals*.

Every token in this file is signed for real with a locally generated RSA key and verified by
the real `oidc.verify_id_token`. Nothing stubs the validator: a test that mocks the thing it is
checking proves the mock works. What is stubbed is the network — `_fetch_json` (discovery/JWKS)
and `_post_form` (the token exchange) — which is the only part that would otherwise need a live
identity provider.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from fastapi.testclient import TestClient

from provekit.database import SessionLocal
from provekit.main import app
from provekit.models import User
from provekit.services import oidc

ISSUER = "https://idp.test"
CLIENT_ID = "provekit-test-client"
REDIRECT = "http://localhost:8000/api/auth/sso/callback"


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


@pytest.fixture(scope="module")
def keypair():
    """One 2048-bit RSA key for the whole module (generation is the slow part)."""
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="module")
def other_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _jwk(key, kid="test-key") -> dict:
    n = key.public_key().public_numbers()
    return {"kty": "RSA", "use": "sig", "alg": "RS256", "kid": kid,
            "n": _b64(n.n.to_bytes((n.n.bit_length() + 7) // 8, "big")),
            "e": _b64(n.e.to_bytes((n.e.bit_length() + 7) // 8, "big"))}


def _mint(key, claims: dict, *, alg="RS256", kid="test-key") -> str:
    header = {"alg": alg, "typ": "JWT", "kid": kid}
    h = _b64(json.dumps(header, separators=(",", ":")).encode())
    p = _b64(json.dumps(claims, separators=(",", ":")).encode())
    if alg == "none":
        return f"{h}.{p}."
    if alg == "HS256":
        # The classic confusion attack: sign with the *public* key as an HMAC secret.
        from cryptography.hazmat.primitives import serialization
        pub = key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        return f"{h}.{p}.{_b64(hmac.new(pub, f'{h}.{p}'.encode(), hashlib.sha256).digest())}"
    sig = key.sign(f"{h}.{p}".encode(), padding.PKCS1v15(), hashes.SHA256())
    return f"{h}.{p}.{_b64(sig)}"


def _claims(**over) -> dict:
    base = {"iss": ISSUER, "aud": CLIENT_ID, "sub": "idp-user-1", "exp": time.time() + 300,
            "iat": time.time(), "nonce": "the-nonce", "email": "person@acme.com",
            "email_verified": True, "name": "A Person"}
    base.update(over)
    return base


def _verify(key, token, **over):
    kw = {"keys": [_jwk(key)], "issuer": ISSUER, "audience": CLIENT_ID, "nonce": "the-nonce"}
    kw.update(over)
    return oidc.verify_id_token(token, **kw)


def _cfg(**over) -> oidc.OIDCSettings:
    kw = {"issuer": ISSUER, "client_id": CLIENT_ID, "redirect_uri": REDIRECT,
          "allowed_domains": "", "allow_signup": False}
    kw.update(over)
    return oidc.OIDCSettings(**kw)


# ---------------------------------------------------------------- ID token: the happy path


def test_valid_token_is_accepted(keypair):
    claims = _verify(keypair, _mint(keypair, _claims()))
    assert claims["email"] == "person@acme.com"
    assert claims["sub"] == "idp-user-1"


def test_email_is_normalised_to_lowercase(keypair):
    claims = _verify(keypair, _mint(keypair, _claims(email="Person@ACME.com")))
    assert claims["email"] == "person@acme.com"


# ---------------------------------------------------------------- ID token: the refusals


def test_signature_from_another_key_is_rejected(keypair, other_key):
    # Signed by a key that is not the one in the JWKS, but carrying the right kid.
    with pytest.raises(oidc.OIDCError, match="signature is not valid"):
        _verify(keypair, _mint(other_key, _claims()))


def test_tampered_payload_is_rejected(keypair):
    token = _mint(keypair, _claims())
    h, p, s = token.split(".")
    forged = json.loads(base64.urlsafe_b64decode(p + "=" * (-len(p) % 4)))
    forged["email"] = "admin@acme.com"
    p2 = _b64(json.dumps(forged, separators=(",", ":")).encode())
    with pytest.raises(oidc.OIDCError, match="signature is not valid"):
        _verify(keypair, f"{h}.{p2}.{s}")


def test_alg_none_is_rejected(keypair):
    with pytest.raises(oidc.OIDCError, match="Unsupported ID token algorithm"):
        _verify(keypair, _mint(keypair, _claims(), alg="none"))


def test_hmac_alg_confusion_is_rejected(keypair):
    """HS256 signed with the RSA public key must not validate."""
    with pytest.raises(oidc.OIDCError, match="Unsupported ID token algorithm"):
        _verify(keypair, _mint(keypair, _claims(), alg="HS256"))


def test_unknown_kid_is_rejected(keypair):
    with pytest.raises(oidc.OIDCError, match="not in the IdP's JWKS"):
        _verify(keypair, _mint(keypair, _claims(), kid="rotated-out"))


def test_wrong_issuer_is_rejected(keypair):
    with pytest.raises(oidc.OIDCError, match="different issuer"):
        _verify(keypair, _mint(keypair, _claims(iss="https://evil.test")))


def test_wrong_audience_is_rejected(keypair):
    with pytest.raises(oidc.OIDCError, match="different client"):
        _verify(keypair, _mint(keypair, _claims(aud="some-other-app")))


def test_multi_audience_requires_azp(keypair):
    tok = _mint(keypair, _claims(aud=[CLIENT_ID, "other-app"], azp="other-app"))
    with pytest.raises(oidc.OIDCError, match="azp"):
        _verify(keypair, tok)
    ok = _mint(keypair, _claims(aud=[CLIENT_ID, "other-app"], azp=CLIENT_ID))
    assert _verify(keypair, ok)["email"] == "person@acme.com"


def test_expired_token_is_rejected(keypair):
    with pytest.raises(oidc.OIDCError, match="expired"):
        _verify(keypair, _mint(keypair, _claims(exp=time.time() - 3600)))


def test_missing_expiry_is_rejected(keypair):
    claims = _claims()
    del claims["exp"]
    with pytest.raises(oidc.OIDCError, match="no expiry"):
        _verify(keypair, _mint(keypair, claims))


def test_iat_far_in_the_future_is_rejected(keypair):
    with pytest.raises(oidc.OIDCError, match="in the future"):
        _verify(keypair, _mint(keypair, _claims(iat=time.time() + 3600)))


def test_mismatched_nonce_is_rejected(keypair):
    with pytest.raises(oidc.OIDCError, match="nonce"):
        _verify(keypair, _mint(keypair, _claims(nonce="someone-elses-nonce")))


def test_missing_nonce_is_rejected(keypair):
    claims = _claims()
    del claims["nonce"]
    with pytest.raises(oidc.OIDCError, match="nonce"):
        _verify(keypair, _mint(keypair, claims))


def test_missing_email_is_rejected(keypair):
    claims = _claims()
    del claims["email"]
    with pytest.raises(oidc.OIDCError, match="no email claim"):
        _verify(keypair, _mint(keypair, claims))


def test_unverified_email_is_rejected(keypair):
    with pytest.raises(oidc.OIDCError, match="unverified"):
        _verify(keypair, _mint(keypair, _claims(email_verified=False)))


def test_malformed_tokens_are_rejected(keypair):
    for bad in ("", "not-a-jwt", "a.b", "a.b.c.d", "!!!.???.***"):
        with pytest.raises(oidc.OIDCError):
            _verify(keypair, bad)


def test_non_object_payload_is_rejected(keypair):
    h = _b64(json.dumps({"alg": "RS256", "kid": "test-key"}).encode())
    p = _b64(json.dumps([1, 2, 3]).encode())
    sig = keypair.sign(f"{h}.{p}".encode(), padding.PKCS1v15(), hashes.SHA256())
    with pytest.raises(oidc.OIDCError, match="malformed"):
        _verify(keypair, f"{h}.{p}.{_b64(sig)}")


def test_non_rsa_jwk_is_rejected(keypair):
    token = _mint(keypair, _claims(), kid="ec-key")
    ec_jwk = {"kty": "EC", "use": "sig", "kid": "ec-key", "crv": "P-256", "x": "AA", "y": "BB"}
    with pytest.raises(oidc.OIDCError, match="not in the IdP's JWKS"):
        _verify(keypair, token, keys=[ec_jwk])


def test_no_kid_uses_the_only_signing_key(keypair):
    h = _b64(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    p = _b64(json.dumps(_claims(), separators=(",", ":")).encode())
    sig = keypair.sign(f"{h}.{p}".encode(), padding.PKCS1v15(), hashes.SHA256())
    assert _verify(keypair, f"{h}.{p}.{_b64(sig)}")["email"] == "person@acme.com"


def test_no_kid_with_several_keys_is_ambiguous(keypair, other_key):
    h = _b64(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    p = _b64(json.dumps(_claims(), separators=(",", ":")).encode())
    sig = keypair.sign(f"{h}.{p}".encode(), padding.PKCS1v15(), hashes.SHA256())
    with pytest.raises(oidc.OIDCError, match="no `kid`"):
        _verify(keypair, f"{h}.{p}.{_b64(sig)}",
                keys=[_jwk(keypair), _jwk(other_key, kid="second")])


# ---------------------------------------------------------------- PKCE + state


def test_pkce_challenge_is_s256_of_the_verifier():
    v = oidc.new_verifier()
    assert 43 <= len(v) <= 128
    expected = base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).decode().rstrip("=")
    assert oidc.challenge(v) == expected
    assert "=" not in oidc.challenge(v)


def test_verifiers_are_unique():
    assert len({oidc.new_verifier() for _ in range(50)}) == 50


def test_transaction_cookie_roundtrip():
    tx = oidc.new_transaction("/traces")
    blob = oidc.seal_tx(tx)
    assert oidc.open_tx(blob)["state"] == tx["state"]
    assert oidc.open_tx(blob)["next"] == "/traces"


def test_tampered_transaction_cookie_is_rejected():
    tx = oidc.new_transaction()
    body, sig = oidc.seal_tx(tx).split(".")
    forged = dict(tx, state="attacker-chosen")
    body2 = _b64(json.dumps(forged, separators=(",", ":"), sort_keys=True).encode())
    assert oidc.open_tx(f"{body2}.{sig}") is None
    assert oidc.open_tx("garbage") is None
    assert oidc.open_tx("") is None


def test_expired_transaction_cookie_is_rejected():
    tx = oidc.new_transaction()
    tx["exp"] = time.time() - 1
    assert oidc.open_tx(oidc.seal_tx(tx)) is None


def test_state_is_single_use():
    state = oidc.new_verifier()
    assert oidc.consume_state(state) is True
    assert oidc.consume_state(state) is False
    assert oidc.consume_state(state) is False


def test_safe_next_rejects_offsite_targets():
    assert oidc.safe_next("/dashboard") == "/dashboard"
    assert oidc.safe_next(None) == "/"
    assert oidc.safe_next("") == "/"
    assert oidc.safe_next("//evil.com") == "/"
    assert oidc.safe_next("https://evil.com") == "/"
    assert oidc.safe_next("/\\evil.com") == "/"
    assert oidc.safe_next("evil.com") == "/"


# ---------------------------------------------------------------- policy: who gets an account


def test_allowed_domains_bound_is_enforced():
    cfg = _cfg(allowed_domains="acme.com, acme.co.uk")
    oidc.check_allowed("person@acme.com", cfg)
    oidc.check_allowed("person@acme.co.uk", cfg)
    with pytest.raises(oidc.OIDCError, match="domain is not permitted"):
        oidc.check_allowed("person@evil.com", cfg)
    # No list configured → no domain restriction (single-tenant IdP).
    oidc.check_allowed("anyone@anywhere.test", _cfg())


def test_jit_provisioning_is_off_by_default():
    db = SessionLocal()
    try:
        with pytest.raises(oidc.OIDCError, match="sign-up is disabled"):
            oidc.resolve_user(db, _claims(email="brand-new@acme.com"), _cfg())
        assert db.query(User).filter(User.email == "brand-new@acme.com").first() is None
    finally:
        db.close()


def test_jit_provisioning_refuses_without_a_domain_bound():
    """allow_signup without allowed_domains means everyone at the IdP gets an account."""
    db = SessionLocal()
    try:
        with pytest.raises(oidc.OIDCError, match="OIDC_ALLOWED_DOMAINS"):
            oidc.resolve_user(db, _claims(email="nobound@acme.com"),
                              _cfg(allow_signup=True, allowed_domains=""))
    finally:
        db.close()


def test_jit_provisioning_refuses_a_foreign_domain():
    db = SessionLocal()
    try:
        with pytest.raises(oidc.OIDCError, match="domain is not permitted"):
            oidc.resolve_user(db, _claims(email="outsider@evil.com"),
                              _cfg(allow_signup=True, allowed_domains="acme.com"))
        assert db.query(User).filter(User.email == "outsider@evil.com").first() is None
    finally:
        db.close()


def test_jit_provisioning_creates_a_bounded_account():
    db = SessionLocal()
    try:
        cfg = _cfg(allow_signup=True, allowed_domains="acme.com")
        u = oidc.resolve_user(db, _claims(email="jit@acme.com", name="JIT User"), cfg)
        assert u.auth_provider == "oidc"
        assert u.email_verified is True
        assert not u.password_hash          # no password → password login can never match
        assert u.name == "JIT User"
        # Second login reuses the same row rather than creating another.
        again = oidc.resolve_user(db, _claims(email="jit@acme.com"), cfg)
        assert again.id == u.id
    finally:
        db.close()


def test_existing_password_account_keeps_its_provider():
    db = SessionLocal()
    try:
        from provekit.services import auth as auth_svc
        existing = User(email="pw@acme.com", name="Pw", auth_provider="password",
                        password_hash=auth_svc.hash_password("hunter2hunter2"))
        db.add(existing); db.commit(); db.refresh(existing)
        u = oidc.resolve_user(db, _claims(email="pw@acme.com"),
                              _cfg(allow_signup=True, allowed_domains="acme.com"))
        assert u.id == existing.id
        assert u.auth_provider == "password"
    finally:
        db.close()


def test_domain_bound_applies_to_existing_accounts_too():
    """A user who already has an account still can't come in through a disallowed domain."""
    db = SessionLocal()
    try:
        db.add(User(email="stale@old-co.com", name="Stale", auth_provider="password"))
        db.commit()
        with pytest.raises(oidc.OIDCError, match="domain is not permitted"):
            oidc.resolve_user(db, _claims(email="stale@old-co.com"), _cfg(allowed_domains="acme.com"))
    finally:
        db.close()


# ---------------------------------------------------------------- provider metadata


def _serve(keypair, *, issuer=ISSUER):
    """A stand-in for the IdP's two published documents."""
    def fetch(url: str) -> dict:
        if url.endswith("/.well-known/openid-configuration"):
            return {"issuer": issuer,
                    "authorization_endpoint": f"{ISSUER}/authorize",
                    "token_endpoint": f"{ISSUER}/token",
                    "jwks_uri": f"{ISSUER}/jwks"}
        if url.endswith("/jwks"):
            return {"keys": [_jwk(keypair)]}
        raise AssertionError(f"unexpected fetch {url}")
    return fetch


@pytest.fixture
def idp(monkeypatch, keypair):
    oidc.clear_cache()
    monkeypatch.setattr(oidc, "_fetch_json", _serve(keypair))
    yield
    oidc.clear_cache()


def test_discovery_issuer_must_match_config(monkeypatch, keypair):
    oidc.clear_cache()
    monkeypatch.setattr(oidc, "_fetch_json", _serve(keypair, issuer="https://someone-else.test"))
    with pytest.raises(oidc.OIDCError, match="different issuer"):
        oidc.discovery(_cfg())
    oidc.clear_cache()


def test_discovery_missing_endpoint_is_rejected(monkeypatch):
    oidc.clear_cache()
    monkeypatch.setattr(oidc, "_fetch_json",
                        lambda url: {"issuer": ISSUER, "authorization_endpoint": f"{ISSUER}/a"})
    with pytest.raises(oidc.OIDCError, match="missing token_endpoint"):
        oidc.discovery(_cfg())
    oidc.clear_cache()


def test_discovery_is_cached(monkeypatch, keypair):
    oidc.clear_cache()
    calls = []
    inner = _serve(keypair)

    def counting(url):
        calls.append(url)
        return inner(url)

    monkeypatch.setattr(oidc, "_fetch_json", counting)
    oidc.discovery(_cfg()); oidc.discovery(_cfg()); oidc.jwks(_cfg())
    assert calls.count(f"{ISSUER}/.well-known/openid-configuration") == 1
    oidc.clear_cache()


def test_authorization_url_carries_pkce_and_state(idp):
    tx = oidc.new_transaction("/traces")
    url = oidc.authorization_url(tx, _cfg())
    assert url.startswith(f"{ISSUER}/authorize?")
    assert f"state={tx['state']}" in url.replace("%2D", "-").replace("%5F", "_")
    assert "code_challenge_method=S256" in url
    assert f"code_challenge={oidc.challenge(tx['verifier'])}" in url.replace("%2D", "-").replace("%5F", "_")
    assert "response_type=code" in url


# ---------------------------------------------------------------- the exchange


def test_login_with_code_end_to_end(idp, monkeypatch, keypair):
    sent = {}

    def post_form(url, data, auth_pair):
        sent.update(data)
        return {"id_token": _mint(keypair, _claims(email="e2e@acme.com", nonce="n-1"))}

    monkeypatch.setattr(oidc, "_post_form", post_form)
    db = SessionLocal()
    try:
        u = oidc.login_with_code(db, "the-code", "the-verifier", "n-1",
                                 _cfg(allow_signup=True, allowed_domains="acme.com"))
        assert u.email == "e2e@acme.com"
        assert sent["code_verifier"] == "the-verifier"   # PKCE actually goes on the wire
        assert sent["grant_type"] == "authorization_code"
        assert sent["redirect_uri"] == REDIRECT
    finally:
        db.close()


def test_login_with_a_replayed_nonce_from_another_session(idp, monkeypatch, keypair):
    """The IdP's token is genuine but was minted for a different login attempt."""
    monkeypatch.setattr(oidc, "_post_form",
                        lambda u, d, a: {"id_token": _mint(keypair, _claims(nonce="other-session"))})
    db = SessionLocal()
    try:
        with pytest.raises(oidc.OIDCError, match="nonce"):
            oidc.login_with_code(db, "c", "v", "my-session", _cfg())
    finally:
        db.close()


def test_token_response_without_id_token_is_rejected(idp, monkeypatch):
    monkeypatch.setattr(oidc, "_post_form", lambda u, d, a: {"access_token": "at"})
    db = SessionLocal()
    try:
        with pytest.raises(oidc.OIDCError, match="no id_token"):
            oidc.login_with_code(db, "c", "v", "n", _cfg())
    finally:
        db.close()


def test_client_secret_is_sent_as_basic_auth_only_when_set(idp, monkeypatch, keypair):
    seen = {}

    def post_form(url, data, auth_pair):
        seen["auth"] = auth_pair
        return {"id_token": _mint(keypair, _claims(nonce="n"))}

    monkeypatch.setattr(oidc, "_post_form", post_form)
    oidc.exchange_code("c", "v", _cfg())
    assert seen["auth"] is None
    seen.clear()
    oidc.exchange_code("c", "v", _cfg(client_secret="s3cret"))
    assert seen["auth"] == (CLIENT_ID, "s3cret")


def test_settings_disabled_until_configured():
    assert oidc.OIDCSettings().enabled is False
    assert oidc.OIDCSettings(issuer=ISSUER, client_id=CLIENT_ID).enabled is False   # no redirect_uri
    assert _cfg().enabled is True


# ---------------------------------------------------------------- HTTP, against the real app
#
# routers/sso.py needs one line in main.py (`app.include_router(sso.router)`), which this wave
# does not own. Until that lands the routes are not on the app, and self-registering the router
# inside the test would only prove the router imports — so these skip, loudly, instead.

_WIRED = any(getattr(r, "path", "").startswith("/api/auth/sso") for r in app.routes)
needs_wiring = pytest.mark.skipif(
    not _WIRED,
    reason="routers/sso.py is not registered on provekit.main.app yet — add "
           "`app.include_router(sso.router)` to main.py (see the wiring note in the PR).")


@pytest.fixture
def sso_env(monkeypatch, idp):
    monkeypatch.setenv("OIDC_ISSUER", ISSUER)
    monkeypatch.setenv("OIDC_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("OIDC_REDIRECT_URI", REDIRECT)
    monkeypatch.setenv("OIDC_ALLOWED_DOMAINS", "acme.com")
    monkeypatch.setenv("OIDC_ALLOW_SIGNUP", "true")
    oidc.get_oidc_settings.cache_clear()
    yield
    oidc.get_oidc_settings.cache_clear()


@needs_wiring
def test_sso_config_reports_disabled_when_unconfigured():
    oidc.get_oidc_settings.cache_clear()
    with TestClient(app) as c:
        body = c.get("/api/auth/sso/config").json()
    assert body["enabled"] is False
    oidc.get_oidc_settings.cache_clear()


@needs_wiring
def test_sso_routes_404_when_unconfigured():
    oidc.get_oidc_settings.cache_clear()
    with TestClient(app) as c:
        assert c.get("/api/auth/sso/login", follow_redirects=False).status_code == 404
    oidc.get_oidc_settings.cache_clear()


@needs_wiring
def test_login_redirects_to_the_idp_and_sets_the_transaction(sso_env):
    with TestClient(app) as c:
        r = c.get("/api/auth/sso/login?next=/traces", follow_redirects=False)
        assert r.status_code == 307
        assert r.headers["location"].startswith(f"{ISSUER}/authorize?")
        tx = oidc.open_tx(c.cookies[oidc.TX_COOKIE])
        assert tx and tx["next"] == "/traces"


@needs_wiring
def test_callback_signs_the_user_in_with_the_normal_session_cookie(sso_env, monkeypatch, keypair):
    from provekit.services import auth as auth_svc

    with TestClient(app) as c:
        c.get("/api/auth/sso/login", follow_redirects=False)
        tx = oidc.open_tx(c.cookies[oidc.TX_COOKIE])
        monkeypatch.setattr(oidc, "_post_form", lambda u, d, a: {
            "id_token": _mint(keypair, _claims(email="http@acme.com", nonce=tx["nonce"]))})
        r = c.get(f"/api/auth/sso/callback?code=abc&state={tx['state']}", follow_redirects=False)
        assert r.status_code == 303
        assert auth_svc.COOKIE in c.cookies
        me = c.get("/api/auth/me").json()
    assert me["email"] == "http@acme.com"
    assert me["auth_provider"] == "oidc"


@needs_wiring
def test_callback_refuses_a_replayed_state(sso_env, monkeypatch, keypair):
    with TestClient(app) as c:
        c.get("/api/auth/sso/login", follow_redirects=False)
        tx = oidc.open_tx(c.cookies[oidc.TX_COOKIE])
        monkeypatch.setattr(oidc, "_post_form", lambda u, d, a: {
            "id_token": _mint(keypair, _claims(email="replay@acme.com", nonce=tx["nonce"]))})
        cookie = c.cookies[oidc.TX_COOKIE]
        assert c.get(f"/api/auth/sso/callback?code=abc&state={tx['state']}",
                     follow_redirects=False).status_code == 303
        # Replay the whole callback, transaction cookie included.
        c.cookies.set(oidc.TX_COOKIE, cookie, path="/api/auth/sso")
        r = c.get(f"/api/auth/sso/callback?code=abc&state={tx['state']}", follow_redirects=False)
    assert r.status_code == 400
    assert "already been used" in r.json()["detail"]


@needs_wiring
def test_callback_refuses_a_state_from_another_browser(sso_env):
    with TestClient(app) as c:
        c.get("/api/auth/sso/login", follow_redirects=False)
        r = c.get("/api/auth/sso/callback?code=abc&state=attacker-supplied", follow_redirects=False)
    assert r.status_code == 400
    assert "did not match" in r.json()["detail"]


@needs_wiring
def test_callback_without_a_transaction_cookie_is_refused(sso_env):
    with TestClient(app) as c:
        r = c.get("/api/auth/sso/callback?code=abc&state=whatever", follow_redirects=False)
    assert r.status_code == 400


@needs_wiring
def test_callback_refuses_a_disallowed_domain(sso_env, monkeypatch, keypair):
    with TestClient(app) as c:
        c.get("/api/auth/sso/login", follow_redirects=False)
        tx = oidc.open_tx(c.cookies[oidc.TX_COOKIE])
        monkeypatch.setattr(oidc, "_post_form", lambda u, d, a: {
            "id_token": _mint(keypair, _claims(email="outsider@evil.com", nonce=tx["nonce"]))})
        r = c.get(f"/api/auth/sso/callback?code=abc&state={tx['state']}", follow_redirects=False)
    assert r.status_code == 403
    assert "domain is not permitted" in r.json()["detail"]


@needs_wiring
def test_callback_refuses_a_bad_signature(sso_env, monkeypatch, other_key):
    with TestClient(app) as c:
        c.get("/api/auth/sso/login", follow_redirects=False)
        tx = oidc.open_tx(c.cookies[oidc.TX_COOKIE])
        monkeypatch.setattr(oidc, "_post_form", lambda u, d, a: {
            "id_token": _mint(other_key, _claims(email="forged@acme.com", nonce=tx["nonce"]))})
        r = c.get(f"/api/auth/sso/callback?code=abc&state={tx['state']}", follow_redirects=False)
    assert r.status_code == 403
    db = SessionLocal()
    try:
        assert db.query(User).filter(User.email == "forged@acme.com").first() is None
    finally:
        db.close()


@needs_wiring
def test_callback_passes_the_idp_error_through(sso_env):
    with TestClient(app) as c:
        c.get("/api/auth/sso/login", follow_redirects=False)
        r = c.get("/api/auth/sso/callback?error=access_denied", follow_redirects=False)
    assert r.status_code == 400
