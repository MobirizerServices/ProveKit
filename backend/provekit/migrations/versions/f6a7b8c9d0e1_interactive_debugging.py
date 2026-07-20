"""interactive debugging: provider_connections + replay_runs

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-07-20 05:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'f6a7b8c9d0e1'
down_revision = 'e5f6a7b8c9d0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('provider_connections',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('workspace_id', sa.Integer(), nullable=True),
    sa.Column('provider', sa.String(length=24), nullable=False),
    sa.Column('label', sa.String(length=120), nullable=False),
    sa.Column('key_sealed', sa.Text(), nullable=False),
    sa.Column('key_hint', sa.String(length=24), nullable=False),
    sa.Column('base_url', sa.String(length=300), nullable=False),
    sa.Column('last_used_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_provider_connections_workspace_id_workspaces')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_provider_connections'))
    )
    with op.batch_alter_table('provider_connections', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_provider_connections_workspace_id'), ['workspace_id'], unique=False)

    op.create_table('replay_runs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('workspace_id', sa.Integer(), nullable=True),
    sa.Column('origin_trace_id', sa.String(length=32), nullable=False),
    sa.Column('fork_span_id', sa.String(length=16), nullable=False),
    sa.Column('overrides', sa.JSON(), nullable=False),
    sa.Column('mode', sa.String(length=16), nullable=False),
    sa.Column('new_trace_id', sa.String(length=32), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_replay_runs_workspace_id_workspaces')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_replay_runs'))
    )
    with op.batch_alter_table('replay_runs', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_replay_runs_workspace_id'), ['workspace_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_replay_runs_origin_trace_id'), ['origin_trace_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_replay_runs_new_trace_id'), ['new_trace_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('replay_runs', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_replay_runs_new_trace_id'))
        batch_op.drop_index(batch_op.f('ix_replay_runs_origin_trace_id'))
        batch_op.drop_index(batch_op.f('ix_replay_runs_workspace_id'))
    op.drop_table('replay_runs')
    with op.batch_alter_table('provider_connections', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_provider_connections_workspace_id'))
    op.drop_table('provider_connections')
