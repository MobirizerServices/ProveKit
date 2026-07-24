"""Rejections name the fix, not the symptom (#34).

Two kinds of check here, and both matter:

* the endpoint tests drive the REAL app (`provekit.main.app`), so a message can't pass by
  existing only in `services/errors.py` while the router still raises its old literal; and
* `test_every_message_offers_an_action` sweeps the whole module, so a message added later
  can't quietly reintroduce "Invalid ingest key" — a sentence that states a symptom and
  leaves the reader with nowhere to go.

Status codes are asserted alongside the text on purpose: #34 was a wording change, and a
client that branches on a code must not have been broken by it.
"""
import uuid

import pytest
from fastapi.testclient import TestClient

from fake_provider import openai_connection

from provekit.main import app
from provekit.services import errors


def _client():
    return TestClient(app, base_url="https://testserver")


def _register(c) -> str:
    email = f"e{uuid.uuid4().hex[:10]}@ex.com"
    assert c.post("/api/auth/register", json={"email": email, "password": "pw12345678"}).status_code == 200
    return email


def _detail(resp) -> str:
    body = resp.json()
    assert isinstance(body.get("detail"), str), f"response shape changed: {body}"
    return body["detail"]


# --------------------------------------------------------------------- the module-wide rule
#
# Either a verb the reader can carry out, or an explicit statement of the requirement they
# failed to meet ("Password must be at least 8 characters" is already a good message — it says
# what would be accepted). Deliberately a list of concrete markers rather than a regex for
# "sounds helpful": the point is that someone had to write down what to do or what is wanted.
_ACTIONS = ("use ", "check ", "ask ", "add ", "pass ", "paste ", "give ", "supply ", "copy ",
            "drop ", "merge ", "remove ", "sign in", "sign up", "request ", "open ", "try again",
            "retry", "get /", "send ", "split ", "leave ", "must ", "needs ", "need ", "require")

# Sample arguments for the builders, so the sweep covers rendered messages and not just the
# constants. Every public callable in the module must appear here — see the test below.
# `with_docs` is the link formatter rather than a message; it has its own test.
_BUILDER_ARGS = {
    "not_in_project": ("API key", "GET /api/api-keys"),
    "bad_alert_metric": ("cpu", {"error_rate", "trace_count"}),
    "bad_comparator": ("eq",),
    "bad_webhook": ("Link-local / metadata addresses are not allowed",),
    "bad_provider": ("cohere", {"openai", "anthropic"}),
    "provider_key_required": ("openai",),
    "span_no_messages": ("abc",),
    "too_many_edits": (12, 8),
    "duplicate_edit": ("abc",),
    "bad_edit_kind": ("retrieval",),
    "tool_edit_needs_arguments": ("abc",),
    "dataset_unusable": (7,),
    "dataset_version_missing": (7, 3, 50),
    "provider_failed": ("429 rate limit",),
    "replay_target_missing": ("origin trace not found",),
}


def _all_messages() -> dict[str, str]:
    out = {}
    for name in dir(errors):
        if name.startswith("_") or name in ("DOCS_BASE", "annotations", "with_docs"):
            continue
        value = getattr(errors, name)
        if isinstance(value, str):
            out[name] = value
        elif callable(value):
            out[name] = value(*_BUILDER_ARGS[name])
    return out


def test_builder_sample_args_cover_every_public_callable():
    """Guards the sweep itself: a new builder with no sample args would silently skip it."""
    callables = {n for n in dir(errors)
                 if not n.startswith("_") and callable(getattr(errors, n))}
    assert callables - {"with_docs"} == set(_BUILDER_ARGS)


@pytest.mark.parametrize("name", sorted(_all_messages()))
def test_every_message_offers_an_action(name):
    msg = _all_messages()[name]
    low = msg.lower()
    assert any(a in low for a in _ACTIONS), f"{name} states a symptom but no fix: {msg!r}"
    # A bare noun phrase ("Alert not found", "Invalid ingest key") is the failure mode this
    # item exists to remove.
    assert len(msg.split()) >= 6, f"{name} is too terse to be actionable: {msg!r}"


def test_docs_links_use_one_convention():
    msg = errors.with_docs("Broken.", "DEBUGGING.md", "guardrails")
    assert msg == f"Broken. See {errors.DOCS_BASE}/DEBUGGING.md#guardrails"
    assert errors.with_docs("Broken.", "API.md") == f"Broken. See {errors.DOCS_BASE}/API.md"
    # Every link in the module points at a docs page that exists in this repo.
    import pathlib
    docs = pathlib.Path(__file__).resolve().parents[2] / "docs"
    for name, msg in _all_messages().items():
        if errors.DOCS_BASE not in msg:
            continue
        page = msg.split(f"{errors.DOCS_BASE}/", 1)[1].split("#")[0].strip()
        assert (docs / page).exists(), f"{name} links to a missing docs page: {page}"


