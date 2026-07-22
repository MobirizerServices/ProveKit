"""Judge calibration — does the LLM judge agree with the humans?

A judge scorer is a model grading a model. Nothing about that is trustworthy on its own: the
only evidence that a judge's 0.87 means anything is that it tracks what people said about the
same traces. This measures exactly that, over the feedback already stored — human thumbs
(`source='human'`) as ground truth, judge/eval scores (`source='eval'` or `'sdk'`) as the
prediction. No new column, and no separate labelling pipeline: the labels are the ones the
portal has been collecting all along.

**Why kappa and not agreement.** Agreement alone is the statistic that makes a useless judge
look good. On a dataset where 90% of traces are fine, a judge that says "good" to everything
scores 90% agreement while carrying zero information. Cohen's kappa divides out that chance
baseline — (observed − expected) / (1 − expected) — and scores the same judge 0.0, which is
the honest answer. Agreement is still reported, because it is what people ask for; kappa is
what decides.

**Why binary.** Kappa is an agreement statistic over categories, and the human label really is
categorical (👍/👎). A judge's continuous score is thresholded at `pass_at` to meet it. That
loses the distinction between a 0.51 and a 0.99 pass, which is the price of being able to say
"agrees with people above chance" at all.

**Why it refuses.** Below `MIN_LABELLED_N` pairs this returns no agreement rate, no kappa and
no verdict — only the raw counts and the disagreeing traces. The standard error of kappa is on
the order of 1/√n, so at twenty labels a reported 0.6 is worth roughly ±0.2; below that the
point estimate is noise wearing a decimal point. A calibration number computed from four
labels is worse than no number, because it gets quoted. Same posture as services/stats.py:
"not enough data to tell" is a different finding from "the judge is bad", and neither may be
silently rendered as the other.
"""
from __future__ import annotations

#: Pairs needed before any rate, kappa or verdict is reported. See the module docstring — this
#: is the point at which the number starts carrying information, not the point at which it
#: becomes precise.
MIN_LABELLED_N = 20

#: A numeric score at or above this is a pass. Matches the experiments router's PASS_AT: most
#: scorers emit 0/1 or a 0..1 fraction, so half-way is the only defensible default.
PASS_AT = 0.5

#: Disagreeing traces returned. Enough to read through; nobody triages past the first screen.
DISAGREEMENT_LIMIT = 50

#: Feedback sources. `source` already separates a person from a machine, which is the whole
#: reason no new column is needed. The trade: a human labelling tool that posts with a project
#: key lands as 'sdk' and is counted as a prediction, not as ground truth.
HUMAN_SOURCES = frozenset({"human"})
JUDGE_SOURCES = frozenset({"eval", "sdk"})

#: Categorical labels a person actually leaves. Checked before the numeric score so an explicit
#: 👎 wins over whatever number happened to ride along on the same row.
PASS_WORDS = frozenset({"up", "good", "pass", "passed", "yes", "correct", "true", "ok",
                        "accept", "accepted", "thumbs_up", "👍", "1"})
FAIL_WORDS = frozenset({"down", "bad", "fail", "failed", "no", "incorrect", "false",
                        "reject", "rejected", "thumbs_down", "👎", "0"})

#: Landis & Koch's conventional bands. Convention, not law — they are a shared vocabulary for
#: talking about a kappa, not a threshold anything should be gated on. Lower bound, label.
_BANDS = ((0.81, "almost perfect"), (0.61, "substantial"), (0.41, "moderate"),
          (0.21, "fair"), (0.01, "slight"), (float("-inf"), "none"))


