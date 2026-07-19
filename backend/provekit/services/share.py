"""Shareable trace links: a stateless, HMAC-signed token that names one (workspace, trace).

No storage — the token carries the identifiers and a signature over them, so a public
read endpoint can verify it without a login. Signed with the app secret (namespaced so a
share token can never be mistaken for a session), so links can't be forged or edited.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import time

DEFAULT_TTL_DAYS = 30


def _share_key() -> bytes:
    from .auth import _secret
    return hashlib.sha256(b"share:" + _secret()).digest()


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def make_share_token(ws_id: int, trace_id: str, ttl_days: int = DEFAULT_TTL_DAYS) -> str:
    """A signed link that expires. The payload carries an absolute expiry (epoch seconds);
    ttl_days<=0 mints a non-expiring link."""
    exp = 0 if ttl_days <= 0 else int(time.time()) + ttl_days * 86400
    payload = _b64(f"{ws_id}:{trace_id}:{exp}".encode())
    sig = _b64(hmac.new(_share_key(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{sig}"


def verify_share_token(token: str) -> tuple[int, str] | None:
    """Return (workspace_id, trace_id) for an authentic, unexpired token, else None."""
    try:
        payload, sig = token.split(".", 1)
        expected = _b64(hmac.new(_share_key(), payload.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(expected, sig):
            return None
        parts = _unb64(payload).decode().split(":")
        # New tokens are ws:trace:exp; tolerate legacy ws:trace (no expiry).
        ws_id, trace_id = parts[0], parts[1]
        exp = int(parts[2]) if len(parts) > 2 else 0
        if exp and time.time() > exp:
            return None    # expired
        return int(ws_id), trace_id
    except (ValueError, TypeError, IndexError):
        return None
