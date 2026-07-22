"""SSO endpoints: the browser-facing half of OIDC Authorization Code + PKCE (#77).

Deliberately thin. Everything with a security decision in it — token validation, state
single-use, the JIT-provisioning bound — lives in services/oidc.py and is tested there. This
file only moves values between the request, that service, and the session cookie.

The session it issues is *the same* session the password login issues: `auth.make_token` bound
to the user's `token_version`, in the same `agm_session` cookie. There is no second
authentication path and no second thing to revoke — bumping token_version still kills an SSO
session, and get_current_user does not know or care how the cookie was obtained.
"""
import hmac

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..services import auth, oidc
from ..services.limits import check_login_rate

router = APIRouter(prefix="/api/auth/sso", tags=["auth"])


def _cfg() -> oidc.OIDCSettings:
    cfg = oidc.get_oidc_settings()
    if not cfg.enabled:
        # 404, not 501: an instance without SSO configured should look like an instance that
        # has no SSO, rather than advertising a half-configured login route to probe.
        raise HTTPException(404, "Single sign-on is not configured on this instance.")
    return cfg


@router.get("/config")
def sso_config():
    """What the login page needs to decide whether to draw the SSO button. No secrets."""
    cfg = oidc.get_oidc_settings()
    return {"enabled": cfg.enabled, "label": cfg.button_label,
            "issuer": cfg.issuer if cfg.enabled else "",
            "start_url": "/api/auth/sso/login" if cfg.enabled else ""}


@router.get("/login")
def sso_login(request: Request, next: str = "/"):
    """Start a login: mint state/nonce/PKCE, stash them in a signed cookie, redirect to the IdP."""
    cfg = _cfg()
    client = request.client.host if request.client else "?"
    check_login_rate(f"sso:{client}")  # same brute-force throttle as password login
    try:
        tx = oidc.new_transaction(next)
        url = oidc.authorization_url(tx, cfg)
    except oidc.OIDCError as e:
        raise HTTPException(502, str(e))
    resp = RedirectResponse(url, status_code=307)
    resp.set_cookie(oidc.TX_COOKIE, oidc.seal_tx(tx), max_age=oidc.TX_TTL, httponly=True,
                    samesite="lax", secure=get_settings().hosted, path="/api/auth/sso")
    return resp


@router.get("/callback")
def sso_callback(request: Request, code: str = "", state: str = "",
                 error: str = "", db: Session = Depends(get_db)):
    """Finish a login. Every failure here is a refusal — never a fallback to a weaker check."""
    cfg = _cfg()
    if error:
        raise HTTPException(400, f"The identity provider refused the login: {error}")

    tx = oidc.open_tx(request.cookies.get(oidc.TX_COOKIE) or "")
    if not tx:
        raise HTTPException(400, "This sign-in link has expired or was opened in a different browser. "
                                 "Start again from the login page.")
    # CSRF: the state in the URL must be the one we minted into this browser's cookie...
    if not code or not state or not hmac.compare_digest(state, tx["state"]):
        raise HTTPException(400, "The sign-in response did not match this browser's login attempt.")
    # ...and it must not have been used before, so a captured callback URL cannot be replayed.
    if not oidc.consume_state(state):
        raise HTTPException(400, "This sign-in response has already been used.")

    try:
        user = oidc.login_with_code(db, code, tx["verifier"], tx["nonce"], cfg)
    except oidc.OIDCError as e:
        raise HTTPException(403, str(e))

    target = get_settings().web_base_url.rstrip("/") + oidc.safe_next(tx.get("next"))
    resp = RedirectResponse(target, status_code=303)
    resp.set_cookie(auth.COOKIE, auth.make_token(user.id, ver=user.token_version),
                    max_age=auth._TTL, httponly=True, samesite="lax",
                    secure=get_settings().hosted, path="/")
    resp.delete_cookie(oidc.TX_COOKIE, path="/api/auth/sso")  # the transaction is spent
    return resp
