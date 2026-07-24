"""The `provekit` CLI — argument parsing, output formatting and exit codes.

The CLI is an HTTP client, so every test stubs `httpx.request` and asserts on the calls it
builds and the text it prints. Nothing here starts a server or touches the database: that is
the whole point of the command (it has to work against a remote portal), and a test that
needed a live app would not be testing the thing that can break.
"""
import json
import types

import pytest

from provekit import cli


class _Resp:
    def __init__(self, status, payload=None, text=None, method="GET", path="/"):
        self.status_code = status
        self._payload = payload
        self.text = text if text is not None else json.dumps(payload if payload is not None else "")
        self.request = types.SimpleNamespace(method=method,
                                             url=types.SimpleNamespace(path=path))

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


class _Stub:
    """Routes (METHOD, path) → a response (or a list of responses consumed in order)."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __call__(self, method, url, **kw):
        path = url.replace("https://portal.test", "")
        self.calls.append({"method": method, "path": path, "params": kw.get("params"),
                           "headers": kw.get("headers"), "body": kw.get("json")})
        resp = self.routes.get((method, path))
        if resp is None:
            return _Resp(404, {"detail": "Not Found"}, method=method, path=path)
        if isinstance(resp, list):
            resp = resp.pop(0)
        resp.request = types.SimpleNamespace(method=method,
                                             url=types.SimpleNamespace(path=path))
        return resp


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("PROVEKIT_API_KEY", "pk_test")
    monkeypatch.setenv("PROVEKIT_ENDPOINT", "https://portal.test/")


def _stub(monkeypatch, routes) -> _Stub:
    s = _Stub(routes)
    monkeypatch.setattr(cli.httpx, "request", s)
    return s


_TRACE_ROW = {"id": 7, "trace_id": "a" * 32, "label": "support-agent", "type": "agent",
              "status": "failed", "duration_ms": 1234, "span_count": 3, "tokens": 90,
              "created_at": "2026-07-20T10:00:00+00:00"}


# ---- helpers ----
def test_hours_accepts_minutes_hours_days_and_bare_numbers():
    assert cli._hours("24h") == 24
    assert cli._hours("7d") == 168
    assert cli._hours("6") == 6
    # rounded UP, so a sub-hour window still asks for a window that contains it
    assert cli._hours("90m") == 2
    assert cli._hours("5m") == 1


@pytest.mark.parametrize("bad", ["", "soon", "0h", "-3d", "12w"])
def test_hours_rejects_junk(bad):
    with pytest.raises(cli.CliError):
        cli._hours(bad)


def test_ms_and_table_formatting():
    assert cli._ms(0) == "-"
    assert cli._ms(None) == "-"
    assert cli._ms(250) == "250ms"
    assert cli._ms(1500) == "1.50s"
    out = cli._table(["A", "BB"], [["xxxx", "y"]]).splitlines()
    assert out[0] == "A     BB"
    assert out[1] == "xxxx  y"


# ---- config ----
def test_missing_config_exits_one_with_a_fixable_message(monkeypatch, capsys):
    monkeypatch.delenv("PROVEKIT_API_KEY", raising=False)
    monkeypatch.delenv("PROVEKIT_ENDPOINT", raising=False)
    assert cli.main(["traces", "list"]) == 1
    assert "PROVEKIT_API_KEY" in capsys.readouterr().err


def test_flags_override_the_environment(monkeypatch, env):
    s = _stub(monkeypatch, {("GET", "/v1/traces"): _Resp(200, [])})
    cli.main(["traces", "list", "--endpoint", "https://other.test/", "--api-key", "pk_flag"])
    # the stub only strips the portal.test prefix, so the full URL is visible here
    assert s.calls[0]["path"] == "https://other.test/v1/traces"
    assert s.calls[0]["headers"]["Authorization"] == "Bearer pk_flag"


# ---- traces ----
def test_traces_list_builds_params_and_renders_a_table(monkeypatch, env, capsys):
    s = _stub(monkeypatch, {("GET", "/v1/traces"): _Resp(200, [_TRACE_ROW])})
    assert cli.main(["traces", "list", "--status", "failed", "--limit", "5", "--since", "24h"]) == 0

    assert s.calls[0]["params"] == {"limit": 5, "status": "failed", "window_hours": 24}
    assert s.calls[0]["headers"]["Authorization"] == "Bearer pk_test"
    out = capsys.readouterr().out
    assert "TRACE" in out and "support-agent" in out and "1.23s" in out


def test_traces_list_json_is_the_raw_payload(monkeypatch, env, capsys):
    _stub(monkeypatch, {("GET", "/v1/traces"): _Resp(200, [_TRACE_ROW])})
    assert cli.main(["traces", "list", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == [_TRACE_ROW]


def test_traces_list_empty_says_so(monkeypatch, env, capsys):
    _stub(monkeypatch, {("GET", "/v1/traces"): _Resp(200, [])})
    cli.main(["traces", "list"])
    assert "No traces matched." in capsys.readouterr().out


def test_traces_get_renders_the_span_tree(monkeypatch, env, capsys):
    spans = [
        {"id": 1, "span_id": "s1", "parent_span_id": "", "type": "agent", "label": "root",
         "status": "completed", "duration_ms": 900},
        {"id": 2, "span_id": "s2", "parent_span_id": "s1", "type": "llm", "label": "chat",
         "status": "failed", "duration_ms": 100, "error": "boom"},
    ]
    _stub(monkeypatch, {("GET", "/v1/traces/t1"): _Resp(200, spans)})
    assert cli.main(["traces", "get", "t1"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "- root [agent] 900ms"
    assert lines[1] == "  x chat [llm] 100ms"
    assert lines[2].strip() == "error: boom"


def test_traces_get_still_prints_a_trace_whose_root_never_arrived(monkeypatch, env, capsys):
    # The process died before the root span ended, so no span has parent "".
    spans = [{"id": 2, "span_id": "s2", "parent_span_id": "missing", "type": "tool",
              "label": "call-upstream", "status": "failed", "duration_ms": 5}]
    _stub(monkeypatch, {("GET", "/v1/traces/t2"): _Resp(200, spans)})
    cli.main(["traces", "get", "t2"])
    assert "call-upstream" in capsys.readouterr().out


def test_traces_get_survives_a_span_that_parents_itself(monkeypatch, env, capsys):
    spans = [{"id": 1, "span_id": "s1", "parent_span_id": "s1", "type": "step",
              "label": "loop", "status": "completed", "duration_ms": 1}]
    _stub(monkeypatch, {("GET", "/v1/traces/t3"): _Resp(200, spans)})
    cli.main(["traces", "get", "t3"])
    assert capsys.readouterr().out.count("loop") == 1


def test_http_error_reports_the_servers_detail_and_exits_one(monkeypatch, env, capsys):
    _stub(monkeypatch, {("GET", "/v1/traces/nope"): _Resp(404, {"detail": "Trace not found"})})
    assert cli.main(["traces", "get", "nope"]) == 1
    assert "Trace not found" in capsys.readouterr().err


def test_non_json_error_body_falls_back_to_the_text(monkeypatch, env, capsys):
    _stub(monkeypatch, {("GET", "/v1/traces"): _Resp(502, None, text="upstream down")})
    assert cli.main(["traces", "list"]) == 1
    assert "upstream down" in capsys.readouterr().err


def test_unreachable_portal_is_a_clean_error(monkeypatch, env, capsys):
    def boom(*a, **kw):
        raise cli.httpx.ConnectError("nope")
    monkeypatch.setattr(cli.httpx, "request", boom)
    assert cli.main(["traces", "list"]) == 1
    assert "could not reach https://portal.test" in capsys.readouterr().err


# ---- datasets ----
def test_datasets_list(monkeypatch, env, capsys):
    rows = [{"id": 3, "name": "qa-golden", "item_count": 12, "created_at": "2026-07-01T00:00:00+00:00"}]
    _stub(monkeypatch, {("GET", "/v1/datasets"): _Resp(200, rows)})
    assert cli.main(["datasets", "list"]) == 0
    out = capsys.readouterr().out
    assert "qa-golden" in out and "12" in out


def test_datasets_list_empty_suggests_create(monkeypatch, env, capsys):
    _stub(monkeypatch, {("GET", "/v1/datasets"): _Resp(200, [])})
    cli.main(["datasets", "list"])
    assert "datasets create" in capsys.readouterr().out


def test_datasets_create_prefers_v1_when_the_server_has_it(monkeypatch, env, capsys):
    s = _stub(monkeypatch, {("POST", "/v1/datasets"): _Resp(200, {"id": 9, "name": "new"})})
    assert cli.main(["datasets", "create", "new", "--description", "d"]) == 0
    assert [c["path"] for c in s.calls] == ["/v1/datasets"]
    assert s.calls[0]["body"] == {"name": "new", "description": "d"}
    assert "Created dataset 9" in capsys.readouterr().out


def test_datasets_create_falls_back_to_the_portal_route(monkeypatch, env):
    s = _stub(monkeypatch, {("POST", "/v1/datasets"): _Resp(405, {"detail": "Method Not Allowed"}),
                            ("POST", "/api/datasets"): _Resp(200, {"id": 4, "name": "new"})})
    assert cli.main(["datasets", "create", "new"]) == 0
    assert [c["path"] for c in s.calls] == ["/v1/datasets", "/api/datasets"]


def test_datasets_create_explains_a_key_only_portal(monkeypatch, env, capsys):
    _stub(monkeypatch, {("POST", "/v1/datasets"): _Resp(404, {"detail": "Not Found"}),
                        ("POST", "/api/datasets"): _Resp(401, {"detail": "Authentication required"})})
    assert cli.main(["datasets", "create", "new"]) == 1
    assert "logged-in session" in capsys.readouterr().err


def test_datasets_add_resolves_the_dataset_by_name(monkeypatch, env, capsys):
    s = _stub(monkeypatch, {
        ("GET", "/v1/datasets"): _Resp(200, [{"id": 5, "name": "qa-golden"}]),
        ("POST", "/v1/datasets/5/items"): _Resp(200, {"id": 11}),
    })
    assert cli.main(["datasets", "add", "qa-golden", "--input", "hi", "--expected", "yo"]) == 0
    assert s.calls[-1]["body"] == {"input": "hi", "expected": "yo", "meta": {}}
    assert "Added 1 item(s) to dataset 5" in capsys.readouterr().out


def test_datasets_add_takes_a_numeric_id_without_a_lookup(monkeypatch, env):
    s = _stub(monkeypatch, {("POST", "/v1/datasets/5/items"): _Resp(200, {"id": 12})})
    assert cli.main(["datasets", "add", "5", "--input", "hi"]) == 0
    assert [c["path"] for c in s.calls] == ["/v1/datasets/5/items"]


def test_datasets_add_unknown_name_is_an_error(monkeypatch, env, capsys):
    _stub(monkeypatch, {("GET", "/v1/datasets"): _Resp(200, [{"id": 5, "name": "other"}])})
    assert cli.main(["datasets", "add", "qa-golden", "--input", "hi"]) == 1
    assert "not found" in capsys.readouterr().err


def test_datasets_add_from_a_jsonl_file(monkeypatch, env, tmp_path, capsys):
    path = tmp_path / "items.jsonl"
    path.write_text('{"input": "a", "expected": "A"}\n\n{"input": "b", "meta": {"k": 1}}\n')
    s = _stub(monkeypatch, {("POST", "/v1/datasets/2/items"): [_Resp(200, {"id": 1}),
                                                               _Resp(200, {"id": 2})]})
    assert cli.main(["datasets", "add", "2", "--file", str(path)]) == 0
    assert [c["body"] for c in s.calls] == [
        {"input": "a", "expected": "A", "meta": {}},
        {"input": "b", "expected": "", "meta": {"k": 1}},
    ]
    assert "Added 2 item(s)" in capsys.readouterr().out


def test_datasets_add_requires_input_or_file(monkeypatch, env, capsys):
    _stub(monkeypatch, {})
    assert cli.main(["datasets", "add", "2"]) == 1
    assert "--input" in capsys.readouterr().err


@pytest.mark.parametrize("body,expected", [
    ("not json\n", "not valid JSON"),
    ('{"expected": "A"}\n', "'input' key"),
    ("\n\n", "no items"),
])
def test_datasets_add_rejects_a_malformed_file(monkeypatch, env, tmp_path, capsys, body, expected):
    path = tmp_path / "bad.jsonl"
    path.write_text(body)
    _stub(monkeypatch, {})
    assert cli.main(["datasets", "add", "2", "--file", str(path)]) == 1
    assert expected in capsys.readouterr().err


def test_datasets_add_missing_file_is_an_error(monkeypatch, env, tmp_path, capsys):
    _stub(monkeypatch, {})
    assert cli.main(["datasets", "add", "2", "--file", str(tmp_path / "gone.jsonl")]) == 1
    assert "could not read" in capsys.readouterr().err


# ---- eval ----
_ITEMS = [{"id": 1, "input": "alpha", "expected": "alpha"},
          {"id": 2, "input": "beta", "expected": "not-beta"}]


def _eval_routes(summary):
    return {("GET", "/v1/datasets"): _Resp(200, [{"id": 5, "name": "qa-golden"}]),
            ("GET", "/v1/datasets/5/items"): _Resp(200, _ITEMS),
            ("POST", "/v1/experiments"): _Resp(200, {"id": 42, "name": "cli-eval"}),
            ("POST", "/v1/experiments/42/results"): [_Resp(200, {"id": 1}), _Resp(200, {"id": 2})],
            ("GET", "/v1/experiments/42"): _Resp(200, summary)}


def test_eval_run_scores_a_shell_target_and_posts_results(monkeypatch, env, capsys):
    summary = {"id": 42, "name": "cli-eval", "result_count": 2,
               "scorer_means": {"exact_match": 0.5}, "mean_score": 0.5}
    s = _stub(monkeypatch, _eval_routes(summary))
    # `cat` echoes the item input back, so item 1 matches its expected and item 2 does not.
    assert cli.main(["eval", "run", "--dataset", "qa-golden", "--command", "cat"]) == 0

    posted = [c["body"] for c in s.calls if c["path"] == "/v1/experiments/42/results"]
    assert [p["output"] for p in posted] == ["alpha", "beta"]
    assert posted[0]["scores"] == {"exact_match": 1.0}
    assert posted[1]["scores"] == {"exact_match": 0.0}
    out = capsys.readouterr().out
    assert "Experiment 42" in out and "exact_match: 0.500" in out and "mean_score: 0.500" in out


def test_eval_run_honours_repeated_scorer_flags(monkeypatch, env):
    s = _stub(monkeypatch, _eval_routes({"id": 42, "result_count": 2, "mean_score": 1.0}))
    cli.main(["eval", "run", "--dataset", "5", "--command", "cat",
              "--scorer", "exact_match", "--scorer", "contains", "--name", "nightly"])
    created = [c["body"] for c in s.calls if c["path"] == "/v1/experiments"]
    assert created == [{"name": "nightly", "dataset_id": 5}]
    posted = [c["body"] for c in s.calls if c["path"] == "/v1/experiments/42/results"]
    assert set(posted[0]["scores"]) == {"exact_match", "contains"}


def test_eval_run_fail_under_gates_the_build(monkeypatch, env, capsys):
    _stub(monkeypatch, _eval_routes({"id": 42, "result_count": 2, "mean_score": 0.5}))
    code = cli.main(["eval", "run", "--dataset", "5", "--command", "cat", "--fail-under", "0.8"])
    assert code == 1
    assert "below --fail-under 0.8" in capsys.readouterr().err


def test_eval_run_passes_the_gate_when_the_score_holds(monkeypatch, env):
    _stub(monkeypatch, _eval_routes({"id": 42, "result_count": 2, "mean_score": 0.9}))
    assert cli.main(["eval", "run", "--dataset", "5", "--command", "cat", "--fail-under", "0.8"]) == 0


def test_eval_run_with_no_score_at_all_fails_the_gate(monkeypatch, env, capsys):
    # mean_score is None when nothing scored; that is not "passing".
    _stub(monkeypatch, _eval_routes({"id": 42, "result_count": 2, "mean_score": None}))
    assert cli.main(["eval", "run", "--dataset", "5", "--command", "cat", "--fail-under", "0.1"]) == 1
    assert "mean_score: -" in capsys.readouterr().out


def test_eval_run_on_an_empty_dataset_is_an_error(monkeypatch, env, capsys):
    _stub(monkeypatch, {("GET", "/v1/datasets/5/items"): _Resp(200, [])})
    assert cli.main(["eval", "run", "--dataset", "5", "--command", "cat"]) == 1
    assert "no items" in capsys.readouterr().err


def test_a_failing_target_is_recorded_not_raised():
    assert cli._run_target("exit 3", "x", 5).startswith("ERROR: target exited 3")


def test_a_hanging_target_times_out_into_a_result():
    assert cli._run_target("sleep 5", "x", 1).startswith("ERROR: target timed out")


# ---- doctor ----
def test_doctor_delegates_to_the_one_implementation(monkeypatch, capsys):
    from provekit import doctor

    calls = []

    def fake_run(send=False):
        calls.append(send)
        rep = doctor.Report()
        rep.add(doctor.BAD, "PROVEKIT_API_KEY", "not set")
        return rep

    monkeypatch.setattr(doctor, "run", fake_run)
    assert cli.main(["doctor", "--send", "--no-color"]) == 1
    assert calls == [True]
    assert "ProveKit doctor" in capsys.readouterr().out


def test_doctor_exits_zero_when_healthy(monkeypatch, capsys):
    from provekit import doctor

    def fake_run(send=False):
        rep = doctor.Report()
        rep.add(doctor.OK, "PROVEKIT_API_KEY", "set")
        return rep

    monkeypatch.setattr(doctor, "run", fake_run)
    assert cli.main(["doctor", "--no-color"]) == 0
    assert "PASS" in capsys.readouterr().out


# ---- parser ----
def test_a_bare_group_is_a_usage_error():
    with pytest.raises(SystemExit) as exc:
        cli.main(["traces"])
    assert exc.value.code == 2


def test_every_leaf_command_is_wired():
    parser = cli.build_parser()
    for argv in (["traces", "list"], ["traces", "get", "t"], ["datasets", "list"],
                 ["datasets", "create", "n"], ["datasets", "add", "1", "--input", "x"],
                 ["eval", "run", "--dataset", "d", "--command", "c"], ["doctor"]):
        assert callable(parser.parse_args(argv).func)


# ---- dataset writes go to /v1 (#91) ----
def test_dataset_create_uses_the_key_authed_v1_route(monkeypatch, env, capsys):
    """The server has POST /v1/datasets now, so the /api fallback must not be reached."""
    stub = _stub(monkeypatch, {("POST", "/v1/datasets"): _Resp(200, {"id": 4, "name": "ci"})})
    assert cli.main(["datasets", "create", "ci"]) == 0
    paths = [c["path"] for c in stub.calls]
    assert paths == ["/v1/datasets"], f"fell back unnecessarily: {paths}"


def test_dataset_add_uses_the_key_authed_v1_route(monkeypatch, env):
    stub = _stub(monkeypatch, {
        ("POST", "/v1/datasets/4/items"): _Resp(200, {"id": 9, "input": "q", "expected": "a"}),
    })
    assert cli.main(["datasets", "add", "4", "--input", "q", "--expected", "a"]) == 0
    assert [c["path"] for c in stub.calls] == ["/v1/datasets/4/items"]


def test_dataset_create_still_falls_back_for_an_older_server(monkeypatch, env):
    """A self-hosted portal a release behind only has the cookie-authed route; `datasets
    create` should look older, not broken."""
    stub = _stub(monkeypatch, {
        ("POST", "/v1/datasets"): _Resp(404, {"detail": "Not Found"}),
        ("POST", "/api/datasets"): _Resp(200, {"id": 5, "name": "ci"}),
    })
    assert cli.main(["datasets", "create", "ci"]) == 0
    assert [c["path"] for c in stub.calls] == ["/v1/datasets", "/api/datasets"]


# ---- provekit up (#38) ----
def test_up_names_the_missing_extra_rather_than_raising_importerror(monkeypatch, capsys):
    """The CLI is core-deps-only by contract, so `up` has to explain the gap it can't fill."""
    import builtins
    real_import = builtins.__import__

    def _no_uvicorn(name, *a, **k):
        if name == "uvicorn":
            raise ImportError("no uvicorn")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _no_uvicorn)
    assert cli.main(["up"]) == 1
    err = capsys.readouterr().err
    assert "provekit[server]" in err
    # …and points out that the remote-facing commands still work without it.
    assert "traces" in err


