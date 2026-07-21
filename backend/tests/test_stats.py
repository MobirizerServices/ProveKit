"""Significance testing. These assert statistical *correctness*, not just that code runs —
a p-value that's subtly wrong is worse than none, because it launders noise as evidence."""
import random

from provekit.services import stats


def test_summary_matches_hand_computed_values():
    xs = [1.0, 2.0, 3.0, 4.0, 5.0]
    s = stats.summarize(xs)
    assert s["n"] == 5 and s["mean"] == 3.0
    assert abs(s["stdev"] - 1.5811388) < 1e-6          # sample sd (n-1)
    assert abs(s["ci95_low"] - (3.0 - 1.96 * 1.5811388 / 5 ** 0.5)) < 1e-6


def test_stdev_undefined_below_two_points():
    assert stats.stdev([]) is None and stats.stdev([1.0]) is None
    assert stats.summarize([1.0])["ci95_low"] is None


def test_identical_runs_are_never_significant():
    xs = [1.0, 0.0, 1.0, 1.0, 0.0, 1.0, 1.0, 0.0, 1.0, 1.0]
    r = stats.compare(xs, xs, pairs=list(zip(xs, xs)))
    assert r["p_value"] == 1.0 and r["significant"] is False
    assert r["delta"] == 0.0


def test_a_large_consistent_improvement_is_significant():
    """Every one of 30 items improves — chance should essentially never produce that."""
    a = [0.0] * 30
    b = [1.0] * 30
    r = stats.compare(a, b, pairs=list(zip(a, b)))
    assert r["paired"] is True
    assert r["p_value"] < 0.001
    assert r["significant"] is True
    assert r["delta"] == 1.0
    assert r["caution"] == ""


def test_a_tiny_sample_cannot_be_significant_and_says_why():
    """0.8 vs 1.0 over 4 items is the exact shape of a result teams wrongly ship on."""
    a = [1.0, 1.0, 0.0, 1.0]
    b = [1.0, 1.0, 1.0, 1.0]
    r = stats.compare(a, b, pairs=list(zip(a, b)))
    assert r["significant"] is False
    assert "no result can reach" in r["caution"]
    assert str(stats.MIN_PAIRED_N) in r["caution"]


def test_pure_noise_is_not_significant():
    """The false-positive guard: random data must not read as a real difference."""
    rng = random.Random(7)
    a = [rng.random() for _ in range(60)]
    b = [rng.random() for _ in range(60)]
    r = stats.compare(a, b, pairs=list(zip(a, b)))
    assert r["significant"] is False
    assert r["p_value"] > 0.05


def test_false_positive_rate_is_near_alpha():
    """Across many null experiments, ~5% should cross p<0.05 — the property that makes the
    threshold mean anything. A badly-built test shows up here as a wildly wrong rate."""
    hits = 0
    trials = 60
    for seed in range(trials):
        rng = random.Random(1000 + seed)
        a = [rng.gauss(0.5, 0.2) for _ in range(25)]
        b = [rng.gauss(0.5, 0.2) for _ in range(25)]      # same distribution: null is true
        if stats.compare(a, b, pairs=list(zip(a, b)))["significant"]:
            hits += 1
    assert hits / trials < 0.20, f"false-positive rate {hits}/{trials} is far above alpha"


def test_pairing_detects_a_difference_that_unpaired_misses():
    """The reason pairing is the default: item difficulty dominates the variance, and pairing
    removes it. Same data, two framings, different conclusions."""
    rng = random.Random(3)
    base = [rng.uniform(0, 1) for _ in range(40)]          # wildly varying item difficulty
    a = base
    b = [x + 0.05 for x in base]                           # small, perfectly consistent gain

    paired = stats.compare(a, b, pairs=list(zip(a, b)))
    unpaired = stats.compare(a, b)
    assert paired["significant"] is True
    assert unpaired["significant"] is False
    assert "independent samples" in unpaired["caution"]


def test_p_value_is_reproducible():
    """An eval you can't reproduce isn't evidence."""
    rng = random.Random(11)
    a = [rng.random() for _ in range(30)]
    b = [x + 0.1 for x in a]
    first = stats.compare(a, b, pairs=list(zip(a, b)))["p_value"]
    second = stats.compare(a, b, pairs=list(zip(a, b)))["p_value"]
    assert first == second


def test_p_value_is_never_exactly_zero():
    """No finite test establishes impossibility; reporting p=0 would overclaim."""
    a = [0.0] * 50
    b = [1.0] * 50
    assert stats.compare(a, b, pairs=list(zip(a, b)))["p_value"] > 0


def test_non_significant_result_is_not_reported_as_equivalence():
    a = [0.5, 0.6, 0.4, 0.55, 0.45, 0.5, 0.52, 0.48, 0.51, 0.49]
    b = [0.52, 0.58, 0.43, 0.54, 0.47, 0.51, 0.5, 0.49, 0.5, 0.5]
    r = stats.compare(a, b, pairs=list(zip(a, b)))
    if not r["significant"]:
        assert "not the same as the runs being equal" in r["caution"]
