"""webhook_subscriptions — push events to customer systems

Revision ID: f8a9b0c1d2e3
Revises: e7f8a9b0c1d2
Create Date: 2026-07-22 19:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'f8a9b0c1d2e3'
down_revision = 'e7f8a9b0c1d2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'webhook_subscriptions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('workspace_id', sa.Integer(), nullable=True),
        sa.Column('url', sa.String(length=500), nullable=False, server_default=''),
        sa.Column('events', sa.JSON(), nullable=True),
        sa.Column('secret', sa.String(length=64), nullable=False, server_default=''),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('failures', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('last_status', sa.String(length=120), nullable=False, server_default=''),
        sa.Column('last_attempt_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'],
                                name=op.f('fk_webhook_subscriptions_workspace_id_workspaces')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_webhook_subscriptions')),
    )
    with op.batch_alter_table('webhook_subscriptions', schema=None) as b:
        b.create_index(b.f('ix_webhook_subscriptions_workspace_id'), ['workspace_id'])


def downgrade() -> None:
    with op.batch_alter_table('webhook_subscriptions', schema=None) as b:
        b.drop_index(b.f('ix_webhook_subscriptions_workspace_id'))
    op.drop_table('webhook_subscriptions')
