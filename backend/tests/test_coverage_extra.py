"""Targeted coverage for the platform utilities: middleware, healthz, logging, Sentry,
SSRF guard, email, sealing, the OTLP emit path, and SDK edge cases."""
import logging
import sys
import types

import httpx
import pytest
from fastapi.testclient import TestClient

from provekit import observability as obs
from provekit.config import get_settings
from provekit.main import app
from provekit.services import deploy, netguard as ng, otel, sealing


# ---- observability: request id, security headers, body-size, healthz ----
def test_request_id_echoed_and_security_headers():
    c = TestClient(app)
    r = c.get("/healthz", headers={"X-Request-ID": "abc123"})
    assert r.headers["X-Request-ID"] == "abc123"
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"


def test_request_id_generated_when_absent():
    assert TestClient(app).get("/healthz").headers.get("X-Request-ID")


def test_hsts_only_in_hosted(monkeypatch):
    monkeypatch.setattr(get_settings(), "hosted", True)
    assert "Strict-Transport-Security" in TestClient(app).get("/healthz").headers


def test_body_size_limit_rejects_413(monkeypatch):
    monkeypatch.setattr(get_settings(), "max_body_bytes", 50)
    r = TestClient(app).post("/v1/traces", content=b"x" * 300,
                             headers={"content-type": "application/json"})
    assert r.status_code == 413


def test_json_formatter_plain_and_exc():
    rec = logging.LogRecord("n", logging.INFO, "p", 1, "hi", None, None)
    assert '"msg": "hi"' in obs._JSONFormatter().format(rec)
    try:
        raise ValueError("e")
    except ValueError:
        rec2 = logging.LogRecord("n", logging.ERROR, "p", 1, "boom", None, sys.exc_info())
        assert '"exc"' in obs._JSONFormatter().format(rec2)


def test_setup_logging_hosted(monkeypatch):
    monkeypatch.setattr(get_settings(), "hosted", True)
    obs.setup_logging()  # attaches the JSON formatter


def test_init_sentry_paths(monkeypatch):
    monkeypatch.setattr(get_settings(), "sentry_dsn", "")
    obs.init_sentry()  # no dsn → early return

    inited = {}
    monkeypatch.setitem(sys.modules, "sentry_sdk", types.SimpleNamespace(init=lambda **k: inited.update(k)))
    monkeypatch.setattr(get_settings(), "sentry_dsn", "https://x@y/1")
    obs.init_sentry()
    assert inited["dsn"] == "https://x@y/1"


def test_init_sentry_missing_package(monkeypatch):
    import builtins
    real = builtins.__import__

    def block(name, *a, **k):
        if name == "sentry_sdk":
            raise ImportError("nope")
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", block)
    monkeypatch.setattr(get_settings(), "sentry_dsn", "https://x@y/1")
    obs.init_sentry()  # logs the warning branch


def test_healthz_redis_check(monkeypatch):
    monkeypatch.setattr(get_settings(), "redis_url", "redis://x")
    monkeypatch.setitem(sys.modules, "redis",
                        types.SimpleNamespace(from_url=lambda u: types.SimpleNamespace(ping=lambda: True)))
    assert TestClient(app).get("/healthz").json()["checks"]["redis"] is True


# ---- netguard (SSRF) ----
def test_guard_url_allows_public_ip():
    ng.guard_url("http://8.8.8.8/v1/traces")  # public literal IP, not hosted → ok


def test_guard_url_blocks_named_metadata_host():
    with pytest.raises(ng.BlockedURL):
        ng.guard_url("http://metadata/latest")


def test_guard_url_hosted_blocks_private_and_resolves_hostnames(monkeypatch):
    monkeypatch.setattr(get_settings(), "hosted", True)
    with pytest.raises(ng.BlockedURL):
        ng.guard_url("http://10.0.0.1/x")            # private literal IP
    with pytest.raises(ng.BlockedURL):
        ng.guard_url("http://localhost/x")           # resolves to 127.0.0.1 → not global
    with pytest.raises(ng.BlockedURL):
        ng.guard_url("http://no-such-host.invalid./x")  # getaddrinfo fails


