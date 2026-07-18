"""Usage aggregation: normalizes provider usage shapes; totals + per-model breakdown."""
from fastapi.testclient import TestClient

from provekit.main import app


def test_usage_aggregates_tokens(monkeypatch):
    with TestClient(app) as c:
        mock = next(x for x in c.get("/api/connections").json() if x["config"].get("provider") == "mock")["id"]
        # run a few mock prompts (the mock reports prompt/completion tokens)
        for i in range(3):
            c.post("/api/run", json={"request": {"type": "prompt", "connection_id": mock,
                    "model": "demo-mock", "user": f"hello {i}"}, "save": True})
        u = c.get("/api/usage?days=30").json()
        assert u["runs"] >= 3
        assert u["tokens_total"] == u["tokens_in"] + u["tokens_out"]
        assert u["tokens_out"] > 0  # mock produced completion tokens
        models = [m["model"] for m in u["by_model"]]
        assert "demo-mock" in models


def test_usage_normalizes_anthropic_shape():
    from provekit.routers.usage import _tokens
    assert _tokens({"input_tokens": 5, "output_tokens": 2}) == (5, 2)
    assert _tokens({"prompt_tokens": 7, "completion_tokens": 3}) == (7, 3)
    assert _tokens({}) == (0, 0)
    assert _tokens(None) == (0, 0)
