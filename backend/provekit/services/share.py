"""Shareable trace links: a stateless, HMAC-signed token that names one (workspace, trace).

No storage — the token carries the identifiers and a signature over them, so a public
read endpoint can verify it without a login. Signed with the app secret (namespaced so a
share token can never be mistaken for a session), so links can't be forged or edited.
"""
from __future__ import annotations

import base64
import hashlib
import hmac

from .auth import _secret


def _share_key() -> bytes:
    return hashlib.sha256(b"share:" + _secret()).digest()


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def make_share_token(ws_id: int, trace_id: str) -> str:
    payload = _b64(f"{ws_id}:{trace_id}".encode())
    sig = _b64(hmac.new(_share_key(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{sig}"


def verify_share_token(token: str) -> tuple[int, str] | None:
    """Return (workspace_id, trace_id) if the token is authentic, else None."""
    try:
        payload, sig = token.split(".", 1)
        expected = _b64(hmac.new(_share_key(), payload.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(expected, sig):
            return None
        ws_id, trace_id = _unb64(payload).decode().split(":", 1)
        return int(ws_id), trace_id
    except (ValueError, TypeError):
        return None
