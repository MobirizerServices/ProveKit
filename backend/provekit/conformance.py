"""What ProveKit maps from the OpenTelemetry GenAI semantic conventions (#89).

An OTel-native tool should be able to say precisely which attributes it understands, which it
ignores, and which it knows it is missing — otherwise "OpenTelemetry-compatible" is a claim
nobody can check, and the first attribute that quietly stops being read looks like a data bug.

**Why the matrix is declared here and verified by a test.** Deriving it by scanning the mapper
at runtime would be fragile (a regex over source), and hard-coding it without a check would let
it drift the moment someone renames a key. So the list below is the *claim*, and
`test_conformance.py` asserts every attribute claimed as mapped actually appears in
`services/otel.py`. A claim that stops being true fails the suite rather than misleading a
reader.

**What this is not.** It does not pin an upstream semconv release: the conventions are versioned
upstream and tracking a specific release — and contributing the mapping back — needs the actual
published spec, which this module cannot verify on its own. Both remain open, and are named as
gaps rather than implied to be done.
"""
from __future__ import annotations

#: Attributes ProveKit reads, grouped by the dialect that emits them.
#:
#: `status` is deliberately only ever "mapped": an attribute that isn't read has no business
#: being listed as though it were. Things we do *not* map are in GAPS below, with the reason.
MAPPED: dict[str, list[tuple[str, str]]] = {
    # The OTel GenAI conventions proper.
    "gen_ai": [
        ("gen_ai.operation.name", "span kind (agent / llm / tool)"),
        ("gen_ai.system", "provider name (legacy key)"),
        ("gen_ai.provider.name", "provider name (current key)"),
        ("gen_ai.request.model", "model requested"),
        ("gen_ai.response.model", "model that answered"),
        ("gen_ai.model", "model (shorthand some exporters emit)"),
        ("gen_ai.request.temperature", "sampling params"),
        ("gen_ai.request.top_p", "sampling params"),
        ("gen_ai.request.max_tokens", "sampling params"),
        ("gen_ai.input.messages", "prompt / conversation in"),
        ("gen_ai.output.messages", "completion out"),
        ("gen_ai.prompt", "prompt (legacy key)"),
        ("gen_ai.completion", "completion (legacy key)"),
        ("gen_ai.usage.input_tokens", "token usage, priced"),
        ("gen_ai.usage.output_tokens", "token usage, priced"),
        ("gen_ai.usage.prompt_tokens", "token usage (legacy key)"),
        ("gen_ai.usage.completion_tokens", "token usage (legacy key)"),
        ("gen_ai.response.finish_reason", "finish reason"),
        ("gen_ai.response.finish_reasons", "finish reason (plural form)"),
        ("gen_ai.tool.name", "tool span identity"),
        ("gen_ai.tool.call.arguments", "tool input"),
        ("gen_ai.tool.call.result", "tool output"),
        ("gen_ai.conversation.id", "session grouping"),
    ],
    # OpenInference — what Arize's instrumentors emit. Not an OTel convention, but the most
    # common thing actually on the wire, so mapping it is what makes "point your exporter here"
    # true rather than aspirational.
    "openinference": [
        ("openinference.span.kind", "span kind"),
        ("llm.model_name", "model"),
        ("llm.provider", "provider"),
        ("llm.input_messages", "prompt"),
        ("llm.output_messages", "completion"),
        ("llm.token_count.prompt", "token usage"),
        ("llm.token_count.completion", "token usage"),
        ("llm.finish_reason", "finish reason"),
        ("llm.response.finish_reason", "finish reason (alternate key)"),
        ("input.value", "generic span input"),
        ("output.value", "generic span output"),
    ],
}

#: Known gaps, stated rather than left to be discovered. Each says *why*, because "not mapped"
#: and "deliberately not mapped" are different answers to a reader deciding whether to trust it.
GAPS: list[tuple[str, str]] = [
    ("gen_ai.request.top_k",
     "not read — no surface prices or displays it, so storing it would be dead weight"),
    ("gen_ai.request.stop_sequences",
     "not read — same reason; replay sends its own params"),
    ("gen_ai.agent.name / gen_ai.agent.id",
     "not read — ProveKit derives agent identity from the span tree, not a label"),
    ("gen_ai.embeddings.*",
     "not mapped — embedding spans are captured as generic spans with no token pricing"),
    ("upstream semconv release pinning",
     "the matrix above is derived from this codebase, not from a published semconv version; "
     "tracking a specific release needs the spec itself"),
    ("contributing the mapping upstream",
     "not done — needs a PR against open-telemetry/semantic-conventions"),
]


def report() -> dict:
    """The conformance matrix, for `GET /api/coverage/otel` and the docs."""
    return {
        "mapped": {dialect: [{"attribute": a, "maps_to": why} for a, why in rows]
                   for dialect, rows in MAPPED.items()},
        "mapped_count": sum(len(v) for v in MAPPED.values()),
        "gaps": [{"item": a, "why": why} for a, why in GAPS],
        "note": ("Derived from this codebase and verified against services/otel.py by "
                 "tests/test_conformance.py. Not pinned to a published semconv release — see gaps."),
    }


def attributes() -> list[str]:
    return [a for rows in MAPPED.values() for a, _why in rows]
