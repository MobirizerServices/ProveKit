"""AgentMan — a generic "Postman for agents": create, run, and debug prompts, MCP tools,
and agent endpoints across any provider."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .database import SessionLocal, init_db
from .models import Connection, Flow, Prompt
from .routers import connections, flows, library, prompts, run

logging.basicConfig(level=logging.INFO)
settings = get_settings()


def _seed_examples(db) -> None:
    if not settings.seed_examples or db.query(Connection).count() > 0:
        return
    db.add_all([
        Connection(name="OpenAI", kind="llm", config={
            "provider": "openai", "base_url": "", "api_key": settings.openai_api_key,
            "models": ["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini"]}),
        Connection(name="Anthropic", kind="llm", config={
            "provider": "anthropic", "base_url": "", "api_key": "",
            "models": ["claude-sonnet-4-5", "claude-haiku-4-5-20251001"]}),
        Connection(name="Magari · catalog (MCP)", kind="mcp", config={"url": settings.magari_mcp_url}),
        Connection(name="Magari · backend (agent)", kind="agent", config={
            "base_url": settings.magari_backend_url, "headers": {}}),
    ])
    db.commit()
    logging.getLogger("agentman").info("seeded example connections")


def _seed_prompts(db) -> None:
    if db.query(Prompt).count() > 0:
        return
    db.add_all([
        Prompt(key="assistant.system", name="Helpful assistant", description="A general system prompt.",
               content="You are a helpful, concise assistant. Answer clearly and cite sources when relevant."),
        Prompt(key="extract.json", name="JSON extractor", description="Extract structured fields as JSON.",
               content="Extract the requested fields from the input. Return ONLY valid JSON, no prose. Use null when a field is not present."),
        Prompt(key="classify.intent", name="Intent classifier", description="Classify a message into one label.",
               content="Classify the user's message into exactly one of: {{labels}}. Reply with only the label."),
    ])
    db.commit()


def _seed_flows(db) -> None:
    if db.query(Flow).count() > 0:
        return
    mcp = db.query(Connection).filter(Connection.kind == "mcp").first()
    db.add(Flow(
        name="Inventory check",
        description="Input a product → check stock via MCP → branch on availability.",
        nodes=[
            {"id": "input", "type": "input", "position": {"x": 40, "y": 140}, "data": {"title": "Input"}, "config": {"sample": {"product": "Berge"}}},
            {"id": "tool", "type": "tool", "position": {"x": 320, "y": 140}, "data": {"title": "Check stock"}, "config": {"connection_id": mcp.id if mcp else None, "tool": "check_inventory", "args": {"product": "{{input.product}}"}}},
            {"id": "cond", "type": "condition", "position": {"x": 620, "y": 140}, "data": {"title": "In stock?"}, "config": {"left": "{{tool.status}}", "op": "==", "right": "in_stock"}},
            {"id": "yes", "type": "output", "position": {"x": 900, "y": 60}, "data": {"title": "Available"}, "config": {"value": "{{tool}}"}},
            {"id": "no", "type": "output", "position": {"x": 900, "y": 240}, "data": {"title": "Out of stock"}, "config": {"value": "{{tool.status}}"}},
        ],
        edges=[
            {"id": "e1", "source": "input", "target": "tool"},
            {"id": "e2", "source": "tool", "target": "cond"},
            {"id": "e3", "source": "cond", "target": "yes", "condition": {"branch": "true"}},
            {"id": "e4", "source": "cond", "target": "no", "condition": {"branch": "false"}},
        ],
    ))
    db.commit()


def _seed_demo(db) -> None:
    """Idempotently add a keyless demo agent + example flows so the app is runnable out of the
    box (no API key). Checks by name, so it also upgrades an existing database."""
    demo = db.query(Connection).filter(Connection.name == "Demo Assistant (mock)").first()
    if not demo:
        demo = Connection(name="Demo Assistant (mock)", kind="llm",
                          config={"provider": "mock", "base_url": "", "api_key": "", "models": ["demo-mock"]})
        db.add(demo); db.commit(); db.refresh(demo)
    existing = {f.name for f in db.query(Flow).all()}
    add = []
    if "Demo · Ask the agent" not in existing:
        add.append(Flow(
            name="Demo · Ask the agent",
            description="Keyless demo — ask a question, the mock agent streams an answer.",
            nodes=[
                {"id": "input", "type": "input", "position": {"x": 60, "y": 160}, "data": {"title": "Question"}, "config": {"sample": {"question": "What is an AI agent?"}}},
                {"id": "ask", "type": "prompt", "position": {"x": 360, "y": 160}, "data": {"title": "Ask agent"}, "config": {"connection_id": demo.id, "model": "demo-mock", "system": "You are a helpful assistant.", "user": "{{input.question}}"}},
                {"id": "out", "type": "output", "position": {"x": 680, "y": 160}, "data": {"title": "Answer"}, "config": {"value": "{{ask.text}}"}},
            ],
            edges=[{"id": "d1", "source": "input", "target": "ask"}, {"id": "d2", "source": "ask", "target": "out"}]))
    if "Demo · Triage & route" not in existing:
        add.append(Flow(
            name="Demo · Triage & route",
            description="Keyless demo — the mock agent replies, then a condition routes urgent vs normal.",
            nodes=[
                {"id": "input", "type": "input", "position": {"x": 40, "y": 200}, "data": {"title": "Message"}, "config": {"sample": {"text": "URGENT: my order never arrived, I want a refund ASAP"}}},
                {"id": "reply", "type": "prompt", "position": {"x": 320, "y": 200}, "data": {"title": "Draft reply"}, "config": {"connection_id": demo.id, "model": "demo-mock", "system": "You are a support assistant.", "user": "{{input.text}}"}},
                {"id": "cond", "type": "condition", "position": {"x": 620, "y": 200}, "data": {"title": "Urgent?"}, "config": {"left": "{{reply.text}}", "op": "contains", "right": "urgent"}},
                {"id": "human", "type": "output", "position": {"x": 900, "y": 120}, "data": {"title": "Human review"}, "config": {"value": "escalate: {{reply.text}}"}},
                {"id": "auto", "type": "output", "position": {"x": 900, "y": 300}, "data": {"title": "Auto-send"}, "config": {"value": "{{reply.text}}"}},
            ],
            edges=[
                {"id": "t1", "source": "input", "target": "reply"},
                {"id": "t2", "source": "reply", "target": "cond"},
                {"id": "t3", "source": "cond", "target": "human", "condition": {"branch": "true"}},
                {"id": "t4", "source": "cond", "target": "auto", "condition": {"branch": "false"}},
            ]))
    if add:
        db.add_all(add); db.commit()
        logging.getLogger("agentman").info("seeded demo agent + flows")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    db = SessionLocal()
    try:
        _seed_examples(db)
        _seed_prompts(db)
        _seed_flows(db)
        _seed_demo(db)
    finally:
        db.close()
    yield


app = FastAPI(title="AgentMan", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(connections.router)
app.include_router(library.router)
app.include_router(prompts.router)
app.include_router(flows.router)
app.include_router(run.router)


@app.get("/")
def root():
    return {"service": "AgentMan", "docs": "/docs"}
