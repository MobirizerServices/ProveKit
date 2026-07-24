"""Project-defined scorers, evaluated server-side (#48).

**Why these are declarative and not code.** The obvious reading of "server-side custom scorers"
is: let people upload a Python function. That is remote code execution wearing a feature's
clothes. A sandbox that is 95% right is a hole, this codebase has no sandbox, and building one
properly is a much larger and riskier project than the scorer feature it would serve.

So a custom scorer is a rule assembled from primitives the server already knows how to evaluate.
That still delivers what client-side scorers could not: it is stored per project, shared by
everyone in it, and — the actual point — usable by **online eval**, which runs on the server
where no SDK is present. Arbitrary Python scorers stay in `provekit.scorers`, client-side, where
running your own code is your own risk rather than the platform's.

**The regex kind is the sharp edge**, so it is fenced on three sides: the pattern is compiled and
rejected at *creation* time (a broken rule fails when someone is looking at it, not silently at
2am), its length is capped, obviously catastrophic constructs are refused, and the text it runs
against is truncated before matching. Python's `re` has no timeout, so bounding the input is the
only real defence available in the standard library; the residual risk is a slow match on a
capped string, by a member of that project, against their own data.
"""
from __future__ import annotations

import json
import logging
import re

from sqlalchemy.orm import Session

from ..models import CustomScorer

log = logging.getLogger("provekit.custom_scorers")

#: What a rule can be. Each maps to a small, total function below — no eval, no import, no code.
KINDS = ("contains", "not_contains", "equals", "regex", "json_path", "length_between")

#: Longest pattern accepted. A legitimate rule is short; a very long one is either generated or
#: an attempt to find a pathological case.
MAX_PATTERN = 200

#: Text is truncated to this before any matching. Bounds the worst case for `re`, which cannot
#: be given a timeout in the standard library.
MAX_INPUT = 4000

#: Constructs that make catastrophic backtracking easy. Refused rather than explained away — a
#: rule that needs one of these is better expressed as two rules.
_CATASTROPHIC = re.compile(r"\([^)]*[+*]\)[+*]|\(\?:[^)]*[+*]\)[+*]")


class ScorerError(ValueError):
    """A rule that cannot be stored, with a message the author can act on."""


def validate(kind: str, config: dict) -> dict:
    """Check a rule at creation time and return the normalised config.

    Everything that can be wrong with a rule is knowable now. Deferring it to evaluation would
    turn a typo into a scorer that silently returns 0.0 for every row — which reads as "the model
    is failing", the most expensive wrong conclusion this product can hand someone.
    """
    if kind not in KINDS:
        raise ScorerError(f"kind must be one of: {', '.join(KINDS)}")
    cfg = dict(config or {})

    if kind in ("contains", "not_contains", "equals"):
        value = str(cfg.get("value") or "")
        if not value.strip():
            raise ScorerError(f"a {kind} scorer needs a non-empty `value` to look for")
        cfg["value"] = value
        cfg["case_sensitive"] = bool(cfg.get("case_sensitive", False))

    elif kind == "regex":
        pattern = str(cfg.get("pattern") or "")
        if not pattern.strip():
            raise ScorerError("a regex scorer needs a `pattern`")
        if len(pattern) > MAX_PATTERN:
            raise ScorerError(f"pattern is longer than {MAX_PATTERN} characters — a scoring rule "
                              "this large is usually better split into two")
        if _CATASTROPHIC.search(pattern):
            raise ScorerError("that pattern nests a quantifier inside a quantified group, which "
                              "can backtrack catastrophically. Express it as two rules, or match "
                              "a simpler substring.")
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ScorerError(f"pattern doesn't compile: {exc}") from None
        cfg["pattern"] = pattern

    elif kind == "json_path":
        path = str(cfg.get("path") or "")
        if not path.strip():
            raise ScorerError("a json_path scorer needs a dotted `path`, e.g. result.status")
        cfg["path"] = path
        cfg["equals"] = str(cfg.get("equals") or "")

    elif kind == "length_between":
        lo, hi = cfg.get("min"), cfg.get("max")
        try:
            lo = int(lo if lo is not None else 0)
            hi = int(hi if hi is not None else 0)
        except (TypeError, ValueError):
            raise ScorerError("`min` and `max` must be whole numbers") from None
        if hi <= 0 or hi < lo:
            raise ScorerError("`max` must be greater than 0 and not below `min`")
        cfg["min"], cfg["max"] = max(0, lo), hi

    return cfg


