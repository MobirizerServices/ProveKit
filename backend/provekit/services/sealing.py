"""Encrypt connection secrets at rest (Fernet). Sealed values carry an "enc:" prefix;
plaintext values from older databases are accepted on read and upgraded by the
one-shot reseal pass at startup (and on any subsequent write).

Key source: SECRET_KEY env var (any string — derived to a Fernet key), or, for local
SQLite use, an auto-generated key file stored next to the database (.provekit.key).
Rotation: set the new SECRET_KEY, then re-enter credentials (values sealed with the
old key decrypt to "" with a logged warning rather than crashing).
"""
from __future__ import annotations

import base64
import hashlib
import logging
import os
from functools import lru_cache
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from ..config import get_settings
from .masking import is_secret_header

_PREFIX = "enc:"
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
    log.info("generated local encryption key at %s", kf)
    return Fernet(key)


def seal(value: str) -> str:
    if not value or not isinstance(value, str) or value.startswith(_PREFIX):
        return value
    return _PREFIX + _fernet().encrypt(value.encode()).decode()


def unseal(value):
    if not isinstance(value, str) or not value.startswith(_PREFIX):
        return value
    try:
        return _fernet().decrypt(value[len(_PREFIX):].encode()).decode()
    except (InvalidToken, ValueError):
        log.warning("could not decrypt a stored secret (SECRET_KEY changed?) — treating as unset")
        return ""


def seal_config(cfg: dict) -> dict:
    """Encrypt the secret fields of a connection config: api_key, secret headers,
    the MCP OAuth client_secret, and stdio env values (which routinely carry tokens)."""
    out = dict(cfg)
    if out.get("api_key"):
        out["api_key"] = seal(out["api_key"])
    hdrs = out.get("headers")
    if isinstance(hdrs, dict):
        out["headers"] = {k: (seal(v) if is_secret_header(k) and isinstance(v, str) and v else v)
                          for k, v in hdrs.items()}
    oauth = out.get("oauth")
    if isinstance(oauth, dict) and oauth.get("client_secret"):
        out["oauth"] = {**oauth, "client_secret": seal(oauth["client_secret"])}
    env = out.get("env")
    if isinstance(env, dict):
        out["env"] = {k: (seal(v) if isinstance(v, str) and v else v) for k, v in env.items()}
    return out


def unseal_config(cfg: dict) -> dict:
    out = dict(cfg)
    if out.get("api_key"):
        out["api_key"] = unseal(out["api_key"])
    hdrs = out.get("headers")
    if isinstance(hdrs, dict):
        out["headers"] = {k: unseal(v) for k, v in hdrs.items()}
    oauth = out.get("oauth")
    if isinstance(oauth, dict) and "client_secret" in oauth:
        out["oauth"] = {**oauth, "client_secret": unseal(oauth.get("client_secret"))}
    env = out.get("env")
    if isinstance(env, dict):
        out["env"] = {k: unseal(v) for k, v in env.items()}
    return out
