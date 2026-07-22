"""MCP write tools: promote a trace (or one span) into a dataset, create a dataset, register
an experiment.

Two layers. Most tests drive the data layer against a fake portal so the refusals — duplicate
promotion, taken name, empty dataset, span with no input — can be asserted *and* checked to
have written nothing. The last test wires the same functions to a real TestClient over the app
with a real project key, which is what proves the URLs and payload shapes are not fiction.
"""
import json

import pytest
from fastapi.testclient import TestClient

import provekit.mcp as mcp
from provekit.main import app
from provekit.routers import dataset_writes

BASE = "https://testserver"


# ---------------------------------------------------------------- fake portal (no network)
class _Resp:
    def __init__(self, data, status=200, body=None):
        self._data = data
        self.status_code = status
        self.text = json.dumps(data) if body is None else body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise AssertionError("unexpected error status")

    def json(self):
        if self._data is None:      # a proxy's HTML error page, say — not JSON at all
            raise ValueError("not json")
        return self._data


class _Portal:
    """Just enough of /v1 to exercise the write tools, and a log of everything written."""

    def __init__(self, spans=None, datasets=None, items=None):
        self.spans = spans if spans is not None else [_span("root", "", "hello?", "hi there")]
        self.datasets = datasets if datasets is not None else [
            {"id": 7, "name": "regression", "description": "", "item_count": 1}]
        # One unrelated item, so the duplicate check has to actually discriminate rather than
        # pass by scanning an empty list.
        self.items = items if items is not None else [
            {"id": 1, "meta": {"trace_id": "some-other-trace", "span_id": "root"}}]
        self.posts = []
        self.next_id = 100
        self.fail = None   # (status, detail) forced on the next POST

    def get(self, url, headers=None, params=None, timeout=None, follow_redirects=None):
        path = url[len(BASE) + len("/v1"):]
        if path.startswith("/traces/"):
            return _Resp(self.spans)
        if path == "/datasets":
            return _Resp(self.datasets)
        if path.endswith("/items"):
            return _Resp(self.items)
        raise AssertionError(f"unexpected GET {path}")

    def post(self, url, headers=None, json=None, timeout=None, follow_redirects=None):
        path = url[len(BASE) + len("/v1"):]
        self.posts.append((path, json))
        if self.fail:
            status, detail = self.fail
            if detail is None:
                return _Resp(None, status, body="<html>502 Bad Gateway</html>")
            return _Resp({"detail": detail} if detail else {}, status)
        self.next_id += 1
        if path == "/datasets":
            return _Resp({"id": self.next_id, "name": json["name"],
                          "description": json["description"], "item_count": 0})
        if path == "/experiments":
            return _Resp({"id": self.next_id, "name": json["name"], "dataset_id": json["dataset_id"]})
        return _Resp({"id": self.next_id, "dataset_id": 7, **json})


def _span(span_id, parent, inp, out, *, type_="agent", status="ok", label="agent"):
    return {"span_id": span_id, "parent_span_id": parent, "type": type_, "label": label,
            "status": status, "request": {"input": inp}, "result": {"text": out}}


@pytest.fixture
def portal(monkeypatch):
    monkeypatch.setenv("PROVEKIT_API_KEY", "pk_test")
    monkeypatch.setenv("PROVEKIT_ENDPOINT", BASE)
    p = _Portal()
    monkeypatch.setattr(mcp.httpx, "get", p.get)
    monkeypatch.setattr(mcp.httpx, "post", p.post)
    return p


# ---------------------------------------------------------------- preview writes nothing
def test_preview_renders_the_item_without_writing(portal):
    out = mcp.preview_dataset_item("t-1", dataset_id=7)
    assert out["input"] == "hello?" and out["expected"] == "hi there"
    assert out["span_id"] == "root" and out["warnings"] == []
    assert out["target"] == {"dataset_id": 7, "dataset_name": "regression", "item_count_now": 1,
                             "already_holds_this_span": False, "existing_item_id": None}
    assert portal.posts == []


def test_preview_warns_when_the_span_carries_no_output(portal):
    portal.spans = [_span("root", "", "why did this fail?", "", status="error")]
    out = mcp.preview_dataset_item("t-1")
    assert out["expected"] == "" and out["expected_source"] == "empty"
    assert any("supply the answer it should have given" in w for w in out["warnings"])


def test_preview_flags_a_span_already_promoted(portal):
    portal.items = [{"id": 55, "meta": {"trace_id": "t-1", "span_id": "root"}}]
    out = mcp.preview_dataset_item("t-1", dataset_id=7)
    assert out["target"]["already_holds_this_span"] and out["target"]["existing_item_id"] == 55


# ---------------------------------------------------------------- span selection
def test_span_id_selects_one_step_of_the_trace(portal):
    portal.spans = [_span("root", "", "hello?", "hi there"),
                    _span("kid", "root", "lookup(42)", "42 -> ok", type_="tool", label="lookup")]
    out = mcp.preview_dataset_item("t-1", span_id="kid")
    assert (out["input"], out["expected"], out["span_type"]) == ("lookup(42)", "42 -> ok", "tool")


