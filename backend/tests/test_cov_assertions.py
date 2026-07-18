"""Coverage tests for assertions, masking, and netguard services.

No real network: llm.collect_text_sync and socket.getaddrinfo are monkeypatched;
netguard hosted mode is toggled via monkeypatching get_settings().hosted.
"""
import pytest

from provekit.config import get_settings
from provekit.database import SessionLocal
from provekit.models import Connection
from provekit.services import assertions as A
from provekit.services import masking as M
from provekit.services import netguard as NG
from provekit.services.providers import llm


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #
def _run(text="", output=None, meta=None, events=None, status="completed", duration_ms=0):
    return {
        "result": {"text": text, "output": output, "meta": meta or {}},
        "status": status,
        "duration_ms": duration_ms,
        "events": events or [],
    }


def _first(db, assertions, run, workspace_id=None):
    res = A.evaluate(db, assertions, run, workspace_id=workspace_id)
    assert len(res) == 1
    return res[0]


@pytest.fixture
def db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def make_conn(db):
    created = []

    def _make(workspace_id=1, config=None, kind="llm", name="Judge"):
        c = Connection(workspace_id=workspace_id, name=name, kind=kind,
                       config=config if config is not None else {"provider": "openai", "models": ["gpt-4o-mini"]})
        db.add(c)
        db.commit()
        db.refresh(c)
        created.append(c)
        return c

    yield _make
    for c in created:
        try:
            db.delete(c)
            db.commit()
        except Exception:
            db.rollback()


# --------------------------------------------------------------------------- #
# assertions: _text_of                                                         #
# --------------------------------------------------------------------------- #
def test_text_of_prefers_text():
    assert A._text_of({"text": "hi", "output": "ignored"}) == "hi"


def test_text_of_string_output():
    assert A._text_of({"text": "", "output": "out-string"}) == "out-string"


def test_text_of_json_dumps_non_string_output():
    assert A._text_of({"output": {"a": 1}}) == '{"a": 1}'


def test_text_of_none_output():
    assert A._text_of({}) == ""


# --------------------------------------------------------------------------- #
# assertions: get_path                                                         #
# --------------------------------------------------------------------------- #
def test_get_path_dict_nested():
    assert A.get_path({"a": {"b": 5}}, "a.b") == 5


def test_get_path_list_index():
    assert A.get_path({"a": [10, 20, 30]}, "a.1") == 20


def test_get_path_list_index_out_of_range():
    assert A.get_path({"a": [1]}, "a.9") is None


def test_get_path_list_index_not_int():
    assert A.get_path([1, 2, 3], "x") is None


def test_get_path_scalar_dead_end():
    # descending into a scalar returns None
    assert A.get_path({"a": 5}, "a.b") is None


def test_get_path_empty_parts_skipped():
    assert A.get_path({"a": 1}, "a.") == 1
    assert A.get_path({"a": 1}, "") == {"a": 1}


# --------------------------------------------------------------------------- #
# assertions: contains                                                         #
# --------------------------------------------------------------------------- #
def test_contains_hit(db):
    r = _first(db, [{"type": "contains", "value": "ell"}], _run(text="hello"))
    assert r["ok"] is True and "contains" in r["detail"]


def test_contains_miss(db):
    r = _first(db, [{"type": "contains", "value": "zzz"}], _run(text="hello"))
    assert r["ok"] is False and "missing" in r["detail"]


# --------------------------------------------------------------------------- #
# assertions: equals (with & without path)                                     #
# --------------------------------------------------------------------------- #
def test_equals_no_path_uses_text(db):
    r = _first(db, [{"type": "equals", "value": "hello"}], _run(text="hello"))
    assert r["ok"] is True


def test_equals_no_path_mismatch(db):
    r = _first(db, [{"type": "equals", "value": "bye"}], _run(text="hello"))
    assert r["ok"] is False


def test_equals_with_path(db):
    run = _run(output={"a": {"b": "v"}})
    r = _first(db, [{"type": "equals", "path": "a.b", "value": "v"}], run)
    assert r["ok"] is True


# --------------------------------------------------------------------------- #
# assertions: regex                                                            #
# --------------------------------------------------------------------------- #
def test_regex_match(db):
    r = _first(db, [{"type": "regex", "value": r"h\w+o"}], _run(text="hello"))
    assert r["ok"] is True and "matched" in r["detail"]


