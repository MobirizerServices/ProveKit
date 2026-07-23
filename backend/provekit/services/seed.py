"""Server-side sample data — traces to click before you have an integration.

A brand-new account lands on an empty portal, which is the one state in which none of the
product is legible: there is no waterfall to read, no failed run to open, nothing to compare.
`provekit-demo` fixes that from the CLI, but only for someone who has *already* wired up a key
— exactly the person who no longer needs it. This does the same thing at account creation.

Two rules, because fabricated traces in a tracing tool are a trust problem, not a UX flourish:

1. **Never mixed with real data.** The sample lives in its own project ("Sample data (demo)"),
   created *after* the user's default project so it can never become the default. Nothing is
   ever written into a project the user's own agent reports to.
2. **Unmistakable and disposable.** Every trace is labelled `sample ·`, every span carries
   `result.meta.sample = true`, every trace id starts with `5eed`, and the whole thing is one
   `DELETE /api/projects/{id}` away (Settings → Delete project) — which removes the runs with
   it, since the sample owns nothing else.

Off by default in tests (`SEED_EXAMPLES=false`, set by tests/conftest.py); on otherwise.
"""
from __future__ import annotations

import logging
import os

from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Flow, Run, User, Workspace, WorkspaceMember
from . import otel
from . import search as search_svc

log = logging.getLogger("provekit.seed")

#: The project the sample lands in. The portal matches on this exact string to offer a
#: shortcut from the empty state; renaming it in the UI only costs that shortcut.
SAMPLE_PROJECT_NAME = "Sample data (demo)"

#: Every seeded trace id starts here, so a sample trace is recognisable from its id alone —
#: in a URL, a log line, or a support screenshot. Same idea as doctor's probe trace.
SAMPLE_TRACE_PREFIX = "5eed"

#: Prefix on every root span's name, which is what the trace list renders as the label.
SAMPLE_LABEL = "sample · "


def seeding_enabled() -> bool:
    """Read from the environment rather than Settings: this is a first-run nicety, and adding
    a field to config.Settings for it would be a schema-ish change tests already opt out of
    via SEED_EXAMPLES."""
    return os.environ.get("SEED_EXAMPLES", "true").strip().lower() not in ("0", "false", "no")


# ---------------------------------------------------------------- the sample gallery
#
# Deliberately the same shapes provekit-demo sends (a support agent with a retrieval step and
# a chat call, a two-turn session, and one failure), so the portal's dashboard, sessions view
# and error panels all have something to render.

_CONVERSATIONS = [
    ("I want a refund for my order", "gpt-4o",
     "I've started your refund — it lands in 3–5 business days."),
    ("VPN won't connect after the update", "gpt-4o",
     "Forget the VPN profile and re-add it; that clears the stale auth token."),
    ("What's your pricing for a 20-person team?", "claude-sonnet-5",
     "The Pro plan is $49/seat/mo; annual billing saves ~15%."),
    ("How do I export my data?", "gpt-4o-mini",
     "Settings → Data → Export builds a downloadable JSON of your workspace."),
]

_SESSION = [
    ("Is the Pro plan monthly?", "The Pro plan is $49/seat/mo; annual billing saves ~15%."),
    ("And does annual billing save money?", "Annual billing saves about 15% over monthly."),
]


def _ids(trace: int, span: int) -> tuple[str, str]:
    """(trace_id, span_id) — 32 and 16 hex chars, both carrying the sample prefix."""
    return f"{SAMPLE_TRACE_PREFIX}{trace:028x}", f"{SAMPLE_TRACE_PREFIX}{trace:04x}{span:08x}"


def _attr(key: str, value) -> dict:
    if isinstance(value, bool):
        return {"key": key, "value": {"boolValue": value}}
    if isinstance(value, int):
        return {"key": key, "value": {"intValue": str(value)}}
    if isinstance(value, float):
        return {"key": key, "value": {"doubleValue": value}}
    return {"key": key, "value": {"stringValue": str(value)}}


