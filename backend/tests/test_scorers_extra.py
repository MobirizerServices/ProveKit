"""Trajectory, RAG and cost/latency scorers — the ones that grade a payload, not a string."""
import json

import pytest

from provekit import scorers


def _span(sid, parent="", start=0, **kw):
    """A span in the shape services/otel.py writes (start_ns is a *string* there)."""
    meta = {"start_ns": str(start)}
    return {"span_id": sid, "parent_span_id": parent, "type": kw.pop("type", "step"),
            "label": kw.pop("label", sid), "duration_ms": kw.pop("duration_ms", 0),
            "request": {"input": kw.pop("input", None)},
            "result": {"text": kw.pop("text", None), "meta": {**meta, **kw.pop("meta", {})}}}


def _tool(sid, name, args=None, parent="root", start=0, **kw):
    s = _span(sid, parent, start, type="tool", label=name, **kw)
    s["result"]["meta"]["tool"] = name
    s["request"]["input"] = args
    return s


# ---------------------------------------------------------------- trajectory shape

def test_trajectory_is_preorder_and_ignores_arrival_order():
    # Arrives child-before-parent and out of start order, which is what late spans look like.
    spans = [_span("b", "root", start=200), _span("a", "root", start=100),
             _span("a1", "a", start=150), _span("root", "", start=50)]
    assert [s["span_id"] for s in scorers.trajectory(spans)] == ["root", "a", "a1", "b"]


def test_trajectory_promotes_orphans_when_the_root_never_arrived():
    # roadmap #3/#4: the root is missing, so its children must still form a trajectory.
    spans = [_span("b", "missing", start=200), _span("a", "missing", start=100),
             _span("a1", "a", start=150)]
    assert [s["span_id"] for s in scorers.trajectory(spans)] == ["a", "a1", "b"]


def test_trajectory_survives_a_parent_cycle_without_losing_spans():
    spans = [_span("a", "b", start=10), _span("b", "a", start=20)]
    assert sorted(s["span_id"] for s in scorers.trajectory(spans)) == ["a", "b"]


def test_trajectory_accepts_both_payload_shapes_and_untimed_spans():
    listed = [{"span_id": "x"}, {"span_id": "y"}]
    assert scorers.trajectory(listed) == scorers.trajectory({"spans": listed})
    assert scorers.trajectory(json.dumps({"trace": listed})) == listed
    # A span with no time sorts after the timed ones rather than jumping to the front.
    mixed = [{"span_id": "n"}, _span("t", start=5)]
    assert [s["span_id"] for s in scorers.trajectory(mixed)] == ["t", "n"]


def test_trajectory_of_a_non_payload_is_empty():
    assert scorers.trajectory("just prose") == []
    assert scorers.trajectory(json.dumps({"answer": "hi"})) == []
    assert scorers.trajectory(json.dumps("a bare json string")) == []
    assert scorers.trajectory(42) == []
    assert scorers.trajectory({"spans": ["not a span"]}) == []


def test_trajectory_orders_by_whatever_time_the_capture_carried():
    # Numeric OTLP nanos, an ISO created_at, and an unparseable one that falls back to arrival.
    spans = [{"span_id": "c", "created_at": "nope"},
             {"span_id": "b", "created_at": "2026-07-22T10:00:01+00:00"},
             {"span_id": "a", "startTimeUnixNano": 1},
             {"span_id": "z", "created_at": ""}]
    assert [s["span_id"] for s in scorers.trajectory(spans)][:2] == ["a", "b"]


# ---------------------------------------------------------------- trajectory scorers

def _agent_run():
    return {"spans": [
        _span("root", "", start=1, type="agent"),
        _tool("t1", "search", args={"q": "capital of France"}, start=2),
        _span("l1", "root", start=3, type="llm"),
        _tool("t2", "summarize", args={"text": "…"}, start=4),
    ]}


def test_expected_tools_used():
    run = _agent_run()
    assert scorers.expected_tools_used(run, "search,summarize") == 1.0
    assert scorers.expected_tools_used(run, "search,translate") == 0.5
    assert scorers.expected_tools_used(run, json.dumps(["Search"])) == 1.0   # case-insensitive
    assert scorers.expected_tools_used(run, "") == 0.0                       # no config, no score
    assert scorers.expected_tools_used("plain text", "search") is None       # not applicable


