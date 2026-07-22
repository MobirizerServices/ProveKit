"""Field-level redaction on share links (#70) and the issue-tracker handoff (#69).

The load-bearing assertion in here is on the raw response *text*: the point of masking on the
server is that a withheld prompt is absent from the bytes, not merely hidden by the client.
"""
import pytest
from fastapi.testclient import TestClient

from provekit.main import app
from provekit.services import share
from tests.conftest import ingest_workspace_id

SECRET_IN = "PATIENT-RECORD-4417-DO-NOT-SHARE"
SECRET_OUT = "diagnosis: withheld-in-real-life"
SECRET_ERR = "psycopg.OperationalError near 'ssn'"
SECRET_LOG = "log line quoting the customer address"

TRACE = "d7" * 16
PLAIN_TRACE = "d8" * 16


def _client():
    return TestClient(app, base_url="https://testserver")


def _span(trace, span_id, parent="", *, failed=False, name="agent"):
    attrs = {"gen_ai.prompt": SECRET_IN, "gen_ai.completion": SECRET_OUT,
             "gen_ai.usage.input_tokens": 11, "gen_ai.usage.output_tokens": 3}
    # The failing child is a tool call, so its label ("tool-call") differs from the LLM root's
    # ("chat gpt-4o-mini") and the issue draft can be seen picking the failing one.
    attrs.update({"gen_ai.tool.name": "lookup"} if failed else
                 {"gen_ai.request.model": "gpt-4o-mini", "gen_ai.provider.name": "openai"})
    span = {"name": name, "traceId": trace, "spanId": span_id, "parentSpanId": parent,
            "startTimeUnixNano": "1000000000", "endTimeUnixNano": "1500000000",
            "status": {"code": 2, "message": SECRET_ERR} if failed else {"code": 1},
            "events": [{"name": SECRET_LOG, "attributes": []}],
            "attributes": [{"key": k, "value": {"intValue": str(v)} if isinstance(v, int)
                            else {"stringValue": v}} for k, v in attrs.items()]}
    return span


@pytest.fixture(scope="module", autouse=True)
def _ingested():
    """One trace with a clean root and a failing child, plus a second, ordinary trace."""
    c = _client()
    for tid in (TRACE, PLAIN_TRACE):
        c.post("/v1/traces", json={"resourceSpans": [{"scopeSpans": [{"spans": [
            _span(tid, "aa" * 8), _span(tid, "bb" * 8, "aa" * 8, failed=True, name="tool-call"),
        ]}]}]})
    return ingest_workspace_id()


def _mint(withhold, spans=None, ttl_days=30):
    r = _client().post(f"/api/traces/{TRACE}/share/redacted",
                       json={"withhold": withhold, "spans": spans or [], "ttl_days": ttl_days})
    assert r.status_code == 200, r.text
    return r.json()


# ---- the mask itself ----
def test_normalize_rejects_an_unknown_field():
    with pytest.raises(ValueError):
        share.normalize_mask(["promt"])
    with pytest.raises(ValueError):
        share.normalize_mask(["input"], ["ab:cd"])   # separator would corrupt the payload


def test_normalize_dedupes_and_drops_blanks():
    m = share.normalize_mask(["output", "input", "input", " "], ["z", "a", "a", " "])
    assert m.fields == ("input", "output") and m.spans == ("a", "z")
    assert share.normalize_mask([]) is share.NO_MASK
    assert not share.normalize_mask([]).active


def test_mask_with_no_spans_covers_every_span():
    m = share.normalize_mask(["input"])
    assert m.covers("anything") and m.covers("")
    scoped = share.normalize_mask(["input"], ["bb"])
    assert scoped.covers("bb") and not scoped.covers("cc")


# ---- the token carries the mask, and carries it tamper-proof ----
def test_token_round_trips_the_mask():
    m = share.normalize_mask(["input", "error"], ["bb"])
    tok = share.make_share_token(7, "t-1", 30, m)
    assert share.share_mask(tok) == m
    assert share.verify_share_token(tok, allow_masked=True) == (7, "t-1")


def test_unmasked_token_is_unchanged_by_the_feature():
    """Links minted before masking existed must still verify byte-for-byte."""
    tok = share.make_share_token(7, "t-1", 30)
    assert tok == share.make_share_token(7, "t-1", 30, share.NO_MASK)
    assert share.verify_share_token(tok) == (7, "t-1")
    assert share.share_mask(tok) == share.NO_MASK


def test_a_masked_token_fails_closed_for_a_reader_that_cannot_mask():
    tok = share.make_share_token(7, "t-1", 30, share.normalize_mask(["input"]))
    assert share.verify_share_token(tok) is None                     # no opt-in → no data
    assert share.verify_share_token(tok, allow_masked=True) == (7, "t-1")


