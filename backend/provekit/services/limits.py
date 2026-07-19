"""Login rate limiting to blunt brute force. Fixed-window counter — Redis-backed when
REDIS_URL is set (correct across workers), else in-memory."""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from functools import lru_cache

from fastapi import HTTPException

from ..config import get_settings


class _MemoryWindow:
    def __init__(self):
        self._c: OrderedDict[str, int] = OrderedDict()
        self._lock = threading.Lock()

    def hit(self, key: str, ttl: int) -> int:
        with self._lock:
            count = self._c.get(key, 0) + 1
            self._c[key] = count
            self._c.move_to_end(key)
            while len(self._c) > 10_000:
                self._c.popitem(last=False)
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
    return int(time.time())


def check_login_rate(ident: str) -> None:
    """Throttle login attempts per identifier (email+IP) to blunt brute force."""
    limit = get_settings().login_attempts_per_min
    if limit <= 0:
        return
    key = f"login:{ident}:{_now() // 60}"
    if _window().hit(key, 60) > limit:
        raise HTTPException(429, "Too many login attempts — wait a minute.",
                            headers={"Retry-After": str(60 - (_now() % 60))})


def check_ingest_rate(ws_id: int) -> None:
    """Throttle trace-ingest requests per project to bound abuse/cost on a public instance.
    Note: without REDIS_URL the window is per-worker, so the effective cap scales with the
    number of uvicorn workers — set REDIS_URL for a hard global cap."""
    limit = get_settings().ingest_rate_per_min
    if limit <= 0:
        return
    key = f"ingest:{ws_id}:{_now() // 60}"
    if _window().hit(key, 60) > limit:
        raise HTTPException(429, "Ingest rate limit exceeded for this project.",
                            headers={"Retry-After": str(60 - (_now() % 60))})
