"""provekit doctor: the SDK is fail-open, so every misconfiguration looks like "working".
These pin that each one is reported as itself rather than as silence."""
import pytest

from provekit import doctor


def _env(monkeypatch, key=None, endpoint=None):
    for name, val in (("PROVEKIT_API_KEY", key), ("PROVEKIT_ENDPOINT", endpoint)):
        monkeypatch.delenv(name, raising=False)
        if val is not None:
            monkeypatch.setenv(name, val)


def _find(rep, name):
    return next((r for r in rep.rows if r[1] == name), None)


def test_unset_config_fails_and_names_both_variables(monkeypatch):
    _env(monkeypatch)
    rep = doctor.run()
    assert _find(rep, "PROVEKIT_API_KEY")[0] == doctor.BAD
    assert _find(rep, "PROVEKIT_ENDPOINT")[0] == doctor.BAD
    assert rep.worst == doctor.BAD


def test_endpoint_including_the_ingest_path_is_caught(monkeypatch):
    """The SDK appends /v1/traces itself, so this produces a 404 that looks like nothing."""
    _env(monkeypatch, "pk_abc123", "https://portal.example.com/v1/traces")
    rep = doctor.run()
    row = _find(rep, "PROVEKIT_ENDPOINT")
    assert row[0] == doctor.BAD and "/v1/traces" in row[2]
    # and we don't then try to reach a URL we've already rejected
    assert _find(rep, "Portal reachable")[0] == doctor.WARN


def test_a_non_url_endpoint_is_rejected(monkeypatch):
    _env(monkeypatch, "pk_abc123", "provekit.example.com")     # no scheme
    assert _find(doctor.run(), "PROVEKIT_ENDPOINT")[0] == doctor.BAD


def test_a_key_that_isnt_a_project_key_warns_but_does_not_block(monkeypatch):
    _env(monkeypatch, "sk-openai-key-pasted-by-mistake", "https://portal.example.com")
    row = _find(doctor.run(), "PROVEKIT_API_KEY")
    assert row[0] == doctor.WARN and "pk_" in row[3]


def test_unreachable_portal_is_reported_with_the_url(monkeypatch):
    _env(monkeypatch, "pk_abc123", "http://127.0.0.1:9")       # discard port: nothing listens
    row = _find(doctor.run(), "Portal reachable")
    assert row[0] == doctor.BAD and "127.0.0.1:9" in row[2]


@pytest.mark.parametrize("code,expect_name,state", [
    (401, "Ingest auth", doctor.BAD),
    (403, "Ingest auth", doctor.BAD),
    (404, "Portal reachable", doctor.BAD),
    (429, "Ingest auth", doctor.WARN),
    (200, "Portal reachable", doctor.OK),
])
def test_http_status_maps_to_the_right_diagnosis(monkeypatch, code, expect_name, state):
    """A rejected key and a wrong host are different problems with different fixes."""
    import urllib.error

    def fake_open(req, timeout=None):
        if code >= 400:
            raise urllib.error.HTTPError(req.full_url, code, "", {}, None)

        class R:
            status = code
            def __enter__(self): return self
            def __exit__(self, *a): return False
        return R()

    monkeypatch.setattr(doctor.urllib.request, "urlopen", fake_open)
    rep = doctor.Report()
    doctor.check_reachable(rep, "https://portal.example.com", "pk_abc", send=False)
    assert _find(rep, expect_name)[0] == state


def test_probe_is_only_sent_when_asked(monkeypatch):
    """The default must not write a fake span into someone's project."""
    sent = []

    def fake_open(req, timeout=None):
        sent.append(req.data)

        class R:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *a): return False
        return R()

    monkeypatch.setattr(doctor.urllib.request, "urlopen", fake_open)
    doctor.check_reachable(doctor.Report(), "https://p.example.com", "pk_a", send=False)
    assert b'"resourceSpans": []' in sent[0]        # empty body, nothing stored

    doctor.check_reachable(doctor.Report(), "https://p.example.com", "pk_a", send=True)
    assert b"provekit.doctor" in sent[1]


def test_exit_code_is_nonzero_only_on_a_real_failure(monkeypatch):
    """So a setup script or CI step can gate on it."""
    _env(monkeypatch)
    monkeypatch.setattr("sys.argv", ["provekit-doctor", "--no-color"])
    assert doctor.main() == 1

    ok = doctor.Report()
    ok.add(doctor.OK, "x", "")
    ok.add(doctor.WARN, "y", "")
    assert ok.worst == doctor.WARN          # a warning alone must not fail the run
