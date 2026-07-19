"""PII redaction — mask sensitive strings in captured spans before they're stored.

A safety net for hosted deployments: even if an agent's inputs/outputs contain emails,
card numbers, or secret keys, they don't land in the database in the clear. Off by default
(config.redact_pii); the client can also redact before sending. Best-effort and pattern
based — not a substitute for not logging secrets, but it catches the common cases.
"""
from __future__ import annotations

import re

# (label, compiled pattern). Order matters: match the most specific/greedy first (a card
# number before a bare digit run). Each match is replaced by [REDACTED_<LABEL>].
_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("EMAIL", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    # 13-16 digit card numbers, optionally separated by spaces/hyphens.
    ("CARD", re.compile(r"\b(?:\d[ -]?){13,16}\b")),
    ("SSN", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    # OpenAI-style / ProveKit / AWS / generic long secret tokens.
    ("KEY", re.compile(r"\b(?:sk|pk|rk)[-_][A-Za-z0-9]{16,}\b")),
    ("KEY", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("KEY", re.compile(r"\bgh[posru]_[A-Za-z0-9]{20,}\b")),
    # Phone numbers (loose): +CC and 7+ digits with common separators.
    ("PHONE", re.compile(r"\+?\d[\d ().-]{7,}\d")),
]


def redact_text(text: str | None) -> str | None:
    """Return `text` with any matched PII replaced by [REDACTED_<TYPE>]. None/empty pass through."""
    if not text or not isinstance(text, str):
        return text
    out = text
    for label, pat in _PATTERNS:
        out = pat.sub(f"[REDACTED_{label}]", out)
    return out


def scrub_run(kw: dict) -> dict:
    """Redact the free-text fields of a Run kwargs dict (input, output text, error) in place."""
    req = kw.get("request")
    if isinstance(req, dict) and req.get("input"):
        req["input"] = redact_text(req["input"])
    res = kw.get("result")
    if isinstance(res, dict) and res.get("text"):
        res["text"] = redact_text(res["text"])
    if kw.get("error"):
        kw["error"] = redact_text(kw["error"])
    return kw