def test_tool_order_grades_the_sequence():
    run = _agent_run()
    assert scorers.tool_order(run, "search,summarize") == 1.0
    assert scorers.tool_order(run, "summarize,search") == 0.5   # only one fits in order
    assert scorers.tool_order(run, "search,translate,summarize") == pytest.approx(2 / 3)
    assert scorers.tool_order(run, "") == 0.0
    assert scorers.tool_order("plain", "search") is None


def test_no_repeat_detects_a_loop_but_not_honest_reuse():
    loop = {"spans": [_tool(f"t{i}", "search", args={"q": "same"}, start=i) for i in range(5)]}
    assert scorers.no_repeat(loop) == 0.2
    varied = {"spans": [_tool(f"t{i}", "search", args={"q": i}, start=i) for i in range(5)]}
    assert scorers.no_repeat(varied) == 1.0
    assert scorers.no_repeat({"spans": [_span("root", start=1)]}) == 1.0   # no tool calls
    assert scorers.no_repeat("plain") is None


def test_no_repeat_normalises_argument_order():
    same = {"spans": [_tool("a", "get", args={"x": 1, "y": 2}, start=1),
                      _tool("b", "get", args={"y": 2, "x": 1}, start=2)]}
    assert scorers.no_repeat(same) == 0.5
    # request.input arrives as JSON *text* from ingest; it must compare equal to the dict form.
    as_text = {"spans": [_tool("a", "get", args=json.dumps({"x": 1}), start=1),
                         _tool("b", "get", args={"x": 1}, start=2)]}
    assert scorers.no_repeat(as_text) == 0.5


def test_step_budget_counts_work_not_the_agent_wrapper():
    run = _agent_run()                      # 1 agent span + 3 steps
    assert scorers.step_budget(run, "3") == 1.0
    assert scorers.step_budget(run, "6") == 1.0
    assert scorers.step_budget(run, 1.5) == 0.5       # twice the budget → half the score
    assert scorers.step_budget(run, "not a number") == 0.0
    assert scorers.step_budget(run, "0") == 0.0
    assert scorers.step_budget(run, True) == 0.0      # bool is an int; it is not a budget
    assert scorers.step_budget("plain", "3") is None


def test_tool_args_normalise_free_text_and_unserialisable_values():
    prose = {"spans": [_tool("a", "get", args="  find   me ", start=1),
                       _tool("b", "get", args="find me", start=2)]}
    assert scorers.no_repeat(prose) == 0.5          # whitespace isn't a different call
    odd = {"spans": [_tool("a", "get", args={(1, 2): "tuple key"}, start=1),
                     _tool("b", "get", args={"x": 1}, start=2)]}
    assert scorers.no_repeat(odd) == 1.0            # unserialisable args still compare, not crash


def test_one_config_object_configures_every_scorer_on_the_item():
    # run_scorers hands each scorer the SAME expected, so a bare "12" could only reach one.
    cfg = json.dumps({"tools": ["search", "summarize"], "max_steps": 3,
                      "max_cost_usd": 0.02, "max_latency_ms": 2000, "max_tokens": 500})
    run = dict(_agent_run(), cost_usd=0.01, latency_ms=1000, tokens=250)
    out = scorers.run_scorers(["expected_tools_used", "tool_order", "step_budget",
                               "cost_budget", "latency_budget", "token_budget"],
                              json.dumps(run), cfg)
    assert out == {"expected_tools_used": 1.0, "tool_order": 1.0, "step_budget": 1.0,
                   "cost_budget": 1.0, "latency_budget": 1.0, "token_budget": 1.0}
    # A separate order can be spelled out when it differs from the set of tools required.
    assert scorers.tool_order(_agent_run(), json.dumps({"tools": ["summarize"],
                                                        "tool_order": ["search", "summarize"]})) == 1.0
    assert scorers.expected_tools_used(_agent_run(), json.dumps({"tools": ["search"]})) == 1.0
    assert scorers.expected_tools_used(_agent_run(), json.dumps({"max_steps": 3})) == 0.0
    assert scorers.expected_tools_used(_agent_run(), json.dumps({"tools": "search,summarize"})) == 1.0
    assert scorers.expected_tools_used(_agent_run(), "12") == 0.0   # a number is not a tool list
    # Junk under the key configures nothing — it must not fall through to splitting the raw
    # JSON text on commas, which would invent tool names out of the config itself.
    assert scorers.expected_tools_used(_agent_run(), json.dumps({"tools": 12})) == 0.0


