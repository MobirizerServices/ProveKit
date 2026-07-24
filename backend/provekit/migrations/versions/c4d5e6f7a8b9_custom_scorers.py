"""project-defined server-side scorers (#48)

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
"""
import sqlalchemy as sa
from alembic import op

revision = 'c4d5e6f7a8b9'
down_revision = 'b3c4d5e6f7a8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'custom_scorers',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('workspace_id', sa.Integer(), nullable=True),
        sa.Column('name', sa.String(length=80), nullable=True),
        sa.Column('description', sa.String(length=300), nullable=True),
        sa.Column('kind', sa.String(length=32), nullable=True),
        sa.Column('config', sa.JSON(), nullable=True),
        sa.Column('enabled', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'],
                                name=op.f('fk_custom_scorers_workspace_id_workspaces')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_custom_scorers')),
        sa.UniqueConstraint('workspace_id', 'name', name='uq_custom_scorer_name'),
    )
    with op.batch_alter_table('custom_scorers', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_custom_scorers_workspace_id'), ['workspace_id'],
                              unique=False)


def downgrade() -> None:
    with op.batch_alter_table('custom_scorers', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_custom_scorers_workspace_id'))
    op.drop_table('custom_scorers')
