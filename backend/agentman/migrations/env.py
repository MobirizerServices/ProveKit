"""Alembic environment — pulls the URL and metadata from the app so migrations track models."""
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from agentman.config import get_settings
from agentman.database import Base
from agentman import models  # noqa: F401  (register all tables on Base.metadata)

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# The URL is read straight from settings and handed to create_engine below rather than
# stored on the alembic config: config values go through ConfigParser interpolation, so a
# DATABASE_URL whose password contains '%' would raise "invalid interpolation syntax".
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=get_settings().database_url, target_metadata=target_metadata,
                      literal_binds=True, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(get_settings().database_url, poolclass=pool.NullPool)
    with connectable.connect() as connection:
        # batch mode keeps ALTERs working on SQLite too
        context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
