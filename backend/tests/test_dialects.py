"""Dialect conformance: one golden OTLP span per instrumentor family per attribute dialect.

ProveKit claims to ingest traces from ANY framework, which means services/otel.py::map_span is
the widest-contract function in the backend — ~20 instrumentors, three attribute dialects, and
a single classification ladder deciding what the reviewer sees. Every genericness bug we have
shipped (#177–#182) was a span that mapped wrong, and each was invisible to a suite that only
tested the shape our own SDK emits. So the mapping is pinned here against realistic payloads
instead of hand-made ones.

Adding an instrumentor? Copy the closest file in `tests/fixtures/otlp/` and edit it. Each is a
standalone JSON document:

    {
      "instrumentor": "openai",       # module tail from trace.py's instrumentor lists
      "dialect": "genai_current",     # genai_current | genai_legacy | openinference | http
      "note": "why this payload looks like this",
      "span": { ...one OTLP span exactly as the exporter sends it... },
      "expect": {"type": "llm", "result.meta.usage.input_tokens": 41, ...},
      "expect_absent": ["result.meta.tool"]
    }

`expect` keys are dotted paths into the Run kwargs map_span returns, and every one becomes its
own test case — a failure names the exact field that moved. A list/dict expectation is compared
against the PARSED stored string, so fixtures stay readable and stay independent of json.dumps
spacing. `expect_absent` asserts a conditionally-set field was NOT written.

`fixtures/otlp/known_gaps/` holds payloads ProveKit maps WRONG today. They assert the mapping we
want and are marked xfail, with the damage described in the fixture's "gap" field: they document
the bug where a reader will meet it, and go green by themselves once map_span learns the key.
"""
import functools
import json
from pathlib import Path

import pytest

from provekit import trace as trace_sdk
from provekit.services import otel

FIXTURES = Path(__file__).parent / "fixtures" / "otlp"
CONFORMANCE = sorted(FIXTURES.glob("*.json"))
KNOWN_GAPS = sorted((FIXTURES / "known_gaps").glob("*.json"))

#: Instrumentor families that MUST stay covered — the LLM providers and agent frameworks users
#: actually arrive with, plus the generic HTTP instrumentors (a tool call is a span too).
REQUIRED_FAMILIES = {"openai", "anthropic", "bedrock", "langchain", "llama_index", "crewai",
                     "httpx", "requests", "urllib"}
#: The three GenAI attribute dialects map_span accepts. "http" is not a GenAI dialect — it is
#: the no-gen_ai.* case, which must still produce a usable step.
GENAI_DIALECTS = {"genai_current", "genai_legacy", "openinference"}

#: Fields map_span writes only under a condition. `expect_absent` may name these and nothing
#: else, so a typo'd path can't silently "pass" by being absent from every run.
OPTIONAL_FIELDS = {
    "result.meta.tool", "result.meta.session_id", "result.meta.finish_reason",
    "result.meta.truncation", "result.meta.events", "result.meta.params",
    "result.meta.params.temperature", "result.meta.params.top_p", "result.meta.params.max_tokens",
    "result.meta.usage.input_tokens", "result.meta.usage.output_tokens",
}

_MISSING = object()


def _families() -> set[str]:
    """Instrumentor families ProveKit installs, as the module tail (…instrumentation.openai)."""
    mods = [m for m, _ in trace_sdk._INSTRUMENTORS + trace_sdk._HTTP_INSTRUMENTORS]
    return {m.rsplit(".", 1)[-1] for m in mods}


@functools.lru_cache(maxsize=None)
def _fixture(path: str) -> tuple[dict, dict]:
    """(fixture, mapped run). Cached: every expectation is its own test case, and re-mapping
    the same span once per assertion would be the bulk of this module's runtime."""
    fx = json.loads(Path(path).read_text())
    return fx, otel.map_span(fx["span"])


def _dig(run: dict, path: str):
    node = run
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return _MISSING
        node = node[part]
    return node


def _matches(expected, actual) -> bool:
    """map_span stores payloads as text; a list/dict expectation is compared against the parsed
    value so a fixture can show the message array a contributor would recognize."""
    if isinstance(expected, (list, dict)) and isinstance(actual, str):
        try:
            return json.loads(actual) == expected
        except ValueError:
            return False
    return expected == actual


def _expected(paths: list[Path]):
    """One parametrize case per expectation, so a break names the field, not the fixture."""
    for p in paths:
        for path, value in json.loads(p.read_text())["expect"].items():
            yield pytest.param(str(p), path, value, id=f"{p.stem}::{path}")


def _absent(paths: list[Path]):
    for p in paths:
        for path in json.loads(p.read_text()).get("expect_absent", []):
            yield pytest.param(str(p), path, id=f"{p.stem}::{path}")


