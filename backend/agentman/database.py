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
    if settings.database_url.startswith("sqlite") and ":memory:" in settings.database_url:
        # Ephemeral in-memory DB (tests only): create_all is fast and needs no migration tooling.
        Base.metadata.create_all(bind=engine)
    else:
        # Every persistent DB — file-based SQLite included — is owned by Alembic so that
        # future column/index changes actually apply on upgrade. create_all only ever adds
        # whole tables and would silently skip new columns on an existing local database.
        _run_migrations()


# Revision that first introduced each column, newest first — used to adopt a pre-migration
# database (built by the old create_all path) at the revision matching its actual columns.
_ADOPT_BY_COLUMN = [
    ("users", "token_version", "a1b2c3d4e5f6"),
    ("users", "email_verified", "323eb73d463c"),
    ("workspaces", "ingest_key_hash", "819ed5ff183e"),
]
_BASELINE_REVISION = "49e8ab812556"


# Postgres advisory-lock key ("AGMN") used to serialize migrations across uvicorn workers.
_MIGRATION_LOCK_ID = 0x4147_4D4E


def _migration_config():
    """Alembic config built in code rather than read from alembic.ini.

    The migrations ship *inside* the package, so script_location is resolved absolutely
    from `__file__`. Reading alembic.ini instead would only work when the process runs
    from a source checkout — a `pip install`ed wheel has no alembic.ini next to the
    package, and the app would fail to boot. alembic.ini stays for `alembic` CLI use.
    """
    import os

    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), "migrations"))
    # No sqlalchemy.url here on purpose: env.py reads it from settings and builds the engine
    # itself, which keeps a '%' in the password out of ConfigParser's interpolation.
    return cfg


def _run_migrations() -> None:
    cfg = _migration_config()
    if settings.database_url.startswith("sqlite"):
        _migrate_to_head(cfg)  # single process — no cross-worker race
        return
    # With `--workers N` every worker runs the lifespan and would race through upgrade
    # (DuplicateTable / duplicate alembic_version). A Postgres session advisory lock lets
    # exactly one run at a time; the rest block, then find the schema already at head.
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.exec_driver_sql("SELECT pg_advisory_lock(%s)", (_MIGRATION_LOCK_ID,))
        try:
            _migrate_to_head(cfg)
        finally:
            conn.exec_driver_sql("SELECT pg_advisory_unlock(%s)", (_MIGRATION_LOCK_ID,))


def _migrate_to_head(cfg) -> None:
    from alembic import command
    from alembic.runtime.migration import MigrationContext
    from sqlalchemy import inspect

    insp = inspect(engine)
    with engine.connect() as conn:
        current = MigrationContext.configure(conn).get_current_revision()
    if current is None and insp.has_table("users"):
        # A database created by create_all before migrations existed has the tables but no
        # alembic version. Stamp it at the revision matching its columns so `upgrade` applies
        # only what's genuinely missing instead of trying to re-create existing tables.
        stamp_at = _BASELINE_REVISION
        for table, column, revision in _ADOPT_BY_COLUMN:
            if any(c["name"] == column for c in insp.get_columns(table)):
                stamp_at = revision
                break
        command.stamp(cfg, stamp_at)
    command.upgrade(cfg, "head")
