"""Durable usage metering (#80).

Quotas were already enforced from counters in services/limits — Redis keys with a 35-day TTL, or
process memory when Redis isn't configured. Those are right for the hot path and wrong for
billing: an in-memory count dies with the process, the TTL drops the history, and neither can
answer "what did this account use in March". Tokens and cost weren't metered at all.

So the roles are split. **Counters gate** (fast, approximate, disposable). **This ledger records**
(durable, queryable, per month). They are allowed to disagree — the counter is a live rate, the
ledger is what actually landed — and the summary says which number is which.

Metering happens after the spans are stored, from the rows that were *actually persisted*: a
duplicate batch is deduped before it gets here (#1), so a retry can't inflate a bill. Cost is
priced at ingest time with the rates then in force, using the same `pricing.estimate` the trace
list shows, so an invoice and a trace can never quote different numbers for the same call.
"""
from __future__ import annotations

import logging
import time

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import UsageRecord
from . import pricing

log = logging.getLogger("provekit.usage")


def period_now() -> str:
    """The billing period a write lands in: UTC year-month."""
    return time.strftime("%Y-%m", time.gmtime())


def measure(rows: list[dict]) -> dict:
    """Tokens and cost for a batch of persisted span rows.

    `priced`/`unpriced` count model calls that did and didn't report usage. Without that split a
    small cost is ambiguous between "cheap" and "nobody reported tokens", which is not a
    distinction to guess at on an invoice.
    """
    tally = {"spans": len(rows), "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0,
             "priced_calls": 0, "unpriced_calls": 0}
    for kw in rows:
        meta = ((kw.get("result") or {}).get("meta") or {})
        model = meta.get("model") or (kw.get("request") or {}).get("model") or ""
        u = meta.get("usage") or {}
        if not model:
            continue                       # not a model call: nothing to price
        inp, out = u.get("input_tokens"), u.get("output_tokens")
        if inp is None and out is None:
            tally["unpriced_calls"] += 1
            continue
        tally["priced_calls"] += 1
        tally["input_tokens"] += int(inp or 0)
        tally["output_tokens"] += int(out or 0)
        tally["cost_usd"] += pricing.estimate(model, inp, out,
                                              version=meta.get("price_version")) or 0.0
    return tally


def record(db: Session, *, user_id: int, workspace_id: int, rows: list[dict],
           period: str | None = None) -> None:
    """Add a batch to the ledger. Never raises — metering must not fail an ingest.

    Losing a meter increment costs an under-count on one batch; raising here would cost the
    customer's spans, which is a far worse trade.
    """
    if not rows or not user_id:
        return
    p = period or period_now()
    try:
        # Inside the guard: pricing walks attacker-influenced span payloads, and a malformed
        # one must cost an under-count rather than the customer's spans.
        tally = measure(rows)
        row = (db.query(UsageRecord)
               .filter(UsageRecord.user_id == user_id,
                       UsageRecord.workspace_id == workspace_id,
                       UsageRecord.period == p).first())
        if row is None:
            row = UsageRecord(user_id=user_id, workspace_id=workspace_id, period=p)
            db.add(row)
            try:
                db.flush()
            except IntegrityError:
                # Another worker created the same (account, project, month) first. Take theirs.
                db.rollback()
                row = (db.query(UsageRecord)
                       .filter(UsageRecord.user_id == user_id,
                               UsageRecord.workspace_id == workspace_id,
                               UsageRecord.period == p).first())
                if row is None:
                    raise
        row.spans = (row.spans or 0) + tally["spans"]
        row.input_tokens = (row.input_tokens or 0) + tally["input_tokens"]
        row.output_tokens = (row.output_tokens or 0) + tally["output_tokens"]
        row.cost_usd = (row.cost_usd or 0.0) + tally["cost_usd"]
        row.priced_calls = (row.priced_calls or 0) + tally["priced_calls"]
        row.unpriced_calls = (row.unpriced_calls or 0) + tally["unpriced_calls"]
        db.commit()
    except Exception:                       # noqa: BLE001 — see docstring
        db.rollback()
        log.exception("usage metering failed for user %s workspace %s", user_id, workspace_id)


def _row(r: UsageRecord) -> dict:
    total = (r.priced_calls or 0) + (r.unpriced_calls or 0)
    return {
        "period": r.period, "workspace_id": r.workspace_id,
        "spans": r.spans or 0,
        "input_tokens": r.input_tokens or 0, "output_tokens": r.output_tokens or 0,
        "tokens": (r.input_tokens or 0) + (r.output_tokens or 0),
        "cost_usd": round(r.cost_usd or 0.0, 6),
        "priced_calls": r.priced_calls or 0, "unpriced_calls": r.unpriced_calls or 0,
        # How much of the cost rests on reported usage rather than on silence.
        "usage_coverage": round((r.priced_calls or 0) / total, 4) if total else None,
    }


def for_period(db: Session, user_id: int, period: str | None = None) -> dict:
    """One account's totals for a month, and the per-project split behind them."""
    p = period or period_now()
    rows = (db.query(UsageRecord)
            .filter(UsageRecord.user_id == user_id, UsageRecord.period == p).all())
    projects = [_row(r) for r in rows]
    priced = sum(r.priced_calls or 0 for r in rows)
    unpriced = sum(r.unpriced_calls or 0 for r in rows)
    return {
        "period": p,
        "spans": sum(r.spans or 0 for r in rows),
        "input_tokens": sum(r.input_tokens or 0 for r in rows),
        "output_tokens": sum(r.output_tokens or 0 for r in rows),
        "tokens": sum((r.input_tokens or 0) + (r.output_tokens or 0) for r in rows),
        "cost_usd": round(sum(r.cost_usd or 0.0 for r in rows), 6),
        "priced_calls": priced, "unpriced_calls": unpriced,
        "usage_coverage": round(priced / (priced + unpriced), 4) if (priced + unpriced) else None,
        "projects": sorted(projects, key=lambda x: -x["spans"]),
    }


def history(db: Session, user_id: int, months: int = 12) -> list[dict]:
    """Per-month totals, newest first — the thing a counter with a TTL could never provide."""
    rows = (db.query(UsageRecord)
            .filter(UsageRecord.user_id == user_id)
            .order_by(UsageRecord.period.desc()).all())
    by_period: dict[str, dict] = {}
    for r in rows:
        acc = by_period.setdefault(r.period, {
            "period": r.period, "spans": 0, "input_tokens": 0, "output_tokens": 0,
            "tokens": 0, "cost_usd": 0.0, "priced_calls": 0, "unpriced_calls": 0})
        acc["spans"] += r.spans or 0
        acc["input_tokens"] += r.input_tokens or 0
        acc["output_tokens"] += r.output_tokens or 0
        acc["tokens"] += (r.input_tokens or 0) + (r.output_tokens or 0)
        acc["cost_usd"] += r.cost_usd or 0.0
        acc["priced_calls"] += r.priced_calls or 0
        acc["unpriced_calls"] += r.unpriced_calls or 0
    out = sorted(by_period.values(), key=lambda x: x["period"], reverse=True)[:months]
    for a in out:
        a["cost_usd"] = round(a["cost_usd"], 6)
    return out
