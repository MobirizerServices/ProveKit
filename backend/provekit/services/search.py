"""Full-text search over span content.

Search used to be `ILIKE '%term%'` over `CAST(request AS TEXT)` and `CAST(result AS TEXT)`.
Three problems, in increasing order of seriousness: a leading-wildcard LIKE cannot use an
index, casting JSON to text does it per row per query, and searching the *whole* JSON blob
matches on keys and structure (`"model"`, `"meta"`) as readily as on anything a model said.

So each span carries a `search_text` column — label plus the human-meaningful input and
output, flattened once at write time — and Postgres indexes `to_tsvector('english', …)` with
GIN. Written once per span instead of parsed on every query.

**The column is built after redaction, never before.** `redact.scrub_run` masks PII in the
request/result before storage; deriving the search column from the pre-redaction row would
copy exactly the values redaction exists to remove into a new column, and then index them for
fast retrieval. That would make PII *easier* to find while the feature reported itself as on.
`text_for` therefore takes the row as it is about to be persisted.

SQLite (dev and tests) has no tsvector. It falls back to LIKE — still unindexed, but against
one narrow text column rather than two JSON casts, and dev datasets are small. The dialect
split lives in `clause()` so callers don't branch.
"""
from __future__ import annotations

import json

from sqlalchemy import String, and_, cast, func, literal, or_

from ..models import Run

#: The text-search configuration. A literal rather than a bind parameter because Postgres
#: requires a constant regcfg here for the expression to match the functional GIN index —
#: a bound value silently produces a sequential scan instead.
_ENGLISH = literal("english")

#: Cap per span. Long enough for a real prompt and answer, short enough that one pathological
#: payload can't dominate the index. Postgres also refuses tsvector entries past ~1MB.
_MAX = 16000


def _flatten(value, out: list[str], depth: int = 0) -> None:
    """Collect the leaf *values* of a JSON payload — not its keys.

    Keys are schema, and matching on them is how a search for "model" used to return every
    LLM span in the project.
    """
    if depth > 6 or len(out) > 400:
        return
    if isinstance(value, str):
        out.append(value)
    elif isinstance(value, (int, float)):
        out.append(str(value))
    elif isinstance(value, dict):
        for v in value.values():
            _flatten(v, out, depth + 1)
    elif isinstance(value, (list, tuple)):
        for v in value:
            _flatten(v, out, depth + 1)


def text_for(row: dict) -> str:
    """Searchable text for a span row, as it will be stored (i.e. already redacted)."""
    parts: list[str] = []
    label = row.get("label")
    if label:
        parts.append(str(label))
    for key in ("request", "result"):
        blob = row.get(key)
        if isinstance(blob, str):
            try:
                blob = json.loads(blob)
            except ValueError:
                parts.append(blob)
                continue
        _flatten(blob, parts)
    err = row.get("error")
    if err:
        parts.append(str(err))
    return " ".join(p for p in parts if p)[:_MAX]


def is_postgres(db) -> bool:
    return db.bind.dialect.name == "postgresql"


def clause(db, term: str):
    """A predicate matching spans whose content contains `term`.

    Postgres gets the indexed `@@` search; everything else gets LIKE against `search_text`,
    which is still a scan but over one narrow column rather than two JSON casts.

    Both dialects also fall back to the old JSON columns *for rows the backfill hasn't reached*
    (`search_text IS NULL`). Dropping those from results would look exactly like data loss to
    anyone searching their own history, and the NULL guard keeps the expensive half off every
    row that has already been converted.
    """
    return postgres_clause(term) if is_postgres(db) else sqlite_clause(term)


def _legacy_clause(like: str):
    """The pre-`search_text` scan, applied only to rows that have no search_text yet."""
    return and_(Run.search_text.is_(None),
                or_(Run.label.ilike(like),
                    cast(Run.request, String).ilike(like),
                    cast(Run.result, String).ilike(like)))


def postgres_clause(term: str):
    term = term.strip()
    indexed = func.to_tsvector(_ENGLISH, func.coalesce(Run.search_text, "")).op("@@")(
        func.plainto_tsquery(_ENGLISH, term))
    return or_(indexed, _legacy_clause(f"%{term}%"))


def sqlite_clause(term: str):
    like = f"%{term.strip()}%"
    return or_(Run.search_text.ilike(like), _legacy_clause(like))
