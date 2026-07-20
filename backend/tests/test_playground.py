"""Interactive debugging: provider connections (sealed BYO keys), the mock re-run path, the
OpenAI/Anthropic request shaping (mocked httpx — no real network), and the replay harness."""
import functools
import json

import anyio
from fastapi.testclient import TestClient

from provekit.database import SessionLocal
from provekit.main import app
from provekit.models import Dataset, DatasetItem, ProviderConnection, Run, Workspace
from provekit.services import llm_client
from provekit.services import replay as replay_mod
from provekit.services.sealing import seal, unseal

_OTLP = {"resourceSpans": [{"scopeSpans": [{"spans": [
    {"name": "chat", "traceId": "webhookbranch0001", "spanId": "s1", "parentSpanId": "",
     "startTimeUnixNano": "1000000000", "endTimeUnixNano": "1200000000", "status": {"code": 1},
     "attributes": [{"key": "gen_ai.request.model", "value": {"stringValue": "gpt-4o"}}]}]}]}]}


def test_seal_roundtrip():
    assert unseal(seal("sk-secret-123")) == "sk-secret-123"


def test_connections_crud_and_masking():
    with TestClient(app, base_url="https://testserver") as c:
        # create an openai connection — the raw key must never come back, only a hint
        row = c.post("/api/connections", json={"provider": "openai", "label": "prod",
                                               "key": "sk-live-abcd1234"}).json()
        assert row["provider"] == "openai" and row["label"] == "prod"
        assert row["key_hint"].endswith("1234")
        assert "key" not in row and "key_sealed" not in row
        cid = row["id"]
        assert any(x["id"] == cid for x in c.get("/api/connections").json())
        assert c.delete(f"/api/connections/{cid}").json()["ok"] is True
        assert all(x["id"] != cid for x in c.get("/api/connections").json())


def test_connection_validation():
    with TestClient(app, base_url="https://testserver") as c:
        assert c.post("/api/connections", json={"provider": "nope"}).status_code == 422
        assert c.post("/api/connections", json={"provider": "openai"}).status_code == 422  # no key
        assert c.post("/api/connections",
                      json={"provider": "openai_compatible", "key": "k"}).status_code == 422  # no base_url
        # mock needs no key
        assert c.post("/api/connections", json={"provider": "mock", "label": "m"}).status_code == 200


def test_playground_run_mock():
    with TestClient(app, base_url="https://testserver") as c:
        # keyless mock provider (no stored connection needed)
        r = c.post("/api/playground/run", json={"provider": "mock", "model": "gpt-4o",
                   "messages": [{"role": "user", "content": "hello world please"}]})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["output"].startswith("[mock:gpt-4o]")
        assert d["usage"]["output_tokens"] > 0
        assert "latency_ms" in d and d["provider"] == "mock"

        # editing the prompt changes the output (the whole point of the playground)
        r2 = c.post("/api/playground/run", json={"provider": "mock", "model": "gpt-4o",
                    "messages": [{"role": "user", "content": "a totally different question"}]})
        assert r2.json()["output"] != d["output"]

        # via a stored mock connection
        mc = c.post("/api/connections", json={"provider": "mock", "label": "m"}).json()
        r3 = c.post("/api/playground/run", json={"connection_id": mc["id"], "model": "x",
                    "messages": [{"role": "user", "content": "hi there"}]})
        assert r3.status_code == 200

        # a run needs either a connection or provider=mock
        assert c.post("/api/playground/run", json={"model": "x",
                      "messages": [{"role": "user", "content": "hi"}]}).status_code == 422
        assert c.post("/api/playground/run", json={"provider": "mock", "model": "x",
                      "messages": []}).status_code == 422


# ---- llm_client provider shaping (mocked httpx) ----
class _FakeResp:
    def __init__(self, status, data):
        self.status_code = status
        self._data = data

    def json(self):
        return self._data


class _FakeClient:
    """Stands in for httpx.AsyncClient — records the last request and returns a canned response."""
    last = None
    resp = None

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None, headers=None):
        type(self).last = {"url": url, "json": json, "headers": headers}
        return type(self).resp