# ---- the corpus ----
@pytest.mark.parametrize("fixture,path,expected", list(_expected(CONFORMANCE)))
def test_mapping(fixture, path, expected):
    _, run = _fixture(fixture)
    actual = _dig(run, path)
    assert actual is not _MISSING, f"{path} is not in the mapped run at all"
    assert _matches(expected, actual), f"{path}: expected {expected!r}, got {actual!r}"


@pytest.mark.parametrize("fixture,path", list(_absent(CONFORMANCE)))
def test_absent(fixture, path):
    _, run = _fixture(fixture)
    assert path in OPTIONAL_FIELDS, f"{path} is not a conditionally-written field"
    assert _dig(run, path) is _MISSING, f"{path} should not have been written"


@pytest.mark.xfail(reason="known map_span gap — see the fixture's 'gap' field", strict=False)
@pytest.mark.parametrize("fixture,path,expected", list(_expected(KNOWN_GAPS)))
def test_known_gap(fixture, path, expected):
    """The mapping we WANT for a payload ProveKit gets wrong today. Non-strict xfail on purpose:
    the day map_span learns the key this xpasses instead of turning the suite red."""
    _, run = _fixture(fixture)
    assert _matches(expected, _dig(run, path))


# ---- the corpus itself ----
@pytest.mark.parametrize("fixture", [pytest.param(str(p), id=p.stem)
                                     for p in CONFORMANCE + KNOWN_GAPS])
def test_fixture_is_wellformed(fixture):
    fx, _ = _fixture(fixture)
    assert fx["instrumentor"] in _families(), "unknown instrumentor family"
    assert fx["dialect"] in GENAI_DIALECTS | {"http"}
    assert fx["note"] and fx["expect"], "a fixture with no expectation asserts nothing"
    span = fx["span"]
    # Real ids, real timestamps: a mapping asserted against a toy span proves nothing about the
    # tree the portal rebuilds (and the columns are String(32)/String(16)).
    assert len(span["traceId"]) == 32 and len(span["spanId"]) == 16
    assert int(span["endTimeUnixNano"]) > int(span["startTimeUnixNano"])
    if "known_gaps" not in fixture:
        # The end-to-end test reads it back by type; a gap fixture asserts only the field it is
        # about, since the rest of its mapping is whatever today's map_span does with it.
        assert fx["expect"]["type"] in ("agent", "llm", "tool", "step")
    else:
        assert fx["gap"], "a known-gap fixture must say what breaks for the reader"


def test_span_ids_are_unique_across_the_corpus():
    """Ingest dedupes on (trace_id, span_id), so a copy-pasted id would make the end-to-end
    test below silently assert on one row twice."""
    ids = [json.loads(p.read_text())["span"]["spanId"] for p in CONFORMANCE + KNOWN_GAPS]
    assert len(ids) == len(set(ids))


def test_required_instrumentor_families_are_covered():
    covered = {json.loads(p.read_text())["instrumentor"] for p in CONFORMANCE + KNOWN_GAPS}
    assert REQUIRED_FAMILIES - covered == set()


@pytest.mark.parametrize("family", ["openai", "anthropic", "bedrock"])
def test_each_provider_family_covers_every_genai_dialect(family):
    """The same provider emits all three dialects depending on which instrumentor is installed,
    and that is exactly where the mapping drifts — so each must be pinned in all three."""
    docs = [json.loads(p.read_text()) for p in CONFORMANCE]
    got = {d["dialect"] for d in docs if d["instrumentor"] == family}
    assert GENAI_DIALECTS - got == set()


# ---- the classification ladder ----
def _span(attrs: dict, name="span", start=1_000_000_000, end=1_500_000_000):
    return {"name": name, "traceId": "e" * 32, "spanId": "f" * 16,
            "startTimeUnixNano": str(start), "endTimeUnixNano": str(end), "status": {"code": 1},
            "attributes": [{"key": k, "value": {"stringValue": str(v)}} for k, v in attrs.items()]}


def test_tool_name_outranks_every_other_rung():
    """A tool call made by an agent carries the agent's operation and the model that chose it.
    It is still a tool span — the top rung — or the tool timeline loses the call."""
    run = otel.map_span(_span({"gen_ai.tool.name": "search",
                               "gen_ai.operation.name": "invoke_agent",
                               "gen_ai.request.model": "gpt-4o"}))
    assert run["type"] == "tool" and run["result"]["meta"]["tool"] == "search"


def test_invoke_agent_outranks_a_model():
    run = otel.map_span(_span({"gen_ai.operation.name": "invoke_agent",
                               "gen_ai.request.model": "gpt-4o"}))
    assert run["type"] == "agent" and run["request"]["operation"] == "invoke_agent"


