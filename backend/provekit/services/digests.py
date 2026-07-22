"""Recurring "here's what changed" summaries.

Alerts answer "is something broken right now". Nobody was answering the slower question — did
quality drift this week, is spend climbing, did a new error start showing up — and that one is
only visible by comparing a window against the one before it. A dashboard shows it to whoever
opens the dashboard; a digest shows it to a team that didn't.

Two things this deliberately does NOT do:

- **It does not invent a comparison it can't make.** A project with no traffic in the previous
  window has no baseline, so the digest says "no comparison available" rather than reporting
  an infinite increase from zero. Every percentage here is computed against a real denominator
  or omitted.
- **It does not skip a missed window.** Scheduling is driven by `last_sent_at`, not by a cron
  expression, so an instance that was down over the boundary sends late rather than never. A
  digest nobody received looks exactly like nothing to report, which is the failure that makes
  people stop trusting the feature.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from ..models import Digest, Workspace

log = logging.getLogger("provekit.digests")

CADENCES = {"daily": 24, "weekly": 24 * 7}


def window_hours(cadence: str) -> int:
    return CADENCES.get(cadence, CADENCES["weekly"])


def due(db: Session, *, now: datetime | None = None) -> list[Digest]:
    """Digests whose window has elapsed.

    A digest that has never been sent is due immediately — otherwise configuring one produces
    nothing for a week and looks broken.
    """
    now = now or datetime.now(timezone.utc)
    out = []
    for d in db.query(Digest).filter(Digest.enabled.is_(True)).all():
        if d.last_sent_at is None:
            out.append(d)
            continue
        last = d.last_sent_at
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        if now - last >= timedelta(hours=window_hours(d.cadence)):
            out.append(d)
    return out


def _delta(current: float, previous: float) -> float | None:
    """Percentage change, or None when there is no baseline to compare against."""
    if previous <= 0:
        return None
    return round((current - previous) / previous * 100, 1)


def build(db: Session, ws: Workspace, cadence: str) -> dict:
    """The content of one digest: this window against the one before it."""
    from ..routers.metrics import compute_metrics

    hours = window_hours(cadence)
    now = compute_metrics(db, ws, hours)
    # The previous window is "twice as wide, minus this one" — computed from the same function
    # so the two halves can't be measured differently. A second implementation of the metric
    # would eventually disagree with the dashboard and nobody would know which was right.
    wide = compute_metrics(db, ws, hours * 2)
    prev_traces = max(0, wide["trace_count"] - now["trace_count"])
    prev_errors = max(0, wide["error_count"] - now["error_count"])
    prev_tokens = max(0, wide["total_tokens"] - now["total_tokens"])
    prev_rate = (prev_errors / prev_traces) if prev_traces else 0.0

    return {
        "project": ws.name,
        "cadence": cadence,
        "window_hours": hours,
        "traces": now["trace_count"],
        "traces_delta_pct": _delta(now["trace_count"], prev_traces),
        "errors": now["error_count"],
        "error_rate": now["error_rate"],
        "error_rate_delta_pct": _delta(now["error_rate"], prev_rate),
        "tokens": now["total_tokens"],
        "tokens_delta_pct": _delta(now["total_tokens"], prev_tokens),
        "latency_p95_ms": now["latency_p95_ms"],
        "top_errors": now["top_errors"][:3],
        # Stated rather than implied: without it a reader assumes every number has a trend.
        "has_baseline": prev_traces > 0,
    }


def render(summary: dict) -> str:
    """Plain text, because it has to read well in Slack, Discord and an email alike."""
    def pct(v):
        return "—" if v is None else f"{v:+.1f}%"

    lines = [f"*[ProveKit] {summary['project']}* — last {summary['window_hours']}h",
             f"traces {summary['traces']} ({pct(summary['traces_delta_pct'])})",
             f"errors {summary['errors']} · rate {summary['error_rate']:.1%} "
             f"({pct(summary['error_rate_delta_pct'])})",
             f"tokens {summary['tokens']:,} ({pct(summary['tokens_delta_pct'])})",
             f"p95 {summary['latency_p95_ms']} ms"]
    if summary["top_errors"]:
        lines.append("top errors: " + "; ".join(
            f"{e['error'][:60]} x{e['count']}" for e in summary["top_errors"]))
    if not summary["has_baseline"]:
        lines.append("(no comparison available — nothing recorded in the previous window)")
    return "\n".join(lines)


def send(db: Session, d: Digest) -> bool:
    """Build and deliver one digest. Never raises — a broken destination must not stop the
    scheduler from sending everyone else's."""
    from . import email as email_svc
    from . import notify

    ws = db.query(Workspace).filter(Workspace.id == d.workspace_id).first()
    if ws is None:
        d.enabled = False
        d.last_status = "project no longer exists"
        return False
    ok = False
    try:
        body = render(build(db, ws, d.cadence))
        if d.webhook_url:
            ok = notify.send_webhook(d.webhook_url, body)
        elif d.email:
            email_svc.send(d.email, f"ProveKit digest — {ws.name}", body)
            ok = True
        d.last_status = "sent" if ok else "delivery failed"
    except Exception as exc:
        d.last_status = f"{type(exc).__name__}: {exc}"[:160]
        log.exception("digest %s failed", d.id)
    # Stamped even on failure, so a permanently broken destination is retried next window
    # rather than every time the scheduler runs.
    d.last_sent_at = datetime.now(timezone.utc)
    return ok


def run_due(db: Session, *, now: datetime | None = None) -> int:
    """Send everything that's due. Returns how many were delivered."""
    sent = 0
    pending = due(db, now=now)
    for d in pending:
        sent += 1 if send(db, d) else 0
    if pending:
        db.commit()
    return sent
