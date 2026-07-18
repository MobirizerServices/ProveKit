"""Round-trip and validation tests for the .provekit file format."""
import pytest

from provekit.services import testfile

REQ = {
    "type": "prompt", "connection_id": 3, "model": "gpt-4o-mini",
    "system": "You are helpful.", "user": "{{message}}",
    "temperature": 0.2, "max_tokens": 512,
    "assertions": [{"type": "contains", "value": "refund"},
                   {"type": "latency_lt", "value": "3000"}],
    "api_key": "sk-should-never-appear", "_k": 7,
}
DATASET = [{"name": "angry", "variables": {"message": "URGENT refund"}},
           {"variables": {"message": "hi"}}]


def test_round_trip_test_file():
    text = testfile.dump_test("Support bot", REQ, "OpenAI (prod)", DATASET)
    doc = testfile.load(text)
    assert doc["kind"] == "test" and doc["name"] == "Support bot"
    assert doc["connection"] == "OpenAI (prod)"
    assert doc["request"]["type"] == "prompt"
    assert doc["request"]["user"] == "{{message}}"
    assert doc["assertions"] == [{"type": "contains", "value": "refund"},
                                 {"type": "latency_lt", "value": "3000"}]
    assert doc["dataset"][0] == {"name": "angry", "variables": {"message": "URGENT refund"}}
    assert doc["dataset"][1]["name"] == "row 2"  # unnamed rows get stable names


def test_secrets_and_ids_never_serialized():
    text = testfile.dump_test("t", REQ, "conn")
    assert "sk-should-never-appear" not in text
    assert "api_key" not in text
    assert "connection_id" not in text
    assert "_k" not in text


def test_dump_is_stable():
    a = testfile.dump_test("t", REQ, "conn", DATASET)
    b = testfile.dump_test("t", dict(reversed(list(REQ.items()))), "conn", DATASET)
    assert a == b  # field order is canonical, not insertion-dependent


def test_flow_round_trip_maps_connections_to_names():
    nodes = [{"id": "p", "type": "prompt", "position": {"x": 0, "y": 0}, "data": {"title": "P"},
              "config": {"connection_id": 5, "model": "m", "user": "{{input.q}}"}}]
    edges = [{"id": "e1", "source": "input", "target": "p"}]
    text = testfile.dump_flow("F", "desc", nodes, edges, {5: "My LLM"})
    assert "connection_id" not in text and "My LLM" in text
    doc = testfile.load(text)
    assert doc["kind"] == "flow"
    assert doc["nodes"][0]["config"]["connection"] == "My LLM"
    assert doc["edges"] == edges


@pytest.mark.parametrize("bad, msg", [
    ("version: 2\nkind: test\nrequest: {type: prompt}", "unsupported version"),
    ("version: 1\nkind: nope", "unsupported kind"),
    ("version: 1\nkind: test\nrequest: {type: wat}", "prompt | tool | agent"),
    ("version: 1\nkind: test\nrequest: {type: prompt, api_key: sk-x}", "credentials"),
    ("version: 1\nkind: flow\nnodes: {}", "nodes and edges"),
    ("[1, 2", "not valid YAML"),
    ("- just\n- a\n- list", "mapping at the top level"),
])
def test_load_rejects(bad, msg):
    with pytest.raises(ValueError, match=msg):
        testfile.load(bad)