def test_tool_name_falls_back_to_the_label_of_a_tool_span():
    bare = {"spans": [{"span_id": "a", "type": "tool", "label": "search"}]}
    assert scorers.expected_tools_used(bare, "search") == 1.0
    assert scorers.expected_tools_used({"spans": [{"span_id": "a", "tool": "search"}]},
                                       "search") == 1.0


# ---------------------------------------------------------------- RAG scorers

_RAG = {"question": "Where is the Eiffel Tower located?",
        "answer": "The Eiffel Tower is located in Paris.",
        "context": ["The Eiffel Tower is located in Paris, France."]}


def test_faithfulness_lexical():
    assert scorers.faithfulness(_RAG) == 1.0
    invented = dict(_RAG, answer="The Eiffel Tower is in Paris. It was designed by Napoleon "
                                 "Bonaparte during the medieval siege of Vienna.")
    assert scorers.faithfulness(invented) == 0.5          # one of two sentences unsupported
    assert scorers.faithfulness({"answer": "x"}) is None  # no context → not applicable
    assert scorers.faithfulness(dict(_RAG, answer="")) == 0.0
    # An answer that asserts nothing can't be unfaithful.
    assert scorers.faithfulness(dict(_RAG, answer="It is what it is.")) == 1.0


def test_context_relevance_and_answer_relevance():
    assert scorers.context_relevance(_RAG) == 1.0
    noisy = dict(_RAG, context=_RAG["context"] + ["Sourdough needs a warm proof."])
    assert scorers.context_relevance(noisy) == 0.5
    assert scorers.context_relevance({"context": ["x"]}) is None    # no question
    assert scorers.answer_relevance(_RAG) > 0.5
    assert scorers.answer_relevance(dict(_RAG, answer="Bread proofs best at 24°C.")) < 0.5
    assert scorers.answer_relevance(dict(_RAG, answer="")) == 0.0
    assert scorers.answer_relevance({"answer": "hi"}) is None


def test_rag_scorers_read_a_captured_trace_with_no_extra_plumbing():
    trace = [_span("root", "", start=1, type="agent",
                   input="Where is the Eiffel Tower located?",
                   text="The Eiffel Tower is located in Paris."),
             _tool("t1", "vector_search", start=2,
                   text="The Eiffel Tower is located in Paris, France.")]
    assert scorers.faithfulness(trace) == 1.0
    assert scorers.context_relevance(trace) == 1.0
    assert scorers.answer_relevance(trace) > 0.5


def test_context_chunks_may_be_dicts_from_a_vector_store():
    payload = {"question": "Where is the Eiffel Tower?",
               "answer": "In Paris.",
               "context": [{"page_content": "The Eiffel Tower stands in Paris.", "score": 0.9}]}
    assert scorers.faithfulness(payload) == 1.0
    # A chunk with no text-ish field, and a non-string chunk, still count as evidence.
    odd = {"question": "Which tower?", "answer": "The id is tower-seven.",
           "context": [{"id": "tower-seven"}, 7]}
    assert scorers.faithfulness(odd) == 1.0


@pytest.fixture
def judge():
    """Install a fake model-graded backend and always remove it again."""
    def install(fn):
        scorers.set_judge(fn)
    yield install
    scorers.set_judge(None)


def test_judge_backend_takes_over_when_installed(judge):
    seen = []

    def grade(prompt):
        seen.append(prompt)
        return 0.25
    judge(grade)
    assert scorers.faithfulness(_RAG) == 0.25
    assert scorers.context_relevance(_RAG) == 0.25
    assert scorers.answer_relevance(_RAG) == 0.25
    assert len(seen) == 3 and "QUESTION" in seen[-1]


