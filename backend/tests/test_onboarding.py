"""Onboarding: the preloaded sample project, the instrumentation catalogue the portal
renders, and the facts the diagnostic empty state is allowed to assert.

Everything that touches the app goes through `provekit.main.app` — the real object, with the
real middleware and the real router registrations. A test that wrapped its own app would
prove that this file's code works, not that the product does.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from provekit import doctor
from provekit.database import SessionLocal
from provekit.main import app
from provekit.models import ApiKey, Flow, Run, User, Workspace, WorkspaceMember
from provekit.services import seed

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"


@pytest.fixture()
def db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture()
def user(db):
    """A throwaway account, so nothing here depends on which tests ran first."""
    import uuid
    u = User(email=f"seed-{uuid.uuid4().hex[:10]}@example.com", name="Seed",
             auth_provider="password")
    db.add(u)
    db.commit()
    db.refresh(u)
    yield u
    for ws in db.query(Workspace).filter(Workspace.owner_user_id == u.id).all():
        db.query(Run).filter(Run.workspace_id == ws.id).delete(synchronize_session=False)
        db.query(Flow).filter(Flow.workspace_id == ws.id).delete(synchronize_session=False)
        db.query(WorkspaceMember).filter(
            WorkspaceMember.workspace_id == ws.id).delete(synchronize_session=False)
        db.delete(ws)
    db.delete(u)
    db.commit()


@pytest.fixture()
def seeding_on(monkeypatch):
    """conftest sets SEED_EXAMPLES=false for the suite; turn it back on for these tests."""
    monkeypatch.setenv("SEED_EXAMPLES", "true")


# ---------------------------------------------------------------- #32 sample project

def test_seeding_is_off_when_the_env_says_so(db, user, monkeypatch):
    """A self-hoster (and this suite) must be able to say no and get nothing."""
    monkeypatch.setenv("SEED_EXAMPLES", "false")
    assert seed.seeding_enabled() is False
    assert seed.ensure_sample_project(db, user) is None
    assert db.query(Workspace).filter(Workspace.owner_user_id == user.id).count() == 0


def test_sample_lands_in_its_own_project_and_never_becomes_the_default(db, user, seeding_on):
    """The whole design rests on this: seeded traces must never share a project with real
    ones, and the default project — the one that gets the user's key — must be theirs."""
    from provekit.services.workspace import get_or_create_default_workspace

    ws = seed.ensure_sample_project(db, user)
    assert ws is not None and ws.name == seed.SAMPLE_PROJECT_NAME

    default = get_or_create_default_workspace(db, user)
    assert default.id != ws.id
    assert default.name == "My project"
    assert db.query(Run).filter(Run.workspace_id == default.id).count() == 0


def test_sample_is_idempotent(db, user, seeding_on):
    a = seed.ensure_sample_project(db, user)
    b = seed.ensure_sample_project(db, user)
    assert a.id == b.id
    assert db.query(Workspace).filter(Workspace.name == seed.SAMPLE_PROJECT_NAME,
                                      Workspace.owner_user_id == user.id).count() == 1


def test_every_seeded_span_says_it_is_a_sample(db, user, seeding_on):
    """Three independent marks — id prefix, span metadata, and the root label — because a
    span gets read in places the project name isn't standing next to it."""
    ws = seed.ensure_sample_project(db, user)
    rows = db.query(Run).filter(Run.workspace_id == ws.id).all()
    assert rows, "the sample project must actually contain traces"
    for r in rows:
        assert r.trace_id.startswith(seed.SAMPLE_TRACE_PREFIX)
        assert (r.result or {}).get("meta", {}).get("sample") is True
    roots = [r for r in rows if not r.parent_span_id]
    assert roots and all(r.label.startswith(seed.SAMPLE_LABEL) for r in roots)