def test_regex_no_match(db):
    r = _first(db, [{"type": "regex", "value": r"^\d+$"}], _run(text="hello"))
    assert r["ok"] is False and "no match" in r["detail"]


def test_regex_redos_nested_quantifier_rejected(db):
    r = _first(db, [{"type": "regex", "value": r"(a+)+"}], _run(text="aaaa"))
    assert r["ok"] is False and "error" in r["detail"] and "nested quantifier" in r["detail"]


def test_regex_pattern_too_long_rejected(db):
    r = _first(db, [{"type": "regex", "value": "a" * 2001}], _run(text="aaaa"))
    assert r["ok"] is False and "error" in r["detail"] and "too long" in r["detail"]


# --------------------------------------------------------------------------- #
# assertions: json_path (value & existence)                                    #
# --------------------------------------------------------------------------- #
def test_json_path_value_match(db):
    run = _run(output={"status": "ok"})
    r = _first(db, [{"type": "json_path", "path": "status", "value": "ok"}], run)
    assert r["ok"] is True


def test_json_path_value_mismatch(db):
    run = _run(output={"status": "bad"})
    r = _first(db, [{"type": "json_path", "path": "status", "value": "ok"}], run)
    assert r["ok"] is False


def test_json_path_existence_present(db):
    run = _run(output={"status": "ok"})
    r = _first(db, [{"type": "json_path", "path": "status"}], run)
    assert r["ok"] is True and "exists" in r["detail"]


def test_json_path_existence_missing(db):
    run = _run(output={"status": "ok"})
    r = _first(db, [{"type": "json_path", "path": "nope"}], run)
    assert r["ok"] is False and "missing" in r["detail"]


# --------------------------------------------------------------------------- #
# assertions: json_schema (pass & fail; dict schema & str schema)             #
# --------------------------------------------------------------------------- #
def test_json_schema_pass_dict(db):
    schema = {"type": "object", "required": ["a"], "properties": {"a": {"type": "number"}}}
    run = _run(output={"a": 1})
    r = _first(db, [{"type": "json_schema", "schema": schema}], run)
    assert r["ok"] is True and r["detail"] == "matches schema"


def test_json_schema_fail(db):
    schema = {"type": "object", "required": ["a"]}
    run = _run(output={"b": 1})
    r = _first(db, [{"type": "json_schema", "schema": schema}], run)
    assert r["ok"] is False


def test_json_schema_string_schema(db):
    run = _run(output={"a": 1})
    r = _first(db, [{"type": "json_schema", "schema": '{"type": "object"}'}], run)
    assert r["ok"] is True


# --------------------------------------------------------------------------- #
# assertions: tool_called (via meta.tool & via events)                        #
# --------------------------------------------------------------------------- #
def test_tool_called_via_meta(db):
    run = _run(meta={"tool": "search"})
    r = _first(db, [{"type": "tool_called", "value": "search"}], run)
    assert r["ok"] is True and "called" in r["detail"]


def test_tool_called_via_event_name_fields(db):
    run = _run(events=[{"tool_name": "lookup"}])
    r = _first(db, [{"type": "tool_called", "value": "lookup"}], run)
    assert r["ok"] is True


def test_tool_called_via_event_tool_calls(db):
    run = _run(events=[{"tool_calls": [{"name": "fetch"}]}])
    r = _first(db, [{"type": "tool_called", "value": "fetch"}], run)
    assert r["ok"] is True


def test_tool_called_via_event_tool_calls_function(db):
    run = _run(events=[{"tool_calls": [{"function": {"name": "calc"}}]}])
    r = _first(db, [{"type": "tool_called", "value": "calc"}], run)
    assert r["ok"] is True


def test_tool_called_not_called(db):
    run = _run(meta={"tool": "search"}, events=[{"name": "other"}])
    r = _first(db, [{"type": "tool_called", "value": "missing"}], run)
    assert r["ok"] is False and "not called" in r["detail"]


# --------------------------------------------------------------------------- #
# assertions: latency_lt                                                       #
# --------------------------------------------------------------------------- #
def test_latency_lt_pass(db):
    r = _first(db, [{"type": "latency_lt", "value": 500}], _run(duration_ms=100))
    assert r["ok"] is True and "<" in r["detail"]


