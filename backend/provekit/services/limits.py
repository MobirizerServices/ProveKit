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

    def add(self, key: str, amount: float, ttl: int) -> float:
        with self._lock:
            total = float(self._c.get(key, 0.0)) + amount
            self._c[key] = total
            self._c.move_to_end(key)
            return total

    def get_float(self, key: str) -> float:
        with self._lock:
            return float(self._c.get(key, 0.0))


class _RedisWindow:
    def __init__(self, url: str):
        import redis
        self._r = redis.Redis.from_url(url, decode_responses=True)

    def hit(self, key: str, ttl: int) -> int:
        pipe = self._r.pipeline()
        pipe.incr(key)
        pipe.expire(key, ttl)
        return pipe.execute()[0]

    def add(self, key: str, amount: float, ttl: int) -> float:
        pipe = self._r.pipeline()
        pipe.incrbyfloat(key, amount)
        pipe.expire(key, ttl)
        return float(pipe.execute()[0])

    def get_float(self, key: str) -> float:
        v = self._r.get(key)
        return float(v) if v else 0.0


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


def _spend_key(ws_id: int) -> str:
    return f"spend:{ws_id}:{time.strftime('%Y-%m', time.gmtime())}"   # per project, per calendar month


def check_spend_cap(ws_id: int) -> None:
    """Reject a re-run if this project has already hit its monthly playground/replay spend cap.
    Checked before the call (which then adds its own cost via record_spend). Cap of 0 disables."""
    cap = get_settings().playground_monthly_usd_cap
    if cap and cap > 0 and _window().get_float(_spend_key(ws_id)) >= cap:
        raise HTTPException(402, f"Monthly playground spend cap of ${cap:.2f} reached for this project.")


def record_spend(ws_id: int, usd: float) -> None:
    """Accrue estimated cost of a re-run toward the project's monthly total (35-day TTL)."""
    if usd > 0:
        _window().add(_spend_key(ws_id), usd, 35 * 24 * 3600)


def check_playground_rate(ws_id: int) -> None:
    """Throttle interactive re-runs (playground/replay) per project — these make live, billable
    provider calls, so bound them harder than ingest. Per-worker without REDIS_URL (see below)."""
    key = f"playground:{ws_id}:{_now() // 60}"
    if _window().hit(key, 60) > 30:
        raise HTTPException(429, "Too many playground runs — wait a minute.",
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
