"""pk.evaluate(): pulls a dataset, runs the target, scores each output, posts an experiment,
and returns its summary. The portal HTTP calls are stubbed (no network)."""
import httpx
import pytest

pytest.importorskip("opentelemetry.sdk.trace")  # evaluate calls configure(), needs [trace]

from provekit import evaluate  # noqa: E402
import provekit.trace as pk  # noqa: E402


class _Resp:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


def test_evaluate_scores_and_returns_summary(monkeypatch):
    pk._configured = False
    pk._tracer = None
    monkeypatch.setenv("PROVEKIT_API_KEY", "pk_x")
    monkeypatch.setenv("PROVEKIT_ENDPOINT", "http://portal.test")
    posts = []

    def fake_get(url, headers=None, timeout=None, follow_redirects=None):
        if url.endswith("/v1/datasets"):
            return _Resp([{"id": 7, "name": "qa"}])
        if url.endswith("/v1/datasets/7/items"):
            return _Resp([{"id": 1, "input": "2+2", "expected": "4"},
                          {"id": 2, "input": "cap", "expected": "Paris"}])
        return _Resp({"id": 99, "result_count": 2, "scorer_means": {"exact_match": 0.5}, "mean_score": 0.5})

    def fake_post(url, headers=None, json=None, timeout=None, follow_redirects=None):
        posts.append({"url": url, "json": json})
        return _Resp({"id": 99}) if url.endswith("/v1/experiments") else _Resp({"id": 1})

    monkeypatch.setattr(httpx, "get", fake_get)
    monkeypatch.setattr(httpx, "post", fake_post)

    def target(q):
        return "4" if q == "2+2" else "Lyon"   # right on item 1, wrong on item 2

    summary = evaluate("qa", target, scorers=["exact_match"], name="ci")
    assert summary["mean_score"] == 0.5

    results = [p for p in posts if p["url"].endswith("/results")]
    assert len(results) == 2
    assert results[0]["json"]["scores"]["exact_match"] == 1.0
    assert results[1]["json"]["scores"]["exact_match"] == 0.0


def test_evaluate_raises_when_unconfigured(monkeypatch):
    pk._configured = False
    pk._tracer = None
    monkeypatch.delenv("PROVEKIT_API_KEY", raising=False)
    monkeypatch.delenv("PROVEKIT_ENDPOINT", raising=False)
    with pytest.raises(RuntimeError):
        evaluate("qa", lambda q: "x", scorers=["exact_match"])


def test_evaluate_unknown_dataset_raises(monkeypatch):
    pk._configured = False
    pk._tracer = None
    monkeypatch.setenv("PROVEKIT_API_KEY", "pk_x")
    monkeypatch.setenv("PROVEKIT_ENDPOINT", "http://portal.test")
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _Resp([]))
    with pytest.raises(ValueError):
        evaluate("missing", lambda q: "x", scorers=["exact_match"])
