"""The SDK must not trace its own calls to the portal (#noise).

`provekit[http]` instruments httpx, and the SDK talks to the portal over httpx. Without
suppression, exporting a batch, fetching a prompt and posting a score each produced their own
parentless span, which arrived in the customer's trace list as a top-level run named "GET" or
"POST" with no model, no tokens and no input. In a first real run of the bundled demo agent,
19 of 24 traces were this. They are also counted, so they drag error rate and p95 toward the
latency of ProveKit's own API.
"""
from provekit import trace as pk_trace


def test_the_suppression_helper_is_a_context_manager():
    with pk_trace._no_self_trace():
        pass


def test_it_degrades_to_a_no_op_without_the_instrumentation_package(monkeypatch):
    """Tracing must never be the thing that breaks a customer's process, so a missing optional
    import has to mean "no suppression", not an exception."""
    import builtins
    real = builtins.__import__

    def _no_otel_utils(name, *a, **kw):
        if name == "opentelemetry.instrumentation.utils":
            raise ImportError("not installed")
        return real(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", _no_otel_utils)
    with pk_trace._no_self_trace():
        pass                                  # did not raise


def test_every_sdk_call_to_the_portal_is_wrapped():
    """A drift guard. A new httpx call added to the SDK without suppression re-opens the bug,
    and the symptom (junk traces in someone else's portal) never shows up in our own tests."""
    import inspect
    import re

    from provekit import eval as pk_eval

    # Every way httpx can be asked to make a request, not just the two we happen to use today.
    # The first version of this guard matched `httpx.get|post` only, which would have waved
    # through a future `httpx.request(...)` or `httpx.Client()` — and the bug it exists to catch
    # is invisible to us by construction, since the junk traces land in someone else's portal.
    CALLS = r"get|post|put|patch|delete|head|options|request|stream|Client|AsyncClient"
    for mod in (pk_trace, pk_eval):
        src = inspect.getsource(mod)
        for m in re.finditer(rf'^(\s*)(?:\w+ = )?(?:await )?httpx\.({CALLS})\b', src, re.M):
            line_no = src[:m.start()].count("\n") + 1
            # Six lines of lookback, not three: a wrapped call can carry a comment above it.
            before = src[:m.start()].rsplit("\n", 6)[-6:]
            assert any("_no_self_trace()" in b for b in before), (
                f"{mod.__name__}:{line_no} calls httpx.{m.group(2)} outside _no_self_trace() — "
                "it will appear as a junk trace in the customer's own portal, never in ours")


# ---------------------------------------------------------------- dataset id as a string

def test_a_dataset_id_that_arrived_as_text_still_resolves():
    """An id read from os.environ or argv is a str. It used to fall through to the name lookup
    and report `dataset '2' not found` — true, and entirely misleading, because the dataset is
    right there and the type is what was wrong."""
    from provekit.eval import _resolve_dataset_id

    def _never_called(*a, **kw):
        raise AssertionError("a numeric id must not need a network lookup")

    import provekit.eval as ev
    real = ev._get
    ev._get = _never_called
    try:
        assert _resolve_dataset_id("http://x", {}, "2") == 2
        assert _resolve_dataset_id("http://x", {}, " 7 ") == 7
        assert _resolve_dataset_id("http://x", {}, 3) == 3
    finally:
        ev._get = real


def test_an_unknown_name_says_what_the_project_does_have():
    """"not found" alone leaves you guessing whether the name is wrong, the project is wrong,
    or the key is. Listing what is actually there settles it in one line."""
    import pytest

    import provekit.eval as ev
    real = ev._get
    ev._get = lambda *a, **kw: [{"id": 1, "name": "support-qa"}, {"id": 2, "name": "billing"}]
    try:
        with pytest.raises(ValueError, match="support-qa, billing"):
            ev._resolve_dataset_id("http://x", {}, "typo-name")
    finally:
        ev._get = real
