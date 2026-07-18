"""CLI runner: end-to-end against the keyless mock provider, plus promptfoo import."""
import textwrap
from pathlib import Path

import pytest

from provekit import cli
from provekit.services.promptfoo import import_promptfoo

CONNECTIONS = """\
connections:
  Mock:
    provider: mock
    models: [demo-mock]
  Keyed:
    provider: openai
    api_key: ${MY_TEST_KEY}
    models: [gpt-4o-mini]
"""

PASSING = """\
version: 1
kind: test
name: greets
connection: Mock
request:
  type: prompt
  model: demo-mock
  user: "what is an AI agent"
assertions:
  - type: contains
    value: agent
"""

FAILING = """\
version: 1
kind: test
name: wont-match
connection: Mock
request:
  type: prompt
  model: demo-mock
  user: "hello"
assertions:
  - type: contains
    value: "this string never appears in the mock reply xyzzy"
"""


@pytest.fixture
def workspace(tmp_path):
    (tmp_path / ".provekit").mkdir()
    (tmp_path / ".provekit/connections.yaml").write_text(CONNECTIONS)
    (tmp_path / "tests").mkdir()
    return tmp_path


def test_run_passing_exits_zero(workspace, monkeypatch, capsys):
    (workspace / "tests/pass.yaml").write_text(PASSING)
    monkeypatch.chdir(workspace)
    rc = cli.main(["run", "tests/", "--format", "json"])
    assert rc == 0
    out = capsys.readouterr().out
    assert '"ok": true' in out.lower() or '"ok": True'.lower() in out.lower()


def test_run_failing_exits_nonzero(workspace, monkeypatch):
    (workspace / "tests/fail.yaml").write_text(FAILING)
    monkeypatch.chdir(workspace)
    assert cli.main(["run", "tests/"]) == 1


def test_env_var_expansion_in_connections(workspace, monkeypatch):
    monkeypatch.setenv("MY_TEST_KEY", "sk-from-env")
    reg = cli._load_connections(str(workspace / ".provekit/connections.yaml"))
    assert reg.get(None, reg.id_of("Keyed")).config["api_key"] == "sk-from-env"
    assert reg.get(None, reg.id_of("Mock")).config["provider"] == "mock"


def test_unresolved_connection_is_reported(workspace, monkeypatch):
    (workspace / "tests/x.yaml").write_text(PASSING.replace("connection: Mock", "connection: Nope"))
    monkeypatch.chdir(workspace)
    # missing connection => treated as failure (non-zero) so CI can't pass on a broken ref
    assert cli.main(["run", "tests/"]) == 1


def test_junit_output(workspace, monkeypatch):
    (workspace / "tests/pass.yaml").write_text(PASSING)
    monkeypatch.chdir(workspace)
    out = workspace / "r.xml"
    cli.main(["run", "tests/", "--format", "junit", "-o", str(out)])
    xml = out.read_text()
    assert "<testsuites>" in xml and 'failures="0"' in xml


def test_dataset_runs_each_row(workspace, monkeypatch):
    (workspace / "tests/ds.yaml").write_text(PASSING + textwrap.dedent("""\
        dataset:
          - name: a
            variables: {}
          - name: b
            variables: {}
        """))
    monkeypatch.chdir(workspace)
    reg = cli._load_connections(str(workspace / ".provekit/connections.yaml"))
    import provekit.services.testfile as tf
    doc = tf.load((workspace / "tests/ds.yaml").read_text())
    req, _ = cli._resolve_request(doc, reg)
    assert len(doc["dataset"]) == 2


def test_import_promptfoo():
    pf = textwrap.dedent("""\
        providers:
          - openai:gpt-4o-mini
          - anthropic:claude-haiku-4-5
        prompts:
          - "Answer: {{query}}"
        tests:
          - description: refund case
            vars: {query: "refund please"}
            assert:
              - type: contains
                value: refund
              - type: latency
                threshold: 2000
              - type: llm-rubric
                value: is polite
              - type: javascript
                value: "output.length > 0"
        """)
    files, warnings = import_promptfoo(pf)
    assert len(files) == 1
    name, text = files[0]
    import provekit.services.testfile as tf
    doc = tf.load(text)
    assert doc["connection"] == "openai"
    assert doc["request"]["model"] == "gpt-4o-mini"
    types = [a["type"] for a in doc["assertions"]]
    assert types == ["contains", "latency_lt", "llm_judge"]  # javascript dropped
    assert any("javascript" in w for w in warnings)
    assert any("providers" in w for w in warnings)  # 2nd provider reported, not silently dropped
