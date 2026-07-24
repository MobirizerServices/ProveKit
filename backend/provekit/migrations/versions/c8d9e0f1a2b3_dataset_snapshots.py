"""dataset snapshots: the contents a dataset had at each version (#45)

Revision ID: c8d9e0f1a2b3
Revises: b7c8d9e0f1a2
"""
import sqlalchemy as sa
from alembic import op

revision = 'c8d9e0f1a2b3'
down_revision = 'b7c8d9e0f1a2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'dataset_snapshots',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('workspace_id', sa.Integer(), nullable=False),
        sa.Column('dataset_id', sa.Integer(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=True),
        sa.Column('fingerprint', sa.String(length=64), nullable=True),
        sa.Column('item_count', sa.Integer(), nullable=True),
        sa.Column('items', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'],
                                name=op.f('fk_dataset_snapshots_dataset_id_datasets')),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'],
                                name=op.f('fk_dataset_snapshots_workspace_id_workspaces')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_dataset_snapshots')),
    )
    with op.batch_alter_table('dataset_snapshots', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_dataset_snapshots_dataset_id'), ['dataset_id'],
                              unique=False)
        batch_op.create_index(batch_op.f('ix_dataset_snapshots_workspace_id'), ['workspace_id'],
                              unique=False)
        batch_op.create_index('ix_dataset_snapshots_dataset_version', ['dataset_id', 'version'],
                              unique=False)


def downgrade() -> None:
    with op.batch_alter_table('dataset_snapshots', schema=None) as batch_op:
        batch_op.drop_index('ix_dataset_snapshots_dataset_version')
        batch_op.drop_index(batch_op.f('ix_dataset_snapshots_workspace_id'))
        batch_op.drop_index(batch_op.f('ix_dataset_snapshots_dataset_id'))
    op.drop_table('dataset_snapshots')
