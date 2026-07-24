"""The OTel conformance matrix must not be able to lie (#89).

`provekit/conformance.py` is a *claim* about which semantic-convention attributes ProveKit
understands. A claim nobody checks is worse than no claim: the first attribute that quietly
stops being read looks like a data bug, and "OpenTelemetry-compatible" becomes unfalsifiable.
So every attribute listed as mapped has to actually appear in the mapper.
"""
import pathlib

from fastapi.testclient import TestClient

from provekit import conformance
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