def test_sample_covers_the_shapes_the_portal_renders(db, user, seeding_on):
    """A gallery with no failure and no session teaches nothing about the failure panel or
    the sessions view — the two things hardest to discover from an empty portal."""
    ws = seed.ensure_sample_project(db, user)
    rows = db.query(Run).filter(Run.workspace_id == ws.id).all()
    assert {r.type for r in rows} >= {"agent", "llm", "tool"}
    assert any(r.status == "failed" and r.error for r in rows)
    assert any(r.session_id for r in rows)
    llm = [r for r in rows if r.type == "llm"]
    assert all(r.result["meta"]["model"] for r in llm)
    assert all(r.result["meta"]["usage"].get("output_tokens") for r in llm)


def test_seeded_rows_go_through_the_real_otlp_mapping(seeding_on):
    """Sample rows are produced by services/otel from an OTLP payload, so they cannot render
    differently from a real trace — which is the one thing fabricated data must not do."""
    from provekit.services import otel
    payload = seed.sample_payload()
    assert otel.ingest(payload) and len(otel.ingest(payload)) == len(seed.sample_rows())


def test_sample_is_skipped_rather_than_eating_the_last_project_slot(db, user, seeding_on,
                                                                    monkeypatch):
    """A demo the user must delete before they can create their own project is worse than
    no demo. With a cap of 1, seeding declines."""
    from provekit.config import get_settings
    get_settings.cache_clear()
    monkeypatch.setenv("MAX_PROJECTS_PER_ACCOUNT", "1")
    try:
        assert seed.ensure_sample_project(db, user) is None
    finally:
        monkeypatch.delenv("MAX_PROJECTS_PER_ACCOUNT", raising=False)
        get_settings.cache_clear()