def _clip(text: str) -> str:
    return (text or "")[:MAX_INPUT]


def _dig(payload, path: str):
    cur = payload
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return None
    return cur


def evaluate(kind: str, config: dict, output: str) -> float | None:
    """Score one output. Returns 1.0 / 0.0, or None for "this rule doesn't apply to this row".

    None rather than 0.0 matters: `run_scorers` omits a None, and an ungradeable row scored zero
    would drag an experiment mean by exactly as much as a genuine failure while looking identical
    to one.
    """
    text = _clip(output or "")
    cfg = config or {}

    if kind in ("contains", "not_contains", "equals"):
        needle = str(cfg.get("value") or "")
        hay, ndl = (text, needle) if cfg.get("case_sensitive") else (text.lower(), needle.lower())
        if kind == "contains":
            return 1.0 if ndl in hay else 0.0
        if kind == "not_contains":
            return 1.0 if ndl not in hay else 0.0
        return 1.0 if hay.strip() == ndl.strip() else 0.0

    if kind == "regex":
        try:
            return 1.0 if re.search(str(cfg.get("pattern") or ""), text) else 0.0
        except re.error:
            return None                      # stored before a validation rule tightened

    if kind == "json_path":
        try:
            payload = json.loads(text)
        except (ValueError, TypeError):
            return None                      # not JSON — this rule has nothing to say
        found = _dig(payload, str(cfg.get("path") or ""))
        if found is None:
            return 0.0
        want = str(cfg.get("equals") or "")
        return 1.0 if (not want or str(found) == want) else 0.0

    if kind == "length_between":
        n = len((output or "").strip())
        return 1.0 if int(cfg.get("min", 0)) <= n <= int(cfg.get("max", 0)) else 0.0

    return None


def compile_row(row: CustomScorer):
    """A `(output, expected) -> float | None` callable that `run_scorers` can take directly."""
    kind, cfg, name = row.kind, dict(row.config or {}), row.name

    def _scorer(output: str, expected: str = "") -> float | None:
        try:
            return evaluate(kind, cfg, output)
        except Exception:                    # noqa: BLE001 — one bad rule must not fail a run
            log.exception("custom scorer %s failed", name)
            return None

    _scorer.__name__ = name
    return _scorer


def resolve(db: Session, workspace_id: int, names) -> list:
    """Turn a list of scorer names into what `run_scorers` wants.

    A name that is a built-in is passed through untouched; one that names a custom scorer in this
    project becomes its compiled callable. Project-scoped on purpose — a scorer name means what
    *this* project defined it to mean, and two projects may use the same name for different rules.
    """
    wanted = [n for n in (names or []) if isinstance(n, str)]
    if not wanted:
        return list(names or [])
    rows = {r.name: r for r in db.query(CustomScorer)
            .filter(CustomScorer.workspace_id == workspace_id,
                    CustomScorer.enabled.is_(True),
                    CustomScorer.name.in_(wanted)).all()}
    return [compile_row(rows[n]) if n in rows else n for n in (names or [])]


def row(r: CustomScorer) -> dict:
    from ..models import iso_utc
    return {"id": r.id, "name": r.name, "description": r.description, "kind": r.kind,
            "config": r.config or {}, "enabled": r.enabled, "created_at": iso_utc(r.created_at)}
