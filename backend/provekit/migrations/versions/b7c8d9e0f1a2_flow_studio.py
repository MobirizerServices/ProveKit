"""flow_studio — visual agent workflows, their published snapshots, and test runs

Revision ID: b7c8d9e0f1a2
Revises: c1d2e3f4a5b6
Create Date: 2026-07-23 16:40:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'b7c8d9e0f1a2'
down_revision = 'c1d2e3f4a5b6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'flows',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('workspace_id', sa.Integer(), nullable=True),
        sa.Column('name', sa.String(length=160), nullable=False, server_default=''),
        sa.Column('description', sa.Text(), nullable=False, server_default=''),
        sa.Column('graph', sa.JSON(), nullable=True),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('published_version', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'],
                                name=op.f('fk_flows_workspace_id_workspaces')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_flows')),
    )
    with op.batch_alter_table('flows', schema=None) as b:
        b.create_index(b.f('ix_flows_workspace_id'), ['workspace_id'])

    op.create_table(
        'flow_versions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('workspace_id', sa.Integer(), nullable=True),
        sa.Column('flow_id', sa.Integer(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('graph', sa.JSON(), nullable=True),
        sa.Column('note', sa.String(length=300), nullable=False, server_default=''),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'],
                                name=op.f('fk_flow_versions_workspace_id_workspaces')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_flow_versions')),
    )
    with op.batch_alter_table('flow_versions', schema=None) as b:
        b.create_index(b.f('ix_flow_versions_workspace_id'), ['workspace_id'])
        b.create_index(b.f('ix_flow_versions_flow_id'), ['flow_id'])

    op.create_table(
        'flow_runs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('workspace_id', sa.Integer(), nullable=True),
        sa.Column('flow_id', sa.Integer(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='running'),
        sa.Column('input', sa.Text(), nullable=False, server_default=''),
        sa.Column('output', sa.Text(), nullable=False, server_default=''),
        sa.Column('error', sa.Text(), nullable=False, server_default=''),
        sa.Column('steps', sa.JSON(), nullable=True),
        sa.Column('duration_ms', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('trace_id', sa.String(length=32), nullable=False, server_default=''),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'],
                                name=op.f('fk_flow_runs_workspace_id_workspaces')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_flow_runs')),
    )
    with op.batch_alter_table('flow_runs', schema=None) as b:
        b.create_index(b.f('ix_flow_runs_workspace_id'), ['workspace_id'])
        b.create_index(b.f('ix_flow_runs_flow_id'), ['flow_id'])
        b.create_index(b.f('ix_flow_runs_trace_id'), ['trace_id'])


def downgrade() -> None:
    with op.batch_alter_table('flow_runs', schema=None) as b:
        b.drop_index(b.f('ix_flow_runs_trace_id'))
        b.drop_index(b.f('ix_flow_runs_flow_id'))
        b.drop_index(b.f('ix_flow_runs_workspace_id'))
    op.drop_table('flow_runs')
    with op.batch_alter_table('flow_versions', schema=None) as b:
        b.drop_index(b.f('ix_flow_versions_flow_id'))
        b.drop_index(b.f('ix_flow_versions_workspace_id'))
    op.drop_table('flow_versions')
    with op.batch_alter_table('flows', schema=None) as b:
        b.drop_index(b.f('ix_flows_workspace_id'))
    op.drop_table('flows')
