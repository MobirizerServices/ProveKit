"""Auth: password hashing, token round-trip, register/login/me/logout, hosted-mode gate."""
import pytest
from fastapi.testclient import TestClient

from agentman.config import get_settings
from agentman.main import app
from agentman.services import auth


def test_password_hash_roundtrip():
    h = auth.hash_password("correct horse battery")
    assert auth.verify_password("correct horse battery", h)
    assert not auth.verify_password("wrong", h)
    assert h != auth.hash_password("correct horse battery")  # salted


def test_token_roundtrip_and_tamper():
    t = auth.make_token(42)
    assert auth.read_token(t) == 42
    assert auth.read_token(t[:-2] + "xx") is None          # bad signature
    assert auth.read_token("garbage") is None
    assert auth.read_token(auth.make_token(1, ttl=-10)) is None  # expired


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_register_login_me_logout(client):
    r = client.post("/api/auth/register", json={"email": "a@b.com", "password": "supersecret1"})
    assert r.status_code == 200 and r.json()["email"] == "a@b.com"
    assert auth.COOKIE in r.cookies

    client.cookies.clear()
    r = client.post("/api/auth/login", json={"email": "a@b.com", "password": "supersecret1"})
    assert r.status_code == 200
    me = client.get("/api/auth/me")
    assert me.status_code == 200 and me.json()["email"] == "a@b.com"

    client.post("/api/auth/logout")
    client.cookies.clear()
    # local mode: /me still resolves to the default local user (no 401)
    assert client.get("/api/auth/me").json()["email"] == auth.LOCAL_EMAIL


def test_duplicate_and_bad_login(client):
    client.post("/api/auth/register", json={"email": "dup@b.com", "password": "supersecret1"})
    assert client.post("/api/auth/register", json={"email": "dup@b.com", "password": "supersecret1"}).status_code == 409
    assert client.post("/api/auth/login", json={"email": "dup@b.com", "password": "nope"}).status_code == 401
    assert client.post("/api/auth/register", json={"email": "x@b.com", "password": "short"}).status_code == 400


def test_hosted_mode_requires_auth(client, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "hosted", True)
    client.cookies.clear()
    assert client.get("/api/auth/me").status_code == 401  # no default user in hosted mode
