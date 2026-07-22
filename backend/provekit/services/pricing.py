"""Cost estimation, versioned.

Two jobs: cap interactive spend (playground/replay) in real time, and let a cost figure be
re-derived later.

The second is why this is versioned. The table used to be one hardcoded list, so the moment a
vendor repriced, every historical cost silently moved with it — a March run would be re-costed
at July's rates and displayed as though that were what it cost. Not a rounding concern: model
prices have moved by an order of magnitude inside a year, and a dashboard that restates last
quarter's spend whenever this file is edited can't be used for anything that matters.

So tables are keyed by an effective date, a span records the version in force when it was
captured, and re-pricing it later resolves that table. **Changing prices means adding a
version, never editing one.** A released table is a historical record; mutating it rewrites
the past, which is the bug this exists to prevent.

Prices are USD per 1M tokens (input, output). The frontend's lib/cost.ts is still a second
copy of this data — `GET /api/pricing` exists so it can stop being one.
"""
from __future__ import annotations

# version → [(model prefix, input $/1M, output $/1M)]. Prefix match; longest prefix wins.
_TABLES: dict[str, list[tuple[str, float, float]]] = {
    # The rates this file shipped with, preserved verbatim so anything captured before
    # versioning existed still re-prices exactly as it originally did.
    "2025-01-01": [
        ("gpt-4o-mini", 0.15, 0.60),
        ("gpt-4o", 2.50, 10.00),
        ("gpt-4.1-mini", 0.40, 1.60),
        ("gpt-4.1", 2.00, 8.00),
        ("o3-mini", 1.10, 4.40),
        ("gpt-3.5", 0.50, 1.50),
        ("claude-3-5-haiku", 0.80, 4.00),
        ("claude-3-5-sonnet", 3.00, 15.00),
        ("claude-sonnet", 3.00, 15.00),
        ("claude-3-opus", 15.00, 75.00),
        ("claude-opus", 15.00, 75.00),
        ("gemini-1.5-pro", 1.25, 5.00),
        ("gemini", 0.30, 1.20),
    ],
}

#: Stamped onto newly captured spans. Bump by ADDING a table above.
CURRENT_VERSION = "2025-01-01"

#: Applied to a model no table knows. Deliberately mid-range and deliberately not zero: a
#: silent 0.00 reads as "this was free" rather than "we don't know", and the second is true.
_FALLBACK = (1.00, 3.00)


def current_version() -> str:
    return CURRENT_VERSION


def versions() -> list[str]:
    return sorted(_TABLES)


def table(version: str | None = None) -> list[tuple[str, float, float]]:
    """Rates for `version`, falling back to current.

    An unknown version resolves to current rather than raising. A span stamped by a newer
    deployment must not make an older one fail to render a cost — an approximate figure beats
    a 500 on the dashboard, provided the approximation is the documented one.
    """
    return _TABLES.get(version or CURRENT_VERSION) or _TABLES[CURRENT_VERSION]


def rates(model: str | None, version: str | None = None) -> tuple[float, float]:
    """(input, output) $/1M for `model` under `version`; the fallback for unknown models.

    Longest prefix wins, rather than first match in list order. The old code took the first
    hit, which made correctness depend on the literal ordering of the table — put "gpt-4o"
    above "gpt-4o-mini" on some future edit and every mini call silently prices at ~16x.
    """
    m = (model or "").lower()
    best: tuple[float, float] | None = None
    best_len = -1
    for prefix, i, o in table(version):
        if m.startswith(prefix) and len(prefix) > best_len:
            best, best_len = (i, o), len(prefix)
    return best if best is not None else _FALLBACK


def estimate(model: str | None, input_tokens: int | None, output_tokens: int | None,
             *, version: str | None = None) -> float:
    """Estimated USD cost of a completion. `mock`/empty model → 0.0.

    Pass `version` to re-derive a historical cost at the rates that applied when the span was
    captured (spans carry it as `result.meta.price_version`).
    """
    m = (model or "").lower()
    if not m or m == "mock":
        return 0.0
    inp, out = rates(m, version)
    return ((input_tokens or 0) * inp + (output_tokens or 0) * out) / 1_000_000


def as_dict(version: str | None = None) -> dict:
    """Serialisable rates, so a client doesn't have to keep its own copy."""
    v = version if version in _TABLES else CURRENT_VERSION
    return {"version": v, "versions": versions(),
            "fallback": {"input": _FALLBACK[0], "output": _FALLBACK[1]},
            "models": [{"prefix": p, "input": i, "output": o} for p, i, o in table(v)]}
