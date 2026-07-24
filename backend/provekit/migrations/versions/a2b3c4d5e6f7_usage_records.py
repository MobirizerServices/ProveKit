"""durable usage ledger for billing (#80)

Revision ID: a2b3c4d5e6f7
Revises: f1a2b3c4d5e6
"""
import sqlalchemy as sa
from alembic import op

revision = 'a2b3c4d5e6f7'
down_revision = 'f1a2b3c4d5e6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'usage_records',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('workspace_id', sa.Integer(), nullable=True),
        sa.Column('period', sa.String(length=7), nullable=False),
        sa.Column('spans', sa.Integer(), nullable=True),
        sa.Column('input_tokens', sa.Integer(), nullable=True),
        sa.Column('output_tokens', sa.Integer(), nullable=True),
        sa.Column('cost_usd', sa.Float(), nullable=True),
        sa.Column('priced_calls', sa.Integer(), nullable=True),
        sa.Column('unpriced_calls', sa.Integer(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_usage_records_user_id_users')),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'],
                                name=op.f('fk_usage_records_workspace_id_workspaces')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_usage_records')),
        sa.UniqueConstraint('user_id', 'workspace_id', 'period', name='uq_usage_period'),
    )
    with op.batch_alter_table('usage_records', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_usage_records_user_id'), ['user_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_usage_records_workspace_id'), ['workspace_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_usage_records_period'), ['period'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('usage_records', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_usage_records_period'))
        batch_op.drop_index(batch_op.f('ix_usage_records_workspace_id'))
        batch_op.drop_index(batch_op.f('ix_usage_records_user_id'))
    op.drop_table('usage_records')
