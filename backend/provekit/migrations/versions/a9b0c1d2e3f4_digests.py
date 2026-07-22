"""digests — recurring project summaries

Revision ID: a9b0c1d2e3f4
Revises: f8a9b0c1d2e3
Create Date: 2026-07-22 21:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'a9b0c1d2e3f4'
down_revision = 'f8a9b0c1d2e3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'digests',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('workspace_id', sa.Integer(), nullable=True),
        sa.Column('cadence', sa.String(length=16), nullable=False, server_default='weekly'),
        sa.Column('webhook_url', sa.String(length=500), nullable=False, server_default=''),
        sa.Column('email', sa.String(length=255), nullable=False, server_default=''),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('last_sent_at', sa.DateTime(), nullable=True),
        sa.Column('last_status', sa.String(length=160), nullable=False, server_default=''),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'],
                                name=op.f('fk_digests_workspace_id_workspaces')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_digests')),
    )
    with op.batch_alter_table('digests', schema=None) as b:
        b.create_index(b.f('ix_digests_workspace_id'), ['workspace_id'])


def downgrade() -> None:
    with op.batch_alter_table('digests', schema=None) as b:
        b.drop_index(b.f('ix_digests_workspace_id'))
    op.drop_table('digests')
