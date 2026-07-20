"""span_notes — per-span collaboration notes

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-07-20 07:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'b8c9d0e1f2a3'
down_revision = 'a7b8c9d0e1f2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('span_notes',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('workspace_id', sa.Integer(), nullable=True),
    sa.Column('trace_id', sa.String(length=32), nullable=False),
    sa.Column('span_id', sa.String(length=16), nullable=False),
    sa.Column('author', sa.String(length=120), nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_span_notes_workspace_id_workspaces')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_span_notes'))
    )
    with op.batch_alter_table('span_notes', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_span_notes_workspace_id'), ['workspace_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_span_notes_trace_id'), ['trace_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('span_notes', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_span_notes_trace_id'))
        batch_op.drop_index(batch_op.f('ix_span_notes_workspace_id'))
    op.drop_table('span_notes')
