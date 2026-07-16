"""SQLAlchemy engine + session (SQLite)."""
from sqlalchemy import MetaData, create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import get_settings

settings = get_settings()
_is_sqlite = settings.database_url.startswith("sqlite")
connect_args = {"check_same_thread": False} if _is_sqlite else {}
# A concurrent stream holds a pooled connection for its lifetime; if the pool is exhausted,
# the next (synchronous) checkout blocks the event loop. Size the pool to the stream
# concurrency so checkouts never block the loop.
if _is_sqlite and ":memory:" in settings.database_url:
    _pool = {}
else:
    _pool = {"pool_size": 20, "max_overflow": max(10, settings.thread_pool_size)}
    if not _is_sqlite:
        _pool["pool_pre_ping"] = True  # Postgres: drop stale connections (harmful w/ SQLite WAL pragma)
engine = create_engine(settings.database_url, connect_args=connect_args, **_pool)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

if _is_sqlite:
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):
        # WAL lets readers and a writer coexist; busy_timeout makes a contended write wait
        # briefly instead of erroring — important now that many async streams write runs.
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.close()

# Named constraints so Alembic's SQLite batch mode (ALTER via table-rebuild) can re-add them.
_NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=_NAMING)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from . import models  # noqa: F401
    if settings.database_url.startswith("sqlite"):
        # Local/dev/tests: create_all is idempotent and needs no migration tooling.
        Base.metadata.create_all(bind=engine)
    else:
        # Postgres/prod: schema is owned by Alembic migrations.
        _run_migrations()


def _run_migrations() -> None:
    import os

    from alembic import command
    from alembic.config import Config
    cfg = Config(os.path.join(os.path.dirname(os.path.dirname(__file__)), "alembic.ini"))
    command.upgrade(cfg, "head")
