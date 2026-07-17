"""Password reset + email verification flows (email sender captured, not sent)."""
import pytest
from fastapi.testclient import TestClient

from agentman.config import get_settings
from agentman.main import app
from agentman.services import auth, email, limits


@pytest.fixture(autouse=True)
def _reset():
    limits._window.cache_clear()
    yield
    limits._window.cache_clear()


@pytest.fixture
def sent(monkeypatch):
    box = []
    monkeypatch.setattr(email, "send", lambda to, subject, body: box.append((to, subject, body)))
    return box


def _link(box, needle):
    for _, _, body in box:
        for line in body.splitlines():
            if needle in line:
                return line.strip()
    return None


def test_password_reset_flow(sent):
    with TestClient(app, base_url="https://testserver") as c:
        c.post("/api/auth/register", json={"email": "u@x.com", "password": "originalpw1"})
        sent.clear()
        # forgot -> emails a reset link (always 200, even for unknown emails)
        assert c.post("/api/auth/forgot", json={"email": "u@x.com"}).status_code == 200
        assert c.post("/api/auth/forgot", json={"email": "nobody@x.com"}).status_code == 200
        link = _link(sent, "/reset?token=")
        assert link and "/reset?token=" in link
        token = link.split("token=")[1]

        # reset with the token sets a new password
        assert c.post("/api/auth/reset", json={"token": token, "password": "brandnewpw2"}).status_code == 200
        # old password no longer works, new one does
        assert c.post("/api/auth/login", json={"email": "u@x.com", "password": "originalpw1"}).status_code == 401
        assert c.post("/api/auth/login", json={"email": "u@x.com", "password": "brandnewpw2"}).status_code == 200


def test_reset_token_cannot_be_used_as_session():
    # a reset-purpose token must not authenticate as a session
    t = auth.make_token(1, purpose="reset")
    assert auth.read_token(t, purpose="session") is None
    assert auth.read_token(t, purpose="reset") == 1


def test_expired_or_bad_reset_token_rejected():
    with TestClient(app, base_url="https://testserver") as c:
        assert c.post("/api/auth/reset", json={"token": "garbage", "password": "whatever8"}).status_code == 400
        expired = auth.make_token(1, ttl=-1, purpose="reset")
        assert c.post("/api/auth/reset", json={"token": expired, "password": "whatever8"}).status_code == 400


def test_email_verification_gate(sent, monkeypatch):
    monkeypatch.setattr(get_settings(), "require_email_verification", True)
    with TestClient(app, base_url="https://testserver") as c:
        c.post("/api/auth/register", json={"email": "v@x.com", "password": "verifypw12"})
        # verification required → login refused until verified
        assert c.post("/api/auth/login", json={"email": "v@x.com", "password": "verifypw12"}).status_code == 403
        link = _link(sent, "/verify?token=")
        token = link.split("token=")[1]
        assert c.post("/api/auth/verify", json={"token": token}).status_code == 200
        # now login works
        assert c.post("/api/auth/login", json={"email": "v@x.com", "password": "verifypw12"}).status_code == 200