def test_unknown_replay_reason_passes_through_unchanged():
    """An unrecognised reason keeps its own wording rather than picking up advice about traces
    (the webhook-not-configured case already names its fix)."""
    reason = "no replay webhook configured for this project (Settings → Replay webhook)"
    assert errors.replay_target_missing(reason) == reason


# --------------------------------------------------------------------- auth
def test_login_failure_points_at_password_reset():
    c = _client()
    email = _register(c)
    r = c.post("/api/auth/login", json={"email": email, "password": "wrong-one-entirely"})
    assert r.status_code == 401
    d = _detail(r)
    assert "Forgot password" in d
    # …and still refuses to say which half was wrong, which is the whole reason it's vague.
    assert "whether an account exists" in d


def test_duplicate_registration_says_what_to_do_instead():
    c = _client()
    email = _register(c)
    r = c.post("/api/auth/register", json={"email": email, "password": "pw12345678"})
    assert r.status_code == 409
    assert "Sign in instead" in _detail(r)


def test_short_password_message_is_left_alone():
    """Already actionable — it names the requirement, so #34 does not touch it."""
    c = _client()
    r = c.post("/api/auth/register", json={"email": f"s{uuid.uuid4().hex[:8]}@ex.com", "password": "abc"})
    assert r.status_code == 400
    assert _detail(r) == "Password must be at least 8 characters"


def test_dead_links_say_how_to_get_a_fresh_one():
    c = _client()
    r = c.post("/api/auth/reset", json={"token": "nonsense", "password": "pw12345678"})
    assert r.status_code == 400
    assert "Forgot password" in _detail(r) and "one hour" in _detail(r)

    r = c.post("/api/auth/verify", json={"token": "nonsense"})
    assert r.status_code == 400
    assert "48 hours" in _detail(r)


# --------------------------------------------------------------------- keys, alerts, projects
def test_cross_project_404s_name_the_header_that_causes_them():
    c = _client()
    r = c.delete("/api/api-keys/98765")
    assert r.status_code == 404
    d = _detail(r)
    assert "X-Project-Id" in d and "GET /api/api-keys" in d


def test_alert_validation_lists_what_is_accepted():
    c = _client()
    r = c.post("/api/alerts", json={"metric": "cpu_load", "threshold": 1})
    assert r.status_code == 422
    assert "error_rate" in _detail(r) and "latency_p95_ms" in _detail(r)

    r = c.post("/api/alerts", json={"metric": "error_rate", "comparator": "eq", "threshold": 1})
    assert r.status_code == 422
    assert "'gt'" in _detail(r) and "'lt'" in _detail(r)

    r = c.get("/api/alerts")
    assert r.status_code == 200
    r = c.delete("/api/alerts/98765")
    assert r.status_code == 404
    assert "GET /api/alerts" in _detail(r)


def test_rejected_webhook_says_what_would_be_accepted():
    c = _client()
    r = c.post("/api/alerts", json={"metric": "error_rate", "threshold": 1,
                                    "webhook_url": "http://169.254.169.254/hook"})
    assert r.status_code == 422
    d = _detail(r)
    assert "Link-local" in d                      # the guard's own reason survives
    assert "public https:// URL" in d             # …plus what to send instead


def test_membership_errors_each_name_the_next_step():
    owner, other = _client(), _client()
    other_email = _register(other)
    pid = owner.post("/api/projects", json={"name": "Errors"}).json()["id"]

    r = owner.post(f"/api/projects/{pid}/members", json={"email": "nobody@nowhere.test"})
    # Inviting an address with no account is no longer a dead end: it records a pending
    # invitation (#73), which is the state the owner actually wanted to see.
    assert r.status_code == 200 and r.json()["status"] == "pending"

    assert owner.post(f"/api/projects/{pid}/members", json={"email": other_email}).status_code == 200
    r = owner.post(f"/api/projects/{pid}/members", json={"email": other_email})
    assert r.status_code == 409 and "remove them and add them again" in _detail(r)

    r = owner.delete(f"/api/projects/{pid}/members/987654")
    assert r.status_code == 404 and "GET /api/projects/{pid}/members" in _detail(r)

    # the local user is the only owner of this project
    me = owner.get("/api/auth/me").json()["id"]
    r = owner.delete(f"/api/projects/{pid}/members/{me}")
    assert r.status_code == 400 and "Add another member as an owner first" in _detail(r)

    # a plain member is told who can make the change
    r = other.patch(f"/api/projects/{pid}", json={"name": "nope"},
                    headers={"X-Project-Id": str(pid)})
    assert r.status_code == 403 and "members" in _detail(r) and "owner role" in _detail(r)


