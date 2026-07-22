"""PII redaction — mask sensitive strings in captured spans before they're stored.

A safety net for hosted deployments: even if an agent's inputs/outputs contain emails,
card numbers, or secret keys, they don't land in the database in the clear. Off by default
(config.redact_pii); the client can also redact before sending. Best-effort and pattern
based — not a substitute for not logging secrets, but it catches the common cases.
"""
from __future__ import annotations

import re

def _enough_digits(match: str) -> bool:
    """A phone number has at least 9 digits.

    Without this the loose pattern ate ISO dates: "2026-03-11" is eight digits with separators
    and matched exactly. Dates are extremely common in agent output, so this was the single
    highest-volume false positive the corpus found. Nine is chosen because the shortest
    international number in the corpus has eleven and the longest false positive (a date) has
    eight — the gap is where the threshold belongs.
    """
    return sum(c.isdigit() for c in match) >= 9


# (label, compiled pattern, extra validator or None). Order matters: match the most
# specific/greedy first (a card number before a bare digit run). Each match is replaced by
# [REDACTED_<LABEL>]. A validator lets a rule express a condition regexes are bad at —
# counting digits across separators — rather than being tuned into unreadability.
_PATTERNS: list[tuple[str, re.Pattern, object]] = [
    ("EMAIL", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), None),
    # 13-16 digit card numbers, optionally separated by spaces/hyphens. Anchored to end on a
    # digit: the previous form let the trailing separator into the match, so masking ate the
    # following space and glued the replacement onto the next word.
    ("CARD", re.compile(r"\b\d(?:[ -]?\d){12,15}\b"), None),
    ("SSN", re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), None),
    # Provider secret tokens. The body allows internal - and _ because current OpenAI keys are
    # `sk-proj-<blob>`: the previous [A-Za-z0-9]{16,} body stopped dead at the second hyphen,
    # so every project-scoped key passed through completely unmasked. That is the worst class
    # of bug this module can have — a leak that looks exactly like working redaction.
    ("KEY", re.compile(r"\b(?:sk|pk|rk)[-_][A-Za-z0-9][A-Za-z0-9_-]{14,}[A-Za-z0-9]\b"), None),
    ("KEY", re.compile(r"\bAKIA[0-9A-Z]{16}\b"), None),
    ("KEY", re.compile(r"\bgh[posru]_[A-Za-z0-9]{20,}\b"), None),
    # Phone numbers (loose): +CC and 7+ digits with common separators, gated on digit count.
    ("PHONE", re.compile(r"\+?\d[\d ().-]{7,}\d"), _enough_digits),
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
    for label, pat, validator in _PATTERNS:
        hits = 0

        def _sub(m, _label=label, _validator=validator):
            nonlocal hits
            if _validator is not None and not _validator(m.group()):
                return m.group()          # matched the shape, failed the rule — leave it alone
            hits += 1
            return f"[REDACTED_{_label}]"

        out = pat.sub(_sub, out)
        if hits:
            counts[label] = counts.get(label, 0) + hits
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
