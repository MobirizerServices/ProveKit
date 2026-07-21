"""idempotent ingest — one row per (workspace, trace_id, span_id)

OTLP exporters retry on 5xx and replay the whole batch, so a retried export used to insert
every span a second time, inflating span counts, tokens and cost. Dedupe what already landed,
then add the partial unique index that makes the repeat insert impossible.

Scoped by trace_id because OTel only guarantees span-id uniqueness within a trace.

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-07-21 09:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'c9d0e1f2a3b4'
down_revision = 'b8c9d0e1f2a3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing duplicates would make the unique index un-creatable. Keep the lowest id of each
    # (workspace_id, span_id) group — the first copy that landed — and drop the retry copies.
    op.execute(sa.text("""
        DELETE FROM runs WHERE id NOT IN (
            SELECT MIN(id) FROM runs WHERE span_id != ''
            GROUP BY workspace_id, trace_id, span_id
        ) AND span_id != ''
    """))
    with op.batch_alter_table('runs', schema=None) as batch_op:
        batch_op.create_index('uq_run_span', ['workspace_id', 'trace_id', 'span_id'], unique=True,
                              sqlite_where=sa.text("span_id != ''"),
                              postgresql_where=sa.text("span_id != ''"))


def downgrade() -> None:
    with op.batch_alter_table('runs', schema=None) as batch_op:
        batch_op.drop_index('uq_run_span')
