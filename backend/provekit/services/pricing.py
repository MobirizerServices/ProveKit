"""Server-side cost estimation for interactive re-runs (playground/replay), so spend can be
capped per project. Mirrors the common-model rates in the frontend's lib/cost.ts. Prices are
USD per 1M tokens (input, output); unknown models fall back to a mid-range estimate."""
from __future__ import annotations

# model prefix → (input $/1M, output $/1M). Prefix match so "gpt-4o-2024-.." still resolves.
_PRICES: list[tuple[str, float, float]] = [
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
]
_FALLBACK = (1.00, 3.00)


def estimate(model: str | None, input_tokens: int | None, output_tokens: int | None) -> float:
    """Estimated USD cost of a completion. `mock`/unknown-with-no-tokens → 0.0."""
    m = (model or "").lower()
    if not m or m == "mock":
        return 0.0
    it, ot = (input_tokens or 0), (output_tokens or 0)
    inp, out = _FALLBACK
    for prefix, i, o in _PRICES:
        if m.startswith(prefix):
            inp, out = i, o
            break
    return (it * inp + ot * out) / 1_000_000