def test_latency_lt_fail(db):
    r = _first(db, [{"type": "latency_lt", "value": 50}], _run(duration_ms=100))
    assert r["ok"] is False


# --------------------------------------------------------------------------- #
# assertions: unknown type                                                     #
# --------------------------------------------------------------------------- #
def test_unknown_assertion_type(db):
    r = _first(db, [{"type": "made_up"}], _run(text="x"))
    assert r["ok"] is False and "unknown assertion type" in r["detail"]


def test_empty_assertions_list(db):
    assert A.evaluate(db, [], _run(text="x")) == []
    assert A.evaluate(db, None, _run(text="x")) == []


def test_assertion_name_defaults_to_type(db):
    r = _first(db, [{"type": "contains", "value": "x"}], _run(text="x"))
    assert r["name"] == "contains"
    r2 = _first(db, [{"type": "contains", "value": "x", "name": "custom"}], _run(text="x"))
    assert r2["name"] == "custom"


# --------------------------------------------------------------------------- #
# assertions: _llm_judge / llm_judge                                          #
# --------------------------------------------------------------------------- #
def test_llm_judge_pass(db, make_conn, monkeypatch):
    conn = make_conn(workspace_id=1, config={"provider": "openai", "models": ["gpt-4o-mini"]})
    monkeypatch.setattr(llm, "collect_text_sync", lambda **kw: "PASS reason")
    run = _run(text="the answer")
    r = _first(db, [{"type": "llm_judge", "connection_id": conn.id, "criteria": "is good"}], run, workspace_id=1)
    assert r["ok"] is True and "PASS" in r["detail"]


def test_llm_judge_fail(db, make_conn, monkeypatch):
    conn = make_conn(workspace_id=1)
    monkeypatch.setattr(llm, "collect_text_sync", lambda **kw: "FAIL reason")
    r = _first(db, [{"type": "llm_judge", "connection_id": conn.id, "criteria": "is good"}],
               _run(text="bad"), workspace_id=1)
    assert r["ok"] is False and "FAIL" in r["detail"]


def test_llm_judge_no_connection_id(db, monkeypatch):
    # no connection_id -> conn is None -> "no judge connection configured"
    monkeypatch.setattr(llm, "collect_text_sync", lambda **kw: (_ for _ in ()).throw(AssertionError("should not call")))
    r = _first(db, [{"type": "llm_judge", "criteria": "x"}], _run(text="y"), workspace_id=1)
    assert r["ok"] is False and r["detail"] == "no judge connection configured"


def test_llm_judge_tenancy_mismatch(db, make_conn, monkeypatch):
    # connection belongs to workspace 2, judge evaluated for workspace 1 -> no judge connection
    conn = make_conn(workspace_id=2)
    monkeypatch.setattr(llm, "collect_text_sync", lambda **kw: (_ for _ in ()).throw(AssertionError("should not call")))
    r = _first(db, [{"type": "llm_judge", "connection_id": conn.id, "criteria": "x"}],
               _run(text="y"), workspace_id=1)
    assert r["ok"] is False and r["detail"] == "no judge connection configured"


def test_llm_judge_model_from_config_and_explicit(db, make_conn, monkeypatch):
    conn = make_conn(workspace_id=1, config={"provider": "openai", "models": ["cfg-model"]})
    seen = {}
    monkeypatch.setattr(llm, "collect_text_sync",
                        lambda **kw: seen.update(kw) or "PASS")
    # explicit model overrides config
    A.evaluate(db, [{"type": "llm_judge", "connection_id": conn.id, "model": "explicit-model", "criteria": "c"}],
               _run(text="t"), workspace_id=1)
    assert seen["model"] == "explicit-model"
    # config model used when no explicit
    A.evaluate(db, [{"type": "llm_judge", "connection_id": conn.id, "criteria": "c"}],
               _run(text="t"), workspace_id=1)
    assert seen["model"] == "cfg-model"


def test_llm_judge_default_model_when_config_empty(db, make_conn, monkeypatch):
    conn = make_conn(workspace_id=1, config={"provider": "openai"})  # no models key
    seen = {}
    monkeypatch.setattr(llm, "collect_text_sync", lambda **kw: seen.update(kw) or "PASS")
    A.evaluate(db, [{"type": "llm_judge", "connection_id": conn.id, "criteria": "c"}],
               _run(text="t"), workspace_id=1)
    assert seen["model"] == "gpt-4o-mini"