def test_unknown_project_explains_the_404():
    c = _client()
    r = c.patch("/api/projects/987654", json={"name": "x"})
    assert r.status_code == 404
    assert "GET /api/projects" in _detail(r) and "ask them to add you" in _detail(r)


# --------------------------------------------------------------------- playground / replay
def test_connection_setup_errors_name_the_missing_field():
    c = _client()
    r = c.post("/api/connections", json={"provider": "cohere"})
    # Names the providers that *are* supported rather than just rejecting the one given.
    assert r.status_code == 422 and "openai" in _detail(r)

    r = c.post("/api/connections", json={"provider": "openai"})
    # A provider needs your own key — and the message says so instead of offering a mock.
    assert r.status_code == 422 and "key is required" in _detail(r)

    r = c.post("/api/connections", json={"provider": "openai_compatible", "key": "sk-x"})
    assert r.status_code == 422
    assert "/chat/completions" in _detail(r)      # says what NOT to include, the usual mistake

    r = c.delete("/api/connections/98765")
    assert r.status_code == 404 and "GET /api/connections" in _detail(r)


def test_a_run_with_no_model_says_how_to_choose_one():
    c = _client()
    r = c.post("/api/playground/run", json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 422
    d = _detail(r)
    assert "GET /api/connections" in d and "model connection" in d

    r = c.post("/api/playground/run", json={"model": "gpt-4o", "messages": [],
                                            "connection_id": openai_connection(c)})
    assert r.status_code == 422 and "role" in _detail(r)


def test_prompt_and_dataset_errors_say_what_to_fix():
    c = _client()
    r = c.post("/api/prompts", json={"name": "  "})
    assert r.status_code == 422 and "version 2" in _detail(r)

    r = c.delete("/api/prompts/98765")
    assert r.status_code == 404 and "GET /api/prompts" in _detail(r)

    r = c.post("/api/playground/experiment",
               json={"dataset_id": 98765, "model": "gpt-4o",
                     "connection_id": openai_connection(c),
                     "messages": [{"role": "user", "content": "{{input}}"}]})
    assert r.status_code == 404
    assert "GET /api/datasets" in _detail(r) and errors.DOCS_BASE in _detail(r)


def test_multi_replay_edit_validation_is_specific_per_edit():
    c = _client()
    base = {"origin_trace_id": "t-missing", "connection_id": openai_connection(c)}

    r = c.post("/api/replay/multi", json={**base, "edits": []})
    assert r.status_code == 422 and "identical branch" in _detail(r)

    r = c.post("/api/replay/multi", json={**base, "edits": [{"span_id": ""}]})
    assert r.status_code == 422 and "trace view" in _detail(r)

    msg = [{"role": "user", "content": "hi"}]
    r = c.post("/api/replay/multi", json={**base, "edits": [{"span_id": "s1", "messages": msg}] * 9})
    assert r.status_code == 422 and "at most 8" in _detail(r)

    r = c.post("/api/replay/multi", json={**base, "edits": [{"span_id": "s1", "messages": msg},
                                                            {"span_id": "s1", "messages": msg}]})
    assert r.status_code == 422 and "silently dropped" in _detail(r)

    r = c.post("/api/replay/multi", json={**base, "edits": [{"span_id": "s1", "kind": "retrieval"}]})
    assert r.status_code == 422 and "ProveKit doesn't execute your tools" in _detail(r)

    r = c.post("/api/replay/multi", json={**base, "edits": [{"span_id": "s1", "kind": "llm"}]})
    assert r.status_code == 422 and "kind='tool'" in _detail(r)

    r = c.post("/api/replay/multi", json={**base, "edits": [{"span_id": "s1", "kind": "tool"}]})
    assert r.status_code == 422 and "`arguments`" in _detail(r)


def test_replay_of_an_unknown_trace_says_where_to_get_the_id():
    c = _client()
    r = c.post("/api/replay", json={"origin_trace_id": "no-such-trace", "fork_span_id": "s1",
                                    "model": "gpt-4o",
                                    "connection_id": openai_connection(c),
                                    "messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 404
    d = _detail(r)
    assert "origin trace not found" in d          # the underlying reason is preserved
    assert "GET /api/traces" in d and "X-Project-Id" in d
