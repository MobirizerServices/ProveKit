"""Scorers — pure functions that grade an output against an expected value, returning a
float in [0, 1]. Deliberately dependency-free so the SAME module runs in the evaluation
SDK (client-side, in pk.evaluate) and on the server. Pass scorers to pk.evaluate() by name
(e.g. "exact_match") or as your own `fn(output, expected) -> float`.
"""
from __future__ import annotations

import json
import re


def exact_match(output: str, expected: str) -> float:
    """1.0 if output equals expected (trimmed), else 0.0."""
    return 1.0 if (output or "").strip() == (expected or "").strip() else 0.0


def contains(output: str, expected: str) -> float:
    """1.0 if expected appears in output (case-insensitive), else 0.0."""
    return 1.0 if expected and expected.lower() in (output or "").lower() else 0.0


def regex_match(output: str, expected: str) -> float:
    """1.0 if the expected regex matches output, else 0.0. (expected is the pattern.)"""
    try:
        return 1.0 if expected and re.search(expected, output or "") else 0.0
    except re.error:
        return 0.0


def json_valid(output: str, expected: str = "") -> float:
    """1.0 if output parses as JSON, else 0.0 (expected is ignored)."""
    try:
        json.loads(output)
        return 1.0
    except (ValueError, TypeError):
        return 0.0


# The named registry pk.evaluate() and the portal resolve string scorer names against.
SCORERS = {
    "exact_match": exact_match,
    "contains": contains,
    "regex_match": regex_match,
    "json_valid": json_valid,
}


def run_scorers(scorers, output: str, expected: str) -> dict[str, float]:
    """Apply each scorer (a name or a callable) to (output, expected) → {name: score}.
    Unknown names are skipped; a scorer that raises contributes 0.0."""
    out: dict[str, float] = {}
    for s in scorers or []:
        if callable(s):
            name, fn = getattr(s, "__name__", "scorer"), s
        else:
            name, fn = s, SCORERS.get(s)
        if fn is None:
            continue
        try:
            out[name] = float(fn(output, expected))
        except Exception:
            out[name] = 0.0
    return out