def test_llm_judge_no_workspace_id_scoping(db, make_conn, monkeypatch):
    # workspace_id=None -> tenancy branch skipped, connection used regardless of its workspace
    conn = make_conn(workspace_id=99)
    monkeypatch.setattr(llm, "collect_text_sync", lambda **kw: "PASS ok")
    r = _first(db, [{"type": "llm_judge", "connection_id": conn.id, "criteria": "c"}], _run(text="t"))
    assert r["ok"] is True


def test_events_read_from_result_when_run_events_absent(db):
    # events falls back to result["events"] when top-level events is empty
    run = {"result": {"text": "", "meta": {}, "events": [{"tool_name": "fromresult"}]},
           "status": "completed", "duration_ms": 0}
    r = _first(db, [{"type": "tool_called", "value": "fromresult"}], run)
    assert r["ok"] is True


# --------------------------------------------------------------------------- #
# masking: mask_value                                                         #
# --------------------------------------------------------------------------- #
def test_mask_value_short():
    assert M.mask_value("abc") == M.MASK  # len<=4 -> full mask, no tail


def test_mask_value_exactly_four():
    assert M.mask_value("abcd") == M.MASK


def test_mask_value_long_keeps_tail():
    assert M.mask_value("sk-1234567890") == M.MASK + "7890"


def test_mask_value_non_string_coerced():
    assert M.mask_value(1234567) == M.MASK + "4567"


# --------------------------------------------------------------------------- #
# masking: is_secret_header                                                   #
# --------------------------------------------------------------------------- #
def test_is_secret_header_fixed_set():
    assert M.is_secret_header("Authorization") is True
    assert M.is_secret_header("cookie") is True


def test_is_secret_header_regex_custom():
    assert M.is_secret_header("X-Custom-Token") is True
    assert M.is_secret_header("X-Session-Id") is True
    assert M.is_secret_header("X-My-Password") is True


def test_is_secret_header_non_secret():
    assert M.is_secret_header("Content-Type") is False
    assert M.is_secret_header("Accept") is False


# --------------------------------------------------------------------------- #
# masking: mask_headers                                                       #
# --------------------------------------------------------------------------- #
def test_mask_headers_mixed():
    headers = {
        "Authorization": "Bearer sk-abcdefgh",
        "X-Custom-Token": "tok-12345678",
        "Content-Type": "application/json",
        "X-Api-Key": "",  # empty value -> not masked (falsy)
    }
    out = M.mask_headers(headers)
    assert out["Authorization"].startswith(M.MASK)
    assert out["X-Custom-Token"].startswith(M.MASK)
    assert out["Content-Type"] == "application/json"
    assert out["X-Api-Key"] == ""  # empty stays empty


# --------------------------------------------------------------------------- #
# masking: is_masked                                                          #
# --------------------------------------------------------------------------- #
def test_is_masked():
    assert M.is_masked(M.MASK + "1234") is True
    assert M.is_masked("plain") is False
    assert M.is_masked(1234) is False


# --------------------------------------------------------------------------- #
# masking: mask_body                                                          #
# --------------------------------------------------------------------------- #
def test_mask_body_nested_dict_and_list():
    body = {
        "api_key": "secretlongvalue",
        "nested": {"password": "hunter2xyz", "keep": "public"},
        "items": [{"token": "abcd1234ef"}, {"other": "val"}],
        "count": 5,               # non-string value stays
        "empty_secret": "",       # secret name but empty -> recurse (stays "")
        "authorization": 999,     # secret name, non-string -> not masked
    }
    out = M.mask_body(body)
    assert out["api_key"].startswith(M.MASK)
    assert out["nested"]["password"].startswith(M.MASK)
    assert out["nested"]["keep"] == "public"
    assert out["items"][0]["token"].startswith(M.MASK)
    assert out["items"][1]["other"] == "val"
    assert out["count"] == 5
    assert out["empty_secret"] == ""
    assert out["authorization"] == 999  # non-string secret untouched


def test_mask_body_scalar_passthrough():
    assert M.mask_body("plain") == "plain"
    assert M.mask_body(42) == 42
    assert M.mask_body(None) is None