def test_editing_the_mask_out_of_a_link_invalidates_it():
    tok = share.make_share_token(7, "t-1", 30, share.normalize_mask(["input"]))
    payload, sig = tok.split(".", 1)
    forged = share._b64(f"7:t-1:{share.time.time() + 999:.0f}".encode()) + "." + sig
    assert share.verify_share_token(forged, allow_masked=True) is None
    assert share.share_mask(forged) == share.NO_MASK


def test_an_unknown_field_in_a_signed_token_is_refused():
    """A field this build can't strip is not a field it may serve."""
    raw = share._b64(b"7:t-1:0:input+telepathy:")
    sig = share._b64(share.hmac.new(share._share_key(), raw.encode(),
                                    share.hashlib.sha256).digest())
    assert share.verify_share_token(f"{raw}.{sig}", allow_masked=True) is None


def test_expired_masked_token_has_no_mask_and_no_grant(monkeypatch):
    tok = share.make_share_token(7, "t-1", 1, share.normalize_mask(["input"]))
    now = share.time.time()
    monkeypatch.setattr(share.time, "time", lambda: now + 2 * 86400)
    assert share.verify_share_token(tok, allow_masked=True) is None
    assert share.share_mask(tok) == share.NO_MASK


# ---- applying it to rows ----
def _rows():
    return [{"span_id": "aa", "parent_span_id": "", "label": "agent", "status": "completed",
             "trace_id": "t", "duration_ms": 5, "error": "",
             "request": {"model": "gpt-4o-mini", "provider": "openai", "input": SECRET_IN},
             "result": {"text": SECRET_OUT, "output": None,
                        "meta": {"usage": {"input_tokens": 11}, "model": "gpt-4o-mini",
                                 "events": [{"name": SECRET_LOG, "level": "INFO"}]}}},
            {"span_id": "bb", "parent_span_id": "aa", "label": "tool-call", "status": "failed",
             "trace_id": "t", "duration_ms": 2, "error": SECRET_ERR,
             "request": {"model": "", "input": ""},
             "result": {"text": None, "output": None, "meta": {}}}]


def test_apply_mask_strips_every_field_kind():
    rows = _rows()
    out = share.apply_mask(rows, share.normalize_mask(
        ["input", "output", "error", "logs", "label"]))
    blob = str(out)
    for secret in (SECRET_IN, SECRET_OUT, SECRET_ERR, SECRET_LOG):
        assert secret not in blob
    assert out[0]["request"]["model"] == "gpt-4o-mini"          # shape of the call survives
    assert out[0]["result"]["meta"]["usage"] == {"input_tokens": 11}
    assert out[0]["withheld"] == ["input", "label", "logs", "output"]
    # The second span had no input and no output — it is not badged for withholding them.
    assert out[1]["withheld"] == ["error", "label"]
    assert rows == _rows()                                     # caller's rows untouched


def test_structured_output_is_masked_too():
    """`result.output` is the same completion in parsed form — masking only `text` would leave
    the answer sitting in the row beside it."""
    rows = _rows()
    rows[0]["result"]["output"] = {"answer": SECRET_OUT}
    out = share.apply_mask(rows, share.normalize_mask(["output"]))
    assert out[0]["result"]["output"] == share.WITHHELD
    assert SECRET_OUT not in str(out)


def test_apply_mask_is_scoped_to_named_spans():
    out = share.apply_mask(_rows(), share.normalize_mask(["input"], ["bb"]))
    assert out[0]["request"]["input"] == SECRET_IN             # not named → untouched
    assert "withheld" not in out[0]
    assert out[1]["withheld"] == []                            # named, but had nothing to hide


def test_apply_mask_without_fields_is_a_no_op():
    rows = _rows()
    assert share.apply_mask(rows, share.NO_MASK) is rows
    assert share.mask_span_rows(rows, "garbage") is rows


# ---- the wired routes, against the real app ----
def test_shared_read_omits_withheld_content_from_the_response_body():
    got = _mint(["input", "output", "logs"])
    assert got["withheld"] == ["input", "logs", "output"]
    pub = _client()                                            # no session cookie at all
    r = pub.get(f"/api/share/{got['token']}")
    assert r.status_code == 200
    assert SECRET_IN not in r.text and SECRET_OUT not in r.text and SECRET_LOG not in r.text
    body = r.json()
    assert len(body) == 2
    assert body[0]["request"]["model"] == "gpt-4o-mini"         # still debuggable
    assert body[0]["request"]["input"] == share.WITHHELD
    assert body[0]["withheld"] == ["input", "logs", "output"]
    assert SECRET_ERR in r.text                                # not withheld, so not removed


def test_an_unmasked_redacted_share_still_serves_everything():
    got = _mint([])
    assert got["withheld"] == []
    r = _client().get(f"/api/share/{got['token']}")
    assert SECRET_IN in r.text and SECRET_OUT in r.text


