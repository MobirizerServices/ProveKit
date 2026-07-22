"""Measured redaction quality (#7).

redact.py is regex-based, so it has both false negatives (PII it misses) and false positives
(real output it mangles). Neither was measured, so neither could be argued about or improved
without guessing. This runs a labelled corpus and asserts both rates.

Recall alone is a useless target — masking everything scores 100%. What makes a masker usable
is not destroying real output, so the clean half of the corpus carries equal weight, and the
cases this masker currently gets wrong are recorded rather than quietly dropped.
"""
import json
from pathlib import Path

from provekit.services import redact

CORPUS = json.loads((Path(__file__).parent / "fixtures" / "redaction_corpus.json").read_text())
SENSITIVE = CORPUS["sensitive"]
CLEAN = CORPUS["clean"]


def _masked(text: str) -> bool:
    return "[REDACTED_" in (redact.redact_text(text) or "")


def measure() -> dict:
    """Recall over sensitive samples, and the false-positive rate over clean ones."""
    caught = [s for s in SENSITIVE if _masked(s["text"])]
    missed = [s for s in SENSITIVE if not _masked(s["text"])]
    tripped = [c for c in CLEAN if _masked(c["text"])]
    return {
        "sensitive": len(SENSITIVE), "caught": len(caught), "missed": missed,
        "clean": len(CLEAN), "false_positives": tripped,
        "recall": len(caught) / len(SENSITIVE),
        "false_positive_rate": len(tripped) / len(CLEAN),
    }


def test_recall_over_the_sensitive_corpus():
    """Everything labelled sensitive must be masked. A miss here is leaked PII."""
    m = measure()
    assert not m["missed"], f"unmasked PII: {[s['text'] for s in m['missed']]}"
    assert m["recall"] == 1.0


def test_false_positives_are_exactly_the_known_ones():
    """Clean text must survive — except the cases we have written down as known-bad.

    This is the assertion that gives the number teeth in both directions: a new false positive
    fails the test, and *fixing* a known one also fails it, forcing the corpus (and the
    published rate) to be updated rather than drifting out of date.
    """
    m = measure()
    tripped = {c["text"] for c in m["false_positives"]}
    expected = {c["text"] for c in CLEAN if "known_false_positive" in c}
    assert tripped == expected, (
        f"new false positives: {sorted(tripped - expected)}; "
        f"now-fixed (update the corpus): {sorted(expected - tripped)}")


def test_published_rates_are_current():
    """The rates in docs/TRACING.md must match what the corpus actually measures — a published
    number nobody re-measures is worse than none."""
    m = measure()
    doc = (Path(__file__).resolve().parents[2] / "docs" / "TRACING.md").read_text()
    assert f"{m['recall'] * 100:.0f}% recall" in doc
    assert f"{m['false_positive_rate'] * 100:.0f}% false-positive rate" in doc


def test_each_sensitive_sample_gets_the_expected_label():
    """Masking an email as [REDACTED_PHONE] would still leak the shape of the data and makes
    the provenance marker (#8) misleading."""
    wrong = []
    for s in SENSITIVE:
        out = redact.redact_text(s["text"]) or ""
        if f"[REDACTED_{s['type']}]" not in out:
            wrong.append((s["text"], s["type"], out))
    assert not wrong, f"mislabelled: {wrong}"


def test_clean_samples_are_returned_byte_identical():
    """Not merely unmasked — untouched."""
    for c in CLEAN:
        if "known_false_positive" in c:
            continue
        assert redact.redact_text(c["text"]) == c["text"]
