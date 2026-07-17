"""Masking helpers for secret values in API responses and persisted records."""
from __future__ import annotations

import re

MASK = "••••••"

# Header keys whose values are secrets — masked in API responses and run history.
SECRET_HEADERS = {"authorization", "x-api-key", "api-key", "cookie", "x-auth-token", "proxy-authorization"}
# Also treat any header whose name looks credential-bearing as secret (e.g. X-Custom-Token),
# so masking isn't limited to the fixed set above.
_SECRET_HEADER_RE = re.compile(r"(authorization|api[-_]?key|secret|token|password|passwd|cookie|credential|session)", re.I)


def is_secret_header(name: str) -> bool:
    n = str(name).lower()
    return n in SECRET_HEADERS or bool(_SECRET_HEADER_RE.search(n))


def mask_value(v) -> str:
    s = str(v)
    return MASK + s[-4:] if len(s) > 4 else MASK


def mask_headers(headers: dict) -> dict:
    return {k: (mask_value(v) if is_secret_header(k) and v else v) for k, v in headers.items()}


def is_masked(v) -> bool:
    return isinstance(v, str) and v.startswith(MASK)


# Body fields whose values look like secrets — masked before persisting to history.
_SECRET_FIELDS = {"api_key", "apikey", "token", "access_token", "refresh_token", "password",
                  "secret", "client_secret", "authorization"}


def mask_body(obj):
    """Recursively mask secret-looking fields in a request/response body for storage."""
    if isinstance(obj, dict):
        return {k: (mask_value(v) if k.lower() in _SECRET_FIELDS and v and isinstance(v, str)
                    else mask_body(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [mask_body(x) for x in obj]
    return obj
