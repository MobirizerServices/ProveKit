"""The evaluator catalog endpoint — surfaces the scorer registry for the portal."""
from fastapi.testclient import TestClient

from provekit.main import app
from provekit.scorers import SCORERS


def test_lists_every_registered_scorer_with_a_category_and_description():
    c = TestClient(app, base_url="https://testserver")
    rows = c.get("/api/evaluators").json()
    assert {r["name"] for r in rows} == set(SCORERS), "every scorer is surfaced, none omitted"
    for r in rows:
        assert r["category"], r["name"]
        assert r["description"], r["name"]


def test_known_scorers_land_in_their_category():
    c = TestClient(app, base_url="https://testserver")
    by = {r["name"]: r["category"] for r in c.get("/api/evaluators").json()}
    assert by["exact_match"] == "Correctness"
    assert by["tool_order"] == "Trajectory"
    assert by["faithfulness"] == "RAG"
    assert by["cost_budget"] == "Budgets"