def test_a_broken_seed_cannot_break_account_creation(db, user, seeding_on, monkeypatch):
    """This runs inside signup. It is allowed to do nothing; it is not allowed to raise."""
    monkeypatch.setattr(seed, "create_sample_project",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert seed.ensure_sample_project(db, user) is None


def test_sample_project_is_deletable_through_the_real_api(seeding_on):
    """"Easy to delete" has to mean an endpoint that exists. This drives the same route the
    Settings page calls, against the real app, and checks the runs go with it."""
    import uuid
    email = f"seed-api-{uuid.uuid4().hex[:8]}@example.com"
    with TestClient(app) as client:
        r = client.post("/api/auth/register",
                        json={"email": email, "password": "hunter2hunter2"})
        assert r.status_code == 200, r.text
        # Registration wiring is pending (see the report): seed explicitly for this account so
        # the deletion path is exercised on data shaped exactly as signup will produce it.
        s = SessionLocal()
        try:
            u = s.query(User).filter(User.email == email).one()
            ws = seed.ensure_sample_project(s, u)
            assert ws is not None
            ws_id, span_count = ws.id, s.query(Run).filter(Run.workspace_id == ws.id).count()
        finally:
            s.close()
        assert span_count > 0

        projects = client.get("/api/projects").json()
        assert [p for p in projects if p["name"] == seed.SAMPLE_PROJECT_NAME]
        assert not [p for p in projects
                    if p["name"] == seed.SAMPLE_PROJECT_NAME and p["is_default"]]

        # The sample's traces are readable through the normal cookie-authed read path.
        traces = client.get("/api/traces", headers={"X-Project-Id": str(ws_id)}).json()
        assert traces and all(t["trace_id"].startswith(seed.SAMPLE_TRACE_PREFIX) for t in traces)

        assert client.delete(f"/api/projects/{ws_id}").status_code == 200

    s = SessionLocal()
    try:
        assert s.query(Run).filter(Run.workspace_id == ws_id).count() == 0
        assert s.get(Workspace, ws_id) is None
    finally:
        s.close()


_FRESH_INSTALL = r"""
import json, os, sys, tempfile
tmp = tempfile.mkdtemp(prefix="provekit-fresh-")
os.environ["DATABASE_URL"] = "sqlite:///%s/fresh.db" % tmp
os.environ["SPOOL_DIR"] = "%s/spool" % tmp
os.environ["SEED_EXAMPLES"] = "true"
os.environ.pop("HOSTED", None)

from fastapi.testclient import TestClient
from provekit.main import app

with TestClient(app) as client:
    projects = client.get("/api/projects").json()
    traces = [
        t for p in projects
        for t in client.get("/api/traces", headers={"X-Project-Id": str(p["id"])}).json()
    ]
print(json.dumps({"projects": projects, "traces": traces}))
"""


def test_a_brand_new_local_install_has_traces_on_its_first_page_load():
    """The point of #32, checked the only way that means anything: a fresh database, the real
    app, and the same requests the portal makes on first load.

    Runs in a subprocess because the suite's database already has a local user — and "what
    happens to an account that has never existed before" cannot be asked of one that has.
    """
    import subprocess
    import sys

    proc = subprocess.run([sys.executable, "-c", _FRESH_INSTALL], capture_output=True,
                          text=True, cwd=str(Path(__file__).resolve().parents[1]))
    assert proc.returncode == 0, proc.stderr[-3000:]
    out = json.loads(proc.stdout.strip().splitlines()[-1])

    names = [p["name"] for p in out["projects"]]
    assert seed.SAMPLE_PROJECT_NAME in names
    # The user's own project is still the default; the sample is beside it, not in front of it.
    assert [p["name"] for p in out["projects"] if p["is_default"]] == ["My project"]

    assert out["traces"], "a fresh install must have traces to click"
    assert all(t["trace_id"].startswith(seed.SAMPLE_TRACE_PREFIX) for t in out["traces"])
    assert all(t["label"].startswith(seed.SAMPLE_LABEL) for t in out["traces"])


# ---------------------------------------------------------------- #31 diagnostic signals
#
# The empty state distinguishes its cases from two existing cookie-authed endpoints. These pin
# that those endpoints really carry the facts it reads — if they stop, the diagnosis becomes a
# guess, which is the failure mode worth a test.

def test_api_keys_reports_whether_a_key_has_ever_authenticated():
    """`last_used_at` is the whole "key seen at all?" signal: null before the key resolves,
    stamped after. Driven end-to-end through the real app."""
    with TestClient(app) as client:
        created = client.post("/api/api-keys", json={"name": "onboarding-probe"})
        assert created.status_code == 200, created.text
        key = created.json()["key"]
        key_id = created.json()["id"]

        listed = [k for k in client.get("/api/api-keys").json() if k["id"] == key_id]
        assert listed and listed[0]["last_used_at"] is None

        span = {"name": "probe", "traceId": "ab" * 16, "spanId": "cd" * 8,
                "startTimeUnixNano": "1000000000", "endTimeUnixNano": "1100000000",
                "status": {"code": 1},
                "attributes": [{"key": "gen_ai.request.model",
                                "value": {"stringValue": "probe"}}]}
        r = client.post("/v1/traces", headers={"Authorization": f"Bearer {key}"},
                        json={"resourceSpans": [{"scopeSpans": [{"spans": [span]}]}]})
        assert r.status_code == 200, r.text

        listed = [k for k in client.get("/api/api-keys").json() if k["id"] == key_id]
        assert listed[0]["last_used_at"] is not None

        client.delete(f"/api/api-keys/{key_id}")

    s = SessionLocal()
    try:
        row = s.query(Run).filter(Run.trace_id == "ab" * 16).first()
        if row is not None:
            s.delete(row)
            s.query(ApiKey).filter(ApiKey.id == key_id).delete()
            s.commit()
    finally:
        s.close()


def test_retention_endpoint_separates_never_arrived_from_deleted():
    """The third case — "spans arrived and retention removed them" — is only distinguishable
    because pruning is recorded. `stored_spans` and `pruned_total` are what the UI reads."""
    with TestClient(app) as client:
        body = client.get("/api/workspace/retention")
        assert body.status_code == 200, body.text
        data = body.json()
    assert {"stored_spans", "pruned_total", "keep"} <= set(data)
    assert isinstance(data["stored_spans"], int) and isinstance(data["pruned_total"], int)


# ---------------------------------------------------------------- #30 instrumentation coverage

def test_coverage_catalog_is_the_doctor_table():
    cat = doctor.coverage_catalog()
    assert len(cat) == len(doctor._COVERAGE)
    assert cat[0].keys() == {"library", "instrumentor", "extra"}
    assert [(c["library"], c["instrumentor"], c["extra"]) for c in cat] == \
        [tuple(row) for row in doctor._COVERAGE]


def test_local_coverage_splits_installed_from_instrumented(monkeypatch):
    """The CLI's answer is about *this* interpreter. Fake the probe so the assertion doesn't
    depend on which extras the test venv happens to have."""
    monkeypatch.setattr(doctor, "_installed",
                        lambda m: m in ("openai", "openinference.instrumentation.openai",
                                        "langchain"))
    local = doctor.local_coverage()
    assert local["instrumented"] == ["openai"]
    assert local["missing"] == [{"library": "langchain", "extra": "provekit[trace-all]"}]

    # ...and the rendered report still names the gap and the extra that closes it.
    rep = doctor.Report()
    doctor.check_coverage(rep)
    gap = next(r for r in rep.rows if r[1] == "Instrumentation gap")
    assert gap[0] == doctor.WARN and "langchain" in gap[2] and "trace-all" in gap[3]


@pytest.mark.skipif(not (FRONTEND / "components" / "EmptyState.tsx").exists(),
                    reason="frontend not checked out")
def test_portal_coverage_table_matches_doctor():
    """The portal renders the same catalogue. It can't import Python, so it holds a copy —
    and a copy that drifts would advertise instrumentation ProveKit doesn't ship."""
    src = (FRONTEND / "components" / "EmptyState.tsx").read_text()
    found = re.findall(
        r'\{\s*library:\s*"([^"]+)",\s*instrumentor:\s*"([^"]+)",\s*extra:\s*"([^"]+)"\s*\}', src)
    assert found, "COVERAGE table not found in EmptyState.tsx"
    assert found == [tuple(row) for row in doctor._COVERAGE]


@pytest.mark.skipif(not (FRONTEND / "components" / "EmptyState.tsx").exists(),
                    reason="frontend not checked out")
def test_portal_and_backend_agree_on_the_sample_project_name():
    """The empty state's "open the sample" shortcut matches on this exact string."""
    src = (FRONTEND / "components" / "EmptyState.tsx").read_text()
    assert f'SAMPLE_PROJECT_NAME = {json.dumps(seed.SAMPLE_PROJECT_NAME)}' in src


def test_the_sample_project_seeds_the_flow_the_landing_page_shows(db, user, seeding_on):
    """A fresh Studio opening on a blank canvas contradicts the hero, which shows a
    'Customer Support Agent' flow. The sample project seeds exactly that — as a draft, since a
    seeded flow is something to open and run, not something claiming to be published."""
    ws = seed.ensure_sample_project(db, user)
    flows = db.query(Flow).filter(Flow.workspace_id == ws.id).all()
    assert len(flows) == 1
    f = flows[0]
    assert f.name == "Customer Support Agent"
    assert f.published_version == 0, "seeded as a draft, not live"
    types = {n["type"] for n in f.graph["nodes"]}
    assert {"trigger", "agent", "logic", "output"} <= types
    # walkable: exactly one trigger, and every edge lands on a real node
    ids = {n["id"] for n in f.graph["nodes"]}
    assert sum(n["type"] == "trigger" for n in f.graph["nodes"]) == 1
    assert all(e["source"] in ids and e["target"] in ids for e in f.graph["edges"])
