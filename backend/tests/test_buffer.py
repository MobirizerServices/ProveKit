"""SDK-side durable buffer: a brief outage shouldn't cost you the traces of the outage."""
import json

import pytest

from provekit.buffer import SpanBuffer
from provekit.trace import _ProveKitExporter


@pytest.fixture
def buf(tmp_path):
    return SpanBuffer(str(tmp_path / "buf"), max_batches=5)


def _body(tag="a"):
    return {"resourceSpans": [{"scopeSpans": [{"spans": [{"name": tag}]}]}]}


def test_buffered_batches_replay_in_order(buf):
    for tag in "abc":
        buf.put(_body(tag))
    assert buf.depth() == 3
    seen = []
    assert buf.drain(lambda b: seen.append(b) or True) == 3
    assert [b["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["name"] for b in seen] == list("abc")
    assert buf.depth() == 0


def test_drain_stops_at_the_first_failure_and_keeps_the_rest(buf):
    for tag in "abc":
        buf.put(_body(tag))
    assert buf.drain(lambda b: False) == 0
    assert buf.depth() == 3        # still down; nothing consumed


def test_buffer_is_bounded_and_drops_the_oldest(buf):
    for i in range(9):
        buf.put(_body(str(i)))
    assert buf.depth() == 5        # capped
    seen = []
    buf.drain(lambda b: seen.append(b) or True)
    names = [b["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["name"] for b in seen]
    # The newest survive: after a long outage those are the ones someone will look for.
    assert names == ["4", "5", "6", "7", "8"]


def test_unwritable_directory_degrades_silently(tmp_path):
    """Fail-open is the contract: no disk means no buffer, never an exception in the app."""
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("i am a file")
    b = SpanBuffer(str(blocker / "buf"), max_batches=5)
    assert b.put(_body()) is False
    assert b.depth() == 0


def test_corrupt_entry_is_dropped_not_retried_forever(buf, tmp_path):
    buf.put(_body("good"))
    bad = sorted((tmp_path / "buf").glob("*.json"))[0].with_name("0000000000000-0-000000.json")
    bad.write_text("{not json")
    sent = []
    assert buf.drain(lambda b: sent.append(b) or True) == 1   # the good one
    assert buf.depth() == 0                                   # the bad one is gone, not stuck


# -- exporter integration ------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code


def test_export_treats_an_error_status_as_failure(monkeypatch, tmp_path):
    """The bug this fixes: the exporter never looked at the status, so a 503 from ingest
    backpressure — or a revoked key — was recorded as a successful export and the spans were
    dropped by the very retry path meant to save them."""
    import httpx
    from opentelemetry.sdk.trace.export import SpanExportResult

    monkeypatch.setattr(httpx, "post", lambda *a, **kw: _FakeResponse(503))
    b = SpanBuffer(str(tmp_path / "buf"), max_batches=5)
    exp = _ProveKitExporter("http://portal/v1/traces", "k", buffer=b)
    assert exp._send(_body()) is False
    assert exp.export([]) == SpanExportResult.FAILURE
    assert b.depth() == 1                       # and the batch was kept


def test_export_recovers_buffered_spans_when_the_portal_returns(monkeypatch, tmp_path):
    import httpx
    from opentelemetry.sdk.trace.export import SpanExportResult

    b = SpanBuffer(str(tmp_path / "buf"), max_batches=5)
    exp = _ProveKitExporter("http://portal/v1/traces", "k", buffer=b)

    monkeypatch.setattr(httpx, "post", lambda *a, **kw: _FakeResponse(503))
    exp.export([])
    assert b.depth() == 1

    posted = []

    def _ok(*a, **kw):
        posted.append(kw.get("json"))
        return _FakeResponse(200)

    monkeypatch.setattr(httpx, "post", _ok)
    assert exp.export([]) == SpanExportResult.SUCCESS
    assert b.depth() == 0
    assert len(posted) == 2                     # the buffered batch, then the live one


def test_force_flush_drains_the_buffer(monkeypatch, tmp_path):
    """A flush is the app's last chance to get its spans out before it exits."""
    import httpx

    b = SpanBuffer(str(tmp_path / "buf"), max_batches=5)
    b.put(_body())
    exp = _ProveKitExporter("http://portal/v1/traces", "k", buffer=b)
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: _FakeResponse(200))
    assert exp.force_flush() is True
    assert b.depth() == 0


def test_network_error_still_never_raises_into_the_app(monkeypatch, tmp_path):
    import httpx
    from opentelemetry.sdk.trace.export import SpanExportResult

    def _boom(*a, **kw):
        raise httpx.ConnectError("portal is unreachable")

    monkeypatch.setattr(httpx, "post", _boom)
    b = SpanBuffer(str(tmp_path / "buf"), max_batches=5)
    exp = _ProveKitExporter("http://portal/v1/traces", "k", buffer=b)
    assert exp.export([]) == SpanExportResult.FAILURE   # not an exception
    assert b.depth() == 1


def test_buffer_can_be_switched_off():
    from provekit.trace import _make_buffer
    assert _make_buffer(0, None) is None


def test_entries_are_valid_json_on_disk(buf, tmp_path):
    """A half-written entry would be a corrupt batch on the next start."""
    buf.put(_body("x"))
    path = sorted((tmp_path / "buf").glob("*.json"))[0]
    assert json.loads(path.read_text())["resourceSpans"]
    assert not list((tmp_path / "buf").glob("*.partial"))
