"""Trace → test: the converter mapping, and the full path — ingest an OTLP trace, turn the
captured run into a saved Request, and export it as a runnable .provekit test."""
from fastapi.testclient import TestClient

from provekit.main import app
from provekit.services import tracetest


def test_run_to_request_payload_seeds_an_llm_judge_from_the_output():
    payload = tracetest.run_to_request_payload(
        {"type": "trace", "model": "gpt-4o", "input": "capital of France?"},
        {"text": "The capital of France is Paris."})
    assert payload["type"] == "prompt"
    assert payload["model"] == "gpt-4o"
    assert payload["user"] == "capital of France?"
    a = payload["assertions"][0]
    assert a["type"] == "llm_judge"
    assert "The capital of France is Paris." in a["criteria"]
    assert "connection_id" not in a          # no connection chosen → judge unbound until attached


def test_run_to_request_payload_wires_the_connection_to_prompt_and_judge():
    payload = tracetest.run_to_request_payload(
        {"input": "q", "model": "gpt-4o"}, {"text": "answer"}, connection_id=7)
    assert payload["connection_id"] == 7                 # the prompt target
    assert payload["assertions"][0]["connection_id"] == 7  # the judge


def test_run_to_request_payload_without_output_seeds_no_assertion():
    payload = tracetest.run_to_request_payload({"input": "q"}, {})
    assert payload["user"] == "q" and "assertions" not in payload


def test_run_to_request_payload_json_encodes_structured_input():
    payload = tracetest.run_to_request_payload(
        {"input": {"messages": [{"role": "user", "content": "hi"}]}}, {"text": "ok"})
    assert '"messages"' in payload["user"]     # non-string input is JSON-encoded


def test_run_to_request_payload_survives_unserializable_input():
    class Weird:
        pass
    payload = tracetest.run_to_request_payload({"input": Weird()}, {})
    assert isinstance(payload["user"], str) and payload["user"]  # str() fallback, no crash


def _otlp_trace(model, prompt, completion):
    return {"resourceSpans": [{"scopeSpans": [{"spans": [{
        "name": f"chat {model}",
        "attributes": [
            {"key": "gen_ai.request.model", "value": {"stringValue": model}},
            {"key": "gen_ai.input.messages", "value": {"stringValue": prompt}},
            {"key": "gen_ai.output.messages", "value": {"stringValue": completion}},
        ],
        "status": {"code": 1},
    }]}]}]}


def test_trace_run_converts_to_an_exportable_provekit_test():
    c = TestClient(app, base_url="https://testserver")
    otlp = _otlp_trace("gpt-4o", "What is the capital of France?", "The capital of France is Paris.")
    assert c.post("/v1/traces", json=otlp).status_code == 200

    traces = c.get("/api/runs?type=trace").json()
    assert traces, "the ingested trace should appear in the traces list"
    rid = traces[0]["id"]

    created = c.post(f"/api/runs/{rid}/to-test", json={"name": "capital test"}).json()
    assert created["type"] == "prompt" and created["name"] == "capital test"

    # the saved Request exports to a real .provekit test carrying the prompt + llm_judge
    doc = c.get(f"/api/requests/{created['id']}/export").text
    assert "kind: test" in doc
    assert "gpt-4o" in doc
    assert "llm_judge" in doc and "Paris" in doc


def test_to_test_wires_a_chosen_connection_and_rejects_bad_ones():
    c = TestClient(app, base_url="https://testserver")
    conn = c.post("/api/connections", json={"name": "judge-llm", "kind": "llm", "config": {
        "provider": "openai", "api_key": "sk-x", "models": ["gpt-4o"]}}).json()
    c.post("/v1/traces", json=_otlp_trace("gpt-4o", "ping", "pong"))
    rid = c.get("/api/runs?type=trace").json()[0]["id"]

    assert c.post(f"/api/runs/{rid}/to-test", json={"connection_id": 999999}).status_code == 400

    created = c.post(f"/api/runs/{rid}/to-test", json={"connection_id": conn["id"]}).json()
    payload = c.get(f"/api/requests/{created['id']}").json()["payload"]
    assert payload["connection_id"] == conn["id"]                       # prompt target wired
    assert payload["assertions"][0]["type"] == "llm_judge"
    assert payload["assertions"][0]["connection_id"] == conn["id"]      # judge wired


def test_to_test_is_404_for_an_unknown_run():
    c = TestClient(app, base_url="https://testserver")
    assert c.post("/api/runs/999999/to-test", json={}).status_code == 404