def test_a_judge_that_cannot_grade_degrades_to_the_lexical_estimate(judge):
    def no_key(prompt):
        raise RuntimeError("missing API key")
    judge(no_key)
    assert scorers.faithfulness(_RAG) == 1.0          # degraded, not a crashed eval run
    judge(lambda prompt: None)                        # judge available but declined to grade
    assert scorers.answer_relevance(_RAG) > 0.5
    judge(lambda prompt: "3.0")                       # out of range → clamped, not trusted raw
    assert scorers.faithfulness(_RAG) == 1.0


# ---------------------------------------------------------------- cost & latency axes

def test_cost_budget_from_an_explicit_total_or_per_span():
    assert scorers.cost_budget({"answer": "x", "cost_usd": 0.01}, "0.02") == 1.0
    assert scorers.cost_budget({"answer": "x", "cost_usd": 0.08}, "0.02") == 0.25   # 4x = 0.25
    per_span = {"spans": [_span("a", start=1, meta={"cost_usd": 0.004}),
                          _span("b", start=2, meta={"cost_usd": 0.006})]}
    assert scorers.cost_budget(per_span, "0.01") == 1.0
    assert scorers.cost_budget({"answer": "x", "cost_usd": 0.0}, "0.01") == 1.0     # free ≠ absent
    assert scorers.cost_budget({"answer": "x"}, "0.01") is None                     # nothing priced
    assert scorers.cost_budget({"cost_usd": 0.01}, "nonsense") == 0.0


def test_latency_budget_uses_the_root_span_and_sums_a_partial_tree():
    whole = {"spans": [_span("root", "", start=1, duration_ms=1800),
                       _span("a", "root", start=2, duration_ms=1700)]}
    assert scorers.latency_budget(whole, "2000") == 1.0
    assert scorers.latency_budget(whole, "900") == 0.5
    orphans = {"spans": [_span("a", "gone", start=1, duration_ms=300),
                         _span("b", "gone", start=2, duration_ms=300)]}
    assert scorers.latency_budget(orphans, "600") == 1.0
    assert scorers.latency_budget({"latency_ms": 100}, "200") == 1.0
    assert scorers.latency_budget("plain", "200") is None


def test_token_budget_reads_captured_usage():
    run = {"spans": [_span("a", start=1, meta={"usage": {"input_tokens": 100, "output_tokens": 50}}),
                     _span("b", start=2, meta={"usage": {"input_tokens": 40}})]}
    assert scorers.token_budget(run, "200") == 1.0
    assert scorers.token_budget(run, "95") == 0.5
    assert scorers.token_budget({"tokens": 10}, "20") == 1.0
    assert scorers.token_budget({"spans": [_span("a", start=1)]}, "10") is None


# ---------------------------------------------------------------- registry wiring

def test_new_scorers_resolve_by_name_through_the_registry():
    run = dict(_agent_run(), **_RAG, cost_usd=0.001, latency_ms=100)
    out = scorers.run_scorers(
        ["expected_tools_used", "tool_order", "no_repeat", "step_budget",
         "faithfulness", "context_relevance", "answer_relevance",
         "cost_budget", "latency_budget"], json.dumps(run), "search,summarize")
    assert out["expected_tools_used"] == 1.0 and out["tool_order"] == 1.0
    assert out["no_repeat"] == 1.0
    assert out["step_budget"] == 0.0          # "search,summarize" is not a step budget
    assert out["faithfulness"] == 1.0
    assert 0.0 <= out["cost_budget"] <= 1.0 and out["latency_budget"] == 0.0


def test_run_scorers_omits_a_scorer_that_cannot_grade_the_row():
    out = scorers.run_scorers(["exact_match", "no_repeat"], "Paris", "Paris")
    assert out == {"exact_match": 1.0}        # not 0.0 for the one that had nothing to grade
    assert scorers.run_scorers(["cost_budget"], "Paris", "0.01") == {}

    def skip(output, expected):
        return None
    assert scorers.run_scorers([skip], "a", "b") == {}
