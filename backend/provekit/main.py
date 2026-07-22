"""ProveKit — drop-in agent tracing. Add one decorator, get a project key, and review
every run your agent makes. No connections to configure, no SDK to swap."""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .database import init_db
from .observability import (
    BodySizeLimitMiddleware,
    RequestIDMiddleware,
    SecurityHeadersMiddleware,
    healthz,
    init_sentry,
    setup_logging,
)
from .routers import (
    admin, alerts, apikeys, auth, datasets, experiments, metrics, playground, projects, traces,
)

logging.basicConfig(level=logging.INFO)
settings = get_settings()
setup_logging()
init_sentry()


_WEAK_KEYS = {"", "dev-only-change-me", "change-me", "changeme", "secret"}


def _guard_production_config() -> None:
    """Refuse to boot hosted mode with an unset/weak SECRET_KEY — otherwise every stored
    credential is decryptable by anyone who reads the (default, public) value."""
    s = settings
    weak_key = s.secret_key.strip() in _WEAK_KEYS or len(s.secret_key.strip()) < 16
    if s.hosted and weak_key:
        raise RuntimeError(
            "HOSTED=true requires a strong SECRET_KEY (>=16 chars, not the dev default). "
            "Generate one: python -c \"import secrets; print(secrets.token_urlsafe(48))\"")
    # Not hosted but using a server database with a weak key = credentials encrypted under a
    # public constant. Legitimate for the dev compose; warn loudly if it reaches a real server.
    if not s.hosted and weak_key and not s.database_url.startswith("sqlite"):
        logging.getLogger("provekit").warning(
            "Weak/default SECRET_KEY with a non-SQLite database and HOSTED=false — stored "
            "credentials are encrypted under a public constant. Set a strong SECRET_KEY (and "
            "HOSTED=true) before exposing this to a network.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    _guard_production_config()
    # Raise the threadpool ceiling: streaming responses run their sync generators here, so
    # the default ~40 tokens caps concurrent streams. This lifts it without an async rewrite.
    try:
        import anyio
        anyio.to_thread.current_default_thread_limiter().total_tokens = settings.thread_pool_size
    except Exception:
        pass
    init_db()
    tasks = [asyncio.create_task(_drain_spool_forever()),
             asyncio.create_task(_roll_up_forever())]
    try:
        yield
    finally:
        for t in tasks:
            t.cancel()


async def _roll_up_forever() -> None:
    """Fold closed hours into metric rollups in the background (services/rollups.py).

    The read path builds whatever is missing anyway, so this is not required for correctness —
    it just means the first dashboard load after a quiet night isn't the one that pays for it.
    """
    from .database import SessionLocal
    from .services import rollups
    interval = max(60.0, settings.rollup_interval_seconds)
    while True:
        try:
            def _pass():
                db = SessionLocal()
                try:
                    return rollups.backfill_all(db)
                finally:
                    db.close()
            await run_in_threadpool(_pass)
        except asyncio.CancelledError:
            raise
        except Exception:
            logging.getLogger("provekit").exception("metric rollup pass failed")
        await asyncio.sleep(interval)


async def _drain_spool_forever() -> None:
    """Retry ingest batches that were staged but never landed (services/spool.py).

    Runs once at startup — which is what recovers a batch that was in flight when the process
    died — and then on an interval, so a database outage self-heals instead of needing an
    operator to notice. The drain itself is blocking DB work, hence the threadpool.
    """
    from .routers.traces import drain_spool
    from .services import spool
    interval = max(1.0, settings.spool_drain_seconds)
    while True:
        try:
            if spool.enabled() and spool.depth():
                await run_in_threadpool(drain_spool)
        except asyncio.CancelledError:
            raise
        except Exception:
            logging.getLogger("provekit").exception("spool drain pass failed")
        await asyncio.sleep(interval)


app = FastAPI(title="ProveKit", version="0.1.0", lifespan=lifespan)

# add_middleware inserts at the front, so the LAST one added is the OUTERMOST. Resulting
# order: CORS -> SecurityHeaders -> RequestID -> BodySizeLimit -> app. Both SecurityHeaders
# and RequestID must stay outside BodySizeLimit, whose 413 short-circuits the rest of the
# stack — inside them, that response would carry no security headers and no X-Request-ID.
app.add_middleware(BodySizeLimitMiddleware)
app.add_middleware(RequestIDMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,  # session cookies
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(apikeys.router)
app.include_router(traces.router)
app.include_router(traces.ws_router)
app.include_router(traces.runs_router)
app.include_router(datasets.router)
app.include_router(datasets.key_router)
app.include_router(experiments.router)
app.include_router(experiments.key_router)
app.include_router(metrics.router)
app.include_router(alerts.router)
app.include_router(projects.router)
app.include_router(playground.router)
app.include_router(admin.router)


@app.get("/")
def root():
    return {"service": "ProveKit", "docs": "/docs"}


@app.get("/healthz")
def health():
    return healthz()
