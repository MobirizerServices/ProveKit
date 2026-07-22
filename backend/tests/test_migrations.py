"""Migrations, exercised on a database that has data in it.

Migrations run automatically on boot (database.py `_run_migrations`), against whatever rows a
deployment already has. Until now nothing tested that: the suite only ever migrated an empty
database, which is the one case where a broken data migration looks fine. A column added with
a NOT NULL and no server default, or an index built on a column that has duplicates, fails
only when there are rows — i.e. only in production.

These run the real Alembic chain against a throwaway SQLite file, so they exercise the same
code path boot does. SQLite is the stricter test for the batch_alter_table pattern the
migrations use (it rebuilds the table, where Postgres alters in place), so a migration that
survives here is unlikely to surprise on Postgres — though it is not a substitute for
rehearsing an upgrade against a production dump.
"""
import os
import tempfile
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from provekit.config import get_settings


@pytest.fixture
def scratch_db():
    """A temp database the migration chain can be run over end to end.

    `env.py` reads the URL from the cached settings, so the override has to go through the
    environment and the cache has to be cleared on both sides — otherwise this would migrate
    (and then drop tables in) the database the rest of the suite is using.
    """
    tmp = tempfile.mkdtemp(prefix="provekit-mig-")
    url = f"sqlite:///{tmp}/mig.db"
    prev = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    get_settings.cache_clear()
    cfg = Config()
    cfg.set_main_option("script_location",
                        str(Path(__file__).resolve().parents[1] / "provekit" / "migrations"))
    try:
        yield cfg, url
    finally:
        if prev is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = prev
        get_settings.cache_clear()


def _seed(url: str) -> None:
    """Representative rows in the tables migrations actually touch.

    Seeded through the ORM rather than raw INSERTs: most columns carry Python-side defaults
    (`default=""`), not server defaults, so hand-written SQL has to spell out every column and
    breaks the moment one is added — which is exactly the change this file exists to test.
    """
    from sqlalchemy.orm import Session

    from provekit.models import Run, User, Workspace
    eng = create_engine(url)
    with Session(eng) as s:
        user = User(email="a@b.c", password_hash="x")
        s.add(user)
        s.flush()
        ws = Workspace(name="w", owner_user_id=user.id)
        s.add(ws)
        s.flush()
        for i in range(50):
            s.add(Run(workspace_id=ws.id, type="llm", label=f"r{i}", status="completed",
                      duration_ms=10, trace_id=f"{i:032x}", span_id=f"{i:016x}",
                      request={}, result={}))
        s.commit()
    eng.dispose()


def _runs(url: str) -> int:
    eng = create_engine(url)
    with eng.connect() as c:
        n = c.execute(text("SELECT count(*) FROM runs")).scalar()
    eng.dispose()
    return n


def test_upgrade_from_scratch_reaches_head(scratch_db):
    cfg, url = scratch_db
    command.upgrade(cfg, "head")
    names = inspect(create_engine(url)).get_table_names()
    assert {"users", "workspaces", "runs", "alembic_version"} <= set(names)


def test_downgrade_and_re_upgrade_preserves_rows(scratch_db):
    """The property that matters on a rollback: stepping back and forward again must not eat
    data. A batch_alter_table that forgets to copy a column loses rows here and only here."""
    cfg, url = scratch_db
    command.upgrade(cfg, "head")
    _seed(url)
    assert _runs(url) == 50
    command.downgrade(cfg, "-1")
    command.upgrade(cfg, "head")
    assert _runs(url) == 50


def test_full_chain_round_trips(scratch_db):
    """Every migration's downgrade is exercised. A missing or wrong downgrade means an
    operator who needs to roll back discovers it during the incident."""
    cfg, url = scratch_db
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    eng = create_engine(url)
    remaining = set(inspect(eng).get_table_names()) - {"alembic_version"}
    eng.dispose()
    assert remaining == set(), f"downgrade to base left tables behind: {sorted(remaining)}"
    command.upgrade(cfg, "head")     # and the schema rebuilds


def test_stepwise_upgrade_matches_a_single_jump(scratch_db):
    """Applying revisions one at a time must land on the same schema as going straight to head
    — they diverge when a migration depends on state a later one happens to provide."""
    cfg, url = scratch_db
    from alembic.script import ScriptDirectory
    revs = list(reversed([s.revision for s in ScriptDirectory.from_config(cfg).walk_revisions()]))
    for rev in revs:
        command.upgrade(cfg, rev)
    eng = create_engine(url)
    stepwise = {t: sorted(c["name"] for c in inspect(eng).get_columns(t))
                for t in sorted(inspect(eng).get_table_names())}
    eng.dispose()

    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    eng = create_engine(url)
    direct = {t: sorted(c["name"] for c in inspect(eng).get_columns(t))
              for t in sorted(inspect(eng).get_table_names())}
    eng.dispose()
    assert stepwise == direct


def test_hot_path_indexes_exist_after_migration(scratch_db):
    """The indexes from #18 must come from the migration, not only from create_all — a model
    that carries an index the chain never builds is an index production doesn't have."""
    cfg, url = scratch_db
    command.upgrade(cfg, "head")
    eng = create_engine(url)
    names = {i["name"] for i in inspect(eng).get_indexes("runs")}
    eng.dispose()
    assert {"ix_runs_ws_root", "ix_runs_ws_created", "ix_runs_ws_status_created",
            "ix_runs_ws_session"} <= names, sorted(names)