def test_up_starts_the_api_and_reports_it(monkeypatch, capsys):
    """Spawns uvicorn rather than importing the server, waits for it to actually answer, and
    names the URL only once it does."""
    import subprocess as _sp
    import time as _time

    started = []

    class _Proc:
        returncode = None

        def __init__(self, argv, *a, **k):
            started.append(argv)

        def poll(self):
            return None

        def terminate(self):
            self.returncode = 0

        def wait(self, timeout=None):
            return 0

        def kill(self):
            pass

    monkeypatch.setattr(_sp, "Popen", _Proc)
    monkeypatch.setattr(cli, "_repo_frontend", lambda: None)
    monkeypatch.setattr(cli.httpx, "get", lambda *a, **k: _Resp(200, {"ok": True}))
    # `_t` in cmd_up is the real time module, so patching it here breaks the monitor loop.
    monkeypatch.setattr(_time, "sleep",
                        lambda *_a: (_ for _ in ()).throw(KeyboardInterrupt()))

    assert cli.main(["up", "--no-frontend", "--port", "8123"]) == 0
    out = capsys.readouterr().out
    assert "http://127.0.0.1:8123" in out
    assert "no login" in out
    # It launched uvicorn against the real app rather than importing the server itself.
    assert any("uvicorn" in part for part in started[0])
