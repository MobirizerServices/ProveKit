"""Coverage for the Redis rate-limit path, LRU eviction, run pruning, and auth edges."""
import sys
import types

import pytest
from fastapi.testclient import TestClient

from provekit.config import get_settings
from provekit.database import SessionLocal
from provekit.main import app
from provekit.models import Run, User, Workspace
from provekit.services import auth, limits


def test_memory_window_evicts_lru_not_active():
    w = limits._MemoryWindow()
    for i in range(10_050):
        w.hit(f"k{i}", 60)
    assert len(w._c) <= 10_000            # eviction ran (popitem)
    assert w.hit("k10049", 60) == 2       # a recently-touched bucket survived


def test_redis_window(monkeypatch):
    class FakePipe:
        def incr(self, k): pass
        def expire(self, k, t): pass
        def execute(self): return [7]

    class FakeClient:
        def pipeline(self): return FakePipe()

    fake_redis = types.SimpleNamespace(
        Redis=types.SimpleNamespace(from_url=lambda url, decode_responses: FakeClient()))
    monkeypatch.setitem(sys.modules, "redis", fake_redis)
    monkeypatch.setattr(get_settings(), "redis_url", "redis://x")
    limits._window.cache_clear()
    try:
        w = limits._window()
        assert isinstance(w, limits._RedisWindow)
        assert w.hit("rk", 60) == 7        # covers _RedisWindow.__init__ + hit
    finally:
        limits._window.cache_clear()


def test_enforce_dataset_size_and_prune(monkeypatch):
    monkeypatch.setattr(get_settings(), "dataset_max_rows", 2)
    with pytest.raises(Exception):
        limits.enforce_dataset_size(5)
    limits.enforce_dataset_size(1)         # under cap: no raise

    db = SessionLocal()
    try:
        u = db.query(User).filter(User.email == "prune@x.com").first()
        if not u:
            u = User(email="prune@x.com", name="p"); db.add(u); db.commit(); db.refresh(u)
        w = Workspace(name="prune-ws", owner_user_id=u.id); db.add(w); db.commit(); db.refresh(w)
        for i in range(5):
            db.add(Run(workspace_id=w.id, type="prompt", label=f"r{i}", status="completed"))
        db.commit()
        monkeypatch.setattr(get_settings(), "runs_retention", 2)
        limits.prune_runs(db, w.id)
        assert db.query(Run).filter(Run.workspace_id == w.id).count() == 2
    finally:
        db.close()


def test_login_rate_and_prune_disabled(monkeypatch):
    monkeypatch.setattr(get_settings(), "login_attempts_per_min", 0)
    assert limits.check_login_rate("someone@x.com:1.2.3.4") is None   # disabled -> early return
    monkeypatch.setattr(get_settings(), "runs_retention", 0)
    db = SessionLocal()
    try:
        assert limits.prune_runs(db, 1) is None                       # disabled -> early return
    finally:
        db.close()


def test_local_user_integrity_fallback(monkeypatch):
    # Deterministically exercise the concurrent-INSERT loser path: make the existence check
    # miss once (so _local_user tries to INSERT) while the row actually exists, so the commit
    # raises IntegrityError and the fallback re-query returns the winning row.
    db = SessionLocal()
    d2 = SessionLocal()
    if not d2.query(User).filter(User.email == auth.LOCAL_EMAIL).first():
        d2.add(User(email=auth.LOCAL_EMAIL, name="Local", auth_provider="local")); d2.commit()
    d2.close()

    orig_query = db.query
    state = {"missed": False}

    class _Wrap:
        def __init__(self, q): self._q = q
        def filter(self, *a, **k): self._q = self._q.filter(*a, **k); return self
        def first(self):
            if not state["missed"]:
                state["missed"] = True
                return None            # first check misses -> forces the INSERT path
            return self._q.first()

    monkeypatch.setattr(db, "query", lambda *a, **k: _Wrap(orig_query(*a, **k)))
    try:
        u = auth._local_user(db)       # INSERT dup -> IntegrityError -> rollback -> re-query
        assert u is not None and u.email == auth.LOCAL_EMAIL
    finally:
        db.close()


def test_secret_uses_secret_key_when_set(monkeypatch):
    monkeypatch.setattr(get_settings(), "secret_key", "x" * 40)
    t = auth.make_token(9, ver=1)
    assert auth.read_token(t) == (9, 1)    # signed with the SECRET_KEY-derived key


def test_verify_password_rejects_malformed_hash():
    assert auth.verify_password("whatever", "not-a-pbkdf2-hash") is False


def test_get_current_user_cookie_revoke_and_no_cookie(monkeypatch):
    monkeypatch.setattr(get_settings(), "hosted", True)
    c = TestClient(app, base_url="https://testserver")
    c.post("/api/auth/register", json={"email": "cu@x.com", "password": "supersecret1"})
    assert c.get("/api/auth/me").status_code == 200          # cookie -> claims -> user

    db = SessionLocal()
    u = db.query(User).filter(User.email == "cu@x.com").first()
    u.token_version += 1; db.commit(); db.close()            # revoke outstanding tokens
    assert c.get("/api/auth/me").status_code == 401          # version mismatch -> 401

    fresh = TestClient(app, base_url="https://testserver")
    assert fresh.get("/api/auth/me").status_code == 401      # no cookie -> hosted 401
