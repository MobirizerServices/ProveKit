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
    out, _ = redact_text_counted(text)
    return out


def redact_text_counted(text: str | None) -> tuple[str | None, dict[str, int]]:
    """`redact_text`, plus how many matches of each type were replaced.

    The counts exist so a span can say it was masked. These patterns have false positives —
    the PHONE rule in particular will eat any long digit run — and when that mangles a real
    output, the visible result is a model that appears to have produced nonsense. Recording
    what the masker did makes that traceable to the masker instead of blamed on the model.
    """
    if not text or not isinstance(text, str):
        return text, {}
    out = text
    counts: dict[str, int] = {}
    for label, pat in _PATTERNS:
        out, n = pat.subn(f"[REDACTED_{label}]", out)
        if n:
            counts[label] = counts.get(label, 0) + n
    return out, counts


def scrub_run(kw: dict) -> dict:
    """Redact the free-text fields of a Run kwargs dict (input, output text, error) in place.

    Also stamps `result.meta.redaction` with the fields touched and the per-type match counts,
    so the portal can badge the span. A span that was silently altered between what the agent
    produced and what you are reading is the kind of thing an observability tool must not do
    without saying so.
    """
    touched: dict[str, dict[str, int]] = {}

    req = kw.get("request")
    if isinstance(req, dict) and req.get("input"):
        req["input"], n = redact_text_counted(req["input"])
        if n:
            touched["input"] = n
    res = kw.get("result")
    if isinstance(res, dict) and res.get("text"):
        res["text"], n = redact_text_counted(res["text"])
        if n:
            touched["output"] = n
    if kw.get("error"):
        kw["error"], n = redact_text_counted(kw["error"])
        if n:
            touched["error"] = n

    if touched and isinstance(res, dict):
        meta = res.setdefault("meta", {})
        if isinstance(meta, dict):
            meta["redaction"] = {"fields": sorted(touched), "counts": touched}
    return kw