def test_openai_request_shaping(monkeypatch):
    monkeypatch.setattr(llm_client.httpx, "AsyncClient", _FakeClient)
    _FakeClient.resp = _FakeResp(200, {"choices": [{"message": {"content": "answer"},
                                       "finish_reason": "stop"}],
                                       "usage": {"prompt_tokens": 5, "completion_tokens": 3}})
    out = anyio.run(functools.partial(
        llm_client.complete, "openai", "gpt-4o", [{"role": "user", "content": "x"}],
        {"temperature": 0.5, "max_tokens": 100}, api_key="sk-k"))
    assert out["output"] == "answer"
    assert out["usage"] == {"input_tokens": 5, "output_tokens": 3}
    assert _FakeClient.last["url"].endswith("/chat/completions")
    assert _FakeClient.last["headers"]["Authorization"] == "Bearer sk-k"
    assert _FakeClient.last["json"]["temperature"] == 0.5


def test_anthropic_request_shaping(monkeypatch):
    monkeypatch.setattr(llm_client.httpx, "AsyncClient", _FakeClient)
    _FakeClient.resp = _FakeResp(200, {"content": [{"type": "text", "text": "hi"}],
                                       "usage": {"input_tokens": 4, "output_tokens": 2},
                                       "stop_reason": "end_turn"})
    out = anyio.run(functools.partial(
        llm_client.complete, "anthropic", "claude-sonnet-5",
        [{"role": "system", "content": "be brief"}, {"role": "user", "content": "hi"}],
        {"max_tokens": 50}, api_key="ak-k"))
    assert out["output"] == "hi" and out["finish_reason"] == "end_turn"
    body = _FakeClient.last["json"]
    assert body["system"] == "be brief"                       # system hoisted out of messages
    assert [m["role"] for m in body["messages"]] == ["user"]  # only user/assistant turns
    assert _FakeClient.last["headers"]["x-api-key"] == "ak-k"


def test_llm_error_on_provider_400(monkeypatch):
    monkeypatch.setattr(llm_client.httpx, "AsyncClient", _FakeClient)
    _FakeClient.resp = _FakeResp(401, {"error": {"message": "bad key"}})
    try:
        anyio.run(functools.partial(
            llm_client.complete, "openai", "gpt-4o", [{"role": "user", "content": "x"}],
            api_key="sk-bad"))
        assert False, "expected LLMError"
    except llm_client.LLMError as e:
        assert "bad key" in str(e)


def test_unknown_provider_raises():
    try:
        anyio.run(functools.partial(llm_client.complete, "grok", "x", [{"role": "user", "content": "y"}]))
        assert False
    except llm_client.LLMError:
        pass


# ---- replay harness ----
def _seed_replay_trace(ws_id: int) -> str:
    """A 3-span trace where a downstream LLM ('decide') consumes the fork LLM's output."""
    db = SessionLocal()
    tid = "rep" + "0" * 29
    db.add_all([
        Run(workspace_id=ws_id, type="agent", label="root", trace_id=tid, span_id="r",
            parent_span_id="", request={}, result={"text": "final"}),
        Run(workspace_id=ws_id, type="llm", label="analyze", trace_id=tid, span_id="f",
            parent_span_id="r",
            request={"model": "gpt-4o", "input": json.dumps([{"role": "user", "content": "Analyze the docs."}])},
            result={"text": "ANALYSIS_ONE", "meta": {"usage": {"input_tokens": 10, "output_tokens": 3}}}),
        Run(workspace_id=ws_id, type="llm", label="decide", trace_id=tid, span_id="d",
            parent_span_id="r",
            request={"model": "gpt-4o", "input": json.dumps([{"role": "user", "content": "Given ANALYSIS_ONE, decide."}])},
            result={"text": "DECISION_X", "meta": {"usage": {"input_tokens": 8, "output_tokens": 2}}}),
    ])
    db.commit(); db.close()
    return tid


