"""experiments + experiment_results

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-07-19 02:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'c3d4e5f6a7b8'
down_revision = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('experiments',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('workspace_id', sa.Integer(), nullable=True),
    sa.Column('name', sa.String(length=160), nullable=False),
    sa.Column('dataset_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'], name=op.f('fk_experiments_dataset_id_datasets')),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_experiments_workspace_id_workspaces')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_experiments'))
    )
    with op.batch_alter_table('experiments', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_experiments_dataset_id'), ['dataset_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_experiments_workspace_id'), ['workspace_id'], unique=False)

    op.create_table('experiment_results',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('workspace_id', sa.Integer(), nullable=True),
    sa.Column('experiment_id', sa.Integer(), nullable=False),
    sa.Column('item_id', sa.Integer(), nullable=True),
    sa.Column('input', sa.Text(), nullable=False),
    sa.Column('output', sa.Text(), nullable=False),
    sa.Column('expected', sa.Text(), nullable=False),
    sa.Column('scores', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['experiment_id'], ['experiments.id'], name=op.f('fk_experiment_results_experiment_id_experiments')),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_experiment_results_workspace_id_workspaces')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_experiment_results'))
    )
    with op.batch_alter_table('experiment_results', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_experiment_results_experiment_id'), ['experiment_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_experiment_results_workspace_id'), ['workspace_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('experiment_results', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_experiment_results_workspace_id'))
        batch_op.drop_index(batch_op.f('ix_experiment_results_experiment_id'))
    op.drop_table('experiment_results')
    with op.batch_alter_table('experiments', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_experiments_workspace_id'))
        batch_op.drop_index(batch_op.f('ix_experiments_dataset_id'))
    op.drop_table('experiments')