def test_unknown_span_id_lists_the_real_ones(portal):
    with pytest.raises(ValueError, match="is not in trace"):
        mcp.preview_dataset_item("t-1", span_id="nope")


def test_rootless_trace_refuses_rather_than_guessing(portal):
    # A partial trace has no obvious "the run as the caller saw it" span; promoting the first
    # arrival would silently write a tool's arguments as if they were the user's question.
    portal.spans = [_span("kid", "root", "lookup(42)", "42 -> ok", type_="tool")]
    with pytest.raises(ValueError, match="no root span"):
        mcp.add_trace_to_dataset(7, "t-1")
    assert portal.posts == []


# ---------------------------------------------------------------- add_trace_to_dataset
def test_add_promotes_the_root_span_with_provenance(portal):
    out = mcp.add_trace_to_dataset(7, "t-1")
    path, body = portal.posts[0]
    assert path == "/datasets/7/items"
    assert body["input"] == "hello?" and body["expected"] == "hi there"
    assert body["meta"] == {"trace_id": "t-1", "span_id": "root", "source": "mcp"}
    assert out["dataset_name"] == "regression" and out["item_count_now"] == 2
    assert "dataset 7 ('regression')" in out["changed"]


def test_expected_override_wins_over_the_recorded_output(portal):
    mcp.add_trace_to_dataset(7, "t-1", expected="the right answer")
    assert portal.posts[0][1]["expected"] == "the right answer"


def test_add_refuses_a_second_copy_of_the_same_span(portal):
    portal.items = [{"id": 55, "meta": {"trace_id": "t-1", "span_id": "root"}}]
    with pytest.raises(ValueError, match="already holds this span as item 55"):
        mcp.add_trace_to_dataset(7, "t-1")
    assert portal.posts == []
    mcp.add_trace_to_dataset(7, "t-1", allow_duplicate=True)
    assert len(portal.posts) == 1


def test_portal_seeded_items_count_as_the_root_already_being_present(portal):
    # Items promoted from the UI predate span-level promotion and carry only a trace_id.
    portal.items = [{"id": 9, "meta": {"trace_id": "t-1"}}]
    with pytest.raises(ValueError, match="item 9"):
        mcp.add_trace_to_dataset(7, "t-1")
    # ...but they say nothing about a child span, which is a different example.
    portal.spans.append(_span("kid", "root", "lookup(42)", "ok", type_="tool"))
    mcp.add_trace_to_dataset(7, "t-1", span_id="kid")
    assert portal.posts[0][1]["meta"]["span_id"] == "kid"


def test_add_refuses_a_span_with_no_input(portal):
    portal.spans = [_span("root", "", "", "hi there")]
    with pytest.raises(ValueError, match="recorded no input"):
        mcp.add_trace_to_dataset(7, "t-1")
    assert portal.posts == []


def test_add_refuses_an_unknown_dataset_id(portal):
    with pytest.raises(ValueError, match="No dataset with id 999"):
        mcp.add_trace_to_dataset(999, "t-1")
    assert portal.posts == []


def test_missing_request_result_dicts_are_tolerated(portal):
    portal.spans = [{"span_id": "root", "parent_span_id": "", "type": "step", "label": "s",
                     "status": "ok", "request": None, "result": None}]
    out = mcp.preview_dataset_item("t-1")
    assert out["input"] == "" and out["expected"] == "" and len(out["warnings"]) == 2


# ---------------------------------------------------------------- create_dataset
def test_create_dataset_returns_the_new_id(portal):
    out = mcp.create_dataset("goldens", "curated by hand")
    assert portal.posts[0] == ("/datasets", {"name": "goldens", "description": "curated by hand"})
    assert out["item_count"] == 0 and "Created empty dataset" in out["changed"]


def test_create_dataset_refuses_a_name_already_in_use(portal):
    with pytest.raises(ValueError, match="id=7"):
        mcp.create_dataset("  REGRESSION ")
    assert portal.posts == []


def test_create_dataset_refuses_a_blank_name(portal):
    with pytest.raises(ValueError, match="needs a name"):
        mcp.create_dataset("   ")
    assert portal.posts == []


# ---------------------------------------------------------------- start_experiment
def test_start_experiment_registers_over_the_dataset(portal):
    out = mcp.start_experiment(7, "nightly")
    assert portal.posts[0] == ("/experiments", {"name": "nightly", "dataset_id": 7})
    assert out["dataset_name"] == "regression" and out["result_count"] == 0
    # The tool must not let a model claim the eval ran: nothing executes server-side.
    assert out["scored"] is False and "never calls your agent" in out["how_results_arrive"]


