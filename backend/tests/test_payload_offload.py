"""Large-payload offload (#20).

Prompts and completions lived inline in the row, so the table every hot index covers was mostly
text nobody was reading, and listing traces dragged whole payloads across to render labels.
"""
import pytest
from fastapi.testclient import TestClient

from provekit.config import get_settings
from provekit.main import app
from provekit.services import payloads


@pytest.fixture
def offloading(tmp_path):
    s = get_settings()
    prev_dir, prev_min = s.payload_offload_dir, s.payload_offload_min_bytes
    s.payload_offload_dir, s.payload_offload_min_bytes = str(tmp_path / "blobs"), 64
    yield tmp_path / "blobs"
    s.payload_offload_dir, s.payload_offload_min_bytes = prev_dir, prev_min


def _span(i, prompt):
    return {"name": "chat", "traceId": f"{i:032x}", "spanId": f"{i:016x}",
            "startTimeUnixNano": "1000000000", "endTimeUnixNano": "1500000000",
            "status": {"code": 1},
            "attributes": [{"key": "gen_ai.request.model", "value": {"stringValue": "gpt-4o"}},
                           {"key": "gen_ai.prompt", "value": {"stringValue": prompt}}]}


def _otlp(*s):
    return {"resourceSpans": [{"scopeSpans": [{"spans": list(s)}]}]}


def test_it_is_off_unless_configured():
    """A deployment that hasn't chosen a store must not start scattering data across two."""
    assert payloads.offload_enabled() is False
    assert payloads.maybe_offload("x" * 100_000) == "x" * 100_000


def test_small_payloads_stay_inline(offloading):
    assert payloads.maybe_offload("short") == "short"


def test_large_payloads_become_a_reference_with_a_preview(offloading):
    big = "the quick brown fox " * 50
    ref = payloads.maybe_offload(big)
    assert payloads.is_ref(ref)
    assert ref["bytes"] == len(big.encode())
    assert ref["preview"] == big[:payloads.PREVIEW_CHARS]
    assert payloads.resolve(ref) == big          # and it round-trips exactly


def test_identical_content_is_stored_once(offloading):
    """Content-addressed, so a retried ingest can't produce a second copy or a torn object."""
    a = payloads.maybe_offload("same payload " * 20)
    b = payloads.maybe_offload("same payload " * 20)
    assert a["__ref__"] == b["__ref__"]
    assert len(list(offloading.rglob("*"))) == 2   # one shard dir + one blob


def test_a_missing_blob_degrades_loudly_not_silently(offloading):
    """Returning the preview quietly would present a 200-character excerpt as the payload —
    the same class of lie as silent truncation."""
    big = "content that will vanish " * 20
    ref = payloads.maybe_offload(big)
    for f in offloading.rglob("*"):
        if f.is_file():
            f.unlink()
    out = payloads.resolve(ref)
    assert "payload unavailable" in out
    assert big[:50] in out                        # ...but you still get what we have


def test_an_unwritable_store_falls_back_to_inline(tmp_path):
    """An offload store that is down should cost disk in the database, not the span."""
    s = get_settings()
    prev = s.payload_offload_dir, s.payload_offload_min_bytes
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("i am a file")
    s.payload_offload_dir, s.payload_offload_min_bytes = str(blocker / "blobs"), 8
    try:
        big = "x" * 500
        assert payloads.maybe_offload(big) == big      # inline, not an exception
    finally:
        s.payload_offload_dir, s.payload_offload_min_bytes = prev


def test_the_list_view_never_reads_a_blob(offloading):
    big = "listing must not fetch this " * 40
    ref = payloads.maybe_offload(big)
    for f in offloading.rglob("*"):
        if f.is_file():
            f.unlink()
    # Blob gone, and preview_of still answers — proving the list path doesn't depend on it.
    assert payloads.preview_of(ref) == big[:payloads.PREVIEW_CHARS]


def test_ingest_offloads_and_the_trace_view_inflates(offloading):
    big = "a genuinely long prompt. " * 100
    with TestClient(app) as client:
        r = client.post("/v1/traces", json=_otlp(_span(0xB10B, big)))
        assert r.status_code == 200
        spans = client.get(f"/api/traces/{0xB10B:032x}").json()
    stored = [s for s in spans if s["request"].get("input")][0]
    # The reader gets the whole thing back, transparently.
    assert stored["request"]["input"].startswith("a genuinely long prompt.")
    assert len(stored["request"]["input"]) > payloads.PREVIEW_CHARS


def test_offload_runs_after_redaction(offloading):
    """Offloading first would write the unmasked payload to a store redaction can never reach."""
    row = {"request": {"input": "x"}, "result": {"text": "y"}}
    # offload_row only handles what it is given; the ingest path calls it after scrub_run, and
    # this pins the ordering contract in the one place a reader will look for it.
    import inspect

    from provekit.routers import traces
    src = inspect.getsource(traces.ingest_traces)
    assert src.index("redact.scrub_run") < src.index("_persist_spans")
