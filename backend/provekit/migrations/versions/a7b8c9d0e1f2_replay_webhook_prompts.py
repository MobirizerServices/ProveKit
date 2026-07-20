"""replay webhook url on workspaces + prompts table

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-07-20 06:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'a7b8c9d0e1f2'
down_revision = 'f6a7b8c9d0e1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('workspaces', schema=None) as batch_op:
        batch_op.add_column(sa.Column('replay_url', sa.String(length=500), nullable=False, server_default=''))

    op.create_table('prompts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('workspace_id', sa.Integer(), nullable=True),
    sa.Column('name', sa.String(length=160), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('model', sa.String(length=120), nullable=False),
    sa.Column('messages', sa.JSON(), nullable=False),
    sa.Column('params', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_prompts_workspace_id_workspaces')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_prompts'))
    )
    with op.batch_alter_table('prompts', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_prompts_workspace_id'), ['workspace_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('prompts', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_prompts_workspace_id'))
    op.drop_table('prompts')
    with op.batch_alter_table('workspaces', schema=None) as batch_op:
        batch_op.drop_column('replay_url')