def test_start_experiment_refuses_an_empty_dataset(portal):
    portal.datasets = [{"id": 7, "name": "regression", "description": "", "item_count": 0}]
    with pytest.raises(ValueError, match="would score nothing"):
        mcp.start_experiment(7, "nightly")
    assert portal.posts == []


# ---------------------------------------------------------------- error surfacing
def test_write_failure_surfaces_the_portals_own_detail(portal):
    portal.fail = (404, "Dataset not found")
    with pytest.raises(RuntimeError, match="HTTP 404 Dataset not found"):
        mcp.add_trace_to_dataset(7, "t-1")


def test_a_portal_without_the_write_routes_says_so(portal):
    portal.fail = (405, "Method Not Allowed")
    with pytest.raises(RuntimeError, match="does not serve key-authed writes"):
        mcp.create_dataset("brand new")


def test_write_failure_falls_back_to_the_body_when_it_is_not_json(portal):
    portal.fail = (502, None)
    with pytest.raises(RuntimeError, match="502 Bad Gateway"):
        mcp.create_dataset("brand new")


# ---------------------------------------------------------------- end to end, real API
def _wire_to_app(monkeypatch, client, key):
    """Point the data layer at a TestClient. Same code path, real routing and real auth."""
    monkeypatch.setenv("PROVEKIT_API_KEY", key)
    monkeypatch.setenv("PROVEKIT_ENDPOINT", BASE)
    monkeypatch.setattr(mcp.httpx, "get", lambda url, headers=None, params=None, **kw:
                        client.get(url[len(BASE):], headers=headers, params=params))
    monkeypatch.setattr(mcp.httpx, "post", lambda url, headers=None, json=None, **kw:
                        client.post(url[len(BASE):], headers=headers, json=json))


def test_full_loop_against_the_real_api(monkeypatch):
    """failing trace → new dataset → promoted item → experiment, over HTTP with a project key."""
    # The key-authed writes live in their own module; main.py wiring lands separately, so
    # register them here if they are not already mounted.
    if not any(getattr(r, "path", "") == "/v1/datasets" and "POST" in (getattr(r, "methods", None) or set())
               for r in app.routes):
        app.include_router(dataset_writes.key_router)

    client = TestClient(app, base_url=BASE)
    key = client.post("/api/api-keys", json={"name": "mcp"}).json()["key"]
    hdr = {"Authorization": f"Bearer {key}"}
    client.post("/v1/traces", headers=hdr, json={"resourceSpans": [{"scopeSpans": [{"spans": [{
        "name": "agent", "traceId": "t-mcp-write", "spanId": "a1" * 8, "parentSpanId": "",
        "startTimeUnixNano": "1000000000", "endTimeUnixNano": "1500000000", "status": {"code": 2},
        "attributes": [
            {"key": "gen_ai.operation.name", "value": {"stringValue": "invoke_agent"}},
            {"key": "gen_ai.input.messages", "value": {"stringValue": "capital of France?"}},
            {"key": "gen_ai.output.messages", "value": {"stringValue": "Berlin"}}],
    }]}]}]})
    _wire_to_app(monkeypatch, client, key)

    preview = mcp.preview_dataset_item("t-mcp-write")
    assert preview["input"] == "capital of France?" and preview["expected"] == "Berlin"

    ds = mcp.create_dataset("mcp-regression", "failures found over MCP")
    added = mcp.add_trace_to_dataset(ds["id"], "t-mcp-write", expected="Paris")
    assert added["item_count_now"] == 1

    items = client.get(f"/v1/datasets/{ds['id']}/items", headers=hdr).json()
    assert [(i["input"], i["expected"]) for i in items] == [("capital of France?", "Paris")]
    assert items[0]["meta"]["trace_id"] == "t-mcp-write" and items[0]["meta"]["source"] == "mcp"

    # The refusals hold against the real API too, and leave the dataset at one item.
    with pytest.raises(ValueError, match="already holds this span"):
        mcp.add_trace_to_dataset(ds["id"], "t-mcp-write")
    with pytest.raises(ValueError, match="already exists"):
        mcp.create_dataset("mcp-regression")
    assert len(client.get(f"/v1/datasets/{ds['id']}/items", headers=hdr).json()) == 1

    exp = mcp.start_experiment(ds["id"], "mcp-nightly")
    assert client.get(f"/v1/experiments/{exp['experiment_id']}", headers=hdr).json()["result_count"] == 0


def test_key_authed_item_write_cannot_reach_another_tenant(monkeypatch):
    """A dataset id from another project 404s instead of being appended to."""
    if not any(getattr(r, "path", "") == "/v1/datasets" and "POST" in (getattr(r, "methods", None) or set())
               for r in app.routes):
        app.include_router(dataset_writes.key_router)
    client = TestClient(app, base_url=BASE)
    key = client.post("/api/api-keys", json={"name": "mcp-tenant"}).json()["key"]
    r = client.post("/v1/datasets/999999/items", headers={"Authorization": f"Bearer {key}"},
                    json={"input": "x", "expected": "y"})
    assert r.status_code == 404