def test_replay_reconstructed_threads_downstream():
    with TestClient(app, base_url="https://testserver") as c:
        # a connection pins the exact current_workspace the replay will run in
        conn = c.post("/api/connections", json={"provider": "mock", "label": "m"}).json()
        db = SessionLocal()
        ws_id = db.get(ProviderConnection, conn["id"]).workspace_id
        db.close()
        tid = _seed_replay_trace(ws_id)

        r = c.post("/api/replay", json={
            "origin_trace_id": tid, "fork_span_id": "f", "provider": "mock", "model": "gpt-4o",
            "messages": [{"role": "user", "content": "Analyze the docs MORE carefully."}]})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["new_trace_id"] and d["new_trace_id"] != tid
        assert d["live_count"] >= 2   # the fork + the threaded downstream call both ran live

        # inspect the new branch: root unchanged, fork live, downstream threaded → live
        db = SessionLocal()
        states = {s.label: (s.result.get("meta") or {}).get("replay_state")
                  for s in db.query(Run).filter(Run.trace_id == d["new_trace_id"]).all()}
        # the downstream call's input had the old output substituted with the new one
        decide = db.query(Run).filter(Run.trace_id == d["new_trace_id"], Run.label == "decide").first()
        db.close()
        assert states == {"root": "unchanged", "analyze": "live", "decide": "live"}
        assert "ANALYSIS_ONE" not in decide.request["input"]   # threaded away


def test_replay_missing_trace_404():
    with TestClient(app, base_url="https://testserver") as c:
        r = c.post("/api/replay", json={"origin_trace_id": "nope", "fork_span_id": "x",
                   "provider": "mock", "model": "gpt-4o",
                   "messages": [{"role": "user", "content": "hi"}]})
        assert r.status_code == 404


def test_replay_webhook(monkeypatch):
    with TestClient(app, base_url="https://testserver") as c:
        conn = c.post("/api/connections", json={"provider": "mock", "label": "m"}).json()
        db = SessionLocal()
        ws = db.get(Workspace, db.get(ProviderConnection, conn["id"]).workspace_id)
        ws.replay_url = "https://hook.example/replay"; db.commit(); db.close()

        monkeypatch.setattr(replay_mod, "guard_url", lambda u: None)      # skip DNS/SSRF check
        monkeypatch.setattr(replay_mod.httpx, "AsyncClient", _FakeClient)
        _FakeClient.resp = _FakeResp(200, _OTLP)

        r = c.post("/api/replay", json={"origin_trace_id": "orig123", "fork_span_id": "f",
                   "model": "gpt-4o", "messages": [{"role": "user", "content": "x"}], "mode": "webhook"})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["mode"] == "webhook" and d["span_count"] >= 1
        # ProveKit POSTed the fork override to the configured webhook
        assert _FakeClient.last["url"] == "https://hook.example/replay"
        assert _FakeClient.last["json"]["fork_span_id"] == "f"
        # the returned OTLP was ingested as a new branch tagged replay_of
        db = SessionLocal()
        run = db.query(Run).filter(Run.trace_id == d["new_trace_id"]).first()
        db.close()
        assert (run.result.get("meta") or {}).get("replay_of") == "orig123"


def test_replay_webhook_unconfigured_404():
    with TestClient(app, base_url="https://testserver") as c:
        c.get("/api/connections")  # ensure the default workspace exists
        db = SessionLocal()
        for w in db.query(Workspace).all():   # ensure no workspace has a webhook configured
            w.replay_url = ""
        db.commit(); db.close()
        r = c.post("/api/replay", json={"origin_trace_id": "o", "fork_span_id": "f",
                   "model": "gpt-4o", "messages": [{"role": "user", "content": "x"}], "mode": "webhook"})
        assert r.status_code == 404