# ---- email ----
def test_email_logs_when_no_smtp(monkeypatch):
    from provekit.services import email
    monkeypatch.setattr(get_settings(), "smtp_host", "")
    monkeypatch.setattr(get_settings(), "hosted", True)
    email.send("a@b.com", "s", "body")   # hosted + no SMTP → error log, returns
    monkeypatch.setattr(get_settings(), "hosted", False)
    email.send("a@b.com", "s", "body")   # local → info log, returns


def test_email_sends_via_smtp(monkeypatch):
    from provekit.services import email
    sent = {}

    class _SMTP:
        def __init__(self, host, port, timeout=None): sent["host"] = host
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def starttls(self): sent["tls"] = True
        def login(self, u, p): sent["login"] = u
        def send_message(self, msg): sent["to"] = msg["To"]

    monkeypatch.setattr(email.smtplib, "SMTP", _SMTP)
    for k in ("smtp_host", "smtp_user", "smtp_password", "smtp_from"):
        monkeypatch.setattr(get_settings(), k, "x")
    email.send("a@b.com", "subj", "body")
    assert sent["to"] == "a@b.com" and sent["tls"] and sent["login"] == "x"


def test_email_send_failure_is_swallowed(monkeypatch):
    from provekit.services import email

    def boom(*a, **k):
        raise OSError("smtp down")

    monkeypatch.setattr(email.smtplib, "SMTP", boom)
    monkeypatch.setattr(get_settings(), "smtp_host", "x")
    email.send("a@b.com", "s", "b")   # exception path → warning, no raise


# ---- otel emit + attr parsing ----
def test_attr_value_types_and_as_text():
    assert otel._attr_value({"intValue": "5"}) == 5
    assert otel._attr_value({"doubleValue": 1.5}) == 1.5
    assert otel._attr_value({"boolValue": True}) is True
    assert otel._attr_value({"arrayValue": {"values": [{"stringValue": "a"}]}}) == ["a"]
    assert otel._attr_value({"kvlistValue": {"values": [{"key": "k", "value": {"stringValue": "v"}}]}}) == {"k": "v"}
    assert otel._attr_value({}) is None
    assert otel._as_text(None) == "" and otel._as_text("x") == "x" and otel._as_text({"a": 1}) == '{"a": 1}'


def test_emit_run_posts_when_configured(monkeypatch):
    monkeypatch.setattr(get_settings(), "otel_export_url", "http://8.8.8.8/v1/traces")
    monkeypatch.setattr("provekit.services.netguard.guard_url", lambda u: None)
    captured = {}
    monkeypatch.setattr(httpx, "post", lambda *a, **k: captured.update(url=a[0] if a else k.get("url"), body=k.get("json")))
    run = types.SimpleNamespace(type="llm", label="chat gpt-4o", status="completed",
                                result={"meta": {"provider": "openai", "model": "gpt-4o",
                                                 "usage": {"input_tokens": 5, "output_tokens": 2}}})
    otel.emit_run(run)
    assert captured["url"] == "http://8.8.8.8/v1/traces"


def test_emit_run_noop_without_url(monkeypatch):
    monkeypatch.setattr(get_settings(), "otel_export_url", "")
    otel.emit_run(types.SimpleNamespace(type="llm", status="completed", result={}))  # returns early


# ---- deploy key helper ----
def test_new_api_key_roundtrip():
    key, h = deploy.new_api_key()
    assert key.startswith("agm_") and deploy.verify_key(key, h) and not deploy.verify_key("x", h)


# ---- sealing ----
def test_key_file_none_for_non_sqlite(monkeypatch):
    monkeypatch.setattr(get_settings(), "database_url", "postgresql://u@h/db")
    assert sealing._key_file() is None


