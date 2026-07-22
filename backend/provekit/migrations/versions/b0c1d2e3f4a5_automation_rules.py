"""automation_rules — route production traces into datasets and online scoring

Revision ID: b0c1d2e3f4a5
Revises: a9b0c1d2e3f4
Create Date: 2026-07-22 22:30:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'b0c1d2e3f4a5'
down_revision = 'a9b0c1d2e3f4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'automation_rules',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('workspace_id', sa.Integer(), nullable=True),
        sa.Column('name', sa.String(length=160), nullable=False, server_default=''),
        sa.Column('match', sa.JSON(), nullable=True),
        sa.Column('action', sa.String(length=16), nullable=False, server_default='promote'),
        sa.Column('target_dataset_id', sa.Integer(), nullable=True),
        sa.Column('scorers', sa.JSON(), nullable=True),
        sa.Column('sample', sa.Float(), nullable=False, server_default='1.0'),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('last_run_id', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('matched', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('acted', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('last_status', sa.String(length=160), nullable=False, server_default=''),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'],
                                name=op.f('fk_automation_rules_workspace_id_workspaces')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_automation_rules')),
    )
    with op.batch_alter_table('automation_rules', schema=None) as b:
        b.create_index(b.f('ix_automation_rules_workspace_id'), ['workspace_id'])


def downgrade() -> None:
    with op.batch_alter_table('automation_rules', schema=None) as b:
        b.drop_index(b.f('ix_automation_rules_workspace_id'))
    op.drop_table('automation_rules')
