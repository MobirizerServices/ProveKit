"""alerts

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-07-19 03:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'd4e5f6a7b8c9'
down_revision = 'c3d4e5f6a7b8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('alerts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('workspace_id', sa.Integer(), nullable=True),
    sa.Column('name', sa.String(length=160), nullable=False),
    sa.Column('metric', sa.String(length=32), nullable=False),
    sa.Column('comparator', sa.String(length=4), nullable=False),
    sa.Column('threshold', sa.Float(), nullable=False),
    sa.Column('window_hours', sa.Integer(), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('last_triggered_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_alerts_workspace_id_workspaces')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_alerts'))
    )
    with op.batch_alter_table('alerts', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_alerts_workspace_id'), ['workspace_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('alerts', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_alerts_workspace_id'))
    op.drop_table('alerts')
