"""The OTel conformance matrix must not be able to lie (#89).

`provekit/conformance.py` is a *claim* about which semantic-convention attributes ProveKit
understands. A claim nobody checks is worse than no claim: the first attribute that quietly
stops being read looks like a data bug, and "OpenTelemetry-compatible" becomes unfalsifiable.
So every attribute listed as mapped has to actually appear in the mapper.
"""
import pathlib

from fastapi.testclient import TestClient

from provekit import conformance, doctor
from provekit.main import app

_OTEL_SRC = (pathlib.Path(__file__).resolve().parents[1]
             / "provekit" / "services" / "otel.py").read_text()


def test_every_claimed_attribute_is_actually_read_by_the_mapper():
    missing = [a for a in conformance.attributes() if f'"{a}"' not in _OTEL_SRC]
    assert not missing, (
        f"conformance.py claims these are mapped but services/otel.py never reads them: {missing}")


def test_the_matrix_does_not_silently_shrink():
    """A guard on the guard: if the mapper grows a dialect the matrix ignores, someone should
    notice. Counted rather than enumerated so it fails loudly without being brittle."""
    assert conformance.report()["mapped_count"] >= 30
    assert set(conformance.MAPPED) >= {"gen_ai", "openinference"}


def test_gaps_are_stated_with_a_reason():
    """"Not mapped" and "deliberately not mapped" are different answers to a reader deciding
    whether to trust this."""
    for item, why in conformance.GAPS:
        assert why.strip(), f"gap {item!r} has no reason"
        assert len(why.split()) >= 4, f"gap {item!r} is too terse to be useful: {why!r}"
    # The two halves this item genuinely has not done are named rather than implied.
    text = " ".join(f"{i} {w}" for i, w in conformance.GAPS).lower()
    assert "semconv" in text, "the unpinned spec version must be stated as a gap"
    assert "upstream" in text, "contributing the mapping upstream must be stated as a gap"


def test_the_endpoint_serves_the_matrix():
    with TestClient(app) as c:
        body = c.get("/api/coverage/otel").json()
    assert body["mapped_count"] == conformance.report()["mapped_count"]
    assert body["gaps"] and "gen_ai" in body["mapped"]
    # It says where the numbers come from, so a reader isn't left to assume a spec version.
    assert "not pinned" in body["note"].lower()


# ---- instrumentation catalogue (the drift that already happened once) ----

def test_the_catalogue_is_derived_from_the_runtime_not_copied():
    """doctor._COVERAGE was a hand-written second copy and it drifted: the runtime
    instrumented 24 libraries while the catalogue advertised 10, so the product under-reported
    itself by more than half and nothing caught it. A catalogue that can disagree with the code
    it describes is worse than none, because it gets quoted in comparisons and believed."""
    from provekit import trace

    runtime = {lib for lib, _m, _c, _e in (*trace._INSTRUMENTORS, *trace._HTTP_INSTRUMENTORS)}
    published = {r["library"] for r in doctor.coverage_catalog()}
    assert published == runtime, f"catalogue and runtime disagree: {published ^ runtime}"


def test_every_instrumentor_row_is_well_formed():
    """A malformed row is a library that silently never instruments."""
    from provekit import trace

    for lib, module, cls, extra in (*trace._INSTRUMENTORS, *trace._HTTP_INSTRUMENTORS):
        assert lib and module and cls and extra
        assert module.startswith(("openinference.instrumentation.", "opentelemetry.instrumentation."))
        assert cls.endswith("Instrumentor"), f"{lib}: {cls} breaks the naming convention"
        assert extra.startswith("provekit["), f"{lib}: {extra} is not an installable extra"


def test_every_named_extra_actually_exists_in_pyproject():
    """The catalogue tells a user which extra to install. If that extra isn't defined, the
    instruction is a dead end."""
    import re
    src = (pathlib.Path(__file__).resolve().parents[1] / "pyproject.toml").read_text()
    defined = set(re.findall(r'(?m)^([a-z-]+) = \[', src))
    named = {r["extra"].removeprefix("provekit[").removesuffix("]")
             for r in doctor.coverage_catalog()}
    assert named <= defined, f"catalogue names undefined extras: {named - defined}"


def test_a_renamed_instrumentor_class_still_resolves():
    """Upstream renames are the quiet failure: the library stays installed, the catalogue keeps
    advertising it, and spans just stop appearing. The loader falls back to the module's single
    *Instrumentor class rather than skipping."""
    import types

    from provekit import trace

    mod = types.SimpleNamespace(RenamedThingInstrumentor=object)
    assert trace._resolve_instrumentor(mod, "OldNameInstrumentor") is object
    # Ambiguity is not guessed at — two candidates means we decline rather than pick wrong.
    two = types.SimpleNamespace(AInstrumentor=object, BInstrumentor=int)
    assert trace._resolve_instrumentor(two, "GoneInstrumentor") is None

