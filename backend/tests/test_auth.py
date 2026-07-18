"""Auth: password hashing, token round-trip, register/login/me/logout, hosted-mode gate."""
import pytest
from fastapi.testclient import TestClient

from provekit.config import get_settings
from provekit.main import app
from provekit.services import auth


def test_password_hash_roundtrip():
    h = auth.hash_password("correct horse battery")
    assert auth.verify_password("correct horse battery", h)
    assert not auth.verify_password("wrong", h)
    assert h != auth.hash_password("correct horse battery")  # salted


def test_local_user_creation_is_concurrency_safe():
    # The frontend mount fires several requests at once; on a fresh local DB they all
    # get-or-create the singleton local user. The losing INSERTs must be absorbed, not 500.
    import threading

    from provekit.database import SessionLocal
    from provekit.models import User

    d = SessionLocal()
    d.query(User).filter(User.email == auth.LOCAL_EMAIL).delete()
    d.commit(); d.close()

    ids, errors = [], []

    def worker():
        s = SessionLocal()
        try:
            ids.append(auth._local_user(s).id)
        except Exception as exc:  # pragma: no cover - the bug this guards against
            errors.append(repr(exc))
        finally:
            s.close()

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads: t.start()
    for t in threads: t.join()

    assert not errors, errors           # no IntegrityError bubbled up as a 500
    assert len(set(ids)) == 1           # everyone resolved to the same local user
    d = SessionLocal()
    assert d.query(User).filter(User.email == auth.LOCAL_EMAIL).count() == 1
    d.close()


def test_token_roundtrip_and_tamper():
    t = auth.make_token(42, ver=3)
    assert auth.read_token(t) == (42, 3)                    # (user_id, token_version)
    assert auth.read_token(t[:-2] + "xx") is None          # bad signature
    assert auth.read_token("garbage") is None
    assert auth.read_token("a.b.é") is None                 # non-ASCII sig → no 500
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
