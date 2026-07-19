"""feedback table + runs.session_id

Revision ID: a1b2c3d4e5f6
Revises: 9d2c06bfa4e6
Create Date: 2026-07-19 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'a1b2c3d4e5f6'
down_revision = '9d2c06bfa4e6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('feedback',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('workspace_id', sa.Integer(), nullable=True),
    sa.Column('trace_id', sa.String(length=32), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('score', sa.Float(), nullable=True),
    sa.Column('value', sa.String(length=200), nullable=False),
    sa.Column('comment', sa.Text(), nullable=False),
    sa.Column('source', sa.String(length=16), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_feedback_workspace_id_workspaces')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_feedback'))
    )
    with op.batch_alter_table('feedback', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_feedback_trace_id'), ['trace_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_feedback_workspace_id'), ['workspace_id'], unique=False)

    with op.batch_alter_table('runs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('session_id', sa.String(length=64), nullable=False,
                                      server_default=''))
        batch_op.create_index(batch_op.f('ix_runs_session_id'), ['session_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('runs', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_runs_session_id'))
        batch_op.drop_column('session_id')

    with op.batch_alter_table('feedback', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_feedback_workspace_id'))
        batch_op.drop_index(batch_op.f('ix_feedback_trace_id'))
    op.drop_table('feedback')
