"""Fernet key material for signing session/reset/verify tokens.

Key source: `SECRET_KEY` (any string, derived to a Fernet key), or — for local SQLite use —
an auto-generated key file next to the database (`.provekit.key`).
"""
from __future__ import annotations

import base64
import hashlib
import logging
import os
from functools import lru_cache
from pathlib import Path

from cryptography.fernet import Fernet

from ..config import get_settings

log = logging.getLogger("provekit.sealing")


def _key_file() -> Path | None:
    url = get_settings().database_url
    if url.startswith("sqlite:///"):
        db_path = Path(url.removeprefix("sqlite:///"))
        parent = db_path.parent if str(db_path.parent) else Path(".")
        return parent / ".provekit.key"
    return None


@lru_cache
def _fernet() -> Fernet:
    s = get_settings()
    if s.secret_key:
        return Fernet(base64.urlsafe_b64encode(hashlib.sha256(s.secret_key.encode()).digest()))
    kf = _key_file()
    if kf is None:
        raise RuntimeError("SECRET_KEY must be set when not using a local SQLite database")
    if kf.exists():
        return Fernet(kf.read_bytes().strip())
    key = Fernet.generate_key()
    kf.parent.mkdir(parents=True, exist_ok=True)
    kf.write_bytes(key)
    try:
        os.chmod(kf, 0o600)
    except OSError:
        pass
    log.info("generated local key at %s", kf)
    return Fernet(key)


def seal(plaintext: str) -> str:
    """Encrypt a secret (e.g. a provider API key) for storage at rest. Reversible by `unseal`."""
    return _fernet().encrypt(plaintext.encode()).decode()


def unseal(token: str) -> str:
    """Decrypt a value sealed by `seal`. Raises cryptography.fernet.InvalidToken if tampered."""
    return _fernet().decrypt(token.encode()).decode()


def mask_key(plaintext: str) -> str:
    """A display-safe hint for a secret: last 4 chars, e.g. 'sk-…a1b2'. Never the full value."""
    tail = plaintext[-4:] if len(plaintext) >= 4 else plaintext
    return f"…{tail}"
