"""AgentMan — a generic "Postman for agents": create, run, and debug prompts, MCP tools,
and agent endpoints across any provider."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .database import SessionLocal, init_db
from .models import Connection
from .observability import RequestIDMiddleware, healthz, init_sentry, setup_logging
from .routers import auth, connections, deployments, flows, library, prompts, run, runtime, traces

logging.basicConfig(level=logging.INFO)
settings = get_settings()
setup_logging()
init_sentry()


def _reseal_connections(db) -> None:
    """Upgrade plaintext secrets from older databases to encrypted-at-rest: force each
    config back through SealedJSON's bind processor (flag_modified beats SQLAlchemy's
    equal-value change suppression). Idempotent — already-sealed values stay sealed."""
    from sqlalchemy.orm.attributes import flag_modified
    for c in db.query(Connection).all():
        flag_modified(c, "config")
    db.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Raise the threadpool ceiling: streaming responses run their sync generators here, so
    # the default ~40 tokens caps concurrent streams. This lifts it without an async rewrite.
    try:
        import anyio
        anyio.to_thread.current_default_thread_limiter().total_tokens = settings.thread_pool_size
    except Exception:
        pass
    init_db()
    db = SessionLocal()
    try:
        _reseal_connections(db)  # per-workspace seeding happens on first workspace access
    finally:
        db.close()
    yield


app = FastAPI(title="AgentMan", version="0.1.0", lifespan=lifespan)

app.add_middleware(RequestIDMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,  # session cookies
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(connections.router)
app.include_router(library.router)
app.include_router(prompts.router)
app.include_router(flows.router)
app.include_router(run.router)
app.include_router(traces.router)
app.include_router(deployments.router)
app.include_router(runtime.router)


@app.get("/")
def root():
    return {"service": "AgentMan", "docs": "/docs"}


@app.get("/healthz")
def health():
    return healthz()
