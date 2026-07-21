"""Significance testing for experiment comparisons.

An eval stack that reports two means and no uncertainty invites teams to ship on noise: 0.82
vs 0.79 over 20 examples is nothing, and over 2,000 it may be decisive. Nothing in the numbers
themselves says which situation you're in.

Two deliberate choices:

**Permutation tests, not t-tests.** A t-test needs the incomplete beta function for its
p-value, which means either SciPy (a heavy dependency for one number) or a hand-rolled special
function that nobody can review. A permutation test needs only resampling, makes no normality
assumption — scores are frequently 0/1 or otherwise very non-normal — and is easy to explain:
*if the labels were arbitrary, how often would chance alone produce a gap this big?*

**Paired by default.** Two experiments on one dataset score the *same items*, so the per-item
difference removes item difficulty from the comparison entirely. That is far more powerful
than treating the runs as independent samples, and it is the case that actually occurs when
comparing prompt A to prompt B. Pairing needs matching `item_id`s; without them we fall back
to an unpaired test and say so.

Seeded, so the same inputs always give the same p-value — an eval you can't reproduce is not
evidence.
"""
from __future__ import annotations

import math
import random

# Enough resolution to distinguish p=0.01 from p=0.06 without making the endpoint slow.
PERMUTATIONS = 10_000
SEED = 20260721
ALPHA = 0.05
# Below this, a permutation test cannot reach p<0.05 no matter how large the gap: with n
# paired items there are only 2^n sign assignments, so the smallest attainable p is 2^-n.
MIN_PAIRED_N = 8


def mean(xs: list[float]) -> float | None:
    return (sum(xs) / len(xs)) if xs else None


def stdev(xs: list[float]) -> float | None:
    """Sample standard deviation (n-1). None below two points, where it's undefined."""
    if len(xs) < 2:
        return None
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def sem(xs: list[float]) -> float | None:
    sd = stdev(xs)
    return None if sd is None else sd / math.sqrt(len(xs))


def ci95(xs: list[float]) -> tuple[float, float] | None:
    """Normal-approximation 95% interval for the mean.

    1.96 rather than a t critical value: below ~30 points the difference is dwarfed by the
    uncertainty the interval is already reporting, and the significance verdict comes from the
    permutation test, not from this.
    """
    m, se = mean(xs), sem(xs)
    if m is None or se is None:
        return None
    return (m - 1.96 * se, m + 1.96 * se)


def summarize(xs: list[float]) -> dict:
    lo_hi = ci95(xs)
    return {"n": len(xs), "mean": mean(xs), "stdev": stdev(xs),
            "ci95_low": lo_hi[0] if lo_hi else None,
            "ci95_high": lo_hi[1] if lo_hi else None}


def _paired_p(diffs: list[float], rng: random.Random) -> float:
    """Sign-flip permutation test on paired differences.

    Under the null the two runs are interchangeable per item, so each difference is equally
    likely to have carried the opposite sign.
    """
    observed = abs(sum(diffs) / len(diffs))
    if observed == 0:
        return 1.0
    hits = 0
    for _ in range(PERMUTATIONS):
        total = 0.0
        for d in diffs:
            total += d if rng.random() < 0.5 else -d
        if abs(total / len(diffs)) >= observed - 1e-12:
            hits += 1
    # +1 in both places: the observed arrangement is itself one of the possibilities, and this
    # keeps p from ever being reported as exactly 0, which no finite test can establish.
    return (hits + 1) / (PERMUTATIONS + 1)


def _unpaired_p(a: list[float], b: list[float], rng: random.Random) -> float:
    """Label-shuffling permutation test for two independent samples."""
    observed = abs(sum(a) / len(a) - sum(b) / len(b))
    if observed == 0:
        return 1.0
    pool = a + b
    cut = len(a)
    hits = 0
    for _ in range(PERMUTATIONS):
        rng.shuffle(pool)
        left = sum(pool[:cut]) / cut
        right = sum(pool[cut:]) / (len(pool) - cut)
        if abs(left - right) >= observed - 1e-12:
            hits += 1
    return (hits + 1) / (PERMUTATIONS + 1)


def compare(a: list[float], b: list[float], *, pairs: list[tuple[float, float]] | None = None
            ) -> dict:
    """Compare scorer values from experiment A against experiment B.

    `pairs` are per-item (a_value, b_value) for items present in both runs; when supplied the
    test is paired. Returns the deltas, a p-value, and — importantly — a `caution` explaining
    when the answer should not be trusted, because "not significant" and "not enough data to
    tell" are different findings that a bare p-value conflates.
    """
    rng = random.Random(SEED)
    out = {
        "a": summarize(a),
        "b": summarize(b),
        "paired": bool(pairs),
        "paired_n": len(pairs) if pairs else 0,
        "p_value": None,
        "significant": False,
        "delta": None,
        "caution": "",
    }
    ma, mb = mean(a), mean(b)
    out["delta"] = None if (ma is None or mb is None) else mb - ma

    if pairs:
        diffs = [y - x for x, y in pairs]
        out["delta"] = mean(diffs)
        d_sum = summarize(diffs)
        out["delta_ci95_low"], out["delta_ci95_high"] = d_sum["ci95_low"], d_sum["ci95_high"]
        if len(diffs) < 2:
            out["caution"] = "Too few overlapping items to test."
            return out
        out["p_value"] = _paired_p(diffs, rng)
        if len(diffs) < MIN_PAIRED_N:
            out["caution"] = (
                f"Only {len(diffs)} paired items — with fewer than {MIN_PAIRED_N} no result can "
                f"reach p<{ALPHA}, however large the difference. Add examples.")
    else:
        if len(a) < 2 or len(b) < 2:
            out["caution"] = "Too few results to test."
            return out
        out["p_value"] = _unpaired_p(list(a), list(b), rng)
        out["caution"] = ("No overlapping item ids, so the runs were compared as independent "
                          "samples. Scoring both over the same dataset items detects smaller "
                          "differences.")

    out["significant"] = out["p_value"] is not None and out["p_value"] < ALPHA
    if out["p_value"] is not None and not out["significant"] and not out["caution"]:
        out["caution"] = ("Not distinguishable from chance at this sample size — which is not "
                          "the same as the runs being equal.")
    return out
