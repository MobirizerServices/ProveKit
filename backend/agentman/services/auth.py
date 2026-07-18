"""Authentication: password hashing (PBKDF2), signed session tokens (HS256), and the
get_current_user dependency.

Local mode (HOSTED=false): auth is optional — an unauthenticated request is transparently
the built-in `local@agentman` user, so single-user local use needs no login.
Hosted mode (HOSTED=true): a valid session cookie is required; unauthenticated → 401.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

from fastapi import Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..models import User

COOKIE = "agm_session"
_TTL = 30 * 24 * 3600
LOCAL_EMAIL = "local@agentman"


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _secret() -> bytes:
    s = get_settings().secret_key
    if s:
        return hashlib.sha256(("jwt:" + s).encode()).digest()
    # Local: reuse the sealing key material so tokens are stable across restarts.
    from .sealing import _fernet
    return hashlib.sha256(b"jwt:" + _fernet()._signing_key).digest()


# ---- passwords (PBKDF2-HMAC-SHA256, stdlib) ----
def hash_password(pw: str, *, iterations: int = 200_000) -> str:
    import os
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, iterations)
    return f"pbkdf2${iterations}${_b64(salt)}${_b64(dk)}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        algo, iters, salt, dk = stored.split("$")
        assert algo == "pbkdf2"
        expected = hashlib.pbkdf2_hmac("sha256", pw.encode(), _unb64(salt), int(iters))
        return hmac.compare_digest(expected, _unb64(dk))
    except (ValueError, AssertionError):
        return False


# Verify against this when the account is missing/OAuth-only, so the not-found login branch
# spends the same PBKDF2 time as a real check and doesn't leak account existence via timing.
DUMMY_HASH = hash_password("agentman-timing-equalizer")


# ---- signed tokens (compact HS256 JWT). purpose separates sessions from reset/verify;
# ver binds the token to the user's token_version so a password reset revokes old tokens. ----
def make_token(uid: int, ttl: int = _TTL, purpose: str = "session", ver: int = 0) -> str:
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = _b64(json.dumps({"uid": uid, "exp": int(time.time()) + ttl, "p": purpose, "v": ver},
                              separators=(",", ":")).encode())
    signing_input = f"{header}.{payload}".encode()
    sig = _b64(hmac.new(_secret(), signing_input, hashlib.sha256).digest())
    return f"{header}.{payload}.{sig}"


def read_token(token: str, purpose: str = "session") -> tuple[int, int] | None:
    """Verify signature/expiry/purpose and return (user_id, token_version), else None. The
    caller checks token_version against the user so revoked tokens are rejected."""
    try:
        header, payload, sig = token.split(".")
        expected = _b64(hmac.new(_secret(), f"{header}.{payload}".encode(), hashlib.sha256).digest())
        # compare_digest raises TypeError on a non-ASCII signature segment — treat as invalid.
        if not hmac.compare_digest(expected, sig):
            return None
        data = json.loads(_unb64(payload))
        if data.get("exp", 0) < time.time():
            return None
        if data.get("p", "session") != purpose:  # a reset token can't be used as a session
            return None
        return int(data["uid"]), int(data.get("v", 0))
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None


def _local_user(db: Session) -> User:
    u = db.query(User).filter(User.email == LOCAL_EMAIL).first()
    if u:
        return u
    u = User(email=LOCAL_EMAIL, name="Local", auth_provider="local")
    db.add(u)
    try:
        db.commit()
    except IntegrityError:
        # A concurrent first request created it (the mount fires several requests at once);
        # the unique-email constraint rejects the loser — fall back to the row that won.
        db.rollback()
        winner = db.query(User).filter(User.email == LOCAL_EMAIL).first()
        if winner is None:
            # Not the race we assumed: some other integrity failure. Returning None here
            # would surface as an opaque AttributeError deep in workspace resolution.
            raise
        return winner
    db.refresh(u)
    return u


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(COOKIE)
    claims = read_token(token) if token else None
    if claims is not None:
        uid, ver = claims
        u = db.get(User, uid)
        if u and u.token_version == ver:  # reject sessions revoked by a password reset
            return u
    if not get_settings().hosted:
        return _local_user(db)  # local mode: no login required
    raise HTTPException(401, "Authentication required")
