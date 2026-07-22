"""Read-only "view as tenant" support sessions.

A support request that starts with "can you screenshot what you see?" takes a day. One where
the operator can look at the tenant's traces takes five minutes. The feature is easy; the
security properties are the product:

1. **One way to be authenticated.** The impersonation flag rides *inside the normal signed
   session token* (an extra `imp` claim), so `auth.read_token` still resolves the cookie to
   the operator's own user id. There is no second credential to forget to guard, and the
   operator's identity never becomes the tenant's — every audit row and every permission check
   still sees the human who is actually looking.
2. **Read only, server-side.** `ReadOnlyImpersonation` (an ASGI middleware, registered once in
   main.py) refuses every non-safe method while the cookie carries an `imp` claim. Hiding the
   buttons is not enforcement.
3. **No cross-tenant reach.** `workspace.current_workspace` does *not* look at `imp`, so the
   ordinary APIs keep resolving to the operator's own project even mid-impersonation. The
   tenant's data is reachable only through the explicitly read-only `/api/admin/impersonate/*`
   endpoints, which re-check operator status on every request.
4. **Time-bounded by the signature.** The impersonation deadline *is* the token's `exp`, not a
   claim next to it, so an expired support session can't be replayed — it stops being a valid
   session at all. Support mode that silently persists is how a support tool becomes an
   incident.

Start and stop are both audited (services/audit.py) with actor, target project and IP.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass

from fastapi import Request, Response
from starlette.requests import Request as ASGIRequest
from starlette.responses import JSONResponse

from ..config import get_settings
from ..models import User
from . import auth

# Audit actions. They live here rather than in services/audit.py only because that module is
# owned elsewhere in this change; move them next to the other constants when convenient.
START = "impersonation.start"
STOP = "impersonation.stop"

DEFAULT_MINUTES = 15
MAX_MINUTES = 60

# Methods that cannot change state. Everything else is refused while impersonating, except the
# one route that *ends* impersonation — which has to stay reachable or the only way out of
# support mode would be waiting for the cookie to expire.
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
STOP_ROUTE = ("DELETE", "/api/admin/impersonate")


@dataclass(frozen=True)
class Claim:
    """The verified impersonation payload of a session cookie."""
    user_id: int
    workspace_id: int
    expires_at: int         # unix seconds; the session token's own exp

    @property
    def seconds_remaining(self) -> int:
        return max(0, int(self.expires_at - time.time()))


def issue(user: User, workspace_id: int, seconds: int) -> str:
    """Mint a session token for `user` that also carries an impersonation claim.

    The payload mirrors `auth.make_token` exactly and adds `imp`; `auth.make_token` takes no
    extra claims, so the four signing lines are repeated rather than reaching across into it.
    `test_impersonation_token_is_an_ordinary_session` asserts the two can't drift apart.
    """
    payload = {"uid": user.id, "exp": int(time.time()) + seconds, "p": "session",
               "v": user.token_version, "imp": int(workspace_id)}
    header = auth._b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body = auth._b64(json.dumps(payload, separators=(",", ":")).encode())
    sig = auth._b64(hmac.new(auth._secret(), f"{header}.{body}".encode(), hashlib.sha256).digest())
    return f"{header}.{body}.{sig}"


def claim_from_token(token: str | None) -> Claim | None:
    """The impersonation claim of a token, or None if it has none / isn't a valid session.

    Signature, expiry and purpose are checked by `auth.read_token` — this only re-reads the
    payload it already validated, so there is exactly one implementation of "is this token
    real". Token *version* is not checked here (that needs the user row); `get_current_user`
    does it on the same cookie, and the callers below run after it.
    """
    if not token:
        return None
    verified = auth.read_token(token)
    if verified is None:
        return None
    try:
        payload = json.loads(auth._unb64(token.split(".")[1]))
        ws_id = int(payload["imp"])
        return Claim(user_id=verified[0], workspace_id=ws_id, expires_at=int(payload["exp"]))
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None


def claim(request: Request | ASGIRequest) -> Claim | None:
    """The impersonation claim carried by this request's session cookie, if any."""
    return claim_from_token(request.cookies.get(auth.COOKIE))


def _cookie(response: Response, token: str, max_age: int) -> None:
    response.set_cookie(auth.COOKIE, token, max_age=max_age, httponly=True,
                        samesite="lax", secure=get_settings().hosted, path="/")


def set_impersonation_cookie(response: Response, token: str, seconds: int) -> None:
    """Swap the operator's session for the impersonating one. Same cookie, same flags — the
    browser cannot hold both, so there is no way to be half in and half out of support mode."""
    _cookie(response, token, seconds)


def restore_session_cookie(response: Response, user: User) -> None:
    """Put the operator back in their own (full-length, unimpersonated) session."""
    _cookie(response, auth.make_token(user.id, ver=user.token_version), auth._TTL)


class ReadOnlyImpersonation:
    """Refuse every write while a request's session is impersonating.

    Pure ASGI (like BodySizeLimitMiddleware) so it can be wrapped around the app directly in
    tests, and so a refusal costs nothing on the overwhelming majority of requests that carry
    no impersonation claim.

    This is the enforcement point for "read only". It is deliberately method-based rather than
    a list of protected routes: a new mutating endpoint is safe the day it is written, and
    nobody has to remember to add it here.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["method"] not in _SAFE_METHODS:
            if (scope["method"], scope["path"]) != STOP_ROUTE and claim(ASGIRequest(scope)):
                response = JSONResponse(
                    {"detail": "This session is impersonating a tenant and is read-only. "
                               "Stop impersonation (DELETE /api/admin/impersonate) to make changes."},
                    status_code=403)
                return await response(scope, receive, send)
        await self.app(scope, receive, send)
