"""OIDC single sign-on: Authorization Code + PKCE, and the ID-token validation behind it (#77).

Scope, stated up front: **OIDC only. SAML is deliberately not implemented** — see docs/SSO.md.
SAML is XML-DSig over a canonicalised document, which drags in signature-wrapping attacks, an
XML parser hardened against entity expansion, IdP metadata parsing, and per-IdP quirks. It is a
larger and sharper surface than the whole of this file, and a half-built SAML verifier is an
authentication bypass rather than a missing feature. Okta, Entra ID, Google Workspace, Keycloak,
Auth0 and Ping all speak OIDC, so this covers the adoption gate; SAML-only IdPs (older ADFS,
Shibboleth) are not supported and the docs say so.

Why hand-rolled rather than a JOSE library: the server's dependency set has no JWT library
(`cryptography` is already present for sealing) and this module cannot add one — so the
verification below is written against `cryptography` primitives directly. That is only
acceptable because the checks are explicit and individually tested (tests/test_sso.py mints
real RSA-signed tokens and asserts each refusal), not because hand-rolling JOSE is a good idea
in general. The rules that matter:

* the algorithm comes from an allow-list, never from the token (`alg: none` and an HMAC
  algorithm keyed with the public key are the two classic forgeries);
* the key comes from the provider's JWKS, matched by `kid`;
* issuer, audience, expiry and nonce are all compared, and a missing claim is a rejection
  rather than a skipped check.

State/PKCE/nonce live in a short-lived signed cookie rather than a table: this wave cannot add
a migration, and the transaction is genuinely per-browser and disposable. See `seal_tx`.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import threading
import time
from functools import lru_cache

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from pydantic_settings import BaseSettings, SettingsConfigDict

from .netguard import guard_url

#: Cookie carrying the in-flight authorization transaction (state, nonce, PKCE verifier).
TX_COOKIE = "agm_oidc_tx"
#: How long a login may sit at the IdP before the transaction is dead.
TX_TTL = 600

#: Signature algorithms we accept. RSA only — every major IdP signs RS256 by default, and each
#: extra family is another verification path to get right. An EC-signing IdP is rejected loudly
#: (docs/SSO.md) rather than silently trusted.
_ALGS = {"RS256": hashes.SHA256, "RS384": hashes.SHA384, "RS512": hashes.SHA512}

#: Tolerance for clock drift between this host and the IdP, in seconds.
LEEWAY = 60


class OIDCError(Exception):
    """A login that must be refused. The message is user-facing; keep it actionable."""


# ---------------------------------------------------------------- configuration
#
# A separate Settings class rather than fields on provekit.config.Settings: config.py is not
# ours to edit this wave (the orchestrator holds it), so the OIDC block lives here with an
# `OIDC_` env prefix. The cost is real and worth naming — these vars do not show up in the
# single `Settings` model a reader greps for, and `.env` is parsed twice. When config.py is
# free, this class should move there verbatim.


class OIDCSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="oidc_", extra="ignore")

    #: e.g. https://acme.okta.com or https://login.microsoftonline.com/<tenant>/v2.0
    issuer: str = ""
    client_id: str = ""
    #: Optional: PKCE alone is enough for a public client. Set it for a confidential app.
    client_secret: str = ""
    #: Must be configured explicitly, and must match the IdP registration exactly. Deriving it
    #: from the request's Host header would let a spoofed Host redirect the code elsewhere.
    redirect_uri: str = ""
    scopes: str = "openid email profile"

    #: Comma-separated email domains permitted to sign in ("acme.com,acme.co.uk"). Empty means
    #: *any* address the IdP asserts — fine for a single-tenant IdP, wrong for Google/Entra
    #: multi-tenant, so JIT provisioning refuses to run without it (see `check_allowed`).
    allowed_domains: str = ""

    #: Does a successful OIDC login create an account that does not exist yet? Off by default:
    #: with it on, everyone at the IdP has an account here the moment they click the button.
    allow_signup: bool = False

    #: Label for the button the frontend renders.
    button_label: str = "Sign in with SSO"

    @property
    def enabled(self) -> bool:
        return bool(self.issuer and self.client_id and self.redirect_uri)

    @property
    def domain_list(self) -> list[str]:
        return [d.strip().lower().lstrip("@") for d in self.allowed_domains.split(",") if d.strip()]


@lru_cache
def get_oidc_settings() -> OIDCSettings:
    return OIDCSettings()


# ---------------------------------------------------------------- provider metadata
#
# Discovery and JWKS are cached because they are fetched on every callback otherwise, and an IdP
# that rate-limits its JWKS endpoint would turn a login spike into a login outage.

_DISCOVERY_TTL = 600.0
_JWKS_TTL = 600.0
_cache: dict[str, tuple[float, dict]] = {}
_cache_lock = threading.Lock()


def _fetch_json(url: str) -> dict:
    """GET JSON from the provider. Seam for tests — they replace this, not the validator."""
    import httpx

    guard_url(url)  # provider URLs are outbound URLs; same SSRF gate as every other one
    r = httpx.get(url, timeout=10, follow_redirects=False)
    r.raise_for_status()
    return r.json()


def _cached(url: str, ttl: float) -> dict:
    now = time.time()
    with _cache_lock:
        hit = _cache.get(url)
        if hit and hit[0] > now:
            return hit[1]
    doc = _fetch_json(url)
    with _cache_lock:
        _cache[url] = (now + ttl, doc)
    return doc


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


def discovery(cfg: OIDCSettings | None = None) -> dict:
    """The provider's openid-configuration.

    The document's own `issuer` is compared against the configured one: a redirect or a hijacked
    well-known path could otherwise hand us endpoints belonging to a different provider while we
    keep validating tokens against the issuer we expected."""
    cfg = cfg or get_oidc_settings()
    doc = _cached(cfg.issuer.rstrip("/") + "/.well-known/openid-configuration", _DISCOVERY_TTL)
    if doc.get("issuer") != cfg.issuer:
        raise OIDCError("The IdP's discovery document reports a different issuer than OIDC_ISSUER — "
                        "set OIDC_ISSUER to exactly the value the provider publishes.")
    for field in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        if not doc.get(field):
            raise OIDCError(f"The IdP's discovery document is missing {field}.")
    return doc


def jwks(cfg: OIDCSettings | None = None) -> dict:
    return _cached(discovery(cfg)["jwks_uri"], _JWKS_TTL)


# ---------------------------------------------------------------- PKCE / random values


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def new_verifier() -> str:
    """A PKCE code_verifier: 43-128 chars of unreserved alphabet (RFC 7636 §4.1)."""
    return _b64(secrets.token_bytes(48))


def challenge(verifier: str) -> str:
    """S256 challenge. `plain` is not offered — it protects nothing."""
    return _b64(hashlib.sha256(verifier.encode()).digest())


# ---------------------------------------------------------------- the transaction cookie
#
# state, nonce and the PKCE verifier have to survive the round trip to the IdP. A table would
# need a migration this wave cannot have, and server-side state for a value that is inherently
# per-browser and dead in ten minutes buys little. So: a signed blob in an httpOnly cookie,
# using the app secret namespaced away from sessions (the same construction as services/share.py)
# so an OIDC transaction can never be replayed as a session token and vice versa.
#
# The cookie is confidentiality-adequate here because it holds no secret about the *user*: the
# verifier and nonce are single-use values that are worthless once the callback has run. It is
# signed so a caller cannot substitute their own state/nonce, and short-lived so a captured one
# expires. Single-use is enforced separately by `consume_state`.


def _tx_key() -> bytes:
    from .auth import _secret

    return hashlib.sha256(b"oidc-tx:" + _secret()).digest()


def seal_tx(data: dict) -> str:
    body = _b64(json.dumps(data, separators=(",", ":"), sort_keys=True).encode())
    return f"{body}.{_b64(hmac.new(_tx_key(), body.encode(), hashlib.sha256).digest())}"


def open_tx(blob: str) -> dict | None:
    """Verify + decode a transaction cookie, or None if it is forged, corrupt or expired."""
    try:
        body, sig = blob.split(".")
        expected = _b64(hmac.new(_tx_key(), body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(expected, sig):
            return None
        data = json.loads(_unb64(body))
        if float(data.get("exp", 0)) < time.time():
            return None
        return data
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None


def consume_state(state: str) -> bool:
    """True the first time this state is seen, False on every replay.

    Rides the same counter as services/limits.py so there is one shared store rather than two:
    Redis-backed when REDIS_URL is set (correct across workers) and in-memory otherwise. Say the
    caveat plainly — without Redis, a replay aimed at a *different* worker is not caught by this
    check. The transaction cookie is cleared on the first callback in every case, so a replay
    needs a copy of the cookie taken before it was cleared, and it still expires in TX_TTL.
    """
    from .limits import _window

    key = f"oidc:state:{hashlib.sha256(state.encode()).hexdigest()}"
    return _window().hit(key, TX_TTL) == 1


def safe_next(path: str | None) -> str:
    """Sanitise the post-login redirect target: a site-relative path only.

    An open redirect on a login callback is a phishing primitive — the URL genuinely is the
    company's SSO endpoint. "//evil.com" and "https:/evil.com" are the two forms that look
    relative to a naive check, so anything not starting with a single "/" is discarded.
    """
    if not path or not path.startswith("/") or path.startswith("//") or "\\" in path:
        return "/"
    return path


# ---------------------------------------------------------------- ID token validation


def _rsa_key(jwk: dict):
    if jwk.get("kty") != "RSA":
        raise OIDCError("The IdP's signing key is not RSA; ProveKit's OIDC support verifies RS256 only.")
    n = int.from_bytes(_unb64(jwk["n"]), "big")
    e = int.from_bytes(_unb64(jwk["e"]), "big")
    return rsa.RSAPublicNumbers(e, n).public_key()


def _select_key(keys: list[dict], kid: str | None) -> dict:
    signing = [k for k in keys if k.get("use", "sig") == "sig" and k.get("kty") == "RSA"]
    if kid:
        for k in signing:
            if k.get("kid") == kid:
                return k
        raise OIDCError("The ID token was signed with a key that is not in the IdP's JWKS.")
    if len(signing) == 1:
        return signing[0]
    # No kid and several candidates: trying each one is how a rotated-out key stays usable.
    raise OIDCError("The ID token has no `kid` and the IdP publishes several signing keys.")


def verify_id_token(token: str, *, keys: list[dict], issuer: str, audience: str,
                    nonce: str, now: float | None = None, leeway: int = LEEWAY) -> dict:
    """Fully validate an ID token and return its claims, or raise OIDCError.

    Every check is a rejection, in this order: shape, algorithm allow-list, signature against
    the JWKS key, issuer, audience (+azp when multi-audience), expiry/iat, nonce, and finally
    a usable, IdP-verified email.
    """
    now = time.time() if now is None else now
    try:
        header_b64, payload_b64, sig_b64 = token.split(".")
        header = json.loads(_unb64(header_b64))
        claims = json.loads(_unb64(payload_b64))
        sig = _unb64(sig_b64)
    except (ValueError, TypeError, json.JSONDecodeError):
        raise OIDCError("The IdP returned a malformed ID token.")
    if not isinstance(claims, dict) or not isinstance(header, dict):
        raise OIDCError("The IdP returned a malformed ID token.")

    # The algorithm is chosen by us from an allow-list. Taking it from the header is how
    # `alg: none` and HMAC-with-the-public-key forgeries get accepted.
    alg = header.get("alg")
    if alg not in _ALGS:
        raise OIDCError(f"Unsupported ID token algorithm {alg!r} — ProveKit accepts {sorted(_ALGS)}.")

    key = _rsa_key(_select_key(keys, header.get("kid")))
    try:
        key.verify(sig, f"{header_b64}.{payload_b64}".encode(), padding.PKCS1v15(), _ALGS[alg]())
    except InvalidSignature:
        raise OIDCError("The ID token signature is not valid for the IdP's published key.")

    if claims.get("iss") != issuer:
        raise OIDCError("The ID token was issued by a different issuer than OIDC_ISSUER.")

    aud = claims.get("aud")
    auds = [aud] if isinstance(aud, str) else list(aud or [])
    if audience not in auds:
        raise OIDCError("The ID token was issued for a different client than OIDC_CLIENT_ID.")
    # Multi-audience tokens must name us as the authorized party, otherwise a token minted for
    # another client at the same IdP and merely listing us would be accepted.
    if len(auds) > 1 and claims.get("azp") != audience:
        raise OIDCError("The ID token lists several audiences and its `azp` is not this client.")

    exp = claims.get("exp")
    if not isinstance(exp, (int, float)):
        raise OIDCError("The ID token has no expiry.")
    if exp + leeway < now:
        raise OIDCError("The ID token has expired.")
    for claim in ("iat", "nbf"):
        v = claims.get(claim)
        if isinstance(v, (int, float)) and v - leeway > now:
            raise OIDCError(f"The ID token's `{claim}` is in the future — check clock sync on this host.")

    got = claims.get("nonce")
    if not isinstance(got, str) or not hmac.compare_digest(got, nonce):
        raise OIDCError("The ID token's nonce does not match this login attempt.")

    email = (claims.get("email") or "").strip().lower()
    if not email or "@" not in email:
        raise OIDCError("The ID token carries no email claim — grant the `email` scope to the ProveKit app.")
    # An IdP that says the address is unverified is saying the user typed it. Accepting that
    # lets anyone at the IdP claim a colleague's address and inherit their ProveKit account.
    if claims.get("email_verified") is False:
        raise OIDCError("The IdP reports this email address as unverified.")
    claims["email"] = email
    return claims


# ---------------------------------------------------------------- who is allowed in
#
# JIT provisioning, stated plainly: a successful OIDC login creates a ProveKit account ONLY when
# OIDC_ALLOW_SIGNUP is true AND OIDC_ALLOWED_DOMAINS is non-empty AND the asserted address is in
# one of those domains. Without the domain bound, "allow signup" against a multi-tenant IdP
# (Google, Entra "common") means every Google account on earth can create an account here — so
# the bound is not optional, and it is checked here, on the server, after signature validation.


def check_allowed(email: str, cfg: OIDCSettings | None = None) -> None:
    """Raise unless this asserted address is permitted to use SSO at all."""
    cfg = cfg or get_oidc_settings()
    domains = cfg.domain_list
    if not domains:
        return
    if email.rsplit("@", 1)[-1] not in domains:
        raise OIDCError("This email domain is not permitted to sign in to this ProveKit instance.")


def resolve_user(db, claims: dict, cfg: OIDCSettings | None = None):
    """Map validated claims to a User row, provisioning one only if policy allows it."""
    from ..models import User
    from .auth import new_account_setup

    cfg = cfg or get_oidc_settings()
    email = claims["email"]
    check_allowed(email, cfg)

    user = db.query(User).filter(User.email == email).first()
    if user:
        # An existing password account keeps auth_provider="password": the column records how
        # the account was created, and silently rewriting it would hide that a password login
        # still works for that user. Whether to *disable* password login once SSO is on is a
        # policy switch this wave has no column for — docs/SSO.md says so.
        return user

    if not cfg.allow_signup:
        raise OIDCError("No ProveKit account exists for this address, and SSO sign-up is disabled "
                        "(set OIDC_ALLOW_SIGNUP=true with OIDC_ALLOWED_DOMAINS to enable it).")
    if not cfg.domain_list:
        raise OIDCError("SSO sign-up requires OIDC_ALLOWED_DOMAINS to be set — without it every "
                        "account at the identity provider could create a ProveKit account.")

    name = (claims.get("name") or claims.get("preferred_username") or email.split("@")[0])[:160]
    # password_hash stays empty, which the password login path already treats as "no password
    # on this account" — so a JIT account cannot be taken over by a password reset flow either.
    user = User(email=email, name=name, auth_provider="oidc", email_verified=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    new_account_setup(db, user)
    return user


# ---------------------------------------------------------------- the two protocol steps


def authorization_url(tx: dict, cfg: OIDCSettings | None = None) -> str:
    """Build the redirect to the IdP for a freshly-minted transaction."""
    from urllib.parse import urlencode

    cfg = cfg or get_oidc_settings()
    params = {
        "response_type": "code",
        "client_id": cfg.client_id,
        "redirect_uri": cfg.redirect_uri,
        "scope": cfg.scopes,
        "state": tx["state"],
        "nonce": tx["nonce"],
        "code_challenge": challenge(tx["verifier"]),
        "code_challenge_method": "S256",
    }
    return discovery(cfg)["authorization_endpoint"] + "?" + urlencode(params)


def new_transaction(next_path: str | None = None) -> dict:
    return {"state": _b64(secrets.token_bytes(24)), "nonce": _b64(secrets.token_bytes(24)),
            "verifier": new_verifier(), "next": safe_next(next_path), "exp": time.time() + TX_TTL}


def _post_form(url: str, data: dict, auth_pair: tuple[str, str] | None) -> dict:
    """POST the token request. Seam for tests, like _fetch_json."""
    import httpx

    guard_url(url)
    r = httpx.post(url, data=data, auth=auth_pair, timeout=15, follow_redirects=False,
                   headers={"Accept": "application/json"})
    if r.status_code >= 400:
        raise OIDCError(f"The IdP rejected the token exchange ({r.status_code}).")
    return r.json()


def exchange_code(code: str, verifier: str, cfg: OIDCSettings | None = None) -> dict:
    """Trade the authorization code + PKCE verifier for tokens."""
    cfg = cfg or get_oidc_settings()
    data = {"grant_type": "authorization_code", "code": code, "redirect_uri": cfg.redirect_uri,
            "client_id": cfg.client_id, "code_verifier": verifier}
    auth_pair = (cfg.client_id, cfg.client_secret) if cfg.client_secret else None
    tokens = _post_form(discovery(cfg)["token_endpoint"], data, auth_pair)
    if not tokens.get("id_token"):
        raise OIDCError("The IdP's token response contained no id_token — is the `openid` scope granted?")
    return tokens


def login_with_code(db, code: str, verifier: str, nonce: str, cfg: OIDCSettings | None = None):
    """The whole callback half: exchange, validate, apply policy, return the User."""
    cfg = cfg or get_oidc_settings()
    tokens = exchange_code(code, verifier, cfg)
    claims = verify_id_token(tokens["id_token"], keys=jwks(cfg).get("keys", []),
                             issuer=cfg.issuer, audience=cfg.client_id, nonce=nonce)
    return resolve_user(db, claims, cfg)
