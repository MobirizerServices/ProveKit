"""saved_views — a named, shareable trace filter

Revision ID: e7f8a9b0c1d2
Revises: d6e7f8a9b0c1
Create Date: 2026-07-22 16:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'e7f8a9b0c1d2'
down_revision = 'd6e7f8a9b0c1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'saved_views',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('workspace_id', sa.Integer(), nullable=True),
        sa.Column('name', sa.String(length=160), nullable=False, server_default=''),
        sa.Column('params', sa.JSON(), nullable=True),
        sa.Column('created_by', sa.String(length=255), nullable=False, server_default=''),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'],
                                name=op.f('fk_saved_views_workspace_id_workspaces')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_saved_views')),
    )
    with op.batch_alter_table('saved_views', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_saved_views_workspace_id'), ['workspace_id'])
        batch_op.create_index('uq_saved_view_name', ['workspace_id', 'name'], unique=True)


def downgrade() -> None:
    with op.batch_alter_table('saved_views', schema=None) as batch_op:
        batch_op.drop_index('uq_saved_view_name')
        batch_op.drop_index(batch_op.f('ix_saved_views_workspace_id'))
    op.drop_table('saved_views')
