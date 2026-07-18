"""run span hierarchy (trace_id, span_id, parent_span_id)

Revision ID: c3e5a7b9d1f2
Revises: b2d4f6a8c1e3
Create Date: 2026-07-18 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'c3e5a7b9d1f2'
down_revision = 'b2d4f6a8c1e3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('runs', schema=None) as batch_op:
        # server_default='' so the NOT NULL adds succeed on databases that already have rows
        batch_op.add_column(sa.Column('trace_id', sa.String(length=32), nullable=False, server_default=''))
        batch_op.add_column(sa.Column('span_id', sa.String(length=16), nullable=False, server_default=''))
        batch_op.add_column(sa.Column('parent_span_id', sa.String(length=16), nullable=False, server_default=''))
        batch_op.create_index(batch_op.f('ix_runs_trace_id'), ['trace_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('runs', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_runs_trace_id'))
        batch_op.drop_column('parent_span_id')
        batch_op.drop_column('span_id')
        batch_op.drop_column('trace_id')
