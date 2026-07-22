"""The read-API contract step-through (#56) depends on.

Step-through is a frontend feature (`frontend/components/StepThrough.tsx`) and this wave added
**no backend code** — no route, no service, no model. What it added is a *dependency* on three
properties of `GET /api/traces/{trace_id}` that nothing previously asserted, and that are each
one careless change away from silently breaking the debugger:

1. The response is in ARRIVAL order (`Run.id.asc()`), which is not execution order. Spans export
   out of order — a child finishes and ships before its parent — so a debugger that stepped
   through array position would walk the trace in the order the exporter's batches flushed.
   The client must sort, and this pins the fact that it has to.
2. Every span carries `result.meta.start_ns`, the epoch-nanosecond start, as a *decimal string*.
   That string is what the client sorts on, via BigInt: epoch nanos exceed 2^53, so a JSON
   number would arrive already rounded. This asserts both the presence and the exactness.
3. A trace whose root span never arrived (#3/#4) still returns every span it does have. That is
   precisely the trace someone opens a debugger on, and dropping the parentless rows — or 404ing
   the trace — would make the feature useless exactly when it is needed.

The assertions are about the bytes on the wire, not about internals, because that is all the
browser gets.
"""
import pytest
from fastapi.testclient import TestClient

from provekit.main import app

# Trace ids are namespaced to this file (roadmap #56). The suite shares one database, and a
# generic id like "5a"*16 collides with another module's fixture — which shows up here as a
# stray extra span in a trace this file thought it owned.
ORDERED = "56ab" * 8     # a complete trace, posted in an order that is not execution order
ROOTLESS = "56cd" * 8    # children only; the root span never arrived

# A realistic wall-clock epoch-nanosecond value (2024-05-01T00:00:00Z). Well beyond 2^53, which
# is the whole reason start_ns travels as a string.
T0 = 1714521600123456789


def _client():
    return TestClient(app, base_url="https://testserver")


def _span(trace, span_id, parent, start_ns, dur_ns, *, name="step"):
    # No gen_ai.request.model attribute: the ingest mapper builds an LLM span's label from the
    # model ("chat gpt-4o-mini"), which would make all three spans here indistinguishable. These
    # are plain steps so the span name survives as the label and each row stays identifiable.
    return {"name": name, "traceId": trace, "spanId": span_id, "parentSpanId": parent,
            "startTimeUnixNano": str(start_ns), "endTimeUnixNano": str(start_ns + dur_ns),
            "status": {"code": 1}, "attributes": []}


@pytest.fixture(scope="module", autouse=True)
def _ingested():
    c = _client()
    # Posted child-first, root-last: the batch order a real exporter produces, since a child
    # span ends (and is queued for export) before the parent that is still awaiting it.
    c.post("/v1/traces", json={"resourceSpans": [{"scopeSpans": [{"spans": [
        _span(ORDERED, "56b2" * 4, "56b1" * 4, T0 + 5_000_000, 20_000_000, name="child"),
        _span(ORDERED, "56b3" * 4, "56b2" * 4, T0 + 9_000_000, 3_000_000, name="grandchild"),
        _span(ORDERED, "56b1" * 4, "", T0, 40_000_000, name="root"),
    ]}]}]})
    # No span with id c0…: the run died before the root could report finishing.
    c.post("/v1/traces", json={"resourceSpans": [{"scopeSpans": [{"spans": [
        _span(ROOTLESS, "56c2" * 4, "56c0" * 4, T0 + 7_000_000, 10_000_000, name="orphan-b"),
        _span(ROOTLESS, "56c1" * 4, "56c0" * 4, T0 + 2_000_000, 10_000_000, name="orphan-a"),
    ]}]}]})


def _trace(trace_id):
    r = _client().get(f"/api/traces/{trace_id}")
    assert r.status_code == 200, r.text
    return r.json()


def _start_ns(span) -> str:
    return (span["result"] or {}).get("meta", {}).get("start_ns")


# ---- 1. the response is in arrival order, so the client has to sort ----

def test_trace_read_returns_arrival_order_not_execution_order():
    rows = _trace(ORDERED)
    assert [s["label"] for s in rows] == ["child", "grandchild", "root"]
    # Stated as an inequality on purpose: if this ever starts matching, the comment in
    # StepThrough.tsx explaining why it sorts is the thing that has gone stale.
    by_start = sorted(rows, key=lambda s: int(_start_ns(s)))
    assert [s["label"] for s in by_start] == ["root", "child", "grandchild"]
    assert [s["label"] for s in rows] != [s["label"] for s in by_start]


# ---- 2. start_ns is present, a string, and exact ----

def test_every_span_carries_start_ns_as_an_exact_decimal_string():
    for trace_id in (ORDERED, ROOTLESS):
        for s in _trace(trace_id):
            v = _start_ns(s)
            assert isinstance(v, str), f"{s['label']}: start_ns must be a string, got {type(v)}"
            assert v.isdigit()

    starts = {s["label"]: int(_start_ns(s)) for s in _trace(ORDERED)}
    assert starts == {"root": T0, "child": T0 + 5_000_000, "grandchild": T0 + 9_000_000}
    # The precision claim, made explicitly: a float64 could not have carried this value back.
    assert starts["root"] > 2 ** 53
    assert float(starts["root"]) != starts["root"]


def test_sorting_by_start_ns_reconstructs_execution_order():
    rows = sorted(_trace(ORDERED), key=lambda s: int(_start_ns(s)))
    assert [s["label"] for s in rows] == ["root", "child", "grandchild"]
    # Parent-before-child holds here because the parent really did start first — the debugger
    # gets the tree shape from parent_span_id, not from this ordering.
    by_id = {s["span_id"]: s for s in rows}
    child = by_id["56b2" * 4]
    assert child["parent_span_id"] == "56b1" * 4


# ---- 3. a trace whose root never arrived still returns everything ----

def test_rootless_trace_returns_every_span_it_has():
    rows = _trace(ROOTLESS)
    assert len(rows) == 2
    ids = {s["span_id"] for s in rows}
    # Both rows point at a parent that is not in the response. The client has to treat each as a
    # root rather than waiting for a parent that is never coming.
    assert all(s["parent_span_id"] not in ids for s in rows)
    assert all(s["parent_span_id"] for s in rows)
    ordered = sorted(rows, key=lambda s: int(_start_ns(s)))
    assert [s["label"] for s in ordered] == ["orphan-a", "orphan-b"]


def test_unknown_trace_is_404_not_an_empty_step_list():
    r = _client().get(f"/api/traces/{'56ef' * 8}")
    assert r.status_code == 404
