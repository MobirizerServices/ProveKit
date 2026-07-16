"""Workspace resolution + per-workspace seeding.

Each user gets a default workspace on first use; its example connections, prompts, and
demo flows are seeded then (not globally at startup). current_workspace is the dependency
every tenant-scoped router uses to isolate data.
"""
from __future__ import annotations

import logging

from fastapi import Depends
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..models import Connection, Flow, Prompt, Workspace, WorkspaceMember
from .auth import get_current_user

log = logging.getLogger("agentman.workspace")


def get_or_create_default_workspace(db: Session, user) -> Workspace:
    w = (db.query(Workspace)
         .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
         .filter(WorkspaceMember.user_id == user.id)
         .order_by(Workspace.id).first())
    if w:
        return w
    w = Workspace(name="My workspace", owner_user_id=user.id)
    db.add(w); db.commit(); db.refresh(w)
    db.add(WorkspaceMember(workspace_id=w.id, user_id=user.id, role="owner")); db.commit()
    seed_workspace(db, w.id)
    return w


def current_workspace(user=Depends(get_current_user), db: Session = Depends(get_db)) -> Workspace:
    return get_or_create_default_workspace(db, user)


# ---- seeding (per workspace) ----
def _seed_connections(db: Session, ws: int) -> None:
    s = get_settings()
    rows = [Connection(workspace_id=ws, name="Demo Assistant (mock)", kind="llm",
                       config={"provider": "mock", "base_url": "", "api_key": "", "models": ["demo-mock"]})]
    if s.seed_examples:
        rows += [
            Connection(workspace_id=ws, name="OpenAI", kind="llm", config={
                "provider": "openai", "base_url": "", "api_key": s.openai_api_key,
                "models": ["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini"]}),
            Connection(workspace_id=ws, name="Anthropic", kind="llm", config={
                "provider": "anthropic", "base_url": "", "api_key": "",
                "models": ["claude-sonnet-4-5", "claude-haiku-4-5-20251001"]}),
            Connection(workspace_id=ws, name="Magari · catalog (MCP)", kind="mcp", config={"url": s.magari_mcp_url}),
        ]
    db.add_all(rows); db.commit()


def _seed_prompts(db: Session, ws: int) -> None:
    db.add_all([
        Prompt(workspace_id=ws, key="assistant.system", name="Helpful assistant",
               description="A general system prompt.",
               content="You are a helpful, concise assistant. Answer clearly and cite sources when relevant."),
        Prompt(workspace_id=ws, key="extract.json", name="JSON extractor",
               description="Extract structured fields as JSON.",
               content="Extract the requested fields from the input. Return ONLY valid JSON, no prose. Use null when a field is not present."),
    ])
    db.commit()


def _seed_flows(db: Session, ws: int) -> None:
    demo = db.query(Connection).filter(Connection.workspace_id == ws, Connection.name == "Demo Assistant (mock)").first()
    did = demo.id if demo else None
    db.add(Flow(workspace_id=ws, name="Demo · Ask the agent",
                description="Keyless demo — ask a question, the mock agent streams an answer.",
                nodes=[
                    {"id": "input", "type": "input", "position": {"x": 60, "y": 160}, "data": {"title": "Question"}, "config": {"sample": {"question": "What is an AI agent?"}}},
                    {"id": "ask", "type": "prompt", "position": {"x": 360, "y": 160}, "data": {"title": "Ask agent"}, "config": {"connection_id": did, "model": "demo-mock", "system": "You are a helpful assistant.", "user": "{{input.question}}"}},
                    {"id": "out", "type": "output", "position": {"x": 680, "y": 160}, "data": {"title": "Answer"}, "config": {"value": "{{ask.text}}"}},
                ],
                edges=[{"id": "d1", "source": "input", "target": "ask"}, {"id": "d2", "source": "ask", "target": "out"}]))
    db.commit()


def seed_workspace(db: Session, ws: int) -> None:
    _seed_connections(db, ws)
    _seed_prompts(db, ws)
    _seed_flows(db, ws)
    log.info("seeded workspace %s", ws)