def _span(name: str, trace: int, span: int, parent: int | None, start_ms: int, dur_ms: int,
          attrs: dict, error: str = "") -> dict:
    """One OTLP span. A non-empty `error` marks it failed (status code 2), as a real
    instrumented span that raised would be."""
    trace_id, span_id = _ids(trace, span)
    # A fixed base instant, comfortably in the past: services/otel flags spans that end in the
    # *future* as clock skew, and a sample must not arrive wearing a warning badge.
    base = 1_700_000_000_000 + start_ms
    return {
        "name": name, "traceId": trace_id, "spanId": span_id,
        "parentSpanId": _ids(trace, parent)[1] if parent is not None else "",
        "startTimeUnixNano": str(base * 1_000_000),
        "endTimeUnixNano": str((base + dur_ms) * 1_000_000),
        "status": {"code": 2, "message": error} if error else {"code": 1},
        "attributes": [_attr(k, v) for k, v in attrs.items()],
    }


def _chat_attrs(model: str, question: str, answer: str, session: str = "") -> dict:
    a = {
        "gen_ai.request.model": model,
        "gen_ai.request.temperature": 0.7,
        "gen_ai.input.messages": question,
        "gen_ai.output.messages": answer,
        "gen_ai.usage.input_tokens": 40 + len(question) // 4,
        "gen_ai.usage.output_tokens": 12 + len(answer) // 4,
        "gen_ai.response.finish_reasons": "stop",
    }
    if session:
        a["session.id"] = session
    return a


def sample_payload() -> dict:
    """The whole gallery as one OTLP ExportTraceServiceRequest.

    Built as OTLP and mapped by services/otel so seeded rows go through exactly the code real
    ingest does. A sample stored by a private shortcut would be a sample that renders
    differently from a real trace — which is the one thing it must not do.
    """
    spans: list[dict] = []
    t = 0
    for question, model, answer in _CONVERSATIONS:
        t += 1
        spans.append(_span(f"{SAMPLE_LABEL}support-agent", t, 0, None, 0, 640,
                           {"gen_ai.operation.name": "invoke_agent"}))
        spans.append(_span("retrieve", t, 1, 0, 5, 90,
                           {"gen_ai.tool.name": "kb_search", "gen_ai.input.messages": question}))
        spans.append(_span("chat", t, 2, 0, 100, 520, _chat_attrs(model, question, answer)))

    session_id = "conv-sample-1"
    for turn, (question, answer) in enumerate(_SESSION):
        t += 1
        spans.append(_span(f"{SAMPLE_LABEL}support-agent", t, 0, None, 0, 430,
                           {"gen_ai.operation.name": "invoke_agent", "session.id": session_id}))
        spans.append(_span("chat", t, 1, 0, 10, 400,
                           _chat_attrs("gpt-4o-mini", question, answer, session_id)))

    # One failure, so the dashboard error rate and a red trace have something real to show.
    t += 1
    boom = "upstream billing_api returned 503"
    spans.append(_span(f"{SAMPLE_LABEL}flaky-agent", t, 0, None, 0, 210,
                       {"gen_ai.operation.name": "invoke_agent"}, error=boom))
    spans.append(_span("call-upstream", t, 1, 0, 5, 190,
                       {"gen_ai.tool.name": "billing_api"}, error=boom))
    return {"resourceSpans": [{"scopeSpans": [{"spans": spans}]}]}


def sample_rows() -> list[dict]:
    """Run kwargs for the gallery, each stamped `result.meta.sample = true`.

    The stamp is on the *span*, not just the project, so a sample span still says what it is
    after it has been shared, exported, or pulled through the MCP server — anywhere the
    project name isn't standing next to it.
    """
    rows = otel.ingest(sample_payload())
    for kw in rows:
        kw.setdefault("result", {}).setdefault("meta", {})["sample"] = True
    return rows


