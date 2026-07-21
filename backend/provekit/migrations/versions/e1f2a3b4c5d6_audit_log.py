"""audit_logs — append-only record of privileged changes

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
Create Date: 2026-07-21 11:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'e1f2a3b4c5d6'
down_revision = 'd0e1f2a3b4c5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'audit_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('workspace_id', sa.Integer(), nullable=True),
        sa.Column('actor_user_id', sa.Integer(), nullable=True),
        sa.Column('actor_email', sa.String(length=255), nullable=False, server_default=''),
        sa.Column('action', sa.String(length=64), nullable=False),
        sa.Column('target_type', sa.String(length=32), nullable=False, server_default=''),
        sa.Column('target_id', sa.String(length=64), nullable=False, server_default=''),
        sa.Column('target_label', sa.String(length=255), nullable=False, server_default=''),
        sa.Column('detail', sa.JSON(), nullable=True),
        sa.Column('ip', sa.String(length=45), nullable=False, server_default=''),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        # No FK on actor_user_id: the record must outlive the account it describes, which is
        # the whole point of keeping a trail of who did what.
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'],
                                name=op.f('fk_audit_logs_workspace_id_workspaces')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_logs')),
    )
    with op.batch_alter_table('audit_logs', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_audit_logs_workspace_id'), ['workspace_id'])
        batch_op.create_index(batch_op.f('ix_audit_logs_action'), ['action'])
        batch_op.create_index(batch_op.f('ix_audit_logs_created_at'), ['created_at'])


def downgrade() -> None:
    with op.batch_alter_table('audit_logs', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_audit_logs_created_at'))
        batch_op.drop_index(batch_op.f('ix_audit_logs_action'))
        batch_op.drop_index(batch_op.f('ix_audit_logs_workspace_id'))
    op.drop_table('audit_logs')
