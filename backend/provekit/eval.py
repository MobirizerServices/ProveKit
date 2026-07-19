"""Offline evaluation from the client: run a target over a dataset, score each output, and
record it as an experiment in your portal — the basis of a CI regression gate.

    import provekit as pk

    def target(question: str) -> str:
        return my_agent(question)

    summary = pk.evaluate("qa-golden", target, scorers=["exact_match", "contains"])
    assert summary["mean_score"] >= 0.8       # fail the build on a regression

`scorers` are names from provekit.scorers (exact_match/contains/regex_match/json_valid) or
your own `fn(output, expected) -> float`. The dataset is a name or id from your portal.
"""
from __future__ import annotations

import json

import httpx

from . import scorers as _scorers
from . import trace as _trace

_TIMEOUT = 60


def _get(endpoint, headers, path):
    r = httpx.get(f"{endpoint}{path}", headers=headers, timeout=_TIMEOUT, follow_redirects=False)
    r.raise_for_status()
    return r.json()


def _post(endpoint, headers, path, body):
    r = httpx.post(f"{endpoint}{path}", headers=headers, json=body, timeout=_TIMEOUT, follow_redirects=False)
    r.raise_for_status()
    return r.json()


def _resolve_dataset_id(endpoint, headers, dataset) -> int:
    if isinstance(dataset, int):
        return dataset
    for d in _get(endpoint, headers, "/v1/datasets"):
        if d.get("name") == dataset:
            return d["id"]
    raise ValueError(f"dataset {dataset!r} not found")


def evaluate(dataset, target, scorers, *, name: str = "experiment") -> dict:
    """Run `target(input)` over every item in `dataset`, score each output with `scorers`,
    post the results as a new experiment, and return its summary (id, result_count,
    scorer_means, mean_score). Raises if ProveKit isn't configured."""
    if not _trace.configure():
        raise RuntimeError("ProveKit not configured: set PROVEKIT_API_KEY and PROVEKIT_ENDPOINT")
    endpoint, headers = _trace._endpoint, {"Authorization": f"Bearer {_trace._api_key}"}

    dsid = _resolve_dataset_id(endpoint, headers, dataset)
    items = _get(endpoint, headers, f"/v1/datasets/{dsid}/items")
    exp = _post(endpoint, headers, "/v1/experiments", {"name": name, "dataset_id": dsid})
    eid = exp["id"]

    for it in items:
        try:
            output = target(it["input"])
        except Exception as exc:   # a target failure is a data point, not a crash
            output = f"ERROR: {exc}"
        if not isinstance(output, str):
            output = json.dumps(output, default=str)
        expected = it.get("expected", "")
        scores = _scorers.run_scorers(scorers, output, expected)
        _post(endpoint, headers, f"/v1/experiments/{eid}/results",
              {"item_id": it.get("id"), "input": it["input"], "output": output,
               "expected": expected, "scores": scores})

    return _get(endpoint, headers, f"/v1/experiments/{eid}")
