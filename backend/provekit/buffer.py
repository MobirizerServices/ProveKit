"""A bounded on-disk buffer for spans the portal wouldn't take.

Client-side half of durable ingest. The SDK is fail-open by design — a tracing library that
can break the app it observes is worse than no tracing — so an unreachable portal has always
meant the batch is dropped. That is the right call for a *long* outage and a poor one for the
common case: a deploy, a restart, thirty seconds of network. Those are exactly the moments
worth having traces for, and exactly the ones we lost.

So a failed export is written to disk and retried on the next export or flush. Bounded by
batch count, and oldest-first eviction when full: a buffer that grows without limit is just a
different way to break the user's app, which is the thing we refuse to do.

SDK module — depends only on the standard library, and imports no server code (see AGENTS.md).
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from pathlib import Path

log = logging.getLogger("provekit")

_DEFAULT_MAX_BATCHES = 500


class SpanBuffer:
    """Failed export batches, staged on disk oldest-first.

    Every method swallows its own errors. A buffer that raises has converted "we lost some
    traces" into "we broke production", and the whole point of fail-open is that the second
    outcome is never acceptable.
    """

    def __init__(self, directory: str | None = None, max_batches: int = _DEFAULT_MAX_BATCHES):
        self._dir = Path(directory) if directory else Path(tempfile.gettempdir()) / "provekit-buffer"
        self._max = max_batches
        self._seq = 0
        self._ok = True          # flipped off if the directory turns out to be unwritable

    # -- staging ---------------------------------------------------------------------------

    def put(self, body: dict) -> bool:
        """Buffer one OTLP body. False if it couldn't be staged (buffer off, full, or no disk)."""
        if not self._ok or self._max <= 0:
            return False
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            # Read-only filesystem or no permission. Stop trying: this will not fix itself, and
            # logging once per export would be its own kind of failure.
            log.debug("provekit: span buffer unavailable (%s); exports will drop on failure", e)
            self._ok = False
            return False
        self._evict()
        self._seq += 1
        name = f"{int(time.time() * 1000):013d}-{os.getpid()}-{self._seq:06d}.json"
        try:
            tmp = self._dir / (name + ".partial")
            tmp.write_text(json.dumps(body), encoding="utf-8")
            os.replace(tmp, self._dir / name)
            return True
        except (OSError, TypeError, ValueError) as e:
            log.debug("provekit: could not buffer span batch (%s)", e)
            return False

    def _evict(self) -> None:
        """Keep the buffer under its cap, dropping the oldest first.

        Oldest-first because a stale batch is the least useful thing here: if the portal has
        been down long enough to fill the buffer, the recent spans are the ones someone is
        about to go looking for.
        """
        entries = self.pending()
        excess = len(entries) - self._max + 1
        for path in entries[:max(0, excess)]:
            try:
                path.unlink()
            except OSError:
                pass

    # -- draining --------------------------------------------------------------------------

    def pending(self) -> list[Path]:
        try:
            return sorted(p for p in self._dir.iterdir() if p.suffix == ".json")
        except OSError:
            return []

    def depth(self) -> int:
        return len(self.pending())

    def drain(self, send) -> int:
        """Retry buffered batches with `send(body) -> bool`. Returns how many were accepted.

        Stops at the first failure. If the portal is still down, walking the rest of the buffer
        just spends the app's time on calls we already know the answer to — and this runs on
        the exporter's thread, in the user's process.
        """
        flushed = 0
        for path in self.pending():
            try:
                body = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                # Unreadable entry: drop it rather than retry forever behind everything else.
                try:
                    path.unlink()
                except OSError:
                    pass
                continue
            try:
                if not send(body):
                    break
            except Exception:
                break
            try:
                path.unlink()
            except OSError:
                pass
            flushed += 1
        return flushed
