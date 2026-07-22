"""runs.search_text + a GIN index on its tsvector (Postgres)

Revision ID: c5d6e7f8a9b0
Revises: b4c5d6e7f8a9
Create Date: 2026-07-22 13:00:00.000000

The column is left NULL for existing rows rather than backfilled here. Backfilling would mean
reading and rewriting every span in the table inside a migration that runs on boot — on a
large instance that is an outage. `services/search.clause()` keeps matching the old JSON
columns for rows where search_text IS NULL, so history stays searchable (on the old, slow
path) and new spans get the fast one. Run scripts/backfill_search.py to convert history at
your own pace.
"""
from alembic import op
import sqlalchemy as sa


revision = 'c5d6e7f8a9b0'
down_revision = 'b4c5d6e7f8a9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('runs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('search_text', sa.Text(), nullable=True))

    # The point of the exercise: a leading-wildcard LIKE can never use an index, a tsvector
    # GIN index can. Postgres only — SQLite has no tsvector and falls back to LIKE over this
    # (much narrower) column.
    if op.get_bind().dialect.name == 'postgresql':
        op.execute("CREATE INDEX ix_runs_search_tsv ON runs "
                   "USING GIN (to_tsvector('english', coalesce(search_text, '')))")


def downgrade() -> None:
    if op.get_bind().dialect.name == 'postgresql':
        op.execute("DROP INDEX IF EXISTS ix_runs_search_tsv")
    with op.batch_alter_table('runs', schema=None) as batch_op:
        batch_op.drop_column('search_text')