def test_the_public_share_route_masks_server_side():
    """The withheld text must not be in the response body at all.

    Masking in the client would leave every prompt one devtools tab away, which is not
    redaction — so this asserts on the raw bytes of the response, not on a parsed field.
    """
    got = _mint(["input"])
    r = _client().get(f"/v1/share/{got['token']}")
    assert r.status_code == 200
    assert SECRET_IN not in r.text, "withheld payload was still in the response body"
    spans = r.json()
    assert any("input" in (s.get("withheld") or []) for s in spans)

    # …and a plain link is unaffected: it still carries its payload.
    plain = _client().post(f"/api/traces/{PLAIN_TRACE}/share").json()["token"]
    assert _client().get(f"/v1/share/{plain}").status_code == 200
    assert _client().get(f"/api/share/{plain}").status_code == 200


def test_share_link_url_and_perpetual_ttl():
    got = _mint(["input"], ttl_days=0)
    assert got["expires_in_days"] is None
    assert got["url"].endswith(f"/shared/{got['token']}")
    assert share.verify_share_token(got["token"], allow_masked=True)[1] == TRACE


def test_bad_mask_and_bad_trace_are_rejected():
    c = _client()
    assert c.post(f"/api/traces/{TRACE}/share/redacted",
                  json={"withhold": ["everything"]}).status_code == 422
    assert c.post("/api/traces/nope/share/redacted", json={"withhold": []}).status_code == 404
    assert c.get("/api/share/not.a.token").status_code == 404
    assert c.get("/api/share/nodothere").status_code == 404


def test_shared_read_404s_when_the_trace_is_gone():
    tok = share.make_share_token(ingest_workspace_id(), "t-never-ingested", 30,
                                 share.normalize_mask(["input"]))
    assert _client().get(f"/api/share/{tok}").status_code == 404


# ---- issue handoff (#69) ----
def test_issue_link_is_prefilled_with_the_trace_context():
    r = _client().post(f"/api/traces/{TRACE}/issue-link",
                       json={"repo": "acme/agent", "withhold": ["input", "output"]})
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["issue_url"].startswith("https://github.com/acme/agent/issues/new?title=")
    assert "tool-call" in got["title"]
    assert got["url"] in got["body"]                            # the share link is the evidence
    assert "gpt-4o-mini" in got["body"] and SECRET_ERR in got["body"]
    assert "input, output" in got["body"]                       # says what the reader can't see
    assert SECRET_IN not in got["body"] and SECRET_OUT not in got["body"]
    from urllib.parse import unquote
    assert got["body"] in unquote(got["issue_url"])


def test_issue_body_never_carries_a_field_the_link_withholds():
    r = _client().post(f"/api/traces/{TRACE}/issue-link",
                       json={"repo": "acme/agent", "withhold": ["error", "label"]})
    got = r.json()
    assert SECRET_ERR not in got["body"] and SECRET_ERR not in got["issue_url"]
    assert share.WITHHELD in got["body"]


def test_issue_link_gitlab_and_custom_template():
    c = _client()
    gl = c.post(f"/api/traces/{TRACE}/issue-link",
                json={"tracker": "gitlab", "repo": "https://gitlab.com/acme/agent.git"}).json()
    assert gl["issue_url"].startswith("https://gitlab.com/acme/agent/-/issues/new?issue[title]=")
    tpl = c.post(f"/api/traces/{TRACE}/issue-link",
                 json={"template": "https://linear.app/new?title={title}&description={body}"}).json()
    assert tpl["issue_url"].startswith("https://linear.app/new?title=%5BProveKit%5D")
    assert "&description=Shared%20trace" in tpl["issue_url"]


def test_issue_link_refuses_a_repo_that_is_not_a_repo():
    c = _client()
    for bad in ({"repo": ""}, {"repo": "javascript:alert(1)"}, {"repo": "not a repo"},
                {"repo": "ftp://files.example.test/acme/agent"},
                {"repo": "acme/agent", "tracker": "carrier-pigeon"},
                {"template": "javascript:alert(1)"}):
        assert c.post(f"/api/traces/{TRACE}/issue-link", json=bad).status_code == 422, bad


def test_issue_draft_of_a_healthy_trace_has_no_failure_section():
    ctx = share.issue_context([{"span_id": "aa", "parent_span_id": "", "label": "nightly",
                                "status": "completed", "trace_id": "t", "duration_ms": 9,
                                "request": {"model": "claude"}, "result": {}}])
    title, body = share.issue_draft(ctx, "https://example.test/shared/x")
    assert title == "[ProveKit] nightly" and "Failing span" not in body
    assert "claude" in body and "Withheld" not in body


def test_issue_body_is_capped():
    ctx = share.issue_context(_rows())
    ctx["error"] = "x" * 9000
    _, body = share.issue_draft(ctx, "https://example.test/shared/x")
    assert len(body) <= share.BODY_CAP
