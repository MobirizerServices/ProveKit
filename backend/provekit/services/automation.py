"""Automation rules: route production traces into datasets and online scoring (#47, #39).

Evaluation was entirely offline. You curated a dataset by hand, ran experiments against it,
and nothing connected what actually happened in production back into that loop — so the
dataset drifted away from real traffic while the traces most worth learning from were the ones
nobody got round to copying across.

A rule is a **match** plus an **action**:

  promote — copy a matching trace into a dataset, so the regression set grows from real
            failures instead of imagination.
  score   — sample matching traces and score them in place (#39). This is the highest-value
            eval loop precisely because it needs no ground truth: it judges what shipped.

Three properties that keep this from being dangerous:

- **A watermark, not a sweep.** Each rule records the highest `Run.id` it has considered and
  only ever looks forward. A rule created today that retroactively swept a project's whole
  history would be a surprise, and for `score` an expensive one — a judge call per trace
  against months of traffic.
- **An empty match is refused**, at save time, rather than treated as "everything". A rule that
  silently matched every trace would promote an entire project into a dataset on its first
  pass, and that is not a mistake you can undo by editing the rule afterwards.
- **Sampling is first-class.** Online scoring costs money per trace, so `sample` is part of the
  rule rather than something bolted on after the first bill. Sampling is deterministic on the
  trace id, so the same trace is always in or out — a re-run of the pass cannot double-score.

It runs on a background pass, never on ingest. Ingest is the hottest write in the product and
now carries a durability spool; making it also evaluate rules and call judge models would trade
a guarantee this codebase worked hard for against a feature nobody needs synchronous.
"""
from __future__ import annotations

import hashlib
import logging

from sqlalchemy.orm import Session

from ..models import AutomationRule, DatasetItem, Feedback, Run

log = logging.getLogger("provekit.automation")

ACTIONS = ("promote", "score")
MATCH_KEYS = ("status", "label_contains", "q", "type")

#: Traces considered per rule per pass. Bounds the work a single pass can do, so a rule pointed
#: at a busy project catches up over several passes instead of one enormous transaction.
BATCH = 200


def validate(match: dict, action: str, *, target_dataset_id=None, scorers=None,
             sample: float = 1.0) -> None:
    """Raise ValueError on a rule that would misbehave. Called at save time, not at run time —
    a rule that only reveals its problem on the background pass fails where nobody is looking."""
    if action not in ACTIONS:
        raise ValueError(f"action must be one of {list(ACTIONS)}")
    clean = {k: v for k, v in (match or {}).items() if k in MATCH_KEYS and str(v).strip()}
    if not clean:
        raise ValueError("a rule needs at least one match condition — an empty match would "
                         "act on every trace in the project")
    if not 0 < sample <= 1:
        raise ValueError("sample must be greater than 0 and at most 1")
    if action == "promote" and not target_dataset_id:
        raise ValueError("a promote rule needs target_dataset_id")
    if action == "score" and not (scorers or []):
        raise ValueError("a score rule needs at least one scorer")


def matches(rule: AutomationRule, root: Run) -> bool:
    """Whether a trace's root span satisfies the rule. All conditions are ANDed."""
    m = rule.match or {}
    if m.get("status") and root.status != m["status"]:
        return False
    if m.get("type") and root.type != m["type"]:
        return False
    if m.get("label_contains") and m["label_contains"].lower() not in (root.label or "").lower():
        return False
    if m.get("q"):
        hay = f"{root.label or ''} {root.search_text or ''}".lower()
        if m["q"].lower() not in hay:
            return False
    return True


def sampled(rule: AutomationRule, trace_id: str) -> bool:
    """Deterministic on the trace id, so the same trace is always in or out.

    Random sampling would make a re-run of the pass score a different subset — and, worse,
    could score the same trace twice across retries, charging twice for a judge call and
    writing two contradictory scores against one trace.
    """
    if rule.sample >= 1:
        return True
    digest = hashlib.sha256(f"{rule.id}:{trace_id}".encode()).digest()
    return int.from_bytes(digest[:4], "big") / 0xFFFFFFFF < rule.sample


