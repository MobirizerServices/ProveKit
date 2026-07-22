"""Durable accept for trace ingest.

Ingest used to write straight through to the database. That is fine until the write fails:
the exporter has already been told 200 (or gets a 5xx and retries the *whole* batch, which
#184 taught us to dedupe), and either way a DB blip during the window is data that no longer
exists anywhere. An observability tool that loses spans is the one failure it cannot have.

So: **write the batch to disk before acknowledging it**, then persist as usual. The spool
entry is removed once the rows are committed. If the commit fails — or the process dies
mid-write — the entry survives and `drain()` retries it, on a background task at startup and
periodically after that.

Why a file and not Redis: Redis is optional here (`redis_url` is unset in the default and
dev deployments), and un-tuned Redis is not durable across a restart anyway. A local
append-and-fsync is durable with no extra infrastructure, which matches how ProveKit is
actually deployed. The trade is that the spool is node-local: it protects against a database
outage, not against losing the node itself.

Ordering note: this deliberately does *not* make ingest asynchronous. The inline persist stays
on the request path, so a trace is queryable the moment the POST returns — the property every
read-after-write caller (and the whole test suite) depends on. The spool is a safety net under
that write, not a queue in front of it.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from pathlib import Path

from ..config import get_settings

log = logging.getLogger("provekit.spool")

# A spooled batch is one file: <epoch_ms>-<pid>-<counter>.json. The name sorts oldest-first,
# which is the order we want to replay them in.
_SEQ = 0

# Process-local counters for the two ways a batch can fail to become rows. Neither is silent
# any more, which is the point of #14: "my trace is missing" should have an answer that doesn't
# require reading the logs. Reset on restart — they describe this worker, not all of history.
_counters = {"shed": 0, "quarantined": 0}


def note_shed() -> None:
    """A batch refused by backpressure. The exporter will retry it; a rising count means the
    database is not keeping up with what clients are sending."""
    _counters["shed"] += 1


def counters() -> dict:
    return dict(_counters)


def spool_dir() -> Path:
    """Where batches are staged. Overridable so tests (and a read-only image) can redirect it."""
    s = get_settings()
    return Path(s.spool_dir) if s.spool_dir else Path(tempfile.gettempdir()) / "provekit-spool"


def enabled() -> bool:
    return get_settings().spool_enabled


def _ensure_dir() -> Path | None:
    d = spool_dir()
    try:
        d.mkdir(parents=True, exist_ok=True)
        return d
    except OSError as e:
        # A spool we cannot write is a degraded safety net, not a reason to reject the batch:
        # the inline persist still runs. Log once per failure so it's visible in /healthz logs.
        log.warning("spool directory unavailable (%s): accepting without durable staging", e)
        return None


def stage(workspace_id: int, rows: list[dict]) -> Path | None:
    """Persist `rows` to disk and return the entry path (None if spooling is off/unavailable).

    Durability here means fsync: a file that is merely in the page cache is exactly as lost as
    no file at all when the box loses power, which is the case this exists for.
    """
    global _SEQ
    if not rows or not enabled():
        return None
    d = _ensure_dir()
    if d is None:
        return None
    _SEQ += 1
    path = d / f"{int(time.time() * 1000):013d}-{os.getpid()}-{_SEQ:06d}.json"
    body = json.dumps({"workspace_id": workspace_id, "staged_at": time.time(), "rows": rows})
    try:
        # Write to a temp name and rename: a reader must never observe a half-written batch,
        # and rename within a directory is atomic.
        tmp = path.with_suffix(".partial")
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(body)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        _adjust_depth(+1)
        return path
    except OSError as e:
        log.warning("could not stage batch to spool (%s)", e)
        return None


def release(path: Path | None) -> None:
    """Drop a staged entry once its rows are safely committed."""
    if path is None:
        return
    try:
        path.unlink()
        _adjust_depth(-1)
    except FileNotFoundError:
        pass
    except OSError as e:
        log.warning("could not release spool entry %s (%s)", path.name, e)


def pending() -> list[Path]:
    """Staged batches awaiting a retry, oldest first."""
    d = spool_dir()
    if not d.exists():
        return []
    try:
        return sorted(p for p in d.iterdir() if p.suffix == ".json")
    except OSError:
        return []


def depth() -> int:
    """How many batches are waiting. Queue depth for #14 and the backpressure signal for #23."""
    return len(pending())


# Backpressure is checked on every ingest request, and an un-cached check is a directory listing
# per request on the hottest path in the product. A backlog does not appear in microseconds, so
# a short TTL is indistinguishable from an exact reading and costs nothing.
_DEPTH_TTL = 1.0
_depth_cache: tuple[float, int] = (0.0, 0)


def depth_cached() -> int:
    global _depth_cache
    now = time.monotonic()
    at, value = _depth_cache
    if now - at >= _DEPTH_TTL:
        value = depth()
        _depth_cache = (now, value)
    return value


def _adjust_depth(delta: int) -> None:
    """Track a stage/release against the cached count instead of re-listing the directory.

    Invalidating on stage would defeat the cache outright — every ingest stages — so the count
    is nudged in place and the TTL re-syncs it from disk, which also corrects any drift from
    another worker draining the same directory.
    """
    global _depth_cache
    at, value = _depth_cache
    if at:
        _depth_cache = (at, max(0, value + delta))


def invalidate_depth_cache() -> None:
    """Force the next `depth_cached()` to re-read from disk."""
    global _depth_cache
    _depth_cache = (0.0, 0)


def oldest_age_seconds() -> float:
    """Age of the oldest un-drained batch — the honest definition of ingest lag: zero when
    everything the server accepted has landed, and growing exactly when it hasn't."""
    entries = pending()
    if not entries:
        return 0.0
    try:
        return max(0.0, time.time() - entries[0].stat().st_mtime)
    except OSError:
        return 0.0


def load(path: Path) -> dict | None:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError) as e:
        # Unparseable entry: quarantine rather than retry forever. Keeping the file (renamed)
        # means a corrupted batch can still be inspected instead of vanishing silently.
        log.error("corrupt spool entry %s (%s) — quarantining", path.name, e)
        _counters["quarantined"] += 1
        try:
            path.rename(path.with_suffix(".corrupt"))
            _adjust_depth(-1)
        except OSError:
            pass
        return None
