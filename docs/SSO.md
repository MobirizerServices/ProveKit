# Single sign-on (OIDC)

ProveKit speaks **OpenID Connect, Authorization Code flow with PKCE** — the protocol Okta, Entra
ID (Azure AD), Google Workspace, Keycloak, Auth0 and Ping all serve. Users click one button, the
identity provider authenticates them, and ProveKit issues **the same session cookie** password
login issues.

> **SAML is not implemented, and this is a deliberate scope decision — not an oversight.**
> SAML is XML-DSig over a canonicalised document: signature wrapping, entity expansion, IdP
> metadata parsing, and a different set of per-vendor quirks. It is a bigger and sharper attack
> surface than the whole of the OIDC implementation, and a half-finished SAML verifier is an
> authentication bypass rather than a missing feature. Every IdP named above speaks OIDC. If your
> IdP is SAML-only (older ADFS, Shibboleth), ProveKit cannot federate with it today.

## Status

| | |
|---|---|
| Protocol | OIDC Authorization Code + PKCE (S256) |
| ID token signing | **RS256 / RS384 / RS512 only** — an EC-signing (ES256) IdP is refused |
| Token endpoint auth | PKCE alone (public client), or HTTP Basic with a client secret |
| SAML | **not supported** |
| SCIM / directory sync | not part of this item |
| Wiring | `routers/sso.py` needs one `include_router` line in `main.py` — see [Enabling](#enabling) |

## Configuration

All variables are read from the backend environment (or `.env`), prefixed `OIDC_`. **SSO is off
unless `OIDC_ISSUER`, `OIDC_CLIENT_ID` and `OIDC_REDIRECT_URI` are all set** — with any of them
missing, `/api/auth/sso/*` returns `404` and `GET /api/auth/sso/config` reports
`{"enabled": false}`, so a login page draws no button.

| Variable | Default | Meaning |
|---|---|---|
| `OIDC_ISSUER` | — | Issuer URL, exactly as the provider publishes it (`https://acme.okta.com`, `https://login.microsoftonline.com/<tenant>/v2.0`). ProveKit appends `/.well-known/openid-configuration`. |
| `OIDC_CLIENT_ID` | — | The application's client id. Also the expected `aud` of every ID token. |
| `OIDC_CLIENT_SECRET` | *empty* | Optional. Sent as HTTP Basic on the token request when set; PKCE alone is used when it isn't. |
| `OIDC_REDIRECT_URI` | — | The callback, e.g. `https://provekit.acme.com/api/auth/sso/callback`. Must match the IdP registration byte-for-byte. |
| `OIDC_SCOPES` | `openid email profile` | Requested scopes. `email` is required — a token with no `email` claim is refused. |
| `OIDC_ALLOWED_DOMAINS` | *empty* | Comma-separated email domains permitted to sign in (`acme.com,acme.co.uk`). Empty = any address the IdP asserts. |
| `OIDC_ALLOW_SIGNUP` | `false` | Whether a successful login **creates** an account that doesn't exist yet. See below. |
| `OIDC_BUTTON_LABEL` | `Sign in with SSO` | Text for the login button. |

Settings are cached per process (`@lru_cache`), so **restart the backend after changing any of
them** — same as `SUPERUSER_EMAILS` in [ADMIN.md](ADMIN.md).

> These live in `services/oidc.py` as their own `OIDCSettings` class rather than in
> `provekit/config.py`. That is a wart with a cause: the config module was owned by another
> change when SSO landed. The cost is that `OIDC_*` doesn't appear in the single `Settings` model
> you'd grep for, and `.env` is parsed twice. It should be folded into `config.py` verbatim.

## Just-in-time provisioning — read this one

**Does a successful OIDC login create a ProveKit account?** Only when *all three* hold:

1. `OIDC_ALLOW_SIGNUP=true`, **and**
2. `OIDC_ALLOWED_DOMAINS` is non-empty, **and**
3. the address the IdP asserted is in one of those domains.

The second condition is not a formality. Against a multi-tenant issuer — Google, or Entra's
`common` endpoint — "allow signup" with no domain bound means *every account at that provider*
can create an account on your instance by clicking the button once. So sign-up with an empty
domain list is **refused**, not merely discouraged.

`OIDC_ALLOWED_DOMAINS` also gates *existing* accounts: a user whose address falls outside the
list cannot sign in through SSO even if they already have a ProveKit account.

Every one of these checks runs **on the server, in `services/oidc.py`, after signature
validation** — never in the browser and never on a claim we haven't verified.

With `OIDC_ALLOW_SIGNUP=false` (the default), SSO is a login method for accounts that already
exist: an unknown address is refused with a message saying so. That is the right setting when
you provision users by invitation.

A JIT-created account gets `auth_provider="oidc"`, `email_verified=true`, and **no password
hash** — so the password login and password-reset paths can never match it.

## What is actually validated

From `services/oidc.py`. Each of these is a rejection with its own test in
`backend/tests/test_sso.py`, against tokens signed by a real RSA key.

**The ID token**

- **Algorithm from an allow-list, never from the token.** `alg: none` and `HS256` signed with the
  provider's public key are the two classic forgeries; both are refused before any key is loaded.
- **Signature** verified against the key from the provider's JWKS, selected by `kid`. An unknown
  `kid`, a non-RSA key, or a token signed by any other key is refused. A `kid`-less token is only
  accepted when the JWKS publishes exactly one signing key.
- **Issuer** must equal `OIDC_ISSUER` exactly.
- **Audience** must contain `OIDC_CLIENT_ID`; when the token carries several audiences, `azp` must
  also be this client — otherwise a token minted for a *different* app at the same IdP that
  merely lists us would pass.
- **Expiry** is required and enforced (60s leeway for clock drift). `iat`/`nbf` in the future are
  refused.
- **Nonce** must equal the nonce minted for this specific login attempt (constant-time compare).
  A genuine token from another session is refused.
- **Email** must be present, and `email_verified: false` is refused — an IdP saying the address is
  unverified is saying the user typed it, which is an account-takeover path onto a colleague's
  ProveKit account.

**The redirect**

- **PKCE S256** on every authorization request; the verifier is sent on the token exchange.
  `plain` is not offered.
- **State** is generated per attempt, compared constant-time against the value sealed in the
  browser's transaction cookie, and **single-use** — a captured callback URL replayed a second
  time is refused (see the caveat below).
- The post-login `next` target is forced to a **site-relative path**. `//evil.com` and
  `https://evil.com` both collapse to `/`; an open redirect on an SSO callback is a phishing
  primitive precisely because the URL really is the company's login endpoint.
- Discovery documents are checked: if the `issuer` inside `/.well-known/openid-configuration`
  disagrees with `OIDC_ISSUER`, the login is refused rather than proceeding with endpoints from
  somewhere else.
- Both outbound calls (discovery/JWKS fetch, token exchange) go through
  `services/netguard.py` — the same SSRF guard as every other outbound URL in ProveKit — and do
  not follow redirects.

**Not implemented, so that you don't assume it is:** ES256/EdDSA signatures, encrypted ID tokens
(JWE), `id_token_hint`/RP-initiated logout at the IdP, back-channel logout, `max_age`/`auth_time`
re-authentication, and the UserInfo endpoint (claims come from the ID token only).

### Single-use state: the honest caveat

Used states are recorded in the same counter store as the rate limits
(`services/limits.py`): Redis-backed when `REDIS_URL` is set, in-process otherwise. **Without
Redis, a multi-worker deployment only enforces single-use per worker.** The transaction cookie is
cleared on the first callback regardless, and it expires after 10 minutes, so a replay needs a
copy of the cookie captured before it was cleared — but if you run more than one worker, set
`REDIS_URL` (which [DEPLOY.md](DEPLOY.md) already provisions).

## Sessions and revocation

There is **one** session mechanism. `/api/auth/sso/callback` calls the same `auth.make_token`
password login calls, sets the same `agm_session` httpOnly cookie, and binds the token to the
user's `token_version`. `get_current_user` cannot tell how a cookie was obtained, which is the
point: a second authentication path is how one of them ends up unguarded.

Consequences worth stating:

- Bumping `token_version` (what a password reset does) revokes SSO sessions too.
- Deactivating a user at the IdP does **not** revoke an already-issued ProveKit session. The
  session lives its full 30 days unless `token_version` moves. There is no back-channel logout
  and no directory sync in this item; until there is, offboarding means removing the user from
  the workspace in ProveKit as well as at the IdP.
- Turning SSO on does **not** disable password login for accounts that already have a password.
  An existing account keeps `auth_provider="password"` after its first SSO login, deliberately —
  rewriting that column would hide the fact that a password still works. "SSO required, passwords
  off" needs a per-instance policy switch that does not exist yet.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/auth/sso/config` | `{enabled, label, issuer, start_url}` — what a login page needs. No secrets. |
| `GET` | `/api/auth/sso/login?next=/traces` | Mints state/nonce/PKCE, sets the transaction cookie, `307` to the IdP. Rate-limited per IP by the same throttle as password login. |
| `GET` | `/api/auth/sso/callback?code=…&state=…` | Validates everything above, sets the session cookie, `303` to the app. |

Failures are refusals, never fallbacks: `400` for a protocol/state/CSRF problem, `403` for a
token or policy rejection at the callback, `404` when SSO isn't configured, and `502` when the
IdP's metadata is unusable at the point where a login starts.

## Enabling

1. Register a **Web / confidential** application at your IdP with redirect URI
   `https://<your-provekit>/api/auth/sso/callback`, grant type *authorization code*, PKCE enabled,
   scopes `openid email profile`.
2. Set the environment variables above and restart the backend.
3. Check `curl https://<your-provekit>/api/auth/sso/config` reports `"enabled": true`.
4. Visit `/api/auth/sso/login` and complete a round trip.

**Wiring, as of this change:** `provekit/routers/sso.py` exists but is not yet registered on the
app — `main.py` was owned by another change in the same wave. Until this line is added to
`main.py`, every `/api/auth/sso/*` path is a plain `404` and the HTTP tests in
`backend/tests/test_sso.py` skip with that reason:

```python
app.include_router(sso.router)
```

(with `sso` added to the `from .routers import (…)` list). Nothing else is needed.