@pytest.mark.parametrize("attrs", [{"gen_ai.request.model": "gpt-4o"},
                                   {"gen_ai.provider.name": "openai"},
                                   {"llm.model_name": "gpt-4o"},
                                   {"llm.provider": "openai"}])
def test_model_or_provider_alone_is_a_model_call(attrs):
    assert otel.map_span(_span(attrs))["type"] == "llm"


def test_a_span_with_only_genai_io_is_not_a_model_call():
    """gen_ai.input.messages on a chain/guardrail span does not make it an LLM run — counting
    it as one would inflate the model-call count and the cost estimate."""
    run = otel.map_span(_span({"gen_ai.input.messages": "hi"}, name="Guardrail.validate"))
    assert run["type"] == "step" and run["label"] == "Guardrail.validate"


def test_step_prefers_the_operation_name_over_the_span_name():
    run = otel.map_span(_span({"gen_ai.operation.name": "create_agent"}, name="Agent.__init__"))
    assert run["type"] == "step" and run["request"]["operation"] == "create_agent"
    assert run["label"] == "Agent.__init__"   # no model, so the span name still labels the row


def test_an_attribute_redacted_to_empty_falls_through_to_the_next_alias():
    """Redaction and some instrumentors write "" rather than dropping the key. An empty string
    must not win the alias race, or a span with a perfectly good fallback maps to no model."""
    span = _span({"gen_ai.request.model": "", "llm.model_name": "gpt-4o", "gen_ai.system": ""})
    run = otel.map_span(span)
    assert run["request"]["model"] == "gpt-4o"
    assert run["type"] == "llm"


# ---- alias precedence, one case per key list in map_span ----
_ALIASES = {
    "model": (["gen_ai.request.model", "gen_ai.response.model", "llm.model_name", "gen_ai.model"],
              lambda r: r["request"]["model"]),
    "provider": (["gen_ai.provider.name", "gen_ai.system", "llm.provider"],
                 lambda r: r["request"]["provider"]),
    "session": (["session.id", "gen_ai.conversation.id", "thread.id", "session_id"],
                lambda r: r["session_id"]),
    "input_tokens": (["gen_ai.usage.input_tokens", "gen_ai.usage.prompt_tokens",
                      "llm.token_count.prompt"],
                     lambda r: r["result"]["meta"]["usage"]["input_tokens"]),
    "output_tokens": (["gen_ai.usage.output_tokens", "gen_ai.usage.completion_tokens",
                       "llm.token_count.completion"],
                      lambda r: r["result"]["meta"]["usage"]["output_tokens"]),
    "prompt": (["gen_ai.input.messages", "gen_ai.prompt", "input.value", "llm.input_messages",
                "input"],
               lambda r: r["request"]["input"]),
    "completion": (["gen_ai.output.messages", "gen_ai.completion", "output.value",
                    "llm.output_messages", "output"],
                   lambda r: r["result"]["text"]),
    "finish_reason": (["gen_ai.response.finish_reasons", "gen_ai.response.finish_reason",
                       "llm.response.finish_reason"],
                      lambda r: r["result"]["meta"]["finish_reason"]),
}


@pytest.mark.parametrize("field,index", [(f, i) for f, (keys, _) in _ALIASES.items()
                                         for i in range(len(keys))])
def test_alias_precedence(field, index):
    """For each key list: the alias at `index` wins when every earlier alias is absent, and each
    alias works on its own. Instrumentors mix dialects on one span (OpenInference emits llm.* and
    session.id; a proxy adds gen_ai.*), so the ORDER is load-bearing, not just the membership."""
    keys, read = _ALIASES[field]
    attrs = {k: f"v{i}" for i, k in enumerate(keys[index:], start=index)}
    if field != "model":
        attrs.setdefault("gen_ai.request.model", "m")   # keep the span an llm span
    run = otel.map_span(_span(attrs))
    assert read(run) == f"v{index}"


# ---- end to end ----
def test_every_fixture_persists_through_the_ingest_endpoint():
    """map_span is only half the contract: the corpus must also survive the router, redaction
    and the spool, and come back out of the database as the type it was classified as."""
    from fastapi.testclient import TestClient

    from provekit.database import SessionLocal
    from provekit.main import app
    from provekit.models import Run

    fixtures = [json.loads(p.read_text()) for p in CONFORMANCE]
    batch = {"resourceSpans": [{"scopeSpans": [{"spans": [f["span"] for f in fixtures]}]}]}
    with TestClient(app) as client:
        assert client.post("/v1/traces", json=batch).status_code == 200
    db = SessionLocal()
    try:
        for fx in fixtures:
            row = db.query(Run).filter(Run.span_id == fx["span"]["spanId"]).one()
            assert row.type == fx["expect"]["type"], fx["span"]["name"]
            assert row.trace_id == fx["span"]["traceId"]
            assert row.status == fx["expect"].get("status", row.status)
    finally:
        db.close()
