"""metric_rollups / model_rollups — hourly pre-aggregation for the dashboard

Revision ID: a3b4c5d6e7f8
Revises: f2a3b4c5d6e7
Create Date: 2026-07-22 10:15:00.000000

No backfill here. Rollups are built lazily on the read path (services/rollups.ensure_range)
and by a background pass, so an upgrade doesn't have to fold every historical hour inside the
migration — which on a large instance would turn a boot-time migration into an outage.
"""
from alembic import op
import sqlalchemy as sa


revision = 'a3b4c5d6e7f8'
down_revision = 'f2a3b4c5d6e7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'metric_rollups',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('workspace_id', sa.Integer(), nullable=True),
        sa.Column('bucket', sa.DateTime(), nullable=False),
        sa.Column('trace_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('error_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('latency_hist', sa.JSON(), nullable=True),
        sa.Column('input_tokens', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('output_tokens', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('model_calls', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('usage_spans', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('fail_by_type', sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'],
                                name=op.f('fk_metric_rollups_workspace_id_workspaces')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_metric_rollups')),
    )
    with op.batch_alter_table('metric_rollups', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_metric_rollups_workspace_id'), ['workspace_id'])
        batch_op.create_index(batch_op.f('ix_metric_rollups_bucket'), ['bucket'])
        batch_op.create_index('uq_metric_rollup', ['workspace_id', 'bucket'], unique=True)

    op.create_table(
        'model_rollups',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('workspace_id', sa.Integer(), nullable=True),
        sa.Column('bucket', sa.DateTime(), nullable=False),
        sa.Column('model', sa.String(length=200), nullable=False, server_default=''),
        sa.Column('calls', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('input_tokens', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('output_tokens', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('usage_spans', sa.Integer(), nullable=False, server_default='0'),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'],
                                name=op.f('fk_model_rollups_workspace_id_workspaces')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_model_rollups')),
    )
    with op.batch_alter_table('model_rollups', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_model_rollups_workspace_id'), ['workspace_id'])
        batch_op.create_index(batch_op.f('ix_model_rollups_bucket'), ['bucket'])
        batch_op.create_index('uq_model_rollup', ['workspace_id', 'bucket', 'model'], unique=True)


def downgrade() -> None:
    with op.batch_alter_table('model_rollups', schema=None) as batch_op:
        batch_op.drop_index('uq_model_rollup')
        batch_op.drop_index(batch_op.f('ix_model_rollups_bucket'))
        batch_op.drop_index(batch_op.f('ix_model_rollups_workspace_id'))
    op.drop_table('model_rollups')
    with op.batch_alter_table('metric_rollups', schema=None) as batch_op:
        batch_op.drop_index('uq_metric_rollup')
        batch_op.drop_index(batch_op.f('ix_metric_rollups_bucket'))
        batch_op.drop_index(batch_op.f('ix_metric_rollups_workspace_id'))
    op.drop_table('metric_rollups')
