"""Bundled flow templates — the searchable gallery served to the New-flow picker."""
from __future__ import annotations

import json
import pathlib
from functools import lru_cache

from . import testfile

_DIR = pathlib.Path(__file__).resolve().parent.parent / "templates" / "flows"

# A small, hand-picked showcase surfaced at the top of the New-flow picker. The gallery is a
# regular 24-domain × 18-pattern grid (432 entries), which reads as a wall of near-duplicates;
# these are eight *distinct patterns* across eight *distinct domains* — each a different
# capability (branching, self-critique, structured output, safety gate, numeric gate,
# language routing) — so a newcomer sees a few great starting points instead of everything.
_FEATURED = [
    "customer-support-triage-route",
    "sales-lead-draft-critique-revise",
    "healthcare-intake-extract-to-json",
    "content-moderation-moderation-gate",
    "legal-intake-summarize-then-decide",
    "e-commerce-sentiment-route",
    "recruiting-score-gate",
    "travel-language-route",
]


@lru_cache
def _manifest() -> list[dict]:
    f = _DIR / "_manifest.json"
    return json.loads(f.read_text()) if f.exists() else []


def featured() -> list[dict]:
    """The curated showcase, in order. Skips any slug missing from the manifest so a
    renamed template can't break the picker."""
    by_slug = {m["slug"]: m for m in _manifest()}
    return [by_slug[s] for s in _FEATURED if s in by_slug]


def search(q: str = "", limit: int = 60) -> list[dict]:
    """Filter templates by a case-insensitive substring over name/description/category."""
    items = _manifest()
    q = (q or "").strip().lower()
    if q:
        items = [m for m in items
                 if q in m["name"].lower() or q in m["description"].lower() or q in m["category"].lower()]
    return items[:limit]


def categories() -> list[str]:
    return sorted({m["category"] for m in _manifest()})


def total() -> int:
    return len(_manifest())


def load(slug: str) -> dict | None:
    """Return the parsed .provekit flow doc for a template slug (None if unknown)."""
    # Reject separators/traversal (incl. Windows drive-relative "C:foo"), then confirm the
    # resolved path stays inside the templates dir before reading.
    if not slug or any(ch in slug for ch in ("/", "\\", ":")) or ".." in slug:
        return None
    f = (_DIR / f"{slug}.yaml").resolve()
    if _DIR not in f.parents or not f.exists():
        return None
    return testfile.load(f.read_text())
