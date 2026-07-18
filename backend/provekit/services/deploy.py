"""API-key helpers: mint a bearer key (shown once) and verify it by hash."""
from __future__ import annotations

import hashlib
import hmac
import secrets


def new_api_key() -> tuple[str, str]:
    """Return (plaintext, hash). Plaintext is shown to the user exactly once."""
    key = "agm_" + secrets.token_urlsafe(32)
    return key, hash_key(key)


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def verify_key(key: str, key_hash: str) -> bool:
    return hmac.compare_digest(hash_key(key), key_hash)