def test_fernet_from_secret_key(monkeypatch):
    monkeypatch.setattr(get_settings(), "secret_key", "z" * 40)
    sealing._fernet.cache_clear()
    f = sealing._fernet()
    assert f.decrypt(f.encrypt(b"hi")) == b"hi"
    sealing._fernet.cache_clear()


def test_fernet_generates_local_key_file(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "secret_key", "")
    monkeypatch.setattr(get_settings(), "database_url", f"sqlite:///{tmp_path}/t.db")
    sealing._fernet.cache_clear()
    sealing._fernet()
    assert (tmp_path / ".provekit.key").exists()
    sealing._fernet.cache_clear()


# ---- config boot guard ----
def test_guard_config_warns_weak_key_non_sqlite(monkeypatch):
    from provekit import main
    s = get_settings()
    monkeypatch.setattr(s, "hosted", False)
    monkeypatch.setattr(s, "secret_key", "")
    monkeypatch.setattr(s, "database_url", "postgresql://u@h/db")
    main._guard_production_config()  # warns (no raise)


def test_guard_config_hosted_weak_key_raises(monkeypatch):
    from provekit import main
    s = get_settings()
    monkeypatch.setattr(s, "hosted", True)
    monkeypatch.setattr(s, "secret_key", "short")
    with pytest.raises(RuntimeError):
        main._guard_production_config()


# ---- traces ingest: invalid JSON ----
def test_ingest_invalid_json_is_reported():
    r = TestClient(app, base_url="https://testserver").post(
        "/v1/traces", content=b"not-json", headers={"content-type": "application/json"})
    assert r.status_code == 200 and "partialSuccess" in r.json()


# ---- SDK: pk.span edges ----
def test_pk_span_noop_when_unconfigured():
    import provekit.trace as pk
    pk._configured = False
    pk._tracer = None
    monkeypatch_env(pk)
    with pk.span("x") as s:
        assert s is None


def monkeypatch_env(pk):
    import os
    os.environ.pop("PROVEKIT_API_KEY", None)
    os.environ.pop("PROVEKIT_ENDPOINT", None)


def test_pk_span_records_error(monkeypatch):
    import provekit.trace as pk
    pk._configured = False
    pk._tracer = None
    monkeypatch.setattr(httpx, "post", lambda *a, **k: None)
    pk.configure(api_key="pk_x", endpoint="http://p.test", batch=False)
    with pytest.raises(ValueError):
        with pk.span("boom"):
            raise ValueError("kaboom")


# ---- a few more error/edge branches ----
def test_healthz_redis_down_reports_false(monkeypatch):
    monkeypatch.setattr(get_settings(), "redis_url", "redis://x")

    def bad_ping():
        raise OSError("down")

    monkeypatch.setitem(sys.modules, "redis",
                        types.SimpleNamespace(from_url=lambda u: types.SimpleNamespace(ping=bad_ping)))
    assert TestClient(app).get("/healthz").json()["checks"]["redis"] is False


def test_as_text_unserializable_falls_back():
    class X:
        pass
    assert isinstance(otel._as_text(X()), str)


def test_emit_run_swallows_transport_errors(monkeypatch):
    monkeypatch.setattr(get_settings(), "otel_export_url", "http://8.8.8.8/x")
    monkeypatch.setattr("provekit.services.netguard.guard_url", lambda u: None)

    def boom(*a, **k):
        raise httpx.ConnectError("x")

    monkeypatch.setattr(httpx, "post", boom)
    otel.emit_run(types.SimpleNamespace(type="llm", label="x", status="completed", result={}))  # no raise


def test_fernet_reads_existing_key_file(tmp_path, monkeypatch):
    from cryptography.fernet import Fernet
    (tmp_path / ".provekit.key").write_bytes(Fernet.generate_key())
    monkeypatch.setattr(get_settings(), "secret_key", "")
    monkeypatch.setattr(get_settings(), "database_url", f"sqlite:///{tmp_path}/t.db")
    sealing._fernet.cache_clear()
    assert sealing._fernet().encrypt(b"x")            # reads the existing key file
    sealing._fernet.cache_clear()