def _num(v) -> float | None:
    """A float from a real number, else None. Booleans are rejected: bool is an int, so a
    JSON `true` would otherwise read as a score of 1.0."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v)


def _label(row, pass_at: float) -> bool | None:
    """Pass/fail for one feedback row, or None when the row carries no usable verdict.

    A thumbs row carries `value` and no score; an eval row carries `score` and no value. Both
    shapes are already in the table, so both are read, and a row that is only a comment is
    dropped rather than guessed at — an unlabelled row is not a failing one.
    """
    word = str(getattr(row, "value", "") or "").strip().lower()
    if word in PASS_WORDS:
        return True
    if word in FAIL_WORDS:
        return False
    score = _num(getattr(row, "score", None))
    return None if score is None else score >= pass_at


def _matches(row, source_set: frozenset[str], name: str) -> bool:
    if str(getattr(row, "source", "") or "") not in source_set:
        return False
    return not name or str(getattr(row, "name", "") or "") == name


def _latest_by_trace(rows: list, pass_at: float) -> tuple[dict, int]:
    """trace_id -> (label, row) for the *newest* usable row per trace, plus the count of rows
    that carried no label.

    A trace relabelled twice has one standing verdict, not two votes: a reviewer who changes
    their mind means the later row, and averaging the two would invent a position nobody held.
    Ids are monotonic within the table, so the highest id is the latest row.
    """
    best: dict[str, tuple] = {}
    unusable = 0
    for row in sorted(rows, key=lambda r: getattr(r, "id", 0) or 0):
        label = _label(row, pass_at)
        if label is None:
            unusable += 1
            continue
        best[str(getattr(row, "trace_id", "") or "")] = (label, row)
    best.pop("", None)
    return best, unusable


def _kappa(a: int, b: int, c: int, d: int) -> float | None:
    """Cohen's kappa over the 2x2 table (both pass, human-pass/judge-fail, human-fail/judge-pass,
    both fail). None when it is undefined — which happens exactly when both raters used a single
    class for everything, leaving no variation for chance-corrected agreement to be about.

    Called only once the table is non-empty (n >= MIN_LABELLED_N), so no zero guard here.
    """
    n = a + b + c + d
    observed = (a + d) / n
    human_pass, judge_pass = (a + b) / n, (a + c) / n
    expected = human_pass * judge_pass + (1 - human_pass) * (1 - judge_pass)
    if 1 - expected <= 1e-12:
        return None
    return (observed - expected) / (1 - expected)


def _band(kappa: float) -> str:
    return next(label for lo, label in _BANDS if kappa >= lo)


def _rate(hits: int, total: int) -> float | None:
    return (hits / total) if total else None


def _clip(s, n: int) -> str:
    s = str(s or "")
    return s if len(s) <= n else s[:n] + "…"


def _disagreement(trace_id: str, human_label: bool, human_row, judge_row) -> dict:
    return {
        "trace_id": trace_id,
        # A judge that passes output a person rejected is the failure that costs you something:
        # it is the one that lets a bad release through a gate built on the judge.
        "direction": "judge_too_lenient" if not human_label else "judge_too_harsh",
        "human_label": "pass" if human_label else "fail",
        "human_name": str(getattr(human_row, "name", "") or ""),
        "human_value": str(getattr(human_row, "value", "") or ""),
        "human_comment": _clip(getattr(human_row, "comment", ""), 400),
        "judge_name": str(getattr(judge_row, "name", "") or ""),
        "judge_score": _num(getattr(judge_row, "score", None)),
        "judge_value": str(getattr(judge_row, "value", "") or ""),
        "judge_comment": _clip(getattr(judge_row, "comment", ""), 400),
    }


def calibrate(rows, *, pass_at: float = PASS_AT, judge_name: str = "", human_name: str = "",
              limit: int = DISAGREEMENT_LIMIT) -> dict:
    """Measure a judge against human labels over feedback rows for one workspace.

    `rows` is any iterable of feedback-shaped objects (id, trace_id, name, score, value,
    comment, source) — the ORM rows, or anything that quacks like them. Only traces carrying
    *both* a human label and a judge score are measured; the rest are counted and reported, so
    "the judge and the humans looked at different traces" can't masquerade as disagreement.

    `judge_name` / `human_name` narrow to one scorer or one annotation by name, for the common
    case of several living side by side ("llm_judge" vs "thumbs").
    """
    rows = list(rows)
    limit = max(1, min(int(limit), 500))
    humans, human_unusable = _latest_by_trace(
        [r for r in rows if _matches(r, HUMAN_SOURCES, human_name)], pass_at)
    judges, judge_unusable = _latest_by_trace(
        [r for r in rows if _matches(r, JUDGE_SOURCES, judge_name)], pass_at)

    shared = sorted(humans.keys() & judges.keys())
    a = b = c = d = 0
    disagreements = []
    for trace_id in shared:
        human_label, human_row = humans[trace_id]
        judge_label, judge_row = judges[trace_id]
        if human_label and judge_label:
            a += 1
        elif human_label and not judge_label:
            b += 1
        elif not human_label and judge_label:
            c += 1
        else:
            d += 1
        if human_label != judge_label:
            disagreements.append(_disagreement(trace_id, human_label, human_row, judge_row))

    # Lenient first: a judge that waves through what a person rejected is the expensive error.
    disagreements.sort(key=lambda x: x["direction"] != "judge_too_lenient")

    n = len(shared)
    out = {
        "n": n,
        "pass_at": pass_at,
        "judge_name": judge_name,
        "human_name": human_name,
        "min_n": MIN_LABELLED_N,
        "sufficient": n >= MIN_LABELLED_N,
        "confusion": {"both_pass": a, "human_pass_judge_fail": b,
                      "human_fail_judge_pass": c, "both_fail": d},
        "coverage": {"human_labelled": len(humans), "judge_scored": len(judges),
                     "both": n, "human_only": len(humans.keys() - judges.keys()),
                     "judge_only": len(judges.keys() - humans.keys()),
                     "unusable_rows": human_unusable + judge_unusable},
        "agreement": None,
        "kappa": None,
        "false_pass_rate": None,
        "false_fail_rate": None,
        "verdict": "",
        "caution": "",
        "disagreement_count": len(disagreements),
        "disagreements": disagreements[:limit],
        "truncated": len(disagreements) > limit,
    }

    if not out["sufficient"]:
        # The counts and the disagreeing traces are facts you can act on — read them, or go
        # label more. The rates are the part that would get quoted as a credibility claim, so
        # they are withheld rather than published with a disclaimer nobody carries forward.
        out["caution"] = (
            f"{n} trace(s) carry both a human label and a judge score — fewer than "
            f"{MIN_LABELLED_N}, so no agreement rate, kappa or verdict is reported. A "
            f"calibration number from a handful of labels is worse than none: it gets quoted. "
            f"Label more traces in the portal.")
        return out

    out["agreement"] = (a + d) / n
    out["false_pass_rate"] = _rate(c, c + d)   # of the traces people failed, the judge passed…
    out["false_fail_rate"] = _rate(b, a + b)   # …and of the ones people passed, it failed
    kappa = _kappa(a, b, c, d)
    out["kappa"] = kappa

    if kappa is None:
        out["caution"] = (
            "Every label on both sides is the same class, so kappa is undefined — with no "
            "variation there is nothing for chance-corrected agreement to measure. Label some "
            "traces of the other kind before trusting this judge.")
        return out

    # A kappa can be defined and still be worthless; the band alone doesn't say so out loud.
    out["verdict"] = _band(kappa)
    if kappa < 0.41:
        out["caution"] = (
            f"Kappa {kappa:.2f} ({out['verdict']}): agreement is {out['agreement']:.0%}, but "
            f"little of it survives correcting for chance. Read the disagreements before "
            f"gating anything on this judge.")
    return out
