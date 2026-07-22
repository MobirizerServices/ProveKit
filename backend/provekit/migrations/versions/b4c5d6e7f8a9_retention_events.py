"""retention_events — make span pruning observable

Revision ID: b4c5d6e7f8a9
Revises: a3b4c5d6e7f8
Create Date: 2026-07-22 12:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'b4c5d6e7f8a9'
down_revision = 'a3b4c5d6e7f8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'retention_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('workspace_id', sa.Integer(), nullable=True),
        sa.Column('bucket', sa.DateTime(), nullable=False),
        sa.Column('deleted', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('keep', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('last_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'],
                                name=op.f('fk_retention_events_workspace_id_workspaces')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_retention_events')),
    )
    with op.batch_alter_table('retention_events', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_retention_events_workspace_id'), ['workspace_id'])
        batch_op.create_index(batch_op.f('ix_retention_events_bucket'), ['bucket'])
        batch_op.create_index('uq_retention_event', ['workspace_id', 'bucket'], unique=True)


def downgrade() -> None:
    with op.batch_alter_table('retention_events', schema=None) as batch_op:
        batch_op.drop_index('uq_retention_event')
        batch_op.drop_index(batch_op.f('ix_retention_events_bucket'))
        batch_op.drop_index(batch_op.f('ix_retention_events_workspace_id'))
    op.drop_table('retention_events')