def test_mask_body_top_level_list():
    assert M.mask_body([{"secret": "topsecretval"}]) == [{"secret": M.MASK + "tval"}]


# --------------------------------------------------------------------------- #
# netguard: guard_url — local mode                                            #
# --------------------------------------------------------------------------- #
@pytest.fixture
def local_mode(monkeypatch):
    monkeypatch.setattr(get_settings(), "hosted", False)


@pytest.fixture
def hosted_mode(monkeypatch):
    monkeypatch.setattr(get_settings(), "hosted", True)


def test_guard_url_local_allows_localhost(local_mode):
    NG.guard_url("http://localhost:8000/x")  # no raise
    NG.guard_url("http://127.0.0.1:8000")


def test_guard_url_local_allows_private(local_mode):
    NG.guard_url("http://10.0.0.5/x")
    NG.guard_url("http://192.168.1.20:9000")


def test_guard_url_local_blocks_link_local_metadata_ip(local_mode):
    with pytest.raises(NG.BlockedURL, match="Link-local"):
        NG.guard_url("http://169.254.169.254/latest/meta-data/")


def test_guard_url_blocks_metadata_hostname(local_mode):
    with pytest.raises(NG.BlockedURL, match="not allowed"):
        NG.guard_url("http://metadata/computeMetadata/")
    with pytest.raises(NG.BlockedURL, match="not allowed"):
        NG.guard_url("http://metadata.google.internal/x")


def test_guard_url_no_host_raises(local_mode):
    with pytest.raises(NG.BlockedURL, match="no host"):
        NG.guard_url("not-a-url")


def test_guard_url_local_does_not_resolve_hostname(local_mode, monkeypatch):
    # In local mode a hostname that isn't a literal IP is allowed without DNS resolution.
    def _boom(*a, **k):
        raise AssertionError("getaddrinfo must not be called in local mode")
    monkeypatch.setattr(NG.socket, "getaddrinfo", _boom)
    NG.guard_url("http://example.com/path")  # no raise, no resolution


# --------------------------------------------------------------------------- #
# netguard: guard_url — hosted mode                                           #
# --------------------------------------------------------------------------- #
def test_guard_url_hosted_blocks_private_literal_ip(hosted_mode):
    with pytest.raises(NG.BlockedURL, match="Private / internal"):
        NG.guard_url("http://10.0.0.5/x")


def test_guard_url_hosted_allows_global_literal_ip(hosted_mode):
    NG.guard_url("http://8.8.8.8/x")  # no raise


def test_guard_url_hosted_resolves_hostname_to_private_blocks(hosted_mode, monkeypatch):
    def _fake(host, *a, **k):
        return [(2, 1, 6, "", ("10.1.2.3", 0))]
    monkeypatch.setattr(NG.socket, "getaddrinfo", _fake)
    with pytest.raises(NG.BlockedURL, match="Private / internal"):
        NG.guard_url("http://internal.example.com/x")


def test_guard_url_hosted_resolves_hostname_to_global_ok(hosted_mode, monkeypatch):
    def _fake(host, *a, **k):
        return [(2, 1, 6, "", ("93.184.216.34", 0))]
    monkeypatch.setattr(NG.socket, "getaddrinfo", _fake)
    NG.guard_url("http://example.com/x")  # no raise


def test_guard_url_hosted_resolution_failure_blocks(hosted_mode, monkeypatch):
    def _fail(host, *a, **k):
        raise OSError("nodename nor servname provided")
    monkeypatch.setattr(NG.socket, "getaddrinfo", _fail)
    with pytest.raises(NG.BlockedURL, match="Cannot resolve host"):
        NG.guard_url("http://doesnotexist.invalid/x")


def test_guard_url_hosted_blocks_link_local_ip(hosted_mode):
    with pytest.raises(NG.BlockedURL, match="Link-local"):
        NG.guard_url("http://169.254.169.254/x")


# --------------------------------------------------------------------------- #
# netguard: guard_stdio                                                       #
# --------------------------------------------------------------------------- #
def test_guard_stdio_local_noop(local_mode):
    NG.guard_stdio()  # no raise


def test_guard_stdio_hosted_raises(hosted_mode):
    with pytest.raises(NG.BlockedURL, match="stdio"):
        NG.guard_stdio()