# ---------------------------------------------------------------- installation

def _existing(db: Session, user: User) -> Workspace | None:
    return (db.query(Workspace)
            .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
            .filter(WorkspaceMember.user_id == user.id,
                    Workspace.name == SAMPLE_PROJECT_NAME)
            .order_by(Workspace.id).first())


def _has_room(db: Session, user: User) -> bool:
    """Never let the demo eat the account's last project slot. A sample the user has to delete
    before they can make their own project is worse than no sample at all."""
    cap = get_settings().max_projects_per_account
    if not cap or cap <= 0:
        return True
    owned = db.query(Workspace).filter(Workspace.owner_user_id == user.id).count()
    return owned + 1 < cap


def sample_flow_graph() -> dict:
    """The graph the landing hero shows — so a fresh Studio opens on the flow the marketing
    page advertises rather than a blank canvas. Left as a draft (never published): a seeded
    flow is something to open and run, not something claiming to be live in production."""
    return {
        "nodes": [
            {"id": "n1", "type": "trigger", "label": "New request", "position": {"x": 60, "y": 200}},
            {"id": "n2", "type": "agent", "label": "Knowledge agent", "position": {"x": 340, "y": 90},
             "config": {"model": "gpt-4o-mini",
                        "prompt": "You are a support agent. Answer the customer:\n{{input}}"}},
            {"id": "n3", "type": "logic", "label": "Route intent", "position": {"x": 340, "y": 320},
             "config": {"conditions": [{"op": "contains", "value": "refund", "label": "refund"}]}},
            {"id": "n4", "type": "approval", "label": "Refund approval", "position": {"x": 620, "y": 320},
             "config": {}},
            {"id": "n5", "type": "output", "label": "Send response", "position": {"x": 900, "y": 200},
             "config": {}},
        ],
        "edges": [
            {"id": "e1", "source": "n1", "target": "n2"},
            {"id": "e2", "source": "n2", "target": "n3"},
            {"id": "e3", "source": "n3", "target": "n4", "label": "refund"},
            {"id": "e4", "source": "n3", "target": "n5", "label": "else"},
            {"id": "e5", "source": "n4", "target": "n5"},
        ],
    }


def create_sample_project(db: Session, user: User) -> Workspace:
    """Create the sample project and fill it. Assumes the caller checked it doesn't exist."""
    # The user's real default must exist first: get_or_create_default_workspace returns the
    # lowest-id project they belong to, so seeding before it would make the demo their default
    # and every key they mint would land in fabricated data.
    from .workspace import get_or_create_default_workspace
    get_or_create_default_workspace(db, user)

    ws = Workspace(name=SAMPLE_PROJECT_NAME, owner_user_id=user.id)
    db.add(ws)
    db.commit()
    db.refresh(ws)
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=user.id, role="owner"))
    for kw in sample_rows():
        db.add(Run(workspace_id=ws.id, search_text=search_svc.text_for(kw), **kw))
    db.add(Flow(workspace_id=ws.id, name="Customer Support Agent",
                description="Sample flow — open it in the Studio, then ▷ Test with Mock.",
                graph=sample_flow_graph()))
    db.commit()
    return ws


def ensure_sample_project(db: Session, user: User) -> Workspace | None:
    """Idempotent, best-effort: give `user` a sample project if they should have one.

    Returns the project, or None when seeding is disabled, out of quota headroom, or failed.
    Callers are account-creation paths, so this never raises — a demo that can break signup
    is not a demo, it is an outage.
    """
    if not seeding_enabled():
        return None
    try:
        existing = _existing(db, user)
        if existing is not None:
            return existing
        if not _has_room(db, user):
            return None
        return create_sample_project(db, user)
    except Exception:
        db.rollback()
        log.exception("sample project seeding failed for user %s", getattr(user, "id", "?"))
        return None
