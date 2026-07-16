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


# ---- session tokens (compact HS256 JWT) ----
def make_token(uid: int, ttl: int = _TTL) -> str:
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = _b64(json.dumps({"uid": uid, "exp": int(time.time()) + ttl}, separators=(",", ":")).encode())
    signing_input = f"{header}.{payload}".encode()
    sig = _b64(hmac.new(_secret(), signing_input, hashlib.sha256).digest())
    return f"{header}.{payload}.{sig}"


def read_token(token: str) -> int | None:
    try:
        header, payload, sig = token.split(".")
        expected = _b64(hmac.new(_secret(), f"{header}.{payload}".encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(expected, sig):
            return None
        data = json.loads(_unb64(payload))
        if data.get("exp", 0) < time.time():
            return None
        return int(data["uid"])
    except (ValueError, KeyError, json.JSONDecodeError):
        return None


def _local_user(db: Session) -> User:
    u = db.query(User).filter(User.email == LOCAL_EMAIL).first()
    if not u:
        u = User(email=LOCAL_EMAIL, name="Local", auth_provider="local")
        db.add(u); db.commit(); db.refresh(u)
    return u


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(COOKIE)
    uid = read_token(token) if token else None
    if uid is not None:
        u = db.get(User, uid)
        if u:
            return u
    if not get_settings().hosted:
        return _local_user(db)  # local mode: no login required
    raise HTTPException(401, "Authentication required")
