"""Masking helpers for secret values in API responses and persisted records."""
from __future__ import annotations

MASK = "••••••"

# Header keys whose values are secrets — masked in API responses and run history.
SECRET_HEADERS = {"authorization", "x-api-key", "api-key", "cookie", "x-auth-token", "proxy-authorization"}


def mask_value(v) -> str:
    s = str(v)
    return MASK + s[-4:] if len(s) > 4 else MASK


def mask_headers(headers: dict) -> dict:
    return {k: (mask_value(v) if k.lower() in SECRET_HEADERS and v else v) for k, v in headers.items()}


def is_masked(v) -> bool:
    return isinstance(v, str) and v.startswith(MASK)
