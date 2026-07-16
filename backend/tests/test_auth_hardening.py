"""Auth hardening: login brute-force throttle + hosted-mode SECRET_KEY guard."""
import pytest
from fastapi.testclient import TestClient

from agentman.config import get_settings
from agentman.main import _guard_production_config, app
from agentman.services import limits


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    limits._window.cache_clear()
    yield
    limits._window.cache_clear()


def test_login_is_rate_limited(monkeypatch):
    monkeypatch.setattr(get_settings(), "login_attempts_per_min", 3)
    with TestClient(app) as c:
        codes = [c.post("/api/auth/login", json={"email": "nope@x.com", "password": "wrongpass1"}).status_code
                 for _ in range(5)]
        assert codes.count(401) == 3 and codes.count(429) == 2  # throttled after 3 tries


def test_secret_key_guard_blocks_hosted_boot(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "hosted", True)
    monkeypatch.setattr(s, "secret_key", "dev-only-change-me")
    with pytest.raises(RuntimeError, match="strong SECRET_KEY"):
        _guard_production_config()
    monkeypatch.setattr(s, "secret_key", "a-genuinely-long-random-secret-value")
    _guard_production_config()  # strong key → no raise


def test_local_mode_ignores_secret_key_guard(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "hosted", False)
    monkeypatch.setattr(s, "secret_key", "")
    _guard_production_config()  # local mode never requires a key
