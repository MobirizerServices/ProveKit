"""Rate limiting + quotas, so one workspace can't exhaust shared infrastructure.

Fixed-window per-workspace counter. Redis-backed when REDIS_URL is set (correct across
workers), else in-memory. A dependency raises 429 with Retry-After when the window is full.
Local mode (no hosting) leaves the limit generous; tune via RATE_LIMIT_PER_MIN.
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from functools import lru_cache

from fastapi import Depends, HTTPException

from ..config import get_settings
from ..models import Workspace
from .workspace import current_workspace


class _MemoryWindow:
    def __init__(self):
        # LRU-ordered so eviction drops the oldest bucket, never the one being counted.
        self._c: OrderedDict[str, int] = OrderedDict()
        self._lock = threading.Lock()

    def hit(self, key: str, ttl: int) -> int:
        # Streams run concurrently in the threadpool, so the read-modify-write must be atomic
        # or concurrent hits under-count and admit more than the limit.
        with self._lock:
            count = self._c.get(key, 0) + 1
            self._c[key] = count
            self._c.move_to_end(key)  # mark as most-recently-used
            while len(self._c) > 10_000:
                self._c.popitem(last=False)  # evict least-recently-used, keeping live buckets
            return count


class _RedisWindow:
    def __init__(self, url: str):
        import redis
        self._r = redis.Redis.from_url(url, decode_responses=True)

    def hit(self, key: str, ttl: int) -> int:
        pipe = self._r.pipeline()
        pipe.incr(key)
        pipe.expire(key, ttl)
        return pipe.execute()[0]


@lru_cache
def _window():
    url = get_settings().redis_url
    return _RedisWindow(url) if url else _MemoryWindow()


def _now() -> int:
    # time.time() is fine here (not a resumable workflow); windows are wall-clock minutes.
    return int(time.time())


def check_rate(ws: Workspace = Depends(current_workspace)) -> Workspace:
    """Dependency: enforce the per-workspace request rate on run endpoints."""
    limit = get_settings().rate_limit_per_min
    if limit <= 0:
        return ws
    window = _now() // 60
    key = f"rl:{ws.id}:{window}"
    count = _window().hit(key, 60)
    if count > limit:
        raise HTTPException(429, "Rate limit exceeded — slow down.",
                            headers={"Retry-After": str(60 - (_now() % 60))})
    return ws


def check_login_rate(ident: str) -> None:
    """Throttle login attempts per identifier (email+IP) to blunt brute force."""
    limit = get_settings().login_attempts_per_min
    if limit <= 0:
        return
    key = f"login:{ident}:{_now() // 60}"
    if _window().hit(key, 60) > limit:
        raise HTTPException(429, "Too many login attempts — wait a minute.",
                            headers={"Retry-After": str(60 - (_now() % 60))})


def enforce_dataset_size(n_rows: int) -> None:
    cap = get_settings().dataset_max_rows
    if cap and n_rows > cap:
        raise HTTPException(400, f"Dataset too large: {n_rows} rows (max {cap}).")


def clamp_max_tokens(req: dict) -> None:
    cap = get_settings().max_tokens_cap
    if cap and isinstance(req.get("max_tokens"), int) and req["max_tokens"] > cap:
        req["max_tokens"] = cap


def prune_runs(db, workspace_id: int) -> None:
    """Keep only the most recent N runs per workspace (called after an insert)."""
    keep = get_settings().runs_retention
    if not keep:
        return
    from ..models import Run
    ids = [r.id for r in db.query(Run.id).filter(Run.workspace_id == workspace_id)
           .order_by(Run.id.desc()).offset(keep).all()]
    if ids:
        db.query(Run).filter(Run.id.in_(ids)).delete(synchronize_session=False)
        db.commit()
