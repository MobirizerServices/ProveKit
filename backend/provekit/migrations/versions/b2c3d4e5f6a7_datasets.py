"""datasets + dataset_items

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-07-19 01:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'b2c3d4e5f6a7'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('datasets',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('workspace_id', sa.Integer(), nullable=True),
    sa.Column('name', sa.String(length=160), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_datasets_workspace_id_workspaces')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_datasets'))
    )
    with op.batch_alter_table('datasets', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_datasets_workspace_id'), ['workspace_id'], unique=False)

    op.create_table('dataset_items',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('workspace_id', sa.Integer(), nullable=True),
    sa.Column('dataset_id', sa.Integer(), nullable=False),
    sa.Column('input', sa.Text(), nullable=False),
    sa.Column('expected', sa.Text(), nullable=False),
    sa.Column('meta', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'], name=op.f('fk_dataset_items_dataset_id_datasets')),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_dataset_items_workspace_id_workspaces')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_dataset_items'))
    )
    with op.batch_alter_table('dataset_items', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_dataset_items_dataset_id'), ['dataset_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_dataset_items_workspace_id'), ['workspace_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('dataset_items', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_dataset_items_workspace_id'))
        batch_op.drop_index(batch_op.f('ix_dataset_items_dataset_id'))
    op.drop_table('dataset_items')
    with op.batch_alter_table('datasets', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_datasets_workspace_id'))
    op.drop_table('datasets')