def test_playground_experiment_over_dataset():
    with TestClient(app, base_url="https://testserver") as c:
        conn = c.post("/api/connections", json={"provider": "mock", "label": "m"}).json()
        db = SessionLocal()
        ws_id = db.get(ProviderConnection, conn["id"]).workspace_id
        ds = Dataset(workspace_id=ws_id, name="golden")
        db.add(ds); db.commit(); db.refresh(ds)
        db.add_all([
            DatasetItem(workspace_id=ws_id, dataset_id=ds.id, input="ping", expected="[mock:gpt-4o] ping."),
            DatasetItem(workspace_id=ws_id, dataset_id=ds.id, input="hello", expected="wrong"),
        ])
        db.commit(); dsid = ds.id; db.close()

        r = c.post("/api/playground/experiment", json={
            "dataset_id": dsid, "provider": "mock", "model": "gpt-4o",
            "messages": [{"role": "user", "content": "{{input}}"}],
            "scorers": ["exact_match", "contains"]})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["result_count"] == 2
        # item 1's mock output equals its expected → exact_match hits; item 2 misses
        assert d["scorer_means"]["exact_match"] == 0.5
        assert d["mean_score"] is not None

        # missing/empty dataset → 404
        assert c.post("/api/playground/experiment", json={
            "dataset_id": 999999, "provider": "mock", "model": "gpt-4o",
            "messages": [{"role": "user", "content": "{{input}}"}]}).status_code == 404


def test_llm_judge_mock_heuristic():
    def j(exp, out):
        return anyio.run(functools.partial(llm_client.judge, "mock", "m", "q", exp, out))
    assert j("cat", "the cat sat") == 1.0        # expected substring present
    assert j("cat", "a dog barks") == 0.0        # no overlap
    assert j("big cat", "a small cat") == 0.5    # partial word overlap


def test_llm_judge_real_provider_parses_number(monkeypatch):
    monkeypatch.setattr(llm_client.httpx, "AsyncClient", _FakeClient)
    _FakeClient.resp = _FakeResp(200, {"choices": [{"message": {"content": "0.8"},
                                       "finish_reason": "stop"}], "usage": {}})
    score = anyio.run(functools.partial(llm_client.judge, "openai", "gpt-4o",
                      "q", "expected", "answer", api_key="sk-k"))
    assert score == 0.8


def test_experiment_with_llm_judge():
    with TestClient(app, base_url="https://testserver") as c:
        conn = c.post("/api/connections", json={"provider": "mock", "label": "m"}).json()
        db = SessionLocal()
        ws_id = db.get(ProviderConnection, conn["id"]).workspace_id
        ds = Dataset(workspace_id=ws_id, name="judged")
        db.add(ds); db.commit(); db.refresh(ds)
        db.add_all([
            DatasetItem(workspace_id=ws_id, dataset_id=ds.id, input="ping", expected="[mock:gpt-4o] ping."),
            DatasetItem(workspace_id=ws_id, dataset_id=ds.id, input="x", expected="totally unrelated"),
        ])
        db.commit(); dsid = ds.id; db.close()
        r = c.post("/api/playground/experiment", json={
            "dataset_id": dsid, "provider": "mock", "model": "gpt-4o",
            "messages": [{"role": "user", "content": "{{input}}"}],
            "scorers": ["exact_match", "llm_judge"]})
        assert r.status_code == 200, r.text
        means = r.json()["scorer_means"]
        assert "llm_judge" in means and "exact_match" in means
        assert means["llm_judge"] == 0.5   # item1 matches (1.0), item2 unrelated (0.0)


def test_prompt_versioning():
    with TestClient(app, base_url="https://testserver") as c:
        body = {"name": "greeter", "model": "gpt-4o",
                "messages": [{"role": "user", "content": "hi {{name}}"}], "params": {"temperature": 0.5}}
        assert c.post("/api/prompts", json=body).json()["version"] == 1
        v2 = c.post("/api/prompts", json=body).json()
        assert v2["version"] == 2                       # same name → next version
        rows = c.get("/api/prompts").json()
        assert any(p["name"] == "greeter" and p["version"] == 2 for p in rows)
        assert c.delete(f"/api/prompts/{v2['id']}").json()["ok"] is True
        assert c.post("/api/prompts", json={"name": ""}).status_code == 422
