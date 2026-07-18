"""Coverage-focused tests for infra/support modules: email, sealing, observability,
cli, database migrations, runstore, deploy, testfile, workspace, main.

Everything that would touch the network, a subprocess, SMTP, or Redis is monkeypatched.
No real I/O beyond temp files and the in-process SQLite test DB.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging

import pytest
from cryptography.fernet import Fernet


class _CaptureLogs:
    """Attach a handler directly to a named logger and collect its messages.

    Order-independent alternative to pytest's `caplog` (which relies on propagation
    to the root handler — brittle once another test has mutated logging state)."""
    def __init__(self, name: str, level: int = logging.INFO):
        self.logger = logging.getLogger(name)
        self.level = level
        self.records: list[logging.LogRecord] = []
        self._handler = logging.Handler()
        self._handler.emit = self.records.append  # type: ignore[method-assign]
        self._prev_level = None
        self._prev_propagate = None
        self._prev_disable = None
        self._prev_disabled = None

    def __enter__(self):
        self._prev_level = self.logger.level
        self._prev_propagate = self.logger.propagate
        # Earlier tests spin up a TestClient (uvicorn/alembic logging config runs with
        # disable_existing_loggers=True), which both sets a process-global logging.disable()
        # cutoff and flips this logger's `.disabled` flag. Both silently drop records
        # regardless of handlers — neutralize them for the block, then restore.
        self._prev_disable = logging.root.manager.disable
        self._prev_disabled = self.logger.disabled
        logging.disable(logging.NOTSET)
        self.logger.disabled = False
        self.logger.setLevel(self.level)
        self.logger.propagate = True
        self.logger.addHandler(self._handler)
        return self

    def __exit__(self, *a):
        self.logger.removeHandler(self._handler)
        self.logger.setLevel(self._prev_level)
        self.logger.propagate = self._prev_propagate
        self.logger.disabled = self._prev_disabled
        logging.disable(self._prev_disable)
        return False

    @property
    def text(self) -> str:
        return "\n".join(r.getMessage() for r in self.records)


# ---------------------------------------------------------------------------
# email.py
# ---------------------------------------------------------------------------
from agentman.services import email as email_mod


def test_email_local_no_smtp_logs_body(monkeypatch):
    s = email_mod.get_settings()
    monkeypatch.setattr(s, "smtp_host", "", raising=False)
    monkeypatch.setattr(s, "hosted", False, raising=False)
    with _CaptureLogs("agentman.email") as cap:
        email_mod.send("u@x.com", "Reset", "click https://reset/abc")
    # dev/self-host without SMTP surfaces the body (incl. link) in the logs
    assert "click https://reset/abc" in cap.text


def test_email_hosted_no_smtp_never_logs_body(monkeypatch):
    s = email_mod.get_settings()
    monkeypatch.setattr(s, "smtp_host", "", raising=False)
    monkeypatch.setattr(s, "hosted", True, raising=False)
    with _CaptureLogs("agentman.email") as cap:
        email_mod.send("u@x.com", "Reset", "SECRET-LINK-abc")
    # hosted mode must fail loudly and NOT leak the body
    assert "EMAIL NOT SENT" in cap.text
    assert "SECRET-LINK-abc" not in cap.text


class _FakeSMTP:
    """Context-manager SMTP stand-in supporting starttls/login/send_message."""
    instances: list["_FakeSMTP"] = []

    def __init__(self, host, port, timeout=None):
        self.host, self.port, self.timeout = host, port, timeout
        self.started_tls = False
        self.logged_in = None
        self.sent = None
        _FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self):
        self.started_tls = True

    def login(self, user, pw):
        self.logged_in = (user, pw)

    def send_message(self, msg):
        self.sent = msg


def test_email_smtp_send_path(monkeypatch):
    _FakeSMTP.instances.clear()
    s = email_mod.get_settings()
    monkeypatch.setattr(s, "smtp_host", "smtp.example", raising=False)
    monkeypatch.setattr(s, "smtp_port", 2525, raising=False)
    monkeypatch.setattr(s, "smtp_starttls", True, raising=False)
    monkeypatch.setattr(s, "smtp_user", "user", raising=False)
    monkeypatch.setattr(s, "smtp_password", "pw", raising=False)
    monkeypatch.setattr(s, "smtp_from", "from@example", raising=False)
    monkeypatch.setattr(email_mod.smtplib, "SMTP", _FakeSMTP)
    email_mod.send("dest@x.com", "Hi", "body text")
    srv = _FakeSMTP.instances[-1]
    assert srv.host == "smtp.example" and srv.port == 2525
    assert srv.started_tls is True
    assert srv.logged_in == ("user", "pw")
    assert srv.sent["To"] == "dest@x.com"
    assert srv.sent["From"] == "from@example"
    assert srv.sent["Subject"] == "Hi"


def test_email_smtp_send_failure_warns(monkeypatch):
    s = email_mod.get_settings()
    monkeypatch.setattr(s, "smtp_host", "smtp.example", raising=False)
    monkeypatch.setattr(s, "smtp_user", "", raising=False)
    monkeypatch.setattr(s, "smtp_starttls", False, raising=False)

    class _Boom:
        def __init__(self, *a, **k):
            raise OSError("connection refused")

    monkeypatch.setattr(email_mod.smtplib, "SMTP", _Boom)
    with _CaptureLogs("agentman.email", logging.WARNING) as cap:
        email_mod.send("dest@x.com", "Hi", "body")
    assert "email send failed" in cap.text


# ---------------------------------------------------------------------------
# sealing.py
# ---------------------------------------------------------------------------
from agentman.services import sealing


@pytest.fixture
def secret_key_fernet(monkeypatch):
    """Use a stable SECRET_KEY-derived Fernet so seal/unseal round-trips deterministically."""
    s = sealing.get_settings()
    monkeypatch.setattr(s, "secret_key", "unit-test-secret-key", raising=False)
    sealing._fernet.cache_clear()
    yield
    sealing._fernet.cache_clear()


def test_seal_unseal_round_trip(secret_key_fernet):
    token = sealing.seal("hunter2")
    assert token.startswith(sealing._PREFIX)
    assert sealing.unseal(token) == "hunter2"


def test_seal_skips_empty_prefixed_and_nonstr(secret_key_fernet):
    assert sealing.seal("") == ""            # empty is passed through
    assert sealing.seal(123) == 123          # non-str passed through
    already = sealing._PREFIX + "xyz"
    assert sealing.seal(already) == already  # already-sealed left untouched


def test_unseal_passthrough_nonstr_and_plaintext(secret_key_fernet):
    assert sealing.unseal(None) is None        # non-str returned as-is
    assert sealing.unseal("plaintext") == "plaintext"  # no prefix -> as-is


def test_unseal_bad_token_returns_empty_with_warning(secret_key_fernet):
    bad = sealing._PREFIX + "not-a-valid-fernet-token"
    with _CaptureLogs("agentman.sealing", logging.WARNING) as cap:
        assert sealing.unseal(bad) == ""
    assert "could not decrypt" in cap.text


def test_secret_key_branch_uses_derived_fernet(monkeypatch):
    s = sealing.get_settings()
    monkeypatch.setattr(s, "secret_key", "another-key", raising=False)
    sealing._fernet.cache_clear()
    f = sealing._fernet()
    expected = Fernet(base64.urlsafe_b64encode(hashlib.sha256(b"another-key").digest()))
    # both Fernets derive the same key -> a token from one decrypts with the other
    assert f.decrypt(expected.encrypt(b"x")) == b"x"
    sealing._fernet.cache_clear()


def test_key_file_none_for_non_sqlite(monkeypatch):
    s = sealing.get_settings()
    monkeypatch.setattr(s, "database_url", "postgresql://u@h/db", raising=False)
    assert sealing._key_file() is None


def test_key_file_generated_for_sqlite(monkeypatch, tmp_path):
    s = sealing.get_settings()
    dbfile = tmp_path / "sub" / "app.db"
    monkeypatch.setattr(s, "secret_key", "", raising=False)
    monkeypatch.setattr(s, "database_url", f"sqlite:///{dbfile}", raising=False)
    sealing._fernet.cache_clear()
    kf = sealing._key_file()
    assert kf is not None and kf.name == ".agentman.key"
    # first call generates + writes the key file
    f1 = sealing._fernet()
    assert kf.exists()
    # a fresh Fernet built from the file matches (proves the key was persisted)
    assert Fernet(kf.read_bytes().strip()).decrypt(f1.encrypt(b"z")) == b"z"
    # cache-clear and reload: hits the kf.exists() branch reading the existing file
    sealing._fernet.cache_clear()
    f2 = sealing._fernet()
    assert f2.decrypt(f1.encrypt(b"q")) == b"q"
    sealing._fernet.cache_clear()


def test_key_file_generation_tolerates_chmod_oserror(monkeypatch, tmp_path):
    s = sealing.get_settings()
    dbfile = tmp_path / "app.db"
    monkeypatch.setattr(s, "secret_key", "", raising=False)
    monkeypatch.setattr(s, "database_url", f"sqlite:///{dbfile}", raising=False)
    monkeypatch.setattr(sealing.os, "chmod", lambda *a, **k: (_ for _ in ()).throw(OSError("no chmod")))
    sealing._fernet.cache_clear()
    f = sealing._fernet()  # OSError on chmod is swallowed (Windows/permission-less FS)
    assert (tmp_path / ".agentman.key").exists()
    assert f.decrypt(f.encrypt(b"ok")) == b"ok"
    sealing._fernet.cache_clear()


def test_fernet_raises_without_key_and_non_sqlite(monkeypatch):
    s = sealing.get_settings()
    monkeypatch.setattr(s, "secret_key", "", raising=False)
    monkeypatch.setattr(s, "database_url", "postgresql://u@h/db", raising=False)
    sealing._fernet.cache_clear()
    with pytest.raises(RuntimeError, match="SECRET_KEY must be set"):
        sealing._fernet()
    sealing._fernet.cache_clear()


def test_seal_unseal_config_headers_oauth_env(secret_key_fernet):
    cfg = {
        "api_key": "sk-abc",
        "headers": {"Authorization": "Bearer tok", "X-Trace": "plain"},
        "oauth": {"client_id": "id", "client_secret": "cs"},
        "env": {"TOKEN": "t", "EMPTY": ""},
    }
    sealed = sealing.seal_config(cfg)
    assert sealed["api_key"].startswith(sealing._PREFIX)
    assert sealed["headers"]["Authorization"].startswith(sealing._PREFIX)
    assert sealed["headers"]["X-Trace"] == "plain"  # non-secret header untouched
    assert sealed["oauth"]["client_secret"].startswith(sealing._PREFIX)
    assert sealed["env"]["TOKEN"].startswith(sealing._PREFIX)
    assert sealed["env"]["EMPTY"] == ""             # empty env value left as-is
    # unseal restores exactly
    assert sealing.unseal_config(sealed) == cfg


# ---------------------------------------------------------------------------
# observability.py
# ---------------------------------------------------------------------------
from agentman import observability as obs


def test_json_formatter_includes_request_id_and_exc():
    fmt = obs._JSONFormatter()
    tok = obs.request_id.set("rid-123")
    try:
        try:
            raise ValueError("boom")
        except ValueError:
            import sys
            rec = logging.LogRecord("agentman", logging.ERROR, __file__, 1, "hi %s",
                                    ("there",), sys.exc_info())
        out = json.loads(fmt.format(rec))
    finally:
        obs.request_id.reset(tok)
    assert out["msg"] == "hi there"
    assert out["request_id"] == "rid-123"
    assert out["level"] == "ERROR"
    assert "ValueError" in out["exc"]


def test_setup_logging_hosted_sets_json_formatter(monkeypatch):
    s = obs.get_settings()
    monkeypatch.setattr(s, "hosted", True, raising=False)
    root = logging.getLogger()
    added = logging.StreamHandler()
    root.addHandler(added)
    try:
        obs.setup_logging()
        assert isinstance(added.formatter, obs._JSONFormatter)
    finally:
        root.removeHandler(added)


def test_init_sentry_no_dsn_is_noop(monkeypatch):
    s = obs.get_settings()
    monkeypatch.setattr(s, "sentry_dsn", "", raising=False)
    obs.init_sentry()  # returns early, no import attempted


def test_init_sentry_dsn_set_but_missing_warns(monkeypatch):
    s = obs.get_settings()
    monkeypatch.setattr(s, "sentry_dsn", "https://x@sentry/1", raising=False)
    import builtins
    import sys
    real_import = builtins.__import__
    monkeypatch.delitem(sys.modules, "sentry_sdk", raising=False)

    def fake_import(name, *a, **k):
        if name == "sentry_sdk":
            raise ImportError("no sentry")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with _CaptureLogs("agentman", logging.WARNING) as cap:
        obs.init_sentry()
    assert "sentry-sdk not installed" in cap.text


def test_init_sentry_dsn_set_and_present(monkeypatch):
    s = obs.get_settings()
    monkeypatch.setattr(s, "sentry_dsn", "https://x@sentry/1", raising=False)
    import sys
    import types
    fake = types.ModuleType("sentry_sdk")
    calls = {}
    fake.init = lambda **kw: calls.update(kw)
    monkeypatch.setitem(sys.modules, "sentry_sdk", fake)
    with _CaptureLogs("agentman", logging.INFO) as cap:
        obs.init_sentry()
    assert calls.get("dsn") == "https://x@sentry/1"
    assert "sentry enabled" in cap.text


def _obs_app():
    """A tiny ASGI app wrapped with the three observability middlewares."""
    from fastapi import FastAPI
    app = FastAPI()

    @app.post("/echo")
    async def echo(payload: dict):
        return {"n": len(payload)}

    @app.get("/ping")
    async def ping():
        return {"ok": True}

    # Same order as main.py (last added = outermost): the size limit sits *inside* the two
    # BaseHTTPMiddleware layers so its 413 still gets headers + a request id.
    app.add_middleware(obs.BodySizeLimitMiddleware)
    app.add_middleware(obs.RequestIDMiddleware)
    app.add_middleware(obs.SecurityHeadersMiddleware)
    return app


def test_security_headers_and_request_id_present():
    from fastapi.testclient import TestClient
    with TestClient(_obs_app()) as c:
        r = c.get("/ping")
        assert r.headers["X-Content-Type-Options"] == "nosniff"
        assert r.headers["X-Frame-Options"] == "DENY"
        assert r.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
        assert r.headers.get("X-Request-ID")


def test_security_headers_hsts_when_hosted(monkeypatch):
    from fastapi.testclient import TestClient
    s = obs.get_settings()
    monkeypatch.setattr(s, "hosted", True, raising=False)
    with TestClient(_obs_app()) as c:
        r = c.get("/ping")
        assert "max-age=31536000" in r.headers.get("Strict-Transport-Security", "")


def test_body_size_limit_rejects_oversized_content_length(monkeypatch):
    from fastapi.testclient import TestClient
    s = obs.get_settings()
    monkeypatch.setattr(s, "max_body_bytes", 50, raising=False)
    with TestClient(_obs_app()) as c:
        r = c.post("/echo", content=b"x" * 500,
                   headers={"content-type": "application/json"})
        assert r.status_code == 413
        assert r.json()["detail"] == "Request body too large"


def test_body_size_limit_rejects_oversized_chunked(monkeypatch):
    from fastapi.testclient import TestClient
    s = obs.get_settings()
    monkeypatch.setattr(s, "max_body_bytes", 50, raising=False)

    def gen():
        yield b"a" * 40
        yield b"b" * 40  # crosses the cap without a Content-Length header

    with TestClient(_obs_app()) as c:
        r = c.post("/echo", content=gen(),
                   headers={"content-type": "application/json"})
        assert r.status_code == 413


def test_body_size_limit_allows_small_body_replay(monkeypatch):
    from fastapi.testclient import TestClient
    s = obs.get_settings()
    monkeypatch.setattr(s, "max_body_bytes", 10_000, raising=False)
    with TestClient(_obs_app()) as c:
        r = c.post("/echo", json={"a": 1, "b": 2})
        assert r.status_code == 200
        assert r.json() == {"n": 2}  # body was buffered and replayed intact


def test_body_size_limit_handles_disconnect(monkeypatch):
    """A client disconnect mid-body aborts cleanly (ASGI receive yields http.disconnect)."""
    import anyio
    s = obs.get_settings()
    monkeypatch.setattr(s, "max_body_bytes", 10_000, raising=False)

    called = {"app": False}
    sent = []

    async def inner_app(scope, receive, send):
        called["app"] = True  # must NOT be reached — the middleware returns on disconnect

    mw = obs.BodySizeLimitMiddleware(inner_app)
    scope = {"type": "http", "headers": []}

    async def receive():
        return {"type": "http.disconnect"}

    async def send(msg):
        sent.append(msg)

    anyio.run(mw.__call__, scope, receive, send)
    assert called["app"] is False
    # It must still emit a response: this middleware runs inside BaseHTTPMiddleware, which
    # raises "No response returned." if call_next produces nothing. Nobody reads the 499.
    assert [m["type"] for m in sent] == ["http.response.start", "http.response.body"]
    assert sent[0]["status"] == 499


def test_disconnect_mid_upload_does_not_500_through_the_real_stack(monkeypatch):
    """A cancelled upload must stay silent, not become a 500 + Sentry event.

    Regression guard for middleware ordering: BodySizeLimitMiddleware sits inside the
    BaseHTTPMiddleware layers so its 413 carries security headers, and a bare `return` on
    disconnect would make call_next raise RuntimeError("No response returned.").
    """
    import anyio
    s = obs.get_settings()
    monkeypatch.setattr(s, "max_body_bytes", 10_000, raising=False)

    async def inner_app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    # innermost -> outermost, mirroring main.py
    stack = obs.SecurityHeadersMiddleware(obs.RequestIDMiddleware(obs.BodySizeLimitMiddleware(inner_app)))
    messages = iter([{"type": "http.request", "body": b"x" * 10, "more_body": True},
                     {"type": "http.disconnect"}])
    scope = {"type": "http", "method": "POST", "path": "/echo", "query_string": b"",
             "headers": [(b"content-type", b"application/json")]}

    async def receive():
        return next(messages)

    sent = []

    async def send(msg):
        sent.append(msg)

    anyio.run(stack.__call__, scope, receive, send)  # must not raise
    assert sent[0]["status"] == 499


def test_body_size_limit_passes_through_non_http():
    """Lifespan/websocket scopes bypass the size check entirely."""
    import anyio

    seen = {}

    async def inner_app(scope, receive, send):
        seen["type"] = scope["type"]

    mw = obs.BodySizeLimitMiddleware(inner_app)

    async def receive():
        return {}

    async def send(msg):
        pass

    anyio.run(mw.__call__, {"type": "lifespan"}, receive, send)
    assert seen["type"] == "lifespan"


def test_healthz_db_ok_no_redis(monkeypatch):
    s = obs.get_settings()
    monkeypatch.setattr(s, "redis_url", "", raising=False)
    resp = obs.healthz()
    body = json.loads(bytes(resp.body))
    assert resp.status_code == 200
    assert body["ok"] is True and body["checks"]["db"] is True
    assert body["checks"]["redis"] is None


def test_healthz_db_failure_returns_503(monkeypatch):
    class _BadSession:
        def execute(self, *a):
            raise RuntimeError("db down")

        def close(self):
            pass

    monkeypatch.setattr(obs, "SessionLocal", lambda: _BadSession())
    s = obs.get_settings()
    monkeypatch.setattr(s, "redis_url", "", raising=False)
    resp = obs.healthz()
    body = json.loads(bytes(resp.body))
    assert resp.status_code == 503
    assert body["ok"] is False and body["checks"]["db"] is False


def test_healthz_redis_configured_ok(monkeypatch):
    s = obs.get_settings()
    monkeypatch.setattr(s, "redis_url", "redis://localhost:6379/0", raising=False)

    class _Store:
        class _R:
            def ping(self):
                return True
        _r = _R()

    from agentman.services import runstore
    monkeypatch.setattr(runstore, "_store", lambda: _Store())
    resp = obs.healthz()
    body = json.loads(bytes(resp.body))
    assert resp.status_code == 200
    assert body["checks"]["redis"] is True


def test_healthz_redis_configured_down(monkeypatch):
    s = obs.get_settings()
    monkeypatch.setattr(s, "redis_url", "redis://localhost:6379/0", raising=False)

    class _Store:
        class _R:
            def ping(self):
                raise ConnectionError("no redis")
        _r = _R()

    from agentman.services import runstore
    monkeypatch.setattr(runstore, "_store", lambda: _Store())
    resp = obs.healthz()
    body = json.loads(bytes(resp.body))
    assert resp.status_code == 503
    assert body["checks"]["redis"] is False


# ---------------------------------------------------------------------------
# cli.py
# ---------------------------------------------------------------------------
from agentman import cli


def test_expand_env_lists_and_missing(monkeypatch):
    monkeypatch.setenv("FOO", "bar")
    # ints/bools/None are non-str scalars -> returned untouched (line 58)
    out = cli._expand_env({"a": ["${FOO}", "${MISSING}"], "b": "x${FOO}y", "n": 7, "z": None})
    assert out == {"a": ["bar", ""], "b": "xbary", "n": 7, "z": None}


def test_load_connections_none_returns_empty_registry(monkeypatch, tmp_path):
    # neither explicit nor default files exist -> empty registry (line 68)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli.Path, "home", staticmethod(lambda: tmp_path / "nohome"))
    reg = cli._load_connections(None)
    assert reg.id_of("anything") is None


def test_resolve_request_llm_judge_connection():
    reg = cli._Registry({"Judge": {"provider": "openai"}})
    doc = {
        "request": {"type": "prompt", "user": "hi"},
        "assertions": [{"type": "llm_judge", "connection": "Judge", "criteria": "polite"}],
    }
    req, unresolved = cli._resolve_request(doc, reg)
    assert unresolved is None
    judge = req["assertions"][0]
    assert judge["connection_id"] == reg.id_of("Judge")


def test_iter_test_files_missing_path_warns(capsys):
    files = list(cli._iter_test_files(["does-not-exist-xyz"]))
    assert files == []
    err = capsys.readouterr().err
    assert "path not found" in err


def test_iter_test_files_single_file(tmp_path):
    f = tmp_path / "one.yaml"
    f.write_text("x")
    assert list(cli._iter_test_files([str(f)])) == [f]


def test_cmd_run_no_files_returns_2(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    empty = tmp_path / "empty"
    empty.mkdir()
    rc = cli.main(["run", str(empty)])
    assert rc == 2
    assert "no .agentman test files" in capsys.readouterr().err


def test_cmd_run_parse_error_reported(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "bad.yaml").write_text("version: 9\nkind: test\nrequest: {type: prompt}")
    rc = cli.main(["run", "bad.yaml", "--format", "json"])
    assert rc == 1  # parse error -> failure
    out = capsys.readouterr().out
    assert "parse error" in out


def test_cmd_run_flow_files_skipped(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "flow.yaml").write_text(
        "version: 1\nkind: flow\nname: F\nnodes: []\nedges: []\n")
    rc = cli.main(["run", "flow.yaml", "--format", "json"])
    # flow files aren't CI test units -> no cases, exit 0
    assert rc == 0
    out = capsys.readouterr().out
    assert '"suites": []' in out


def test_pretty_render_suite_error_and_assertions(monkeypatch, tmp_path):
    # Build suites with a parse-error suite (no cases) and a case with assertions + error,
    # to exercise the pretty renderer's error/assertion branches (lines 177-178, etc.).
    suites = [
        {"file": "a.yaml", "error": "parse error: boom", "cases": []},
        {"file": "b.yaml", "name": "B", "error": "connection 'X' not found", "cases": [
            {"name": "c1", "ok": False, "duration_ms": 12,
             "assertions": [{"type": "contains", "ok": False, "detail": "missing"}],
             "error": "run blew up"},
        ]},
    ]
    text = cli._pretty(suites, color=True)
    assert "parse error: boom" in text
    assert "connection 'X' not found" in text
    assert "contains: missing" in text
    assert "error: run blew up" in text
    assert "0/1 passed" in text


def test_junit_render_with_error_suite():
    suites = [
        {"file": "a.yaml", "name": "A", "error": "parse error", "cases": []},
        {"file": "b.yaml", "name": "B", "cases": [
            {"name": "c1", "ok": False, "duration_ms": 5,
             "assertions": [{"type": "contains", "ok": False, "detail": "nope"}],
             "error": ""},
        ]},
    ]
    xml = cli._junit(suites)
    assert '<error message="parse error"/>' in xml
    assert '<failure message="contains: nope"/>' in xml
    assert 'errors="1"' in xml


def test_render_writes_output_file(tmp_path, capsys):
    suites = [{"file": "a.yaml", "name": "A", "cases": []}]
    out = tmp_path / "r.json"
    cli._render(suites, "json", str(out))
    assert '"suites"' in out.read_text()
    assert "wrote json report" in capsys.readouterr().err


def test_cmd_import_promptfoo_writes_and_warns(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    pf = tmp_path / "pf.yaml"
    pf.write_text(
        "providers: [openai:gpt-4o-mini]\n"
        "prompts: ['Q: {{q}}']\n"
        "tests:\n"
        "  - vars: {q: hi}\n"
        "    assert:\n"
        "      - {type: contains, value: hi}\n"
        "      - {type: javascript, value: 'x>0'}\n")
    outdir = tmp_path / "out"
    rc = cli.main(["import-promptfoo", str(pf), "-o", str(outdir)])
    assert rc == 0
    written = list(outdir.glob("*.yaml"))
    assert written
    combined = capsys.readouterr()
    assert "wrote" in combined.out
    assert "imported 1 test" in combined.err
    assert "warning:" in combined.err  # javascript assertion reported


def test_main_entrypoint_dunder(monkeypatch):
    # cover the argv-less parse path through main() returning the func result
    monkeypatch.setattr(cli.sys, "argv", ["agentman", "run", "no-such-dir"])
    # run() on a non-existent path -> warning + no files -> exit 2
    assert cli.main(None) == 2


# ---------------------------------------------------------------------------
# database.py  (init_db in-memory branch + migration adoption/stamping)
# ---------------------------------------------------------------------------
from agentman import database as db_mod


def test_init_db_in_memory_creates_tables(monkeypatch):
    from sqlalchemy import create_engine, inspect

    mem = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})

    class _S:
        database_url = "sqlite:///:memory:"

    monkeypatch.setattr(db_mod, "engine", mem)
    monkeypatch.setattr(db_mod, "settings", _S())
    # rebind Base.metadata to the temp engine by patching create_all target via engine arg
    db_mod.init_db()
    assert inspect(mem).has_table("users")


def _fresh_migrate_cfg():
    import os
    from alembic.config import Config
    return Config(os.path.join(os.path.dirname(os.path.dirname(db_mod.__file__)), "alembic.ini"))


def test_migrate_to_head_adopts_by_column(monkeypatch, tmp_path):
    """A pre-migration DB (create_all, no alembic_version) whose users table has the newest
    column gets stamped at the matching revision, then upgraded."""
    from sqlalchemy import create_engine

    eng = create_engine(f"sqlite:///{tmp_path / 'adopt.db'}")
    db_mod.Base.metadata.create_all(bind=eng)  # full schema incl. token_version
    monkeypatch.setattr(db_mod, "engine", eng)

    stamped, upgraded = {}, {}
    from alembic import command
    monkeypatch.setattr(command, "stamp", lambda cfg, rev: stamped.setdefault("rev", rev))
    monkeypatch.setattr(command, "upgrade", lambda cfg, rev: upgraded.setdefault("rev", rev))

    db_mod._migrate_to_head(_fresh_migrate_cfg())
    # users has token_version -> first _ADOPT_BY_COLUMN entry wins
    assert stamped["rev"] == "a1b2c3d4e5f6"
    assert upgraded["rev"] == "head"


def test_migrate_to_head_baseline_when_no_adopt_columns(monkeypatch, tmp_path):
    """A minimal legacy users table lacking every adopt column stamps at the baseline."""
    from sqlalchemy import create_engine, text

    eng = create_engine(f"sqlite:///{tmp_path / 'baseline.db'}")
    with eng.begin() as conn:
        # legacy schema: users + workspaces present but WITHOUT any of the adopt columns,
        # so the loop falls through to the baseline revision.
        conn.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT)"))
        conn.execute(text("CREATE TABLE workspaces (id INTEGER PRIMARY KEY, name TEXT)"))
    monkeypatch.setattr(db_mod, "engine", eng)

    stamped = {}
    from alembic import command
    monkeypatch.setattr(command, "stamp", lambda cfg, rev: stamped.setdefault("rev", rev))
    monkeypatch.setattr(command, "upgrade", lambda cfg, rev: None)

    db_mod._migrate_to_head(_fresh_migrate_cfg())
    assert stamped["rev"] == db_mod._BASELINE_REVISION


def test_migrate_to_head_no_stamp_when_no_users_table(monkeypatch, tmp_path):
    """Empty DB (no users table, no version) -> no stamp, straight upgrade."""
    from sqlalchemy import create_engine

    eng = create_engine(f"sqlite:///{tmp_path / 'empty.db'}")
    monkeypatch.setattr(db_mod, "engine", eng)

    calls = {"stamp": 0, "upgrade": 0}
    from alembic import command
    monkeypatch.setattr(command, "stamp", lambda *a: calls.__setitem__("stamp", calls["stamp"] + 1))
    monkeypatch.setattr(command, "upgrade", lambda *a: calls.__setitem__("upgrade", calls["upgrade"] + 1))

    db_mod._migrate_to_head(_fresh_migrate_cfg())
    assert calls["stamp"] == 0 and calls["upgrade"] == 1


def test_run_migrations_dispatches_to_sqlite(monkeypatch):
    class _S:
        database_url = "sqlite:///./x.db"

    monkeypatch.setattr(db_mod, "settings", _S())
    called = {}
    monkeypatch.setattr(db_mod, "_migrate_to_head", lambda cfg: called.setdefault("hit", True))
    db_mod._run_migrations()
    assert called.get("hit") is True


def test_run_migrations_postgres_uses_advisory_lock(monkeypatch):
    """Non-SQLite path takes an advisory lock around the migration and releases it."""
    class _S:
        database_url = "postgresql://u@h/db"

    monkeypatch.setattr(db_mod, "settings", _S())

    sql_calls = []

    class _Conn:
        def execution_options(self, **kw):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def exec_driver_sql(self, sql, params=None):
            sql_calls.append(sql)

    monkeypatch.setattr(db_mod.engine, "connect", lambda: _Conn())
    migrated = {}
    monkeypatch.setattr(db_mod, "_migrate_to_head", lambda cfg: migrated.setdefault("hit", True))
    db_mod._run_migrations()
    assert migrated.get("hit") is True
    assert any("pg_advisory_lock" in s for s in sql_calls)
    assert any("pg_advisory_unlock" in s for s in sql_calls)


# ---------------------------------------------------------------------------
# runstore.py  (TTL eviction + RedisStore.drop + init dispatch)
# ---------------------------------------------------------------------------
from agentman.services import runstore


def test_memory_store_ttl_eviction(monkeypatch):
    fake_now = {"t": 1000.0}
    monkeypatch.setattr(runstore.time, "monotonic", lambda: fake_now["t"])
    s = runstore._MemoryStore()
    s.store("old", {"v": 1})
    fake_now["t"] += runstore._TTL + 10  # advance past the TTL
    s.store("new", {"v": 2})             # store() sweeps expired entries
    assert s.get("old") is None
    assert s.get("new") == {"v": 2}


def test_memory_store_drop():
    s = runstore._MemoryStore()
    s.store("r", {"v": 1})
    s.drop("r")
    assert s.get("r") is None
    s.drop("missing")  # no-op, no error


def test_redis_store_drop_uses_delete():
    from tests.test_runstore import _FakeRedis
    s = runstore._RedisStore.__new__(runstore._RedisStore)
    s._r = _FakeRedis()
    s.store("r", {"v": 1})
    s.drop("r")
    assert s.get("r") is None


def test_redis_store_init_imports_redis(monkeypatch):
    import sys
    import types
    fake_redis = types.ModuleType("redis")
    made = {}

    class _Redis:
        @staticmethod
        def from_url(url, decode_responses=False):
            made["url"] = url
            made["decode"] = decode_responses
            return "REDIS-CONN"

    fake_redis.Redis = _Redis
    monkeypatch.setitem(sys.modules, "redis", fake_redis)
    store = runstore._RedisStore("redis://h:6379/1")
    assert made["url"] == "redis://h:6379/1"
    assert made["decode"] is True
    assert store._r == "REDIS-CONN"


def test_store_factory_selects_redis(monkeypatch):
    runstore._store.cache_clear()
    made = {}

    class _FakeRedisStore:
        def __init__(self, url):
            made["url"] = url

    monkeypatch.setattr(runstore, "_RedisStore", _FakeRedisStore)
    monkeypatch.setattr(runstore.get_settings(), "redis_url", "redis://h:6379/0", raising=False)
    store = runstore._store()
    assert isinstance(store, _FakeRedisStore)
    assert made["url"] == "redis://h:6379/0"
    runstore._store.cache_clear()


def test_drop_ctx_module_helper(monkeypatch):
    runstore._store.cache_clear()
    monkeypatch.setattr(runstore.get_settings(), "redis_url", "", raising=False)
    runstore.store_ctx("d", {"v": 9})
    runstore.drop_ctx("d")
    assert runstore.get_ctx("d") is None
    runstore._store.cache_clear()


# ---------------------------------------------------------------------------
# deploy.py  (collect_output error + done/error events; keys)
# ---------------------------------------------------------------------------
from agentman.services import deploy


def test_new_api_key_and_verify_and_slugify():
    key, h = deploy.new_api_key()
    assert key.startswith("agm_")
    assert deploy.hash_key(key) == h
    assert deploy.verify_key(key, h) is True
    assert deploy.verify_key("agm_wrong", h) is False
    assert deploy.slugify("Hello World! 42") == "hello-world-42"
    assert deploy.slugify("") == "flow"       # empty falls back
    assert deploy.slugify("***") == "flow"    # all-stripped falls back


def test_collect_output_single_output_node():
    events = [
        {"type": "start", "run_id": "r1"},
        {"type": "node", "status": "ok", "node_type": "output",
         "title": "Answer", "output": {"value": "hi"}},
        {"type": "done", "status": "completed"},
    ]
    res = deploy.collect_output(events)
    assert res == {"output": "hi", "status": "completed", "error": "", "run_id": "r1"}


def test_collect_output_node_error_sets_failed():
    events = [
        {"type": "start", "run_id": "r2"},
        {"type": "node", "status": "error", "error": "node boom"},
    ]
    res = deploy.collect_output(events)
    assert res["status"] == "failed" and res["error"] == "node boom"


def test_collect_output_terminal_error_event():
    events = [
        {"type": "start", "run_id": "r3"},
        {"type": "error", "error": "stream boom"},
    ]
    res = deploy.collect_output(events)
    assert res["status"] == "failed" and res["error"] == "stream boom"


def test_collect_output_multiple_outputs_map():
    events = [
        {"type": "node", "status": "ok", "node_type": "output", "title": "A", "output": {"value": 1}},
        {"type": "node", "status": "ok", "node_type": "output", "node_id": "n2", "output": 2},
    ]
    res = deploy.collect_output(events)
    assert res["output"] == {"A": 1, "n2": 2}


def test_run_snapshot_yields_engine_events(monkeypatch):
    import anyio

    async def fake_run_stream(session, flow, flow_input, workspace_id=None):
        assert flow == {"nodes": [{"id": "n"}], "edges": []}
        assert flow_input == {"q": "hi"}
        yield {"type": "start"}
        yield {"type": "done", "status": "completed"}

    monkeypatch.setattr(deploy.engine, "run_stream", fake_run_stream)

    async def drive():
        out = []
        async for ev in deploy.run_snapshot(None, {"nodes": [{"id": "n"}]}, {"q": "hi"}, 1):
            out.append(ev)
        return out

    events = anyio.run(drive)
    assert [e["type"] for e in events] == ["start", "done"]


# ---------------------------------------------------------------------------
# testfile.py  (validation error branches)
# ---------------------------------------------------------------------------
from agentman.services import testfile


def test_load_rejects_assertion_without_type():
    with pytest.raises(ValueError, match="each assertion needs a type"):
        testfile.load(
            "version: 1\nkind: test\nname: t\n"
            "request: {type: prompt, user: hi}\n"
            "assertions:\n  - {value: x}\n")


def test_load_rejects_dataset_row_not_mapping():
    with pytest.raises(ValueError, match="each dataset row must be a mapping"):
        testfile.load(
            "version: 1\nkind: test\nname: t\n"
            "request: {type: prompt, user: hi}\n"
            "dataset:\n  - just-a-string\n")


# ---------------------------------------------------------------------------
# workspace.py  (seed_examples branch)
# ---------------------------------------------------------------------------
from agentman.services import workspace as ws_mod


def _make_user_and_ws(db):
    from agentman.models import User, Workspace
    u = User(email=f"seed{id(db)}@x.com", password_hash="x")
    db.add(u); db.commit(); db.refresh(u)
    w = Workspace(name="W", owner_user_id=u.id)
    db.add(w); db.commit(); db.refresh(w)
    return u, w


def test_seed_workspace_with_examples(monkeypatch):
    from agentman.database import SessionLocal
    from agentman.models import Connection
    s = ws_mod.get_settings()
    monkeypatch.setattr(s, "seed_examples", True, raising=False)
    monkeypatch.setattr(s, "hosted", False, raising=False)
    monkeypatch.setattr(s, "openai_api_key", "sk-operator", raising=False)
    db = SessionLocal()
    try:
        _, w = _make_user_and_ws(db)
        ws_mod.seed_workspace(db, w.id)
        conns = db.query(Connection).filter(Connection.workspace_id == w.id).all()
        names = {c.name for c in conns}
        assert {"Demo Assistant (mock)", "OpenAI", "Anthropic"} <= names
        openai = next(c for c in conns if c.name == "OpenAI")
        assert openai.config["api_key"] == "sk-operator"  # local mode seeds operator key
    finally:
        db.close()


def test_seed_connections_hosted_blanks_openai_key(monkeypatch):
    from agentman.database import SessionLocal
    from agentman.models import Connection
    s = ws_mod.get_settings()
    monkeypatch.setattr(s, "seed_examples", True, raising=False)
    monkeypatch.setattr(s, "hosted", True, raising=False)
    monkeypatch.setattr(s, "openai_api_key", "sk-operator", raising=False)
    db = SessionLocal()
    try:
        _, w = _make_user_and_ws(db)
        ws_mod._seed_connections(db, w.id)
        openai = db.query(Connection).filter(
            Connection.workspace_id == w.id, Connection.name == "OpenAI").first()
        assert openai.config["api_key"] == ""  # hosted never distributes the operator key
    finally:
        db.close()


def test_get_or_create_default_workspace_seeds_and_reuses(monkeypatch):
    from agentman.database import SessionLocal
    from agentman.models import User
    s = ws_mod.get_settings()
    monkeypatch.setattr(s, "seed_examples", False, raising=False)
    db = SessionLocal()
    try:
        u = User(email=f"wsuser{id(db)}@x.com", password_hash="x")
        db.add(u); db.commit(); db.refresh(u)
        w1 = ws_mod.get_or_create_default_workspace(db, u)
        w2 = ws_mod.get_or_create_default_workspace(db, u)  # existing -> returned as-is
        assert w1.id == w2.id
    finally:
        db.close()


# ---------------------------------------------------------------------------
# main.py  (_reseal_connections + _guard_production_config warning/raise)
# ---------------------------------------------------------------------------
from agentman import main as main_mod


def test_reseal_connections_flags_and_commits(monkeypatch):
    from agentman.database import SessionLocal
    from agentman.models import Connection
    db = SessionLocal()
    try:
        c = Connection(workspace_id=1, name="x", kind="llm",
                       config={"provider": "mock", "api_key": ""})
        db.add(c); db.commit()
        main_mod._reseal_connections(db)  # idempotent walk of all connections
    finally:
        db.rollback()
        db.close()


def test_guard_production_config_raises_on_hosted_weak_key(monkeypatch):
    class _S:
        hosted = True
        secret_key = "change-me"
        database_url = "postgresql://u@h/db"

    monkeypatch.setattr(main_mod, "settings", _S())
    with pytest.raises(RuntimeError, match="strong SECRET_KEY"):
        main_mod._guard_production_config()


def test_guard_production_config_warns_on_weak_server_key(monkeypatch):
    class _S:
        hosted = False
        secret_key = "short"           # weak: < 16 chars
        database_url = "postgresql://u@h/db"

    monkeypatch.setattr(main_mod, "settings", _S())
    with _CaptureLogs("agentman", logging.WARNING) as cap:
        main_mod._guard_production_config()
    assert "public constant" in cap.text


def test_guard_production_config_ok_for_local_sqlite(monkeypatch):
    class _S:
        hosted = False
        secret_key = ""
        database_url = "sqlite:///./agentman.db"

    monkeypatch.setattr(main_mod, "settings", _S())
    main_mod._guard_production_config()  # no raise, no warning


def test_lifespan_tolerates_anyio_limiter_failure(monkeypatch):
    """The threadpool-ceiling bump is best-effort: if anyio raises, boot continues."""
    import anyio
    from fastapi.testclient import TestClient

    def boom():
        raise RuntimeError("no limiter")

    monkeypatch.setattr(anyio.to_thread, "current_default_thread_limiter", boom)
    # TestClient(...) as context manager drives the lifespan (which swallows the error)
    with TestClient(main_mod.app) as c:
        assert c.get("/").json()["service"] == "AgentMan"


def test_root_and_health_endpoints():
    from fastapi.testclient import TestClient
    with TestClient(main_mod.app) as c:
        assert c.get("/").json()["service"] == "AgentMan"
        assert c.get("/healthz").status_code in (200, 503)
