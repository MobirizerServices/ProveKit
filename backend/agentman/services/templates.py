"""Bundled flow templates — the searchable gallery served to the New-flow picker."""
from __future__ import annotations

import json
import pathlib
from functools import lru_cache

from . import testfile

_DIR = pathlib.Path(__file__).resolve().parent.parent / "templates" / "flows"


@lru_cache
def _manifest() -> list[dict]:
    f = _DIR / "_manifest.json"
    return json.loads(f.read_text()) if f.exists() else []


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
    """Return the parsed .agentman flow doc for a template slug (None if unknown)."""
    # Reject separators/traversal (incl. Windows drive-relative "C:foo"), then confirm the
    # resolved path stays inside the templates dir before reading.
    if not slug or any(ch in slug for ch in ("/", "\\", ":")) or ".." in slug:
        return None
    f = (_DIR / f"{slug}.yaml").resolve()
    if _DIR not in f.parents or not f.exists():
        return None
    return testfile.load(f.read_text())
