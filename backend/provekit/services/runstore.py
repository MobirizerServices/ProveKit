"""Storage for paused flow-run contexts (breakpoint/step debugging).

In-memory by default (single-process local use). When REDIS_URL is set, contexts live in
Redis so step-debugging survives across uvicorn workers and restarts — pop uses GETDEL so
two concurrent /continue calls can't resume the same run twice.
"""
from __future__ import annotations

import json
import time
from functools import lru_cache

from ..config import get_settings

_TTL = 1800          # evict paused runs abandoned for 30 min
_MAX = 200           # in-memory hard cap
_MAX_BYTES = 1_000_000  # reject a ctx that serializes larger than ~1MB


class _MemoryStore:
    def __init__(self):
        self._d: dict[str, dict] = {}
        self._ts: dict[str, float] = {}

    def store(self, rid: str, ctx: dict) -> None:
        now = time.monotonic()
        self._d[rid] = ctx
        self._ts[rid] = now
        for k in [k for k, t in list(self._ts.items()) if now - t > _TTL]:
            self._d.pop(k, None); self._ts.pop(k, None)
        if len(self._d) > _MAX:
            for k in sorted(self._ts, key=self._ts.get)[: len(self._d) - _MAX]:
                self._d.pop(k, None); self._ts.pop(k, None)

    def get(self, rid: str) -> dict | None:
        return self._d.get(rid)

    def pop(self, rid: str) -> dict | None:
        self._ts.pop(rid, None)
        return self._d.pop(rid, None)

    def drop(self, rid: str) -> None:
        self._d.pop(rid, None); self._ts.pop(rid, None)


class _RedisStore:
    _PREFIX = "agm:run:"

    def __init__(self, url: str):
        import redis  # imported only when REDIS_URL is set
        self._r = redis.Redis.from_url(url, decode_responses=True)

    def _k(self, rid: str) -> str:
        return self._PREFIX + rid

    def store(self, rid: str, ctx: dict) -> None:
        blob = json.dumps(ctx)
        if len(blob) > _MAX_BYTES:
            raise ValueError("run context too large to persist")
        self._r.setex(self._k(rid), _TTL, blob)

    def get(self, rid: str) -> dict | None:
        blob = self._r.get(self._k(rid))
        return json.loads(blob) if blob else None

    def pop(self, rid: str) -> dict | None:
        blob = self._r.getdel(self._k(rid))  # atomic — prevents double-resume
        return json.loads(blob) if blob else None

    def drop(self, rid: str) -> None:
        self._r.delete(self._k(rid))


@lru_cache
def _store():
    url = get_settings().redis_url
    return _RedisStore(url) if url else _MemoryStore()


def store_ctx(rid: str, ctx: dict) -> None:
    _store().store(rid, ctx)


def get_ctx(rid: str) -> dict | None:
    return _store().get(rid)


def pop_ctx(rid: str) -> dict | None:
    return _store().pop(rid)


def drop_ctx(rid: str) -> None:
    _store().drop(rid)
