"""Pure scorers + the run_scorers registry."""
from provekit import scorers


def test_exact_and_contains():
    assert scorers.exact_match(" Paris ", "Paris") == 1.0
    assert scorers.exact_match("London", "Paris") == 0.0
    assert scorers.contains("The capital is Paris.", "paris") == 1.0
    assert scorers.contains("nope", "paris") == 0.0


def test_regex_and_json():
    assert scorers.regex_match("order #12345", r"#\d+") == 1.0
    assert scorers.regex_match("no number", r"#\d+") == 0.0
    assert scorers.regex_match("x", "(") == 0.0          # invalid pattern → 0, not a crash
    assert scorers.json_valid('{"a": 1}') == 1.0
    assert scorers.json_valid("not json") == 0.0


def test_run_scorers_by_name_and_callable():
    def half(output, expected):
        return 0.5
    out = scorers.run_scorers(["exact_match", "unknown_name", half], "Paris", "Paris")
    assert out["exact_match"] == 1.0
    assert out["half"] == 0.5
    assert "unknown_name" not in out


def test_run_scorers_swallows_exceptions():
    def boom(output, expected):
        raise ValueError("x")
    assert scorers.run_scorers([boom], "a", "b")["boom"] == 0.0
