"""Paused-run store: in-memory + Redis-shaped backend, atomic pop, size cap."""
import pytest

from agentman.services import runstore


def test_memory_store_roundtrip_and_atomic_pop():
    s = runstore._MemoryStore()
    s.store("r1", {"a": 1})
    assert s.get("r1") == {"a": 1}
    assert s.pop("r1") == {"a": 1}
    assert s.pop("r1") is None  # gone after pop — a second /continue can't resume it


def test_memory_store_evicts_over_cap(monkeypatch):
    monkeypatch.setattr(runstore, "_MAX", 3)
    s = runstore._MemoryStore()
    for i in range(5):
        s.store(f"r{i}", {"i": i})
    assert len(s._d) <= 3


class _FakeRedis:
    """Minimal getdel/setex/get/delete-compatible stand-in for redis.Redis."""
    def __init__(self):
        self.kv = {}

    def setex(self, k, ttl, v):
        self.kv[k] = v

    def get(self, k):
        return self.kv.get(k)

    def getdel(self, k):
        return self.kv.pop(k, None)

    def delete(self, k):
        self.kv.pop(k, None)


def test_redis_store_roundtrip_and_getdel(monkeypatch):
    s = runstore._RedisStore.__new__(runstore._RedisStore)
    s._r = _FakeRedis()
    s.store("r1", {"nodes": {"a": {"text": "hi"}}, "_steps": 2})
    assert s.get("r1")["_steps"] == 2
    assert s.pop("r1")["_steps"] == 2
    assert s.pop("r1") is None  # getdel removed it


def test_redis_store_rejects_oversized_ctx(monkeypatch):
    s = runstore._RedisStore.__new__(runstore._RedisStore)
    s._r = _FakeRedis()
    monkeypatch.setattr(runstore, "_MAX_BYTES", 100)
    with pytest.raises(ValueError, match="too large"):
        s.store("big", {"blob": "x" * 500})


def test_module_helpers_use_configured_backend(monkeypatch):
    runstore._store.cache_clear()
    monkeypatch.setattr(runstore.get_settings(), "redis_url", "")  # in-memory
    runstore.store_ctx("z", {"v": 1})
    assert runstore.get_ctx("z") == {"v": 1}
    assert runstore.pop_ctx("z") == {"v": 1}
    runstore._store.cache_clear()