def _promote(db: Session, rule: AutomationRule, root: Run) -> bool:
    """Copy a trace into the target dataset, unless it is already there.

    Idempotent on trace id: a rule that re-ran over the same trace must not add a second copy,
    which would quietly weight that example twice in every experiment afterwards.
    """
    exists = (db.query(DatasetItem)
              .filter(DatasetItem.dataset_id == rule.target_dataset_id).all())
    if any((it.meta or {}).get("trace_id") == root.trace_id for it in exists):
        return False
    inp = (root.request or {}).get("input", "") if isinstance(root.request, dict) else ""
    out = (root.result or {}).get("text") or "" if isinstance(root.result, dict) else ""
    db.add(DatasetItem(workspace_id=rule.workspace_id, dataset_id=rule.target_dataset_id,
                       input=inp or "", expected=out or "",
                       meta={"trace_id": root.trace_id, "source": "automation",
                             "rule_id": rule.id}))
    from . import datasets as datasets_svc
    datasets_svc.bump(db, rule.target_dataset_id)      # the dataset changed; #45 must see it
    return True


def _score(db: Session, rule: AutomationRule, root: Run) -> bool:
    """Score a live trace in place, writing Feedback rows.

    Recorded with source='eval' so judge calibration (#49) can measure these against human
    labels — an online score nobody can check is a number, not a signal.
    """
    from ..scorers import run_scorers
    from . import custom_scorers

    out = (root.result or {}).get("text") or "" if isinstance(root.result, dict) else ""
    already = {f.name for f in db.query(Feedback)
               .filter(Feedback.trace_id == root.trace_id, Feedback.source == "eval").all()}
    wrote = False
    # Custom scorers are the reason this resolution exists: online eval runs on the server,
    # where there is no SDK to supply a Python scorer, so a project-defined rule is the only
    # kind that can grade a live trace (#48).
    resolved = custom_scorers.resolve(db, rule.workspace_id, rule.scorers or [])
    for name, value in (run_scorers(resolved, out, "") or {}).items():
        if name in already:
            continue                       # don't re-score a trace a previous pass handled
        db.add(Feedback(workspace_id=rule.workspace_id, trace_id=root.trace_id, name=name,
                        score=float(value) if value is not None else None, source="eval",
                        comment=f"online eval · rule {rule.id}"))
        wrote = True
    return wrote


def run_rule(db: Session, rule: AutomationRule, *, batch: int = BATCH) -> dict:
    """Advance one rule over new traces. Returns what it did."""
    roots = (db.query(Run)
             .filter(Run.workspace_id == rule.workspace_id, Run.parent_span_id == "",
                     Run.id > (rule.last_run_id or 0))
             .order_by(Run.id.asc()).limit(batch).all())
    matched = acted = 0
    for root in roots:
        rule.last_run_id = max(rule.last_run_id or 0, root.id)
        if not matches(rule, root):
            continue
        matched += 1
        if not sampled(rule, root.trace_id):
            continue
        try:
            done = _promote(db, rule, root) if rule.action == "promote" else _score(db, rule, root)
            acted += 1 if done else 0
        except Exception as exc:
            # One bad trace must not stop the rule. The watermark has already advanced past it,
            # so a permanently unprocessable trace is skipped rather than blocking everything
            # behind it forever.
            rule.last_status = f"{type(exc).__name__}: {exc}"[:160]
            log.exception("automation rule %s failed on trace %s", rule.id, root.trace_id)
    rule.matched = (rule.matched or 0) + matched
    rule.acted = (rule.acted or 0) + acted
    if not rule.last_status or acted:
        rule.last_status = f"considered {len(roots)}, matched {matched}, acted {acted}"
    return {"considered": len(roots), "matched": matched, "acted": acted}


def run_all(db: Session) -> int:
    """Advance every enabled rule. Returns how many actions were taken."""
    total = 0
    rules = db.query(AutomationRule).filter(AutomationRule.enabled.is_(True)).all()
    for rule in rules:
        try:
            total += run_rule(db, rule)["acted"]
        except Exception:
            log.exception("automation rule %s pass failed", rule.id)
            db.rollback()
    if rules:
        db.commit()
    return total
